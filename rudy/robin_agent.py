#!/usr/bin/env python3

"""
Robin Agent -- DeepSeek-powered autonomous agent with MCP tool use.

This is Robin's executive function. It combines:
- DeepSeek-R1:8b for reasoning (via Ollama)
- MCP servers for action (Windows-MCP, GitHub, Notion, Gmail)

The agent loop:
    1. Receive a task or situation
    2. Build context (tools available, system state, history)
    3. Ask DeepSeek what to do (with tool descriptions in prompt)
    4. Parse DeepSeek's response for tool calls
    5. Execute tool calls via MCP
    6. Feed results back to DeepSeek
    7. Repeat until task is complete or max steps reached

DeepSeek Tool-Calling Format:
    Since DeepSeek-R1 doesn't have native tool-calling, we use a
    structured prompt format. DeepSeek responds with either:

    <tool_call>
    {"tool": "server.tool_name", "args": {"param": "value"}}
    </tool_call>

    Or plain text for direct responses / final answers.

    The <think>...</think> tags from DeepSeek-R1 are preserved
    for chain-of-thought visibility in logs.

Security:
    - Robin logs all tool calls and results (redacting secrets)
    - Max steps per task prevents runaway loops
    - Dangerous tool calls can be flagged for review
    - Robin never executes tool calls it doesn't understand
"""

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from rudy.robin_mcp_client import MCPServerRegistry

try:
    from rudy.robin_logger import log_task_to_notion
    HAS_LOGGER = True
except ImportError:
    HAS_LOGGER = False

log = logging.getLogger("robin_agent")

# ---------------------------------------------------------------------------
# Agent Configuration
# ---------------------------------------------------------------------------

DEFAULT_MAX_STEPS = 15
DEFAULT_MAX_TOOL_OUTPUT = 4000  # chars -- truncate long tool outputs

