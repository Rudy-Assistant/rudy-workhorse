#!/usr/bin/env python3

"""
Robin Agent v2 -- LangGraph-powered autonomous agent with MCP tool use.

Replaces the manual agent loop in robin_agent.py with a LangGraph StateGraph.
The MCP transport layer (robin_mcp_client.py) is preserved unchanged.

Architecture:
    StateGraph with nodes:
        reason   -> Call Ollama LLM, parse response
        execute  -> Dispatch tool call via MCPServerRegistry
        nudge    -> Re-prompt when LLM describes instead of calling tools

    Conditional routing:
        reason -> [has_tool_call]  -> execute -> reason
        reason -> [needs_nudge]    -> nudge   -> reason
        reason -> [final_answer]   -> END
        reason -> [max_steps]      -> END

    Tool routing pre-filter:
        Framework-level enforcement of Shell-over-Snapshot for file/script
        tasks. This fixes the qwen2.5:7b tool-selection regression at the
        graph level, not just the prompt level.

Compatibility:
    - Drop-in replacement for RobinAgent in robin_main.py
    - Same constructor signature: (registry, ollama_host, model, max_steps)
    - Same entry point: run(task, context) -> AgentResult
    - Same AgentResult / AgentStep dataclasses
    - Same logging hooks (Notion, file-based)

Dependencies (already installed per Session 5):
    - langgraph
    - langchain-ollama
    - langchain-community
"""

import json
import logging
import re
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, TypedDict, Annotated

from langgraph.graph import StateGraph, END

logger = logging.getLogger("robin.agent.langgraph")

# Browser tool integration (Playwright-direct, Session 7)
try:
    from rudy.tools.browser_integration import (
        is_browser_tool_call,
        dispatch_browser_tool,
        BROWSER_TOOLS_PROMPT,
    )
    BROWSER_TOOLS_AVAILABLE = True
    logger.info("Browser tools loaded (Playwright-direct)")
except ImportError:
    BROWSER_TOOLS_AVAILABLE = False
    BROWSER_TOOLS_PROMPT = ""
    logger.warning("Browser tools not available (playwright not installed)")

    def is_browser_tool_call(tool_name):
        return False

    def dispatch_browser_tool(tool_name, tool_args):
        return "Browser tools not available"

# ---------------------------------------------------------------------------
# Data classes (preserved from robin_agent.py for compatibility)
# ---------------------------------------------------------------------------

@dataclass
class AgentStep:
    """Single step in the agent's execution."""
    step_num: int
    timestamp: str
    action: str  # think, tool_call, tool_result, final_answer, nudge
    content: str = ""
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    tool_result: str = ""
    thinking: str = ""
    duration_ms: int = 0

@dataclass
class AgentResult:
    """Complete result of an agent run."""
    task: str
    success: bool
    final_answer: str = ""
    steps: list = field(default_factory=list)
    total_steps: int = 0
    total_tool_calls: int = 0
    total_duration_ms: int = 0
    error: str = ""

    def to_summary(self) -> str:
        status = "SUCCESS" if self.success else "FAILED"
        lines = [
            f"[{status}] Task: {self.task[:80]}",
            f"  Steps: {self.total_steps}, Tool calls: {self.total_tool_calls}",
            f"  Duration: {self.total_duration_ms}ms",
        ]
        if self.error:
            lines.append(f"  Error: {self.error}")
        if self.final_answer:
            lines.append(f"  Answer: {self.final_answer[:200]}")
        return "\n".join(lines)

# ---------------------------------------------------------------------------
# LangGraph State
# ---------------------------------------------------------------------------

def _merge_messages(left: list, right: list) -> list:
    """Append new messages to existing list (reducer for Annotated)."""
    return left + right

def _merge_steps(left: list, right: list) -> list:
    """Append new steps to existing list."""
    return left + right

