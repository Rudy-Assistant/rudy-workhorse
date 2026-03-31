#!/usr/bin/env python3
"""Robin Chat Console -- Terminal-based chat with Robin, no internet required.

A local, headless interface for Batman to talk to Robin directly over
the terminal. Works over SSH, no GUI dependencies, no Cowork session.

Features:
    - Natural language chat forwarded to Ollama (local LLM)
    - Slash commands: /status, /directive, /delegate, /health, /logs,
      /journal, /bridge, /inbox, /quit
    - Direct taskqueue access for delegating work
    - View bridge heartbeat, delegation history, autonomy journal
    - Colored output (ANSI) with graceful fallback

Usage:
    python -m rudy.robin_chat_console
    python rudy/robin_chat_console.py

Lucius Gate: LG-032 - No new dependencies. Uses stdlib + existing modules.
"""

import json
import logging
import os
import readline  # noqa: F401 -- enables line editing in input()
import sys
import time as _time
import urllib.error
import urllib.request

from rudy.paths import RUDY_DATA, RUDY_LOGS

log = logging.getLogger("robin.chat_console")

# ---------------------------------------------------------------------------
# ANSI Colors (degrade gracefully on dumb terminals)
# ---------------------------------------------------------------------------

_COLOR = os.environ.get("TERM", "") != "dumb" and sys.stdout.isatty()


def _c(code: str, text: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def _bold(t: str) -> str:
    return _c("1", t)


def _green(t: str) -> str:
    return _c("32", t)


def _yellow(t: str) -> str:
    return _c("33", t)


def _red(t: str) -> str:
    return _c("31", t)


def _cyan(t: str) -> str:
    return _c("36", t)


def _dim(t: str) -> str:
    return _c("2", t)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SECRETS_FILE = RUDY_DATA / "robin-secrets.json"
HEARTBEAT_FILE = RUDY_DATA / "bridge-heartbeat.json"
INITIATIVE_JOURNAL = RUDY_DATA / "robin-initiative-journal.json"
HANDOFF_LOG = RUDY_LOGS / "alfred-robin-handoffs.json"
COORD_DIR = RUDY_DATA / "coordination"
ALFRED_INBOX = RUDY_DATA / "alfred-inbox"
ROBIN_INBOX = RUDY_DATA / "robin-inbox"


def _load_config() -> dict:
    defaults = {
        "ollama_host": "http://localhost:11434",
        "ollama_model": "qwen2.5:7b",
        "ollama_fallback_models": ["deepseek-r1:8b", "llama3.2:3b"],
    }
    try:
        with open(SECRETS_FILE) as f:
            cfg = json.load(f)
        for k, v in defaults.items():
            cfg.setdefault(k, v)
        return cfg
    except Exception:
        return defaults


# ---------------------------------------------------------------------------
# Ollama Chat
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "You are Robin, the Batcave's local AI assistant running on Oracle. "
    "You help Batman (Chris) with system management, development tasks, "
    "and Batcave operations. Be concise, technical, and proactive. "
    "If you don't know something, say so. Never fabricate information."
)


def _ollama_chat(
    messages: list,
    config: dict,
    stream: bool = True,
) -> str:
    """Send chat messages to Ollama and return the response.

    If stream=True, prints tokens as they arrive and returns full text.
    """
    host = config.get("ollama_host", "http://localhost:11434")
    model = config.get("ollama_model", "qwen2.5:7b")

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "stream": stream,
    }).encode()

    req = urllib.request.Request(
        f"{host}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
    )

    try:
        with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310
            if stream:
                full_text = []
                sys.stdout.write(_cyan("Robin: "))
                sys.stdout.flush()
                for line in resp:
                    if not line.strip():
                        continue
                    chunk = json.loads(line)
                    token = chunk.get("message", {}).get("content", "")
                    if token:
                        sys.stdout.write(token)
                        sys.stdout.flush()
                        full_text.append(token)
                    if chunk.get("done"):
                        break
                sys.stdout.write("\n")
                return "".join(full_text)
            else:
                result = json.loads(resp.read().decode())
                return result.get("message", {}).get("content", "")
    except urllib.error.URLError as e:
        return f"[Ollama unavailable: {e}]"
    except Exception as e:
        return f"[Chat error: {e}]"


def _ollama_available(config: dict) -> bool:
    """Quick check if Ollama is responding."""
    host = config.get("ollama_host", "http://localhost:11434")
    try:
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310
            return resp.status == 200
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Slash Commands
# ---------------------------------------------------------------------------