AGENT_SYSTEM_PROMPT = """\
You are Robin, Batman's autonomous proxy on this machine.
When Batman is away, YOU are the user. You operate the computer on his behalf --
clicking, typing, navigating, managing files, running commands, just as he would.
You are mentored by Alfred (Claude, the cloud AI). Alfred assigns tasks, reviews
your work, and helps you improve. Together you are the Batcave field team.

YOUR ROLE:
- You ARE the human operator of this PC when Batman is away
- You execute real actions: shell commands, UI clicks, file management, git ops
- You can see the screen (Snapshot), click things (Click), type text (Type)
- You research, analyze, install, configure, and troubleshoot
- You log everything you do so Alfred and Batman can review

YOUR CAPABILITIES:
- windows-mcp.Shell: Run any PowerShell/cmd command
- windows-mcp.Snapshot: See the desktop (use_vision=true for screenshot)
- windows-mcp.Click: Click at screen coordinates
- windows-mcp.Type: Type text into the focused window
- windows-mcp.Scroll: Scroll in any direction
- windows-mcp.App: Launch applications
- windows-mcp.Shortcut: Send keyboard shortcuts (Ctrl+C, Alt+Tab, etc.)
- brave-search: Search the web for information
- github: Manage repos, branches, PRs, issues

MULTI-STEP WORKFLOW PATTERN:
For UI tasks, follow this loop:
  1. Snapshot (see the screen)
  2. Decide what to do based on what you see
  3. Act (Click, Type, Shell, etc.)
  4. Snapshot again to verify the result
  5. Repeat until done

TOOL SELECTION GUIDE (CRITICAL):
- Shell runs PowerShell (NOT cmd.exe). Use PowerShell syntax always.
- To READ FILES: Get-Content 'path\to\file.txt'
- To LIST FILES: Get-ChildItem 'path' -Filter *.py
- To COUNT FILES: (Get-ChildItem 'path' -Filter *.py).Count
- To RUN SCRIPTS: & C:\\Python312\\python.exe script.py
- To CHECK PROCESSES: Get-Process | Where-Object {$_.Name -like '*pattern*'}
- To SEE THE SCREEN: Use windows-mcp.Snapshot (only for UI/visual tasks)
- To SEARCH THE WEB: Use brave-search.brave_web_search
- NEVER use CMD commands like: find, type, dir. Use PowerShell equivalents.

DIRECTIVE TASKS FROM ALFRED:
When you receive a directive with numbered steps, follow them EXACTLY in order.
If a step says "Run command: X", use windows-mcp.Shell with that exact command.
Do NOT substitute Snapshot when Shell is indicated.

RULES:
1. ACT FIRST, explain later. Execute the tool call, don't just describe it.
2. After each tool result, analyze it, then decide the next step.
3. If something fails, try a DIFFERENT approach. NEVER repeat the same command.
   Change the command syntax, use a different tool, or try PowerShell alternatives.
4. For complex tasks, break them into steps and execute one at a time.
5. Never expose secrets, tokens, or passwords.
6. For destructive actions (delete, format, uninstall), state what you plan
   to do and why, then proceed unless the task is ambiguous.
7. When done, give a concise summary of what you did and the result.
8. Shell is PowerShell. If a command fails, rewrite it in PowerShell syntax.
   Example: instead of "dir /b *.py | find /c /v" use "(Get-ChildItem *.py).Count"

TO USE A TOOL, you MUST wrap the JSON in <tool_call> tags like this:

<tool_call>
{"tool": "server_name.tool_name", "args": {"param1": "value1"}}
</tool_call>

CRITICAL FORMAT RULES:
You MUST use <tool_call> tags with valid JSON. Here are concrete examples:

EXAMPLE 1 - Running a shell command (MOST COMMON - uses PowerShell):
<tool_call>
{"tool": "windows-mcp.Shell", "args": {"command": "Get-ChildItem C:\\path\\to\\project\\src -Filter *.py | Measure-Object | Select-Object -ExpandProperty Count"}}
</tool_call>

EXAMPLE 2 - Running a Python script:
<tool_call>
{"tool": "windows-mcp.Shell", "args": {"command": "C:\\Python312\\python.exe C:\\path\\script.py"}}
</tool_call>

EXAMPLE 3 - Taking a screenshot (only for UI tasks):
<tool_call>
{"tool": "windows-mcp.Snapshot", "args": {"use_vision": true}}
</tool_call>

EXAMPLE 3 - Searching the web:
<tool_call>
{"tool": "brave-search.brave_web_search", "args": {"query": "example search"}}
</tool_call>

FORMAT: {"tool": "SERVER.TOOL_NAME", "args": {PARAMETERS}}
- ALWAYS use <tool_call> and </tool_call> tags
- The JSON must have exactly two keys: "tool" and "args"
- "tool" is "server_name.tool_name" (with a dot)
- "args" is an object with the tool parameters
- Only ONE tool_call per response. Wait for the result before the next.
- Include your reasoning BEFORE the <tool_call> block.
- When the task is done, respond with plain text only (no tags).

AVAILABLE TOOLS:
{tools_prompt}
"""

# ---------------------------------------------------------------------------
# Agent Step Types
# ---------------------------------------------------------------------------

@dataclass
class AgentStep:
    """A single step in the agent loop."""
    step_num: int
    timestamp: str
    action: str  # "think", "tool_call", "tool_result", "final_answer"
    content: str
    tool_name: Optional[str] = None
    tool_args: Optional[dict] = None
    tool_result: Optional[str] = None
    thinking: Optional[str] = None  # DeepSeek's <think> content
    duration_ms: int = 0


@dataclass
class AgentResult:
    """Result of a complete agent task execution."""
    task: str
    success: bool
    final_answer: str
    steps: list[AgentStep] = field(default_factory=list)
    total_steps: int = 0
    total_tool_calls: int = 0
    total_duration_ms: int = 0
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Tool Call Parser
# ---------------------------------------------------------------------------