class RobinState(TypedDict):
    """State flowing through the LangGraph."""
    messages: Annotated[list[dict], _merge_messages]
    steps: Annotated[list[AgentStep], _merge_steps]
    current_step: int
    tool_call_count: int
    max_steps: int
    final_answer: str
    route_decision: str  # "tool_call", "nudge", "final_answer", "max_steps"
    last_tool_name: str
    last_tool_args: dict
    error: str

# ---------------------------------------------------------------------------
# Tool-call parsing (preserved from robin_agent.py, all 5 patterns)
# ---------------------------------------------------------------------------

# Patterns ordered by priority
TOOL_CALL_PATTERNS = [
    re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL),
    re.compile(r"<tool>\s*(.*?)\s*</tool>", re.DOTALL),
    re.compile(r"<function_call>\s*(.*?)\s*</function_call>", re.DOTALL),
    re.compile(r"<action>\s*(.*?)\s*</action>", re.DOTALL),
]

BARE_JSON_PATTERN = re.compile(
    r'\{\s*"tool"\s*:\s*"[^"]+"\s*,\s*"args"\s*:\s*\{.*?\}\s*\}', re.DOTALL
)

def _normalize_tool_json(raw: str) -> Optional[dict]:
    """Parse tool call JSON, handling DeepSeek quirks."""
    raw = raw.strip()

    # Standard JSON
    try:
        parsed = json.loads(raw)
        if "tool" in parsed:
            return parsed
    except json.JSONDecodeError:
        pass

    # Comma-separated: server.tool, {"key": "value"}
    if "," in raw and not raw.startswith("{"):
        parts = raw.split(",", 1)
        tool_name = parts[0].strip().strip('"')
        try:
            args = json.loads(parts[1].strip())
            return {"tool": tool_name, "args": args}
        except (json.JSONDecodeError, IndexError):
            pass

    # Space-separated: server.tool {"key": "value"}
    if "{" in raw and not raw.startswith("{"):
        idx = raw.index("{")
        tool_name = raw[:idx].strip().strip('"')
        try:
            args = json.loads(raw[idx:])
            return {"tool": tool_name, "args": args}
        except json.JSONDecodeError:
            pass

    return None

def parse_tool_call(text: str) -> Optional[dict]:
    """Extract tool call from LLM response text."""
    # Try tagged patterns first
    for pattern in TOOL_CALL_PATTERNS:
        match = pattern.search(text)
        if match:
            result = _normalize_tool_json(match.group(1))
            if result:
                return result

    # Try bare JSON
    match = BARE_JSON_PATTERN.search(text)
    if match:
        result = _normalize_tool_json(match.group(0))
        if result:
            return result

    return None

def extract_thinking(text: str) -> tuple[str, str]:
    """Separate <think>...</think> from the rest of the response."""
    think_pattern = re.compile(r"<think>(.*?)</think>", re.DOTALL)
    thinking_parts = think_pattern.findall(text)
    clean = think_pattern.sub("", text).strip()
    thinking = "\n".join(thinking_parts)
    return clean, thinking

# ---------------------------------------------------------------------------
# Tool routing pre-filter (framework-level Shell vs Snapshot fix)
# ---------------------------------------------------------------------------

# Keywords that indicate file/script operations -> must use Shell, not Snapshot
SHELL_KEYWORDS = [
    "get-content", "set-content", "read", "write", "cat ", "type ",
    "dir ", "ls ", "cd ", "mkdir", "remove-item", "copy-item",
    "move-item", "test-path", "invoke-expression", "start-process",
    "python", "pip ", "npm ", "node ", "git ", "curl ", "wget",
    ".ps1", ".py", ".bat", ".cmd", ".sh",
    "get-process", "stop-process", "get-service",
    "get-childitem", "select-string", "out-file",
]

SNAPSHOT_LEGITIMATE = [
    "screenshot", "screen", "display", "window", "ui ", "gui ",
    "visual", "what do you see", "look at", "monitor",
]

