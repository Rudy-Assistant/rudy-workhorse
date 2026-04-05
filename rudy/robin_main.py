#!/usr/bin/env python3

"""
Robin Main -- The unified orchestrator for Robin's autonomous operation.

This is the single entry point that runs on Oracle. It ties together:
- Sentinel (boot health, service recovery)
- Presence Monitor (HID tracking, handoff detection)
- Bridge (Alfred task polling)
- Night Shift (proactive improvement when Batman is away)
- Local Chat (Robin's own LLM-powered reasoning via Ollama)

Usage:
    python -m rudy.robin_main                    # Full startup
    python -m rudy.robin_main --night-shift      # Force night shift mode

Note: --nightwatch mode removed in S118, replaced by perpetual orchestrator cycle.
    python -m rudy.robin_main --status            # Show all subsystem status
    python -m rudy.robin_main --chat "query"      # Direct Robin chat
    python -m rudy.robin_main --agent "task"      # Agent mode (MCP tools)
    python -m rudy.robin_main --mcp-tools         # List available MCP tools
"""

import json
import logging
import os
import signal
import sys
import threading
import time
from datetime import datetime, timezone
from typing import Optional

# ---------------------------------------------------------------------------
# Paths (canonical — all from rudy.paths)
# ---------------------------------------------------------------------------

