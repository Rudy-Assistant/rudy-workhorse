#!/usr/bin/env python3

"""
Robin MCP Client -- Connects Robin to MCP servers via stdio JSON-RPC.

This gives Robin hands, eyes, and reach. Instead of just reasoning via
DeepSeek, Robin can now ACT through MCP servers:

- Windows-MCP: Shell, Click, Type, Snapshot, Scroll (desktop control)
- GitHub MCP: Create branches, push files, manage PRs (code management)
- Notion MCP: Read/write pages (knowledge base)
- Gmail MCP: Search/read/draft emails (communications)

Architecture:
    Robin spawns each MCP server as a subprocess with stdio transport.
    Communication is JSON-RPC 2.0 over stdin/stdout.
    Robin discovers available tools via tools/list, then calls them
    via tools/call. Results feed back into DeepSeek for reasoning.

Security:
    - Server configs live in robin-secrets.json (never committed)
    - Falls back to reading Claude's own config for server paths
    - Tokens and API keys are passed via env vars to server processes
    - Robin NEVER logs secrets or tool call results containing secrets
"""

import json
import logging
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger("robin_mcp")

# ---------------------------------------------------------------------------
# MCP Protocol Types
# ---------------------------------------------------------------------------

@dataclass
class MCPTool:
    """A tool exposed by an MCP server."""
    name: str
    description: str
    input_schema: dict = field(default_factory=dict)
    server_name: str = ""

    def to_prompt_description(self) -> str:
        """Format for inclusion in DeepSeek's system prompt."""
        params = ""
        props = self.input_schema.get("properties", {})
        required = self.input_schema.get("required", [])
        if props:
            param_parts = []
            for pname, pinfo in props.items():
                req = " (required)" if pname in required else ""
                desc = pinfo.get("description", "")
                ptype = pinfo.get("type", "any")
                param_parts.append(f"    - {pname}: {ptype}{req} -- {desc}")
            params = "\n".join(param_parts)
        return (
            f"Tool: {self.server_name}.{self.name}\n"
            f"  Description: {self.description}\n"
            f"  Parameters:\n{params}" if params else
            f"Tool: {self.server_name}.{self.name}\n"
            f"  Description: {self.description}\n"
            f"  Parameters: none"
        )


@dataclass
class MCPToolResult:
    """Result from calling an MCP tool."""
    success: bool
    content: Any = None
    error: Optional[str] = None
    is_error: bool = False


# ---------------------------------------------------------------------------
# MCP Server Connection
# ---------------------------------------------------------------------------