def should_override_to_shell(tool_name: str, tool_args: dict) -> Optional[str]:
    """
    Framework-level tool routing override.

    Returns corrected tool name if Snapshot was chosen for a Shell task,
    or None if the original choice is fine.
    """
    if "snapshot" not in tool_name.lower():
        return None  # Not a Snapshot call, no override needed

    # Check if args suggest this is actually a file/script operation
    args_text = json.dumps(tool_args).lower()

    for keyword in SHELL_KEYWORDS:
        if keyword in args_text:
            logger.warning(
                f"TOOL ROUTER: Overriding {tool_name} -> Shell "
                f"(detected shell keyword '{keyword}' in args)"
            )
            # Reconstruct as Shell call
            return tool_name.replace("Snapshot", "Shell").replace("snapshot", "Shell")

    return None  # Snapshot is legitimate

# ---------------------------------------------------------------------------
# Prompt template (preserved + enhanced from robin_agent.py)
# ---------------------------------------------------------------------------

AGENT_SYSTEM_PROMPT = """You are Robin, Batman's autonomous agent running on Oracle (Windows PC).
You execute tasks by calling tools via MCP servers. You think step-by-step, then act.

AVAILABLE TOOLS:
{tools_prompt}

- To BROWSE WEB PAGES, CHECK DASHBOARDS, or SEARCH THE WEB:
  -> Use robin.Browse, robin.SearchWeb, or robin.CheckURLs
  -> These use a headless browser (Playwright) - works even when screen is locked
TOOL SELECTION GUIDE (CRITICAL — FOLLOW EXACTLY):
- To READ FILES, LIST DIRECTORIES, RUN SCRIPTS, or EXECUTE COMMANDS:
  → Use windows-mcp.Shell with PowerShell commands
  → NEVER use Snapshot for file operations
- To SEE THE SCREEN (UI inspection, visual verification only):
  → Use windows-mcp.Snapshot
- To SEARCH THE WEB:
  → Use brave-search.brave_web_search

TOOL CALL FORMAT — use EXACTLY this format, one tool per response:
<tool_call>
{{"tool": "server-name.ToolName", "args": {{"param": "value"}}}}
</tool_call>

RULES:
1. Call ONE tool per response. Wait for the result before calling another.
2. After receiving a tool result, analyze it and decide your next action.
3. When the task is complete, respond with your final answer in plain text (no tool_call tags).
4. If a directive has numbered steps, follow them IN ORDER.
5. Do NOT describe what you would do — actually call the tool.
6. Keep PowerShell commands simple. Prefer Get-Content, Get-ChildItem, Set-Content.
"""

NUDGE_MESSAGE = (
    "You described what you want to do but did not call a tool. "
    "Output the tool call NOW using the exact <tool_call> format. "
    "Do not explain — just call the tool."
)

# Patterns that indicate meta-reasoning instead of action
META_PATTERNS = [
    re.compile(r"i (?:would|will|should|can|need to) (?:use|call|run|execute)", re.I),
    re.compile(r"let me (?:use|call|run|try)", re.I),
    re.compile(r"the (?:next|first|right) (?:step|tool|action)", re.I),
    re.compile(r"i'(?:ll|m going to) (?:use|call|run)", re.I),
]

def _needs_nudge(text: str) -> bool:
    """Detect if LLM is describing actions instead of performing them."""
    # If there's a tool call, no nudge needed
    if parse_tool_call(text):
        return False
    # Check for meta-reasoning patterns
    for pattern in META_PATTERNS:
        if pattern.search(text):
            return True
    return False

# ---------------------------------------------------------------------------
# Ollama LLM caller (preserved from robin_agent.py)
# ---------------------------------------------------------------------------

def call_ollama(
    messages: list[dict],
    ollama_host: str,
    model: str,
    timeout: int = 180,
) -> str:
    """Call Ollama chat API and return assistant message content."""
    url = f"{ollama_host}/api/chat"
    payload = {
        "model": model,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.3,
            "num_predict": 2048,
        },
    }

    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return result.get("message", {}).get("content", "")
    except urllib.error.URLError as e:
        logger.error(f"Ollama call failed: {e}")
        raise
    except json.JSONDecodeError as e:
        logger.error(f"Ollama response parse error: {e}")
        raise