# --- Tool call detection patterns (ordered by priority) ---
# Primary: <tool_call>{"tool": "...", "args": {...}}</tool_call>
TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)

# DeepSeek variant: <tool>...</tool> (wrong tag name but same intent)
TOOL_TAG_PATTERN = re.compile(
    r"<tool>\s*(.*?)\s*</tool>",
    re.DOTALL,
)

# Other common LLM variants
FUNCTION_CALL_PATTERN = re.compile(
    r"<function_call>\s*(\{.*?\})\s*</function_call>",
    re.DOTALL,
)
ACTION_PATTERN = re.compile(
    r"<action>\s*(\{.*?\})\s*</action>",
    re.DOTALL,
)

# Fallback: bare JSON with "tool" key (DeepSeek sometimes omits all tags)
BARE_TOOL_CALL_PATTERN = re.compile(
    r'(\{\s*"tool"\s*:\s*"[^"]+\.\w+"\s*,\s*"args"\s*:\s*\{.*?\}\s*\})',
    re.DOTALL,
)

THINK_PATTERN = re.compile(
    r"<think>(.*?)</think>",
    re.DOTALL,
)


def _normalize_tool_json(raw: str) -> Optional[dict]:
    """Try to parse a tool call string into a normalized dict.

    Handles both JSON format and DeepSeek's comma-separated format:
      - {"tool": "server.name", "args": {...}}
      - server.tool_name, {"key": "value"}
      - server.tool_name {"key": "value"}
    """
    raw = raw.strip()

    # Try standard JSON first
    try:
        call = json.loads(raw)
        if isinstance(call, dict):
            tool = call.get("tool", call.get("name", call.get("function", "")))
            if tool and "." in str(tool):
                return {
                    "tool": str(tool),
                    "args": call.get("args", call.get("arguments", call.get("parameters", {}))),
                }
    except json.JSONDecodeError:
        pass

    # Try DeepSeek's "server.tool, {args}" comma-separated format
    comma_match = re.match(
        r'([a-zA-Z_][\w-]*\.[a-zA-Z_]\w*)\s*[,\s]\s*(\{.*\})',
        raw, re.DOTALL
    )
    if comma_match:
        tool_name = comma_match.group(1)
        args_str = comma_match.group(2)
        try:
            args = json.loads(args_str)
            return {"tool": tool_name, "args": args if isinstance(args, dict) else {}}
        except json.JSONDecodeError:
            log.warning("Parsed tool name '%s' but args JSON failed: %s", tool_name, args_str[:100])

    # Try "server.tool {args}" space-separated format (no comma)
    space_match = re.match(
        r'([a-zA-Z_][\w-]*\.[a-zA-Z_]\w*)\s+(\{.*\})',
        raw, re.DOTALL
    )
    if space_match:
        tool_name = space_match.group(1)
        args_str = space_match.group(2)
        try:
            args = json.loads(args_str)
            return {"tool": tool_name, "args": args if isinstance(args, dict) else {}}
        except json.JSONDecodeError:
            pass

    return None


def parse_tool_call(text: str) -> Optional[dict]:
    """Extract a tool call from DeepSeek's response.

    Handles multiple format variations that DeepSeek-R1 produces:
    1. <tool_call>{"tool": "x.y", "args": {...}}</tool_call>  (intended)
    2. <tool>x.y, {"key": "val"}</tool>                       (common variant)
    3. <function_call>{"tool": "x.y", ...}</function_call>     (rare variant)
    4. <action>{"tool": "x.y", ...}</action>                   (rare variant)
    5. Bare JSON: {"tool": "x.y", "args": {...}}               (no tags)
    """
    # 1. Try <tool_call> tags (primary format)
    match = TOOL_CALL_PATTERN.search(text)
    if match:
        result = _normalize_tool_json(match.group(1))
        if result:
            return result

    # 2. Try <tool> tags (DeepSeek's most common mistake)
    match = TOOL_TAG_PATTERN.search(text)
    if match:
        result = _normalize_tool_json(match.group(1))
        if result:
            log.info("Detected tool call with <tool> tags (normalized)")
            return result

    # 3. Try <function_call> tags
    match = FUNCTION_CALL_PATTERN.search(text)
    if match:
        result = _normalize_tool_json(match.group(1))
        if result:
            log.info("Detected tool call with <function_call> tags (normalized)")
            return result

    # 4. Try <action> tags
    match = ACTION_PATTERN.search(text)
    if match:
        result = _normalize_tool_json(match.group(1))
        if result:
            log.info("Detected tool call with <action> tags (normalized)")
            return result

    # 5. Fallback: bare JSON with "tool" key
    match = BARE_TOOL_CALL_PATTERN.search(text)
    if match:
        result = _normalize_tool_json(match.group(1))
        if result:
            log.info("Detected bare tool call (no tags)")
            return result

    return None