class MCPServerConnection:
    """
    A connection to a single MCP server via stdio JSON-RPC.

    Lifecycle:
    1. start() -- spawn the server process
    2. initialize() -- send initialize handshake
    3. discover_tools() -- get available tools
    4. call_tool(name, args) -- execute a tool
    5. stop() -- kill the server process
    """

    def __init__(self, name: str, command: str, args: list = None,
                 env: dict = None, timeout: int = 30):
        self.name = name
        self.command = command
        self.args = args or []
        self.env = env or {}
        self.timeout = timeout
        self.process: Optional[subprocess.Popen] = None
        self.tools: dict[str, MCPTool] = {}
        self._request_id = 0
        self._lock = threading.Lock()
        self._read_buffer = ""
        self._reader_thread: Optional[threading.Thread] = None
        self._pending_responses: dict[int, Any] = {}
        self._response_events: dict[int, threading.Event] = {}
        self._running = False

    def start(self) -> bool:
        """Spawn the MCP server process."""
        try:
            # Build full environment
            full_env = os.environ.copy()
            full_env.update(self.env)

            self.process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
                bufsize=0,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )

            self._running = True

            # Start reader thread for stdout
            self._reader_thread = threading.Thread(
                target=self._read_stdout,
                name=f"mcp-reader-{self.name}",
                daemon=True,
            )
            self._reader_thread.start()

            log.info("MCP server '%s' started (PID %d)", self.name, self.process.pid)
            return True

        except Exception as e:
            log.error("Failed to start MCP server '%s': %s", self.name, e)
            return False

    def initialize(self) -> bool:
        """Send the MCP initialize handshake."""
        result = self._send_request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "robin-agent",
                "version": "1.0.0",
            },
        })

        if result is None:
            log.error("MCP initialize failed for '%s'", self.name)
            return False

        # Send initialized notification
        self._send_notification("notifications/initialized", {})
        log.info("MCP server '%s' initialized: %s",
                 self.name, result.get("serverInfo", {}).get("name", "unknown"))
        return True

    def discover_tools(self) -> list[MCPTool]:
        """Discover all tools the server exposes."""
        result = self._send_request("tools/list", {})
        if result is None:
            log.warning("Tool discovery failed for '%s'", self.name)
            return []

        tools = []
        for tool_def in result.get("tools", []):
            tool = MCPTool(
                name=tool_def["name"],
                description=tool_def.get("description", ""),
                input_schema=tool_def.get("inputSchema", {}),
                server_name=self.name,
            )
            self.tools[tool.name] = tool
            tools.append(tool)

        log.info("Discovered %d tools from '%s': %s",
                 len(tools), self.name, [t.name for t in tools])
        return tools

    def call_tool(self, name: str, arguments: dict = None) -> MCPToolResult:
        """Call a tool on this server."""
        if name not in self.tools:
            return MCPToolResult(
                success=False,
                error=f"Unknown tool '{name}' on server '{self.name}'",
                is_error=True,
            )

        result = self._send_request("tools/call", {
            "name": name,
            "arguments": arguments or {},
        })

        if result is None:
            return MCPToolResult(
                success=False,
                error=f"Tool call '{name}' timed out or failed",
                is_error=True,
            )

        # Parse MCP tool result format
        content_parts = result.get("content", [])
        is_error = result.get("isError", False)

        # Combine content parts
        text_parts = []
        for part in content_parts:
            if part.get("type") == "text":
                text_parts.append(part.get("text", ""))
            elif part.get("type") == "image":
                text_parts.append(f"[Image: {part.get('mimeType', 'image')}]")
            else:
                text_parts.append(json.dumps(part))

        combined = "\n".join(text_parts)

        return MCPToolResult(
            success=not is_error,
            content=combined,
            error=combined if is_error else None,
            is_error=is_error,
        )

    def stop(self) -> None:
        """Stop the MCP server process."""
        self._running = False
        if self.process:
            try:
                self.process.stdin.close()
                self.process.terminate()
                self.process.wait(timeout=5)
            except Exception:
                try:
                    self.process.kill()
                except Exception:
                    pass
            log.info("MCP server '%s' stopped", self.name)

    # --- JSON-RPC Communication ---

    def _next_id(self) -> int:
        with self._lock:
            self._request_id += 1
            return self._request_id

    def _send_request(self, method: str, params: dict) -> Optional[dict]:
        """Send a JSON-RPC request and wait for the response."""
        req_id = self._next_id()
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        event = threading.Event()
        self._response_events[req_id] = event

        try:
            self._write_message(message)
        except Exception as e:
            log.error("Failed to send to '%s': %s", self.name, e)
            del self._response_events[req_id]
            return None

        # Wait for response
        if not event.wait(timeout=self.timeout):
            log.warning("Request %d to '%s' timed out (%s)",
                        req_id, self.name, method)
            del self._response_events[req_id]
            return None

        response = self._pending_responses.pop(req_id, None)
        del self._response_events[req_id]

        if response and "error" in response:
            log.error("RPC error from '%s': %s", self.name, response["error"])
            return None

        return response.get("result") if response else None

    def _send_notification(self, method: str, params: dict) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        message = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            self._write_message(message)
        except Exception as e:
            log.error("Failed to send notification to '%s': %s", self.name, e)

    def _write_message(self, message: dict) -> None:
        """Write a JSON-RPC message as newline-delimited JSON."""
        body = json.dumps(message)
        data = (body + "\n").encode("utf-8")

        if self.process and self.process.stdin:
            self.process.stdin.write(data)
            self.process.stdin.flush()

    def _read_stdout(self) -> None:
        """Background thread: read newline-delimited JSON-RPC messages from stdout."""
        while self._running and self.process and self.process.stdout:
            try:
                line = self.process.stdout.readline()
                if not line:
                    break

                line = line.strip()
                if not line:
                    continue

                try:
                    message = json.loads(line.decode("utf-8"))
                    self._handle_message(message)
                except json.JSONDecodeError as e:
                    log.warning("Invalid JSON from '%s': %s (line: %s)",
                                self.name, e, line[:200])

            except Exception as e:
                if self._running:
                    log.error("Reader error for '%s': %s", self.name, e)
                break

        log.debug("Reader thread for '%s' exiting", self.name)

    def _handle_message(self, message: dict) -> None:
        """Handle an incoming JSON-RPC message."""
        if "id" in message and "method" not in message:
            # This is a response
            req_id = message["id"]
            if req_id in self._response_events:
                self._pending_responses[req_id] = message
                self._response_events[req_id].set()
        elif "method" in message and "id" not in message:
            # This is a notification from the server
            log.debug("Notification from '%s': %s", self.name, message.get("method"))
        elif "method" in message and "id" in message:
            # This is a request from the server (e.g., sampling)
            log.debug("Server request from '%s': %s", self.name, message.get("method"))
            # Send empty response for now
            self._write_message({
                "jsonrpc": "2.0",
                "id": message["id"],
                "error": {
                    "code": -32601,
                    "message": "Method not supported by Robin client",
                },
            })


# ---------------------------------------------------------------------------
# MCP Server Registry
# ---------------------------------------------------------------------------