# ---------------------------------------------------------------------------
# LangGraph Node Functions
# ---------------------------------------------------------------------------

MAX_TOOL_RESULT_LENGTH = 4000

def reason_node(state: RobinState) -> dict:
    """
    Call Ollama with current messages. Parse response for tool calls.
    Sets route_decision for the conditional edge.
    """
    step_num = state["current_step"] + 1
    start_time = time.time()

    # Check max steps
    if step_num > state["max_steps"]:
        return {
            "current_step": step_num,
            "route_decision": "max_steps",
            "error": f"Max steps ({state['max_steps']}) exceeded",
        }

    # Call LLM
    try:
        raw_response = call_ollama(
            messages=state["messages"],
            ollama_host=state.get("_ollama_host", "http://localhost:11434"),
            model=state.get("_model", "qwen2.5:7b"),
        )
    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        step = AgentStep(
            step_num=step_num,
            timestamp=datetime.now().isoformat(),
            action="error",
            content=str(e),
            duration_ms=duration,
        )
        return {
            "current_step": step_num,
            "steps": [step],
            "route_decision": "final_answer",
            "final_answer": f"Error calling LLM: {e}",
            "error": str(e),
        }

    duration = int((time.time() - start_time) * 1000)

    # Extract thinking
    clean_response, thinking = extract_thinking(raw_response)

    # Append assistant message
    assistant_msg = {"role": "assistant", "content": raw_response}

    # Try to parse tool call
    tool_call = parse_tool_call(clean_response)

    if tool_call:
        tool_name = tool_call.get("tool", "")
        tool_args = tool_call.get("args", {})

        step = AgentStep(
            step_num=step_num,
            timestamp=datetime.now().isoformat(),
            action="tool_call",
            content=clean_response,
            tool_name=tool_name,
            tool_args=tool_args,
            thinking=thinking,
            duration_ms=duration,
        )

        return {
            "messages": [assistant_msg],
            "steps": [step],
            "current_step": step_num,
            "route_decision": "tool_call",
            "last_tool_name": tool_name,
            "last_tool_args": tool_args,
        }

    elif _needs_nudge(clean_response):
        step = AgentStep(
            step_num=step_num,
            timestamp=datetime.now().isoformat(),
            action="nudge",
            content=clean_response,
            thinking=thinking,
            duration_ms=duration,
        )

        return {
            "messages": [assistant_msg],
            "steps": [step],
            "current_step": step_num,
            "route_decision": "nudge",
        }

    else:
        # Final answer
        step = AgentStep(
            step_num=step_num,
            timestamp=datetime.now().isoformat(),
            action="final_answer",
            content=clean_response,
            thinking=thinking,
            duration_ms=duration,
        )

        return {
            "messages": [assistant_msg],
            "steps": [step],
            "current_step": step_num,
            "route_decision": "final_answer",
            "final_answer": clean_response,
        }