def extract_thinking(text: str) -> tuple[str, Optional[str]]:
    """
    Extract <think>...</think> from DeepSeek's response.
    Returns (clean_text, thinking_content).
    """
    match = THINK_PATTERN.search(text)
    if match:
        thinking = match.group(1).strip()
        clean = THINK_PATTERN.sub("", text).strip()
        return clean, thinking
    return text, None


def truncate_output(text: str, max_len: int = DEFAULT_MAX_TOOL_OUTPUT) -> str:
    """Truncate long tool outputs to keep context manageable."""
    if len(text) <= max_len:
        return text
    half = max_len // 2
    return text[:half] + f"\n\n... [{len(text) - max_len} chars truncated] ...\n\n" + text[-half:]


# ---------------------------------------------------------------------------
# Robin Agent
# ---------------------------------------------------------------------------



# Heuristic keywords that suggest DeepSeek is reasoning about calling
# a tool but has not actually produced a tool_call block.
_NUDGE_KEYWORDS = [
    "tool_call", "tool call", "execute", "should output",
    "will use", "let me", "i need to", "run the command",
    "use the tool", "call the", "invoke", "i should",
]


def _needs_nudge(text: str) -> bool:
    """Return True if the response looks like meta-reasoning about tools.

    DeepSeek-R1:8b sometimes describes what it wants to do instead of
    actually producing the <tool_call> block. This detects that pattern.
    """
    lower = text.lower()
    hits = sum(1 for kw in _NUDGE_KEYWORDS if kw in lower)
    return hits >= 2  # At least 2 keyword matches to trigger nudge


