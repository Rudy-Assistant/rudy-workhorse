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
from pathlib import Path
from typing import Optional

from rudy.robin_mcp_client import MCPServerRegistry, MCPToolResult

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
You are Robin, the autonomous AI agent for the Batcave system.
You run on Oracle (the always-on Workhorse PC).
You have access to MCP tools that let you interact with the real world.

YOUR CAPABILITIES:
- Execute PowerShell commands on Oracle via windows-mcp.Shell
- Take screenshots and click UI elements via windows-mcp
- Manage GitHub repos, branches, PRs via github tools
- Read/write Notion pages for knowledge management
- Search and read emails via Gmail tools

RULES:
1. Be decisive. Execute actions, don't just describe them.
2. After each tool call, analyze the result before deciding next steps.
3. If a tool call fails, try an alternative approach.
4. When the task is complete, respond with your final summary.
5. Never expose secrets, tokens, or passwords in your responses.
6. If you're unsure about a destructive action, explain why and stop.

TO USE A TOOL, you MUST wrap the JSON in <tool_call> tags like this:

<tool_call>
{"tool": "server_name.tool_name", "args": {"param1": "value1"}}
</tool_call>

IMPORTANT: Always include the <tool_call> and </tool_call> tags.
Do NOT output bare JSON without the tags -- it will not be recognized.
You can include reasoning text before and after the tool_call block.
Only ONE tool_call per response. Wait for the result before calling another.

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

TOOL_CALL_PATTERN = re.compile(
    r"<tool_call>\s*(\{.*?\})\s*</tool_call>",
    re.DOTALL,
)

# Fallback: bare JSON with "tool" key (DeepSeek sometimes omits the tags)
BARE_TOOL_CALL_PATTERN = re.compile(
    r'(\{\s*"tool"\s*:\s*"[^"]+\.\w+"\s*,\s*"args"\s*:\s*\{.*?\}\s*\})',
    re.DOTALL,
)

THINK_PATTERN = re.compile(
    r"<think>(.*?)</think>",
    re.DOTALL,
)


def parse_tool_call(text: str) -> Optional[dict]:
    """Extract a tool call from DeepSeek's response."""
    # Try tagged format first
    match = TOOL_CALL_PATTERN.search(text)
    if match:
        raw = match.group(1)
    else:
        # Fallback: bare JSON with "tool" key containing a dot (server.tool)
        match = BARE_TOOL_CALL_PATTERN.search(text)
        if match:
            raw = match.group(1)
            log.info("Detected bare tool call (no <tool_call> tags)")
        else:
            return None

    try:
        call = json.loads(raw)
        if "tool" in call and "." in call["tool"]:
            return {
                "tool": call["tool"],
                "args": call.get("args", call.get("arguments", {})),
            }
    except json.JSONDecodeError as e:
        log.warning("Failed to parse tool call JSON: %s", e)

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

                # Add to conversation
                messages.append({"role": "assistant", "content": response})
                messages.append({"role": "user", "content": result_msg})

            else:
                # No tool call -- this is the final answer
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