def execute_tool_node(state: RobinState) -> dict:
    """
    Execute the tool call via MCPServerRegistry.
    Applies framework-level tool routing override before dispatch.
    """
    start_time = time.time()
    step_num = state["current_step"]  # Already incremented by reason

    tool_name = state["last_tool_name"]
    tool_args = state["last_tool_args"]

    # --- Framework-level tool routing override ---
    override = should_override_to_shell(tool_name, tool_args)
    if override:
        original_name = tool_name
        tool_name = override
        # If args were for Snapshot but task is Shell, reconstruct
        if "command" not in tool_args:
            # Try to extract command intent from args
            desc = tool_args.get("description", tool_args.get("query", ""))
            if desc:
                tool_args = {"command": desc}
                logger.info(
                    f"TOOL ROUTER: Rewrote args from Snapshot format to Shell. "
                    f"Original: {original_name}, New: {tool_name}"
                )

    # --- Browser tool dispatch (Playwright-direct, no MCP needed) ---
    if BROWSER_TOOLS_AVAILABLE and is_browser_tool_call(tool_name):
        try:
            result_text = dispatch_browser_tool(tool_name, tool_args)
            duration = int((time.time() - start_time) * 1000)
            step = AgentStep(
                step_num=step_num,
                timestamp=datetime.now().isoformat(),
                action="tool_result",
                content=result_text[:500],
                tool_name=tool_name,
                tool_args=tool_args,
                tool_result=result_text,
                duration_ms=duration,
            )
            result_msg = {"role": "user", "content": f"Tool result ({tool_name}):\n{result_text}"}
            return {
                "messages": [result_msg],
                "steps": [step],
                "tool_call_count": state["tool_call_count"] + 1,
            }
        except Exception as e:
            logger.error(f"Browser tool failed: {e}")
            # Fall through to MCP dispatch as fallback

    # --- Dispatch via registry ---
    registry = state.get("_registry")
    if not registry:
        error_msg = "MCPServerRegistry not available in state"
        result_msg = {"role": "user", "content": f"Tool error: {error_msg}"}
        step = AgentStep(
            step_num=step_num,
            timestamp=datetime.now().isoformat(),
            action="tool_error",
            content=error_msg,
            tool_name=tool_name,
            tool_args=tool_args,
            duration_ms=int((time.time() - start_time) * 1000),
        )
        return {
            "messages": [result_msg],
            "steps": [step],
            "tool_call_count": state["tool_call_count"] + 1,
        }

    try:
        result = registry.call_tool(tool_name, tool_args)
        duration = int((time.time() - start_time) * 1000)

        if hasattr(result, "is_error") and result.is_error:
            content = f"Tool error ({tool_name}): {getattr(result, 'error', str(result))}"
        else:
            content = str(getattr(result, "content", result))
            # Truncate long results
            if len(content) > MAX_TOOL_RESULT_LENGTH:
                content = content[:MAX_TOOL_RESULT_LENGTH] + "\n... (truncated)"

        result_text = f"Tool result ({tool_name}):\n{content}"

    except Exception as e:
        duration = int((time.time() - start_time) * 1000)
        result_text = f"Tool error ({tool_name}): {e}"
        logger.error(f"Tool execution failed: {tool_name} -> {e}")

    result_msg = {"role": "user", "content": result_text}

    step = AgentStep(
        step_num=step_num,
        timestamp=datetime.now().isoformat(),
        action="tool_result",
        content=result_text[:500],
        tool_name=tool_name,
        tool_args=tool_args,
        tool_result=result_text,
        duration_ms=duration,
    )

    return {
        "messages": [result_msg],
        "steps": [step],
        "tool_call_count": state["tool_call_count"] + 1,
    }

def nudge_node(state: RobinState) -> dict:
    """Inject nudge message when LLM describes instead of acting."""
    nudge_msg = {"role": "user", "content": NUDGE_MESSAGE}

    step = AgentStep(
        step_num=state["current_step"],
        timestamp=datetime.now().isoformat(),
        action="nudge",
        content=NUDGE_MESSAGE,
    )

    return {
        "messages": [nudge_msg],
        "steps": [step],
    }

# ---------------------------------------------------------------------------
# Conditional edge router
# ---------------------------------------------------------------------------

def route_after_reason(state: RobinState) -> str:
    """Route based on what the reason node decided."""
    decision = state.get("route_decision", "final_answer")

    if decision == "tool_call":
        return "execute_tool"
    elif decision == "nudge":
        return "nudge"
    elif decision == "max_steps":
        return END
    else:  # final_answer
        return END

# ---------------------------------------------------------------------------
# Graph builder
# ---------------------------------------------------------------------------

def build_robin_graph() -> StateGraph:
    """Build the Robin agent LangGraph."""
    graph = StateGraph(RobinState)

    # Add nodes
    graph.add_node("reason", reason_node)
    graph.add_node("execute_tool", execute_tool_node)
    graph.add_node("nudge", nudge_node)

    # Entry point
    graph.set_entry_point("reason")

    # Conditional routing after reason
    graph.add_conditional_edges(
        "reason",
        route_after_reason,
        {
            "execute_tool": "execute_tool",
            "nudge": "nudge",
            END: END,
        },
    )

    # After tool execution, go back to reason
    graph.add_edge("execute_tool", "reason")

    # After nudge, go back to reason
    graph.add_edge("nudge", "reason")

    return graph.compile()