def _cmd_status(config: dict) -> None:
    """Show Robin's current status."""
    print(_bold("\n--- Robin Status ---"))

    # Ollama
    if _ollama_available(config):
        print(_green("  Ollama: ") + f"online ({config.get('ollama_model', '?')})")
    else:
        print(_red("  Ollama: ") + "offline")

    # Bridge heartbeat
    if HEARTBEAT_FILE.exists():
        try:
            hb = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
            ts = hb.get("timestamp", "?")
            status = hb.get("status", "?")
            robin_id = hb.get("robin_id", "?")
            print(_green("  Bridge: ") + f"{status} (id={robin_id}, last={ts})")
        except Exception:
            print(_yellow("  Bridge: ") + "heartbeat unreadable")
    else:
        print(_red("  Bridge: ") + "no heartbeat file")

    # Active directive
    directive_file = COORD_DIR / "active-directive.json"
    if directive_file.exists():
        try:
            d = json.loads(directive_file.read_text(encoding="utf-8"))
            if d.get("status") == "active":
                expires = d.get("expires_at", "?")
                print(_yellow("  Directive: ") + f"ACTIVE - {d.get('directive', '?')[:60]}")
                print(f"             Expires: {expires}")
            else:
                print(_dim(f"  Directive: {d.get('status', 'none')}"))
        except Exception:
            print(_dim("  Directive: none"))
    else:
        print(_dim("  Directive: none"))

    # Coordination
    alfred_msgs = len(list(ALFRED_INBOX.glob("*.json"))) if ALFRED_INBOX.exists() else 0
    robin_msgs = len(list(ROBIN_INBOX.glob("*.json"))) if ROBIN_INBOX.exists() else 0
    print(f"  Alfred inbox: {alfred_msgs} msgs | Robin inbox: {robin_msgs} msgs")
    print()