class MCPServerRegistry:
    """
    Manages all MCP server connections Robin can use.

    Reads server configurations from:
    1. robin-secrets.json (mcp_servers key) -- preferred
    2. Claude's own config -- fallback for discovering installed servers

    Robin can connect to servers on demand and discover their tools.
    """

    CLAUDE_CONFIG = Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json"

    def __init__(self, secrets: dict = None):
        self.servers: dict[str, MCPServerConnection] = {}
        self.all_tools: dict[str, MCPTool] = {}  # "server.tool" -> MCPTool
        self._configs = {}
        self._load_configs(secrets or {})

    def _load_configs(self, secrets: dict) -> None:
        """Load MCP server configurations."""
        # Source 1: robin-secrets.json mcp_servers
        if "mcp_servers" in secrets:
            for name, config in secrets["mcp_servers"].items():
                self._configs[name] = config
                log.info("Loaded MCP config from secrets: %s", name)

        # Source 2: Claude desktop config (fallback)
        if self.CLAUDE_CONFIG.exists():
            try:
                with open(self.CLAUDE_CONFIG) as f:
                    claude_config = json.load(f)
                for name, config in claude_config.get("mcpServers", {}).items():
                    if name not in self._configs:
                        self._configs[name] = config
                        log.info("Loaded MCP config from Claude: %s", name)
            except Exception as e:
                log.warning("Failed to read Claude config: %s", e)

        # Source 3: Built-in Windows-MCP config (if available)
        wmcp_path = self._find_windows_mcp()
        if wmcp_path and "windows-mcp" not in self._configs:
            self._configs["windows-mcp"] = {
                "command": str(wmcp_path),
                "args": [],
            }
            log.info("Found Windows-MCP at %s", wmcp_path)

        log.info("MCP registry: %d servers configured: %s",
                 len(self._configs), list(self._configs.keys()))

    def _find_windows_mcp(self) -> Optional[Path]:
        """Find the Windows-MCP executable."""
        # Check common locations
        candidates = [
            Path(os.environ.get("APPDATA", "")) / "Claude" / "Claude Extensions",
        ]

        for base in candidates:
            if base.exists():
                for p in base.rglob("windows-mcp.exe"):
                    return p
        return None

    def connect(self, server_name: str) -> bool:
        """Connect to a specific MCP server."""
        if server_name in self.servers:
            log.info("Already connected to '%s'", server_name)
            return True

        config = self._configs.get(server_name)
        if not config:
            log.error("No config for MCP server '%s'", server_name)
            return False

        conn = MCPServerConnection(
            name=server_name,
            command=config["command"],
            args=config.get("args", []),
            env=config.get("env", {}),
            timeout=config.get("timeout", 60),
        )

        if not conn.start():
            return False

        # Give the server a moment to initialize
        time.sleep(1)

        if not conn.initialize():
            conn.stop()
            return False

        # Discover tools
        tools = conn.discover_tools()
        for tool in tools:
            key = f"{server_name}.{tool.name}"
            self.all_tools[key] = tool

        self.servers[server_name] = conn
        log.info("Connected to '%s' with %d tools", server_name, len(tools))
        return True

    def connect_all(self) -> dict[str, bool]:
        """Connect to all configured servers."""
        results = {}
        for name in self._configs:
            results[name] = self.connect(name)
        return results

    def call_tool(self, tool_key: str, arguments: dict = None) -> MCPToolResult:
        """
        Call a tool by its full key (server_name.tool_name).

        Example: call_tool("windows-mcp.Shell", {"command": "dir"})
        """
        parts = tool_key.split(".", 1)
        if len(parts) != 2:
            return MCPToolResult(
                success=False,
                error=f"Invalid tool key '{tool_key}' -- use 'server.tool' format",
                is_error=True,
            )

        server_name, tool_name = parts

        if server_name not in self.servers:
            # Try to connect on demand
            if not self.connect(server_name):
                return MCPToolResult(
                    success=False,
                    error=f"Cannot connect to server '{server_name}'",
                    is_error=True,
                )

        return self.servers[server_name].call_tool(tool_name, arguments)

    def get_tools_prompt(self, servers: list[str] = None) -> str:
        """Generate a tools description for DeepSeek's system prompt."""
        lines = ["# Available Tools\n"]
        tools = self.all_tools.values()

        if servers:
            tools = [t for t in tools if t.server_name in servers]

        for tool in sorted(tools, key=lambda t: f"{t.server_name}.{t.name}"):
            lines.append(tool.to_prompt_description())
            lines.append("")

        return "\n".join(lines)

    def get_tool_names(self) -> list[str]:
        """Get all available tool keys."""
        return list(self.all_tools.keys())

    def disconnect_all(self) -> None:
        """Stop all server connections."""
        for name, conn in self.servers.items():
            conn.stop()
        self.servers.clear()
        self.all_tools.clear()
        log.info("All MCP servers disconnected")