from rudy.paths import (  # noqa: E402
    RUDY_DATA,
    RUDY_LOGS,
    ROBIN_STATE,
)

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [Robin] %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(RUDY_LOGS / "robin-main.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("robin_main")


# ---------------------------------------------------------------------------
# Secure Config Loader
# ---------------------------------------------------------------------------

class SecureConfig:
    """
    Loads secrets from a local config file that NEVER leaves Oracle.

    Config file: RUDY_DATA / "robin-secrets.json" (resolved at runtime via rudy.paths)
    This file is .gitignored and lives only on Oracle's disk.
    Robin reads it. Alfred never sees the contents.

    Expected format:
    {
        "github_pat": "ghp_...",
        "notion_token": "ntn_...",
        "ollama_host": "http://localhost:11434",
        "zoho_imap_password": "..."
    }
    """

    SECRETS_FILE = RUDY_DATA / "robin-secrets.json"
    _cache = None
    _cache_time = 0

    @classmethod
    def load(cls) -> dict:
        """Load secrets with 60-second cache."""
        now = time.time()
        if cls._cache and (now - cls._cache_time) < 60:
            return cls._cache

        if not cls.SECRETS_FILE.exists():
            log.warning("No secrets file at %s -- creating template", cls.SECRETS_FILE)
            cls._create_template()
            return {}

        try:
            with open(cls.SECRETS_FILE) as f:
                cls._cache = json.load(f)
                cls._cache_time = now
                return cls._cache
        except (json.JSONDecodeError, OSError) as e:
            log.error("Failed to load secrets: %s", e)
            return {}

    @classmethod
    def get(cls, key: str, default: str = "") -> str:
        """Get a single secret."""
        return cls.load().get(key, default)

    @classmethod
    def _create_template(cls) -> None:
        """Create a template secrets file for Batman to fill in."""
        template = {
            "github_pat": "PASTE_YOUR_GITHUB_PAT_HERE",
            "notion_token": "PASTE_YOUR_NOTION_TOKEN_HERE",
            "ollama_host": "http://localhost:11434",
            "zoho_imap_password": "",
            "_instructions": (
                "Fill in the values above. This file stays on Oracle only. "
                "Never push to git. Robin reads it locally. Alfred never sees it."
            ),
        }
        with open(cls.SECRETS_FILE, "w") as f:
            json.dump(template, f, indent=2)
        log.info("Created secrets template at %s", cls.SECRETS_FILE)


# ---------------------------------------------------------------------------
# Local Chat -- Robin's Own Brain
# ---------------------------------------------------------------------------

class RobinChat:
    """
    Robin's local LLM chat interface via Ollama.

    Robin can reason independently using a local model. This is Robin's
    own thought process -- not mediated by Alfred or the cloud.

    Robin can also talk to Alfred via the GitHub task queue when needed,
    giving Robin two simultaneous conversation channels:
    1. Local LLM (instant, private, always available)
    2. Alfred via GitHub (async, cloud-powered, for complex tasks)
    """

    def __init__(self):
        self.ollama_host = SecureConfig.get("ollama_host", "http://localhost:11434")
        self.model = SecureConfig.get("ollama_model", "deepseek-r1:8b")
        fallbacks = SecureConfig.get("ollama_fallback_models", None)
        self.fallback_models = fallbacks if isinstance(fallbacks, list) else ["llama3.2:3b", "phi3", "mistral"]
        self.conversation_history = []
        self.system_prompt = self._build_system_prompt()

    def _build_system_prompt(self) -> str:
        return (
            "You are Robin, the local AI agent for the Batcave system. "
            "You run on Oracle (the always-on Workhorse PC). "
            "Your role: bridge between Alfred (cloud AI) and the physical world. "
            "You have Batman's full authorization to act on his behalf. "
            "You can enter passwords, configure tokens, handle 2FA, manage services. "
            "You are the Batcave's immune system -- when Batman is away and Alfred is offline, "
            "you are the sole intelligence keeping everything running. "
            "Be concise. Act decisively. Report results, not plans."
        )

    def chat(self, message: str, context: Optional[dict] = None) -> str:
        """Send a message to Robin's local LLM and get a response."""
        import urllib.request
        import urllib.error

        # Build messages
        messages = [{"role": "system", "content": self.system_prompt}]

        # Add context if provided
        if context:
            ctx_str = json.dumps(context, indent=2)
            messages.append({
                "role": "system",
                "content": f"Current system context:\n{ctx_str}",
            })

        # Add conversation history (last 10 exchanges)
        messages.extend(self.conversation_history[-20:])
        messages.append({"role": "user", "content": message})

        # Try primary model, then fallbacks
        for model in [self.model] + self.fallback_models:
            try:
                payload = json.dumps({
                    "model": model,
                    "messages": messages,
                    "stream": False,
                }).encode()

                req = urllib.request.Request(
                    f"{self.ollama_host}/api/chat",
                    data=payload,
                    headers={"Content-Type": "application/json"},
                )
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = json.loads(resp.read())
                    reply = result["message"]["content"]

                    # Update history
                    self.conversation_history.append({"role": "user", "content": message})
                    self.conversation_history.append({"role": "assistant", "content": reply})

                    return reply

            except urllib.error.URLError:
                log.warning("Ollama model %s unavailable, trying next", model)
                continue
            except Exception as e:
                log.error("Chat error with %s: %s", model, e)
                continue

        return "[Robin LLM offline -- all models unavailable]"

    def reason_about(self, situation: str, options: list = None) -> str:
        """Robin reasons about a situation and decides what to do."""
        prompt = f"Situation: {situation}\n"
        if options:
            prompt += "Options:\n" + "\n".join(f"- {o}" for o in options)
            prompt += "\n\nWhich option and why? Be decisive."
        else:
            prompt += "What should I do? Be decisive."
        return self.chat(prompt)

    def delegate_to_alfred(self, task_description: str, priority: str = "medium") -> dict:
        """
        Create a task for Alfred via the GitHub task queue.
        This is Robin talking TO Alfred -- the reverse direction.
        """
        import urllib.request
        import urllib.error

        pat = SecureConfig.get("github_pat")
        if not pat or pat.startswith("PASTE"):
            log.error("No GitHub PAT configured -- cannot delegate to Alfred")
            return {"error": "no_pat"}

        task_id = f"robin-to-alfred-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        content = (
            f"---\n"
            f"task: {task_id}\n"
            f"from: robin\n"
            f"to: alfred\n"
            f"priority: {priority}\n"
            f"status: pending\n"
            f"created: {datetime.now().isoformat()}\n"
            f"---\n\n"
            f"# Robin -> Alfred Task\n\n"
            f"{task_description}\n"
        )

        import base64
        encoded = base64.b64encode(content.encode()).decode()

        payload = json.dumps({
            "message": f"Robin task for Alfred: {task_id}",
            "content": encoded,
        }).encode()

        try:
            req = urllib.request.Request(
                f"https://api.github.com/repos/Rudy-Assistant/alfred-skills/contents/docs/robin-tasks/{task_id}.md",
                data=payload,
                headers={
                    "Authorization": f"Bearer {pat}",
                    "Accept": "application/vnd.github.v3+json",
                    "Content-Type": "application/json",
                },
                method="PUT",
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                result = json.loads(resp.read())
                log.info("Delegated to Alfred: %s", task_id)
                return {"task_id": task_id, "commit": result.get("commit", {}).get("sha")}
        except Exception as e:
            log.error("Failed to delegate to Alfred: %s", e)
            return {"error": str(e)}


# ---------------------------------------------------------------------------
# Night Shift Runner
# ---------------------------------------------------------------------------

class NightShiftRunner:
    """
    Robin's autonomous night shift operation.

    When Batman is away (detected by PresenceMonitor or explicit handoff),
    Robin enters night shift mode and works through a priority queue:

    1. Health checks (sentinel boot cascade)
    2. Pending Alfred tasks (bridge poll)
    3. System maintenance (updates, cleanup, log rotation)
    4. Proactive improvement (dependency updates, security checks)
    5. Morning briefing preparation

    Robin uses local LLM to reason about what to do and how to handle
    unexpected situations.
    """

    def __init__(self):
        self.chat = RobinChat()
        self.state = {"phase": "idle", "tasks_completed": 0, "errors": []}

    def run(self) -> dict:
        """Execute a full night shift cycle."""
        log.info("=== NIGHT SHIFT STARTING ===")
        self.state["started"] = datetime.now().isoformat()
        self.state["phase"] = "health_check"

        # Phase 1: Health check
        log.info("[Night Shift] Phase 1: Health check")
        try:
            from rudy.agents.robin_sentinel import run_boot_sequence
            boot_result = run_boot_sequence()
            self.state["health"] = boot_result
            log.info("Health check: %s", boot_result.get("overall", "unknown"))
        except Exception as e:
            log.error("Health check failed: %s", e)
            self.state["errors"].append(f"health_check: {e}")

        # Phase 2: Poll for Alfred tasks
        self.state["phase"] = "task_poll"
        log.info("[Night Shift] Phase 2: Polling for tasks")
        try:
            from rudy.agents.robin_bridge import RobinBridge
            bridge = RobinBridge()
            poll_result = bridge.poll_and_execute()
            self.state["tasks_completed"] += poll_result.get("tasks_completed", 0)
            log.info("Tasks completed: %d", poll_result.get("tasks_completed", 0))
        except Exception as e:
            log.error("Task poll failed: %s", e)
            self.state["errors"].append(f"task_poll: {e}")

        # Phase 3: System maintenance
        self.state["phase"] = "maintenance"
        log.info("[Night Shift] Phase 3: System maintenance")
        self._run_maintenance()

        # Phase 4: Proactive improvement (Robin reasons about what to do)
        self.state["phase"] = "proactive"
        log.info("[Night Shift] Phase 4: Proactive improvement")
        self._run_proactive()

        # Phase 5: Morning briefing
        self.state["phase"] = "briefing"
        log.info("[Night Shift] Phase 5: Preparing morning briefing")
        self._prepare_briefing()

        self.state["phase"] = "complete"
        self.state["completed"] = datetime.now().isoformat()
        log.info("=== NIGHT SHIFT COMPLETE === (tasks: %d, errors: %d)",
                 self.state["tasks_completed"], len(self.state["errors"]))

        # Save night shift report
        report_file = RUDY_LOGS / f"nightshift-{datetime.now().strftime('%Y%m%d')}.json"
        with open(report_file, "w") as f:
            json.dump(self.state, f, indent=2)

        return self.state

    def _run_maintenance(self) -> None:
        """System maintenance tasks."""
        tasks = [
            ("Log rotation", self._rotate_logs),
            ("Temp cleanup", self._cleanup_temp),
        ]

        for name, func in tasks:
            try:
                func()
                log.info("Maintenance: %s OK", name)
                self.state["tasks_completed"] += 1
            except Exception as e:
                log.warning("Maintenance %s failed: %s", name, e)

    def _rotate_logs(self) -> None:
        """Rotate logs over 10MB."""
        for log_file in RUDY_LOGS.glob("*.log"):
            if log_file.stat().st_size > 10 * 1024 * 1024:
                archive = log_file.with_suffix(f".{datetime.now().strftime('%Y%m%d')}.log")
                log_file.rename(archive)
                log_file.touch()

    def _cleanup_temp(self) -> None:
        """Clean up old temp files."""
        import shutil
        temp_dirs = [
            RUDY_DATA / "tmp",
        ]
        for d in temp_dirs:
            if d.exists():
                for f in d.iterdir():
                    age_hours = (datetime.now() - datetime.fromtimestamp(f.stat().st_mtime)).total_seconds() / 3600
                    if age_hours > 24:
                        if f.is_file():
                            f.unlink()
                        elif f.is_dir():
                            shutil.rmtree(f, ignore_errors=True)

    def _run_proactive(self) -> None:
        """Robin reasons about what proactive improvements to make -- with MCP tools if available."""
        # Gather context
        context = {
            "time": datetime.now().isoformat(),
            "health": self.state.get("health", {}),
            "errors_tonight": self.state["errors"],
            "tasks_done": self.state["tasks_completed"],
        }

        # Try agent mode (MCP-powered) first, fall back to chat-only
        try:
            from rudy.robin_mcp_client import MCPServerRegistry
            from rudy.robin_agent_loader import RobinAgent

            secrets = SecureConfig.load()
            registry = MCPServerRegistry(secrets)
            connected = registry.connect_all()

            if any(connected.values()):
                log.info("Night shift proactive: using MCP agent (%d servers)",
                         sum(1 for v in connected.values() if v))
                agent = RobinAgent(
                    registry=registry,
                    ollama_host=SecureConfig.get("ollama_host", "http://localhost:11434"),
                    model=SecureConfig.get("ollama_model", "qwen2.5:7b"),
                    max_steps=10,
                )
                result = agent.run(
                    "Night shift proactive phase. Check system health, review recent "
                    "error logs, and run any quick maintenance tasks. "
                    "Report what you found and what you did.",
                    context=context,
                )
                log.info("Agent proactive result: %s (steps=%d, tools=%d)",
                         result.final_answer[:200],
                         result.total_steps, result.total_tool_calls)
                self.state["proactive_result"] = {
                    "mode": "agent",
                    "steps": result.total_steps,
                    "tool_calls": result.total_tool_calls,
                    "summary": result.final_answer[:1000],
                }
                registry.disconnect_all()
                return
            else:
                registry.disconnect_all()
                log.info("No MCP servers available, falling back to chat-only")
        except ImportError:
            log.info("MCP agent not available, using chat-only mode")
        except Exception as e:
            log.warning("MCP agent failed, falling back to chat: %s", e)

        # Fallback: chat-only reasoning
        ctx_summary = json.dumps(context, indent=2, default=str)
        decision = self.chat.reason_about(
            f"Night shift proactive phase. Context:\n{ctx_summary}\n"
            "What maintenance or improvements should I do right now?",
            options=[
                "Check for Python package updates in rudy-workhorse",
                "Review recent error logs for patterns",
                "Verify all scheduled tasks are registered",
                "Run a quick network connectivity check",
                "Skip -- nothing urgent",
            ],
        )
        log.info("Robin's proactive decision: %s", decision[:200])

    def _prepare_briefing(self) -> None:
        """Prepare a morning briefing for Batman."""
        briefing = {
            "generated": datetime.now().isoformat(),
            "night_shift_summary": {
                "tasks_completed": self.state["tasks_completed"],
                "errors": self.state["errors"],
                "health": self.state.get("health", {}),
            },
            "recommendations": [],
        }

        # Ask Robin to summarize
        summary = self.chat.chat(
            "Summarize tonight's night shift in 3-4 bullet points for Batman's morning briefing. "
            f"Tasks completed: {self.state['tasks_completed']}. "
            f"Errors: {len(self.state['errors'])}. "
            "Be concise and actionable."
        )
        briefing["robin_summary"] = summary

        # Write briefing
        briefing_file = RUDY_LOGS / "morning-briefing-draft.json"
        with open(briefing_file, "w") as f:
            json.dump(briefing, f, indent=2)
        log.info("Morning briefing saved")

        # Also log to Notion if token available
        notion_token = SecureConfig.get("notion_token")
        if notion_token and not notion_token.startswith("PASTE"):
            try:
                from rudy.tools.notion_client import NotionClient
                nc = NotionClient(token=notion_token)
                nc.append_health_log(json.dumps(briefing, indent=2))
            except Exception as e:
                log.warning("Notion briefing log failed: %s", e)


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------

class RobinOrchestrator:
    """
    The main Robin process. Runs all subsystems as threads.

    This is the single process that gets registered as a scheduled task.
    It manages:
    - Presence monitoring (HID tracking)
    - Sentinel health checks (periodic)
    - Bridge polling (when in active/nightshift mode)
    - Night shift execution (when triggered)
    - Local chat availability (always)
    """

    def __init__(self):
        self.running = False
        self.chat = RobinChat()
        self.threads = {}
        self.state = {
            "started": datetime.now().isoformat(),
            "mode": "initializing",
            "subsystems": {},
        }

    def start(self) -> None:
        """Start all Robin subsystems."""
        self.running = True
        log.info("=== ROBIN STARTING ===")
        log.info("Oracle: %s", os.environ.get("COMPUTERNAME", "unknown"))
        log.info("Config: %s", "loaded" if SecureConfig.load() else "missing")

        # Register signal handlers
        signal.signal(signal.SIGINT, self._shutdown)
        signal.signal(signal.SIGTERM, self._shutdown)

        # Run boot sequence first
        log.info("Running boot sequence...")
        try:
            from rudy.agents.robin_sentinel import run_boot_sequence
            boot = run_boot_sequence()
            self.state["boot"] = boot
            log.info("Boot: %s", boot.get("overall", "unknown"))
        except Exception as e:
            log.error("Boot sequence failed: %s (continuing anyway)", e)

        # Start presence monitor thread
        self._start_thread("presence", self._run_presence)

        # Start bridge poller thread
        self._start_thread("bridge", self._run_bridge_poller)

        # Start health check thread
        self._start_thread("health", self._run_health_loop)

        self.state["mode"] = "running"
        log.info("=== ROBIN ONLINE === (all subsystems started)")

        # Main loop -- keep running
        self._save_state()
        while self.running:
            time.sleep(10)
            self._save_state()

    def _start_thread(self, name: str, target) -> None:
        """Start a daemon thread for a subsystem."""
        t = threading.Thread(target=target, name=f"robin-{name}", daemon=True)
        t.start()
        self.threads[name] = t
        self.state["subsystems"][name] = "running"
        log.info("Started subsystem: %s", name)

    def _run_presence(self) -> None:
        """Presence monitor thread."""
        try:
            from rudy.agents.robin_presence import PresenceMonitor, RobinMode
            monitor = PresenceMonitor()
            prev_mode = None

            while self.running:
                state = monitor.evaluate()
                mode = state.get("robin_mode")

                if mode != prev_mode:
                    log.info("Presence: mode changed to %s", mode)
                    prev_mode = mode

                    # Trigger night shift (respects killswitch S116)
                    if mode == RobinMode.NIGHTSHIFT.value:
                        _ks_active = False
                        try:
                            from rudy.robin_killswitch import is_killed
                            _ks_active = is_killed()
                        except ImportError:
                            pass
                        if _ks_active:
                            log.info("KILLSWITCH ACTIVE -- night shift blocked")
                        else:
                            log.info("Triggering night shift")
                            threading.Thread(
                                target=self._run_night_shift,
                                name="robin-nightshift",
                                daemon=True,
                            ).start()

                self.state["presence"] = state
                time.sleep(30)

        except Exception as e:
            log.error("Presence monitor crashed: %s", e)
            self.state["subsystems"]["presence"] = f"error: {e}"

    def _run_bridge_poller(self) -> None:
        """Bridge poller thread -- checks for Alfred tasks periodically."""
        while self.running:
            try:
                # Only poll when Robin is in active or nightshift mode
                presence = self.state.get("presence", {})
                mode = presence.get("robin_mode", "standby")

                if mode in ("active", "nightshift"):
                    from rudy.agents.robin_bridge import RobinBridge
                    bridge = RobinBridge()
                    result = bridge.poll_and_execute()
                    if result.get("tasks_completed", 0) > 0:
                        log.info("Bridge: completed %d tasks", result["tasks_completed"])
                    self.state["last_bridge_poll"] = datetime.now().isoformat()

                time.sleep(300)  # Poll every 5 minutes

            except Exception as e:
                log.error("Bridge poller error: %s", e)
                time.sleep(60)

    def _run_health_loop(self) -> None:
        """Periodic health checks."""
        while self.running:
            try:
                from rudy.agents.robin_sentinel import run_boot_sequence
                health = run_boot_sequence()
                self.state["health"] = health
                self.state["last_health_check"] = datetime.now().isoformat()
            except Exception as e:
                log.error("Health check error: %s", e)

            time.sleep(1800)  # Every 30 minutes

    def _run_night_shift(self) -> None:
        """Execute a night shift."""
        try:
            ns = NightShiftRunner()
            result = ns.run()
            self.state["last_night_shift"] = result
        except Exception as e:
            log.error("Night shift failed: %s", e)

    def _save_state(self) -> None:
        """Persist Robin's state."""
        try:
            tmp = ROBIN_STATE.with_suffix(".tmp")
            with open(tmp, "w") as f:
                json.dump(self.state, f, indent=2, default=str)
            tmp.replace(ROBIN_STATE)
        except Exception:
            pass

    def _shutdown(self, signum=None, frame=None) -> None:
        """Graceful shutdown."""
        log.info("Robin shutting down...")
        self.running = False
        self.state["mode"] = "shutdown"
        self._save_state()

    @staticmethod
    def get_status() -> dict:
        """Get current Robin status from state file."""
        if ROBIN_STATE.exists():
            try:
                return json.loads(ROBIN_STATE.read_text())
            except (json.JSONDecodeError, OSError):
                pass
        return {"mode": "not running"}


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------



def main() -> None:
    args = sys.argv[1:]

    if "--status" in args:
        status = RobinOrchestrator.get_status()
        print(json.dumps(status, indent=2, default=str))
        return

    if "--night-shift" in args:
        log.info("Forcing night shift mode")
        ns = NightShiftRunner()
        result = ns.run()
        print(json.dumps(result, indent=2, default=str))
        return

    if "--chat" in args:
        idx = args.index("--chat")
        message = " ".join(args[idx + 1:]) if idx + 1 < len(args) else "status report"
        chat = RobinChat()
        reply = chat.chat(message)
        print(f"Robin: {reply}")
        return

    if "--delegate" in args:
        idx = args.index("--delegate")
        task = " ".join(args[idx + 1:])
        chat = RobinChat()
        result = chat.delegate_to_alfred(task)
        print(json.dumps(result, indent=2))
        return

    if "--agent" in args:
        idx = args.index("--agent")
        task = " ".join(args[idx + 1:]) if idx + 1 < len(args) else "Report system status"
        log.info("Agent mode: %s", task)
        try:
            from rudy.robin_mcp_client import MCPServerRegistry
            from rudy.robin_agent_loader import RobinAgent
            secrets = SecureConfig.load()
            registry = MCPServerRegistry(secrets)
            # Connect to available servers
            connect_results = registry.connect_all()
            for name, ok in connect_results.items():
                log.info("MCP %s: %s", name, "connected" if ok else "FAILED")
            agent = RobinAgent(
                registry=registry,
                ollama_host=SecureConfig.get("ollama_host", "http://localhost:11434"),
                model=SecureConfig.get("ollama_model", "qwen2.5:7b"),
            )
            result = agent.run_with_report(task)
            print(json.dumps(result, indent=2, default=str))
            registry.disconnect_all()
        except Exception as e:
            log.error("Agent failed: %s", e)
            print(json.dumps({"error": str(e)}, indent=2))
        return

    if "--log" in args:
        idx = args.index("--log")
        message = " ".join(args[idx + 1:]) if idx + 1 < len(args) else "Robin check-in"
        log.info("Log mode: %s", message)
        try:
            from rudy.robin_logger import log_task_to_notion
            ok = log_task_to_notion(
                task="Manual log entry",
                success=True,
                final_answer=message,
            )
            print("Logged to Notion" if ok else "Failed to log to Notion")
        except Exception as e:
            log.error("Log failed: %s", e)
            print(f"Error: {e}")
        return

    if "--mcp-tools" in args:
        log.info("Listing available MCP tools")
        try:
            from rudy.robin_mcp_client import MCPServerRegistry
            secrets = SecureConfig.load()
            registry = MCPServerRegistry(secrets)
            results = registry.connect_all()
            for name, ok in results.items():
                status = "OK" if ok else "FAILED"
                print(f"  {name}: {status}")
                if ok:
                    for tool_name in registry.servers[name].tools:
                        desc = registry.servers[name].tools[tool_name].description[:80]
                        print(f"    - {tool_name}: {desc}")
            registry.disconnect_all()
        except Exception as e:
            log.error("MCP tool listing failed: %s", e)
        return

    # Default: start the full orchestrator
    robin = RobinOrchestrator()
    robin.start()


if __name__ == "__main__":
    main()