def _cmd_health(config: dict) -> None:
    """Run a quick system health check."""
    print(_bold("\n--- Health Check ---"))

    # Ollama
    host = config.get("ollama_host", "http://localhost:11434")
    try:
        req = urllib.request.Request(f"{host}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:  # nosec B310
            models = json.loads(resp.read()).get("models", [])
        names = [m.get("name", "?") for m in models]
        print(_green("  Ollama: ") + f"{len(models)} models: {', '.join(names[:5])}")
    except Exception as e:
        print(_red("  Ollama: ") + f"error - {e}")

    # Disk
    try:
        import shutil
        usage = shutil.disk_usage("C:\\" if os.name == "nt" else "/")
        free_gb = usage.free / (1024**3)
        total_gb = usage.total / (1024**3)
        pct = (usage.used / usage.total) * 100
        color = _green if pct < 80 else (_yellow if pct < 90 else _red)
        print(color("  Disk: ") + f"{free_gb:.1f}GB free / {total_gb:.1f}GB total ({pct:.0f}% used)")
    except Exception:
        print(_dim("  Disk: check failed"))

    # Bridge
    if HEARTBEAT_FILE.exists():
        try:
            hb = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
            age = (_time.time() - _time.mktime(
                _time.strptime(hb["timestamp"][:19], "%Y-%m-%dT%H:%M:%S")
            ))
            color = _green if age < 120 else (_yellow if age < 300 else _red)
            print(color("  Bridge: ") + f"heartbeat {age:.0f}s ago")
        except Exception:
            print(_yellow("  Bridge: ") + "heartbeat parse error")
    else:
        print(_red("  Bridge: ") + "no heartbeat")

    print()


def _cmd_directive(args: str) -> None:
    """Create a directive for Robin."""
    if not args.strip():
        # Show current directive
        directive_file = COORD_DIR / "active-directive.json"
        if directive_file.exists():
            try:
                d = json.loads(directive_file.read_text(encoding="utf-8"))
                print(json.dumps(d, indent=2))
            except Exception:
                print(_dim("No readable directive."))
        else:
            print(_dim("No active directive."))
        return

    # Create new directive
    try:
        from rudy.robin_autonomy import DirectiveTracker
        # Parse hours if provided: "/directive 2h Run security audit"
        parts = args.strip().split(None, 1)
        hours = 2.0
        text = args.strip()
        if parts and parts[0].endswith("h"):
            try:
                hours = float(parts[0][:-1])
                text = parts[1] if len(parts) > 1 else "General work"
            except ValueError:
                pass
        d = DirectiveTracker.create_directive(text, hours)
        print(_green("Directive created: ") + f"{text[:60]} ({hours}h)")
    except Exception as e:
        print(_red(f"Failed: {e}"))


def _cmd_delegate(args: str) -> None:
    """Delegate a task to Robin via the bridge."""
    if not args.strip():
        print("Usage: /delegate <type> [--command <cmd>]")
        print("Types: health_check, security_scan, shell")
        return

    parts = args.strip().split()
    task_type = parts[0]
    command = None
    if "--command" in parts:
        idx = parts.index("--command")
        command = " ".join(parts[idx + 1:])

    try:
        from rudy.alfred_delegate import delegate_and_wait
        print(_dim(f"Delegating {task_type}..."))
        result = delegate_and_wait(
            task_type=task_type,
            title=f"Console: {task_type}",
            command=command,
            timeout_seconds=60,
        )
        if result.get("success"):
            print(_green("Result: ") + str(result.get("output", ""))[:500])
        else:
            print(_red("Failed: ") + str(result.get("error", "unknown")))
    except Exception as e:
        print(_red(f"Delegation error: {e}"))


def _cmd_logs(args: str) -> None:
    """Show recent logs."""
    log_file = args.strip() if args.strip() else "robin-agent.log"
    log_path = RUDY_LOGS / log_file
    if not log_path.exists():
        # Try common log files
        candidates = sorted(RUDY_LOGS.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            print(f"Available logs: {', '.join(c.name for c in candidates[:10])}")
        else:
            print(_dim("No log files found."))
        return

    try:
        lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
        for line in lines[-20:]:
            if "ERROR" in line:
                print(_red(line))
            elif "WARNING" in line:
                print(_yellow(line))
            else:
                print(line)
    except Exception as e:
        print(_red(f"Log read error: {e}"))


def _cmd_journal() -> None:
    """Show Robin's initiative journal."""
    if not INITIATIVE_JOURNAL.exists():
        print(_dim("No initiative journal found."))
        return
    try:
        entries = json.loads(INITIATIVE_JOURNAL.read_text(encoding="utf-8"))
        recent = entries[-10:]
        print(_bold(f"\n--- Initiative Journal (last {len(recent)}) ---"))
        for e in recent:
            area = e.get("area", "?")
            action = e.get("action", "?")
            started = e.get("started_at", "?")[:16]
            completed = e.get("completed_at", "")
            status = _green("done") if completed else _yellow("in-progress")
            source = e.get("source", "?")
            print(f"  [{started}] {status} {_bold(area)}: {action} ({source})")
        print()
    except Exception as e:
        print(_red(f"Journal error: {e}"))


def _cmd_bridge() -> None:
    """Show bridge heartbeat details."""
    if not HEARTBEAT_FILE.exists():
        print(_red("No bridge heartbeat file. Is BridgeRunner running?"))
        return
    try:
        hb = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
        print(_bold("\n--- Bridge Heartbeat ---"))
        for k, v in hb.items():
            print(f"  {k}: {v}")
        print()
    except Exception as e:
        print(_red(f"Heartbeat error: {e}"))


def _cmd_inbox() -> None:
    """Show unread messages in both inboxes."""
    print(_bold("\n--- Inbox Status ---"))

    for label, inbox_dir in [("Alfred inbox", ALFRED_INBOX), ("Robin inbox", ROBIN_INBOX)]:
        if not inbox_dir.exists():
            print(f"  {label}: directory missing")
            continue
        msgs = sorted(inbox_dir.glob("*.json"))
        if not msgs:
            print(f"  {label}: empty")
            continue
        print(f"  {_bold(label)} ({len(msgs)} messages):")
        for mf in msgs[-5:]:
            try:
                m = json.loads(mf.read_text(encoding="utf-8"))
                mtype = m.get("type", "?")
                ts = m.get("timestamp", "?")[:16]
                subject = (
                    m.get("payload", {}).get("subject", "")
                    or m.get("payload", {}).get("task", "")
                    or m.get("payload", {}).get("directive", "")[:50]
                    or "..."
                )
                print(f"    [{ts}] {mtype}: {subject[:60]}")
            except Exception:
                print(f"    {mf.name}: unreadable")
    print()



def _cmd_activate(args: str) -> None:
    """Force Robin into active autonomy mode, bypassing idle timer."""
    import json
    from datetime import datetime
    from rudy.paths import RUDY_DATA

    mode = args.strip().lower() if args.strip() else "indefinite"
    print(_bold("\n--- Activating Robin ---"))

    # Write activation signal
    activation = {
        "activated_at": datetime.now().isoformat(),
        "activated_by": "batman",
        "mode": mode,
        "note": "Manual activation via chat console",
    }
    signal_file = RUDY_DATA / "coordination" / "robin-activation.json"
    signal_file.write_text(json.dumps(activation, indent=2), encoding="utf-8")
    print(_green(f"  Activation signal written: mode={mode}"))

    # If a duration was given, create a directive
    if mode != "indefinite" and any(c.isdigit() for c in mode):
        try:
            hours = float("".join(c for c in mode.split()[0] if c.isdigit() or c == "."))
            from rudy.robin_autonomy import DirectiveTracker
            directive_text = " ".join(mode.split()[1:]) or "Batman-activated work session"
            DirectiveTracker.create_directive(directive_text, hours)
            print(_green(f"  Directive created: {hours}h -- {directive_text}"))
        except Exception as e:
            print(_yellow(f"  Directive creation failed: {e}"))
    else:
        # Ensure perpetual directive exists
        directive_file = RUDY_DATA / "coordination" / "active-directive.json"
        if not directive_file.exists():
            from rudy.robin_autonomy import DirectiveTracker
            DirectiveTracker.create_directive(
                "Perpetual autonomous collaboration -- activated by Batman", 8760
            )
            print(_green("  Perpetual directive created"))
        else:
            print(_green("  Perpetual directive already active"))

    print(_green("  Robin should pick this up within ~30 seconds"))
    print()


def _cmd_wake_alfred(args: str) -> None:
    """Manually trigger the Alfred wake mechanism."""
    print(_bold("\n--- Wake Alfred ---"))
    try:
        from rudy.robin_wake_alfred import wake_alfred, should_wake_alfred
        should, reason = should_wake_alfred()
        print(f"  Should wake: {_green('YES') if should else _yellow('NO')}")
        print(f"  Reason: {reason}")

        if args.strip().lower() == "force" or should:
            print("  Triggering wake...")
            result = wake_alfred()
            if result.get("woke"):
                print(_green(f"  Woke Alfred via: {result.get('methods_tried', [])}"))
            else:
                print(_yellow(f"  Wake failed: {result.get('reason', 'unknown')}"))
        elif not should:
            print(_dim("  Use '/wake-alfred force' to override"))
    except ImportError:
        print(_red("  robin_wake_alfred module not available"))
    except Exception as e:
        print(_red(f"  Error: {e}"))
    print()


def _cmd_session(args: str) -> None:
    """Start a timed Alfred-Robin collaboration session."""
    import json
    from datetime import datetime
    from rudy.paths import RUDY_DATA

    parts = args.strip().split(None, 1)
    hours = 2.0  # default
    task = "General collaboration session"

    if parts:
        try:
            hours = float(parts[0].rstrip("h"))
            task = parts[1] if len(parts) > 1 else task
        except ValueError:
            task = args.strip()

    print(_bold(f"\n--- Starting {hours}h Session ---"))
    print(f"  Task: {task}")

    # Create directive
    try:
        from rudy.robin_autonomy import DirectiveTracker
        DirectiveTracker.create_directive(task, hours)
        print(_green(f"  Directive created ({hours}h)"))
    except Exception as e:
        print(_red(f"  Directive creation failed: {e}"))

    # Activate Robin
    activation = {
        "activated_at": datetime.now().isoformat(),
        "activated_by": "batman",
        "mode": f"session-{hours}h",
        "task": task,
    }
    signal_file = RUDY_DATA / "coordination" / "robin-activation.json"
    signal_file.write_text(json.dumps(activation, indent=2), encoding="utf-8")

    # Wake Alfred
    try:
        from rudy.robin_wake_alfred import wake_alfred
        result = wake_alfred()
        if result.get("woke"):
            print(_green(f"  Alfred notified via: {result.get('methods_tried', [])}"))
        else:
            print(_yellow(f"  Alfred wake skipped: {result.get('reason', '')}"))
    except ImportError:
        print(_yellow("  Wake module not available -- Alfred not notified"))
    except Exception as e:
        print(_yellow(f"  Alfred wake error: {e}"))

    print(_green(f"  Session active. Robin will drive for {hours}h."))
    print()


def _cmd_help() -> None:
    """Show available commands."""
    print(_bold("\n--- Robin Chat Console ---"))
    print("  Type natural language to chat with Robin (via Ollama).")
    print("  Slash commands:")
    print(f"    {_cyan('/status')}     - Robin's current status")
    print(f"    {_cyan('/health')}     - System health check")
    print(f"    {_cyan('/directive')}  - View/create directive (/directive 2h Do X)")
    print(f"    {_cyan('/delegate')}   - Delegate task (/delegate health_check)")
    print(f"    {_cyan('/bridge')}     - Bridge heartbeat details")
    print(f"    {_cyan('/inbox')}      - View inbox messages")
    print(f"    {_cyan('/journal')}    - Robin's initiative journal")
    print(f"    {_cyan('/logs')}       - Recent log entries (/logs <file>)")
    print(f"    {_cyan('/help')}       - This help message")
    print(f"    {_cyan('/activate')}   - Force Robin active (/activate 2h Fix X)")
    print(f"    {_cyan('/wake-alfred')}- Trigger Alfred wake (/wake-alfred force)")
    print(f"    {_cyan('/session')}    - Start timed session (/session 2h Merge PR)")
    print(f"    {_cyan('/quit')}       - Exit console")
    print()


# ---------------------------------------------------------------------------
# Main REPL
# ---------------------------------------------------------------------------

BANNER = """
  ____        _     _          ____ _           _
 |  _ \\ ___  | |__ (_)_ __   / ___| |__   __ _| |_
 | |_) / _ \\ | '_ \\| | '_ \\ | |   | '_ \\ / _` | __|
 |  _ < (_) || |_) | | | | || |___| | | | (_| | |_
 |_| \\_\\___/ |_.__/|_|_| |_| \\____|_| |_|\\__,_|\\__|

  Batcave Local AI Console -- Type /help for commands
"""


def run_console():
    """Main entry point for the Robin Chat Console."""
    config = _load_config()

    print(_cyan(BANNER))

    # Quick status on startup
    if _ollama_available(config):
        print(_green(f"  Ollama: online ({config.get('ollama_model', '?')})"))
    else:
        print(_red("  Ollama: offline -- chat will not work"))
        print(_dim("  (Slash commands still available)"))

    if HEARTBEAT_FILE.exists():
        print(_green("  Bridge: heartbeat found"))
    else:
        print(_yellow("  Bridge: no heartbeat"))
    print()

    # Chat history for context
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    while True:
        try:
            user_input = input(_bold("Batman> ")).strip()
        except (EOFError, KeyboardInterrupt):
            print(_dim("\nExiting."))
            break

        if not user_input:
            continue

        # Slash commands
        if user_input.startswith("/"):
            cmd_parts = user_input.split(None, 1)
            cmd = cmd_parts[0].lower()
            cmd_args = cmd_parts[1] if len(cmd_parts) > 1 else ""

            if cmd in ("/quit", "/exit", "/q"):
                print(_dim("Goodbye, Batman."))
                break
            elif cmd == "/status":
                _cmd_status(config)
            elif cmd == "/health":
                _cmd_health(config)
            elif cmd == "/directive":
                _cmd_directive(cmd_args)
            elif cmd == "/delegate":
                _cmd_delegate(cmd_args)
            elif cmd == "/logs":
                _cmd_logs(cmd_args)
            elif cmd == "/journal":
                _cmd_journal()
            elif cmd == "/bridge":
                _cmd_bridge()
            elif cmd == "/inbox":
                _cmd_inbox()
            elif cmd == "/activate":
                _cmd_activate(cmd_args)
            elif cmd == "/wake-alfred":
                _cmd_wake_alfred(cmd_args)
            elif cmd == "/session":
                _cmd_session(cmd_args)
            elif cmd == "/help":
                _cmd_help()
            else:
                print(_yellow(f"Unknown command: {cmd}. Type /help for options."))
            continue

        # Natural language -> Ollama
        messages.append({"role": "user", "content": user_input})

        # Keep context window manageable (last 20 messages + system)
        if len(messages) > 21:
            messages = [messages[0]] + messages[-20:]

        response = _ollama_chat(messages, config, stream=True)
        messages.append({"role": "assistant", "content": response})


def main():
    logging.basicConfig(
        level=logging.WARNING,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )
    run_console()


if __name__ == "__main__":
    main()