# ---------------------------------------------------------------------------
# RobinAgent v2 (drop-in replacement)
# ---------------------------------------------------------------------------

class RobinAgentV2:
    """
    LangGraph-powered Robin agent.

    Drop-in replacement for the original RobinAgent class.
    Same constructor, same run() signature, same AgentResult output.
    """

    def __init__(
        self,
        registry,  # MCPServerRegistry
        ollama_host: str = "http://localhost:11434",
        model: str = "qwen2.5:7b",
        max_steps: int = 15,
    ):
        self.registry = registry
        self.ollama_host = ollama_host
        self.model = model
        self.max_steps = max_steps
        self.graph = build_robin_graph()

        logger.info(
            f"RobinAgentV2 initialized: model={model}, "
            f"max_steps={max_steps}, host={ollama_host}"
        )

    def run(self, task: str, context: Optional[dict] = None) -> AgentResult:
        """
        Execute a task using the LangGraph agent loop.

        Args:
            task: The task description or directive
            context: Optional system context dict (datetime, mode, etc.)

        Returns:
            AgentResult with steps, final answer, and metrics
        """
        start_time = time.time()

        # Build initial messages
        tools_prompt = ""
        if self.registry:
            try:
                tools_prompt = self.registry.get_tools_prompt()
            except Exception as e:
                logger.warning(f"Could not get tools prompt: {e}")
                tools_prompt = "(Tool discovery failed — proceed with known tools)"

        system_prompt = AGENT_SYSTEM_PROMPT.format(tools_prompt=tools_prompt)
        messages = [{"role": "system", "content": system_prompt}]

        if context:
            ctx_str = json.dumps(context, indent=2, default=str)
            messages.append({
                "role": "system",
                "content": f"Current system context:\n{ctx_str}",
            })

        messages.append({"role": "user", "content": task})

        # Build initial state
        # Note: _registry, _ollama_host, _model are passed via state for node access
        # They use underscore prefix to indicate they're config, not graph data
        initial_state = {
            "messages": messages,
            "steps": [],
            "current_step": 0,
            "tool_call_count": 0,
            "max_steps": self.max_steps,
            "final_answer": "",
            "route_decision": "",
            "last_tool_name": "",
            "last_tool_args": {},
            "error": "",
            # Config passthrough (accessed by nodes via state)
            "_registry": self.registry,
            "_ollama_host": self.ollama_host,
            "_model": self.model,
        }

        # Run the graph
        try:
            final_state = self.graph.invoke(initial_state)
        except Exception as e:
            logger.error(f"Graph execution failed: {e}")
            return AgentResult(
                task=task,
                success=False,
                error=str(e),
                total_duration_ms=int((time.time() - start_time) * 1000),
            )

        total_duration = int((time.time() - start_time) * 1000)

        # Build result
        steps = final_state.get("steps", [])
        final_answer = final_state.get("final_answer", "")
        error = final_state.get("error", "")

        result = AgentResult(
            task=task,
            success=bool(final_answer and not error),
            final_answer=final_answer,
            steps=steps,
            total_steps=final_state.get("current_step", 0),
            total_tool_calls=final_state.get("tool_call_count", 0),
            total_duration_ms=total_duration,
            error=error,
        )

        logger.info(result.to_summary())
        return result

    def run_with_report(self, task: str, context: Optional[dict] = None) -> dict:
        """Run a task and return a serializable dict report.

        Backward-compatible wrapper around run() that returns a plain dict
        instead of an AgentResult dataclass. Used by AutonomyEngine and
        other callers that expect .get() semantics.

        Session 39 fix: RobinAgentV2 was missing this method, causing
        autonomy engine to fail with AttributeError since S38.
        """
        result = self.run(task, context)
        report = {
            "task": result.task,
            "success": result.success,
            "final_answer": result.final_answer,
            "summary": result.final_answer[:200] if result.final_answer else "",
            "total_steps": result.total_steps,
            "total_tool_calls": result.total_tool_calls,
            "total_duration_ms": result.total_duration_ms,
            "error": result.error,
            "steps": [
                {
                    "step": getattr(s, "step", i),
                    "thought": getattr(s, "thought", ""),
                    "action": getattr(s, "action", ""),
                    "result": getattr(s, "result", "")[:500]
                    if getattr(s, "result", "") else "",
                }
                for i, s in enumerate(result.steps)
            ],
        }
        return report