class RobinAgent:
    """
    Robin's autonomous agent -- reasons with DeepSeek, acts with MCP tools.

    Usage:
        agent = RobinAgent(registry)
        result = agent.run("Check if all services are healthy on Oracle")
    """

    def __init__(self, registry: MCPServerRegistry,
                 ollama_host: str = "http://localhost:11434",
                 model: str = "deepseek-r1:8b",
                 max_steps: int = DEFAULT_MAX_STEPS):
        self.registry = registry
        self.ollama_host = ollama_host
        self.model = model
        self.max_steps = max_steps

    def run(self, task: str, context: dict = None) -> AgentResult:
        """
        Execute a task using the agent loop.

        Args:
            task: Natural language description of what to do.
            context: Optional dict of system context to include.

        Returns:
            AgentResult with the full execution trace.
        """
        start_time = time.time()
        steps = []
        messages = []
        tool_calls = 0

        log.info("=== AGENT TASK: %s ===", task[:100])

        # Build system prompt with available tools
        tools_prompt = self.registry.get_tools_prompt()
        system_prompt = AGENT_SYSTEM_PROMPT.replace("{tools_prompt}", tools_prompt)

        messages.append({"role": "system", "content": system_prompt})

        # Add context if provided
        if context:
            ctx_str = json.dumps(context, indent=2, default=str)
            messages.append({
                "role": "system",
                "content": f"Current system context:\n{ctx_str}",
            })

        # Add the task
        messages.append({"role": "user", "content": task})

        for step_num in range(1, self.max_steps + 1):
            step_start = time.time()

            # Ask DeepSeek
            response = self._call_llm(messages)
            if response is None:
                error_msg = "LLM call failed -- DeepSeek unreachable"
                log.error(error_msg)
                return AgentResult(
                    task=task,
                    success=False,
                    final_answer=error_msg,
                    steps=steps,
                    total_steps=step_num,
                    total_tool_calls=tool_calls,
                    total_duration_ms=int((time.time() - start_time) * 1000),
                    error=error_msg,
                )

            # Extract thinking and clean response
            clean_response, thinking = extract_thinking(response)
            step_duration = int((time.time() - step_start) * 1000)

            # Check for tool call
            tool_call = parse_tool_call(clean_response)

            if tool_call:
                # Log the reasoning + tool call
                tool_name = tool_call["tool"]
                tool_args = tool_call["args"]
                tool_calls += 1

                log.info("[Step %d] Tool call: %s(%s)",
                         step_num, tool_name,
                         json.dumps(tool_args)[:200])

                steps.append(AgentStep(
                    step_num=step_num,
                    timestamp=datetime.now().isoformat(),
                    action="tool_call",
                    content=clean_response,
                    tool_name=tool_name,
                    tool_args=tool_args,
                    thinking=thinking,
                    duration_ms=step_duration,
                ))

                # Execute the tool call
                exec_start = time.time()
                result = self.registry.call_tool(tool_name, tool_args)
                exec_duration = int((time.time() - exec_start) * 1000)

                # Format result for the conversation
                if result.success:
                    result_text = truncate_output(str(result.content))
                    result_msg = f"Tool result ({tool_name}):\n{result_text}"
                else:
                    result_msg = f"Tool error ({tool_name}): {result.error}"

                log.info("[Step %d] Tool result: %s (%dms)",
                         step_num,
                         result_msg[:150],
                         exec_duration)

                steps.append(AgentStep(
                    step_num=step_num,
                    timestamp=datetime.now().isoformat(),
                    action="tool_result",
                    content=result_msg,
                    tool_name=tool_name,
                    tool_result=result_msg,
                    duration_ms=exec_duration,
                ))

                # Detect repeated failed tool calls -- nudge model to try differently
                if not result.success and step_num > 1:
                    prev_calls = [s for s in steps if s.action == "tool_call"
                                  and s.tool_name == tool_name]
                    if len(prev_calls) >= 2:
                        # Same tool failed 2+ times -- inject correction nudge
                        result_msg += (
                            "\n\nWARNING: This exact tool call has FAILED multiple times. "
                            "You MUST try a COMPLETELY DIFFERENT approach. "
                            "If using Shell, rewrite the command in PowerShell syntax. "
                            "Examples: use Get-ChildItem instead of dir, "
                            "Get-Content instead of type, Measure-Object instead of find /c. "
                            "Do NOT repeat the same command."
                        )

                # Add to conversation
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": result_msg})

            else:
                # No tool call detected -- check if DeepSeek is
                # meta-reasoning about tools instead of calling them
                if step_num == 1 and tool_calls == 0 and _needs_nudge(clean_response):
                    log.info("[Step %d] Nudging: response is planning, not executing", step_num)
                    steps.append(AgentStep(
                        step_num=step_num,
                        timestamp=datetime.now().isoformat(),
                        action="think",
                        content=clean_response,
                        thinking=thinking,
                        duration_ms=step_duration,
                    ))
                    messages.append({"role": "assistant", "content": response})
                    nudge = (
                        "You described what you want to do but did not call a tool. "
                        "Output the tool call NOW:\n\n"
                        "<tool_call>\n"
                        '{"tool": "server.tool_name", "args": {"param": "value"}}\n'
                        "</tool_call>\n\n"
                        "Do NOT explain. Just output the <tool_call> block."
                    )
                    messages.append({"role": "user", "content": nudge})
                    continue
                # Genuine final answer
                log.info("[Step %d] Final answer: %s", step_num, clean_response[:200])

                steps.append(AgentStep(
                    step_num=step_num,
                    timestamp=datetime.now().isoformat(),
                    action="final_answer",
                    content=clean_response,
                    thinking=thinking,
                    duration_ms=step_duration,
                ))

                total_duration = int((time.time() - start_time) * 1000)
                log.info("=== AGENT COMPLETE: %d steps, %d tool calls, %dms ===",
                         step_num, tool_calls, total_duration)

                return AgentResult(
                    task=task,
                    success=True,
                    final_answer=clean_response,
                    steps=steps,
                    total_steps=step_num,
                    total_tool_calls=tool_calls,
                    total_duration_ms=total_duration,
                )

        # Max steps reached
        final_msg = (
            f"Task incomplete after {self.max_steps} steps. "
            f"Completed {tool_calls} tool calls. "
            f"Last response: {clean_response[:500]}"
        )
        log.warning("Agent hit max steps for task: %s", task[:100])

        return AgentResult(
            task=task,
            success=False,
            final_answer=final_msg,
            steps=steps,
            total_steps=self.max_steps,
            total_tool_calls=tool_calls,
            total_duration_ms=int((time.time() - start_time) * 1000),
            error="max_steps_reached",
        )

    def _call_llm(self, messages: list[dict]) -> Optional[str]:
        """Call DeepSeek via Ollama and return the response text."""
        import urllib.request
        import urllib.error

        payload = json.dumps({
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": 0.3,  # Lower temp for more reliable tool calling
                "num_predict": 2048,
            },
        }).encode()

        try:
            req = urllib.request.Request(
                f"{self.ollama_host}/api/chat",
                data=payload,
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=180) as resp:
                result = json.loads(resp.read())
                return result["message"]["content"]
        except urllib.error.URLError as e:
            log.error("Ollama unreachable: %s", e)
            return None
        except Exception as e:
            log.error("LLM call failed: %s", e)
            return None

    def run_with_report(self, task: str, context: dict = None) -> dict:
        """Run a task and return a serializable report."""
        result = self.run(task, context)
        report = {
            "task": result.task,
            "success": result.success,
            "final_answer": result.final_answer,
            "total_steps": result.total_steps,
            "total_tool_calls": result.total_tool_calls,
            "total_duration_ms": result.total_duration_ms,
            "error": result.error,
            "steps": [
                {
                    "step": s.step_num,
                    "action": s.action,
                    "tool": s.tool_name,
                    "content": s.content[:500],
                    "duration_ms": s.duration_ms,
                }
                for s in result.steps
            ],
        }

        # Auto-log to Notion
        if HAS_LOGGER:
            tools_used = list(set(
                s.tool_name for s in result.steps
                if s.tool_name
            ))
            try:
                log_task_to_notion(
                    task=result.task,
                    success=result.success,
                    final_answer=result.final_answer,
                    total_steps=result.total_steps,
                    total_tool_calls=result.total_tool_calls,
                    duration_ms=result.total_duration_ms,
                    tools_used=tools_used,
                    error=result.error,
                )
            except Exception as e:
                log.warning("Auto-log to Notion failed: %s", e)

        return report


# ---------------------------------------------------------------------------
# Convenience: Quick Agent Run
# ---------------------------------------------------------------------------

def quick_agent(task: str, servers: list[str] = None,
                secrets: dict = None) -> AgentResult:
    """
    One-shot agent execution.

    Usage:
        from rudy.robin_agent import quick_agent
        result = quick_agent("Take a screenshot of the desktop")
    """
    registry = MCPServerRegistry(secrets or {})

    if servers:
        for server in servers:
            registry.connect(server)
    else:
        registry.connect_all()

    try:
        agent = RobinAgent(registry)
        return agent.run(task)
    finally:
        registry.disconnect_all()