# ---------------------------------------------------------------------------
# Convenience: backward-compatible alias
# ---------------------------------------------------------------------------
RobinAgent = RobinAgentV2

# ---------------------------------------------------------------------------
# CLI test harness
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("Robin Agent v2 (LangGraph) — Test Harness")
    print("=" * 60)

    # Test 1: Graph builds
    print("\n[TEST 1] Graph compilation...")
    try:
        graph = build_robin_graph()
        print("  PASS: Graph compiled successfully")
    except Exception as e:
        print(f"  FAIL: {e}")
        sys.exit(1)

    # Test 2: Tool call parsing
    print("\n[TEST 2] Tool call parsing...")
    test_cases = [
        ('<tool_call>\n{"tool": "windows-mcp.Shell", "args": {"command": "dir"}}\n</tool_call>',
         "windows-mcp.Shell"),
        ('<tool>{"tool": "brave-search.brave_web_search", "args": {"query": "test"}}</tool>',
         "brave-search.brave_web_search"),
        ('{"tool": "windows-mcp.Shell", "args": {"command": "Get-Process"}}',
         "windows-mcp.Shell"),
        ("Let me think about this... I would use the Shell tool.", None),
    ]
    for text, expected_tool in test_cases:
        result = parse_tool_call(text)
        actual = result["tool"] if result else None
        status = "PASS" if actual == expected_tool else "FAIL"
        print(f"  {status}: Expected {expected_tool}, got {actual}")

    # Test 3: Tool routing override
    print("\n[TEST 3] Tool routing override (Shell vs Snapshot)...")
    override_cases = [
        ("windows-mcp.Snapshot", {"command": "Get-Content file.txt"}, True),
        ("windows-mcp.Snapshot", {"description": "run python script.py"}, True),
        ("windows-mcp.Snapshot", {}, False),  # Legit snapshot
        ("windows-mcp.Shell", {"command": "dir"}, False),  # Already Shell
    ]
    for tool, args, should_override in override_cases:
        result = should_override_to_shell(tool, args)
        did_override = result is not None
        status = "PASS" if did_override == should_override else "FAIL"
        print(f"  {status}: {tool} with {args} -> override={did_override}")

    # Test 4: Nudge detection
    print("\n[TEST 4] Nudge detection...")
    nudge_cases = [
        ("I would use the Shell tool to read the file.", True),
        ("Let me call the Shell tool next.", True),
        ('<tool_call>{"tool": "x.y", "args": {}}</tool_call>', False),
        ("The task is complete. All files processed.", False),
    ]
    for text, expected in nudge_cases:
        result = _needs_nudge(text)
        status = "PASS" if result == expected else "FAIL"
        print(f"  {status}: needs_nudge={result} for: {text[:50]}")

    # Test 5: Agent instantiation (no MCP, just structure)
    print("\n[TEST 5] Agent instantiation...")
    try:
        agent = RobinAgentV2(
            registry=None,
            ollama_host="http://localhost:11434",
            model="qwen2.5:7b",
            max_steps=10,
        )
        print(f"  PASS: RobinAgentV2 created, graph={type(agent.graph).__name__}")
    except Exception as e:
        print(f"  FAIL: {e}")

    print("\n" + "=" * 60)
    print("All structural tests complete.")
    print("To test with live Ollama + MCP, use robin_main.py integration.")
    print("=" * 60)
                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                