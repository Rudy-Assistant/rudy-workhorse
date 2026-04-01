"""rudy.bridge_runner -- Peers Bridge + Autonomy Runner

Unified entry point for Robin's runtime on Oracle. Combines the delegation
bridge (poll broker for Alfred tasks) with autonomous behaviors:
  - Inbox checking (reads messages from Alfred every cycle)
  - Alfred struggle detection (offers help when Alfred is stuck)
  - AutonomyEngine integration (self-directed work when idle)
  - Directive awareness (reads active-directive.json)

Usage:
    C:\\Python312\\python.exe rudy\\bridge_runner.py
    C:\\Python312\\python.exe rudy\\bridge_runner.py --interval 15

Lucius Gate: LG-029 - No new dependencies. Uses existing modules.
Session 34: Wired autonomy into the running process (was dead code).
"""

import json
import logging
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# Ensure rudy is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rudy.peers_delegation import register_peer
from rudy.peers_taskqueue_bridge import poll_once
from rudy.paths import RUDY_DATA, REPO_ROOT

# === Configuration ===
DATA_DIR = RUDY_DATA
LOG_DIR = DATA_DIR / "logs"
LOG_FILE = LOG_DIR / "bridge-runner.log"
HEARTBEAT_FILE = DATA_DIR / "bridge-heartbeat.json"
DEFAULT_INTERVAL = 10  # seconds
HEARTBEAT_INTERVAL = 30  # write heartbeat every N seconds
LOCK_FILE = DATA_DIR / "bridge-runner.lock"

# Autonomy cadence (in poll cycles, not seconds)
INBOX_CHECK_EVERY = 3        # Check inbox every 3 cycles (~30s)
STRUGGLE_CHECK_EVERY = 6     # Detect Alfred struggle every 6 cycles (~60s)
AUTONOMY_CHECK_EVERY = 30    # Run AutonomyEngine every 30 cycles (~5min)
WAKE_CHECK_EVERY = 60        # Check if Alfred needs waking every 60 cycles (~10min)

log = logging.getLogger("bridge.runner")


def setup_logging():
    """Configure dual logging: file + console."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE, encoding="utf-8"),
            logging.StreamHandler(),
        ],
    )


def write_heartbeat(robin_id, iterations=0, autonomy_runs=0, inbox_msgs=0):
    """Write heartbeat JSON for external health monitoring."""
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        HEARTBEAT_FILE.write_text(json.dumps({
            "timestamp": datetime.now().isoformat(),
            "pid": os.getpid(),
            "robin_id": robin_id,
            "status": "running",
            "iterations": iterations,
            "autonomy_runs": autonomy_runs,
            "inbox_messages_processed": inbox_msgs,
        }, indent=2), encoding="utf-8")
    except Exception as e:
        log.warning("Heartbeat write failed: %s", e)


def check_health():
    """External health check: is heartbeat recent?"""
    if not HEARTBEAT_FILE.exists():
        return False, "No heartbeat file"
    try:
        data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
        ts = datetime.fromisoformat(data["timestamp"])
        age = (datetime.now() - ts).total_seconds()
        if age > 120:
            return False, f"Stale heartbeat ({age:.0f}s)"
        return True, f"OK (age={age:.0f}s, pid={data.get('pid')}, iter={data.get('iterations',0)})"
    except Exception as e:
        return False, str(e)


def _signal_handler(signum, _frame):
    log.info("Received signal %d, shutting down...", signum)
    _release_lock()
    sys.exit(0)


def _is_process_alive(pid):
    """Check if a process with given PID is still running."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if handle:
            kernel32.CloseHandle(handle)
            return True
        return False
    except Exception:
        # Fallback: use os.kill with signal 0
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False


def _acquire_lock():
    """Acquire a PID lockfile. Returns True if lock acquired, False if another instance is running."""
    if LOCK_FILE.exists():
        try:
            lock_data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
            old_pid = lock_data.get("pid", 0)
            if old_pid and _is_process_alive(old_pid):
                return False  # Another instance is genuinely running
            else:
                log.info("Stale lock from PID %d (dead), taking over", old_pid)
        except (json.JSONDecodeError, OSError):
            log.warning("Corrupt lock file, overwriting")

    # Write our lock
    LOCK_FILE.write_text(json.dumps({
        "pid": os.getpid(),
        "started": datetime.now().isoformat(),
    }, indent=2), encoding="utf-8")
    return True


def _release_lock():
    """Release the PID lockfile on exit."""
    try:
        if LOCK_FILE.exists():
            lock_data = json.loads(LOCK_FILE.read_text(encoding="utf-8"))
            if lock_data.get("pid") == os.getpid():
                LOCK_FILE.unlink()
    except Exception:
        pass


# =========================================================================
# Autonomy subsystem -- wired into the poll loop
# =========================================================================

def _check_inbox():
    """Check Robin's inbox for messages from Alfred. Process and respond."""
    try:
        from rudy.robin_alfred_protocol import RobinMailbox
        mailbox = RobinMailbox()
        messages = mailbox.check_inbox()
        if not messages:
            return 0

        processed = 0
        for msg in messages:
            msg_type = msg.get("type", "unknown")
            msg_id = msg.get("id", "?")
            payload = msg.get("payload", {})
            log.info("[Inbox] Message: type=%s id=%s", msg_type, msg_id)

            if msg_type == "task":
                # Alfred assigned a task -- acknowledge and queue it
                log.info("[Inbox] Task from Alfred: %s", payload.get("task", payload.get("title", "?")))
                mailbox.acknowledge_task(msg_id, eta_minutes=5)
                # Route to robin_taskqueue for execution (LF-S46-001)
                try:
                    from rudy.robin_taskqueue import add_task
                    _pri_map = {"critical": 10, "high": 20, "medium": 30, "low": 40}
                    add_task({
                        "type": payload.get("type", "shell"),
                        "title": payload.get("title", payload.get("task", "Alfred task")),
                        "description": payload.get("description", payload.get("details", "")),
                        "command": payload.get("command"),
                        "priority": _pri_map.get(str(msg.get("priority", "medium")).lower(), 30),
                        "from_msg_id": msg_id,
                        "status": "pending",
                    })
                except Exception as te:
                    log.error("[Inbox] Failed to enqueue task: %s", te)

            elif msg_type == "session_start":
                log.info("[Inbox] Alfred session started: %s (session #%s)",
                         payload.get("session_id"), payload.get("session_number"))

            elif msg_type == "session_end":
                log.info("[Inbox] Alfred session ended: %s",
                         payload.get("summary", "")[:100])

            elif msg_type == "finding":
                log.info("[Inbox] Finding from Alfred: %s (sev=%s)",
                         payload.get("title"), payload.get("severity"))

            else:
                log.info("[Inbox] Unhandled msg type: %s", msg_type)

            mailbox.mark_read(msg_id)
            processed += 1

        return processed
    except ImportError as e:
        log.warning("[Inbox] Protocol not available: %s", e)
        return 0
    except Exception as e:
        log.error("[Inbox] Error: %s", e)
        return 0


def _detect_and_offer_help():
    """Check if Alfred is struggling and proactively offer help."""
    try:
        from rudy.robin_alfred_protocol import RobinMailbox
        mailbox = RobinMailbox()
        result = mailbox.detect_alfred_struggle()

        if result.get("struggling"):
            signals = result.get("signals", [])
            log.info("[Assertive] Alfred struggle detected: %s", signals)
            mailbox.offer_help(
                context="bridge_runner autonomy check",
                what_noticed="; ".join(signals),
                suggested_action="Robin is available for local tasks. Delegate freely.",
            )
            return True
        return False
    except ImportError:
        return False
    except Exception as e:
        log.error("[Assertive] Struggle detection error: %s", e)
        return False




# =========================================================================
# Session Loop Orchestrator (S47) -- Alfred/Lucius automated cycle
# =========================================================================

SESSION_LOOP_CHECK_EVERY = 18  # Check every 18 cycles (~3 min)

def _check_session_loop():
    """Orchestrate the Alfred/Lucius session loop.

    Reads session-loop-config.json. If status is "running":
    - Detects signal files (alfred-done, lucius-done)
    - Writes the next session prompt to next-session-prompt.md
    - Launches Claude app to start the next session
    """
    config_path = RUDY_DATA / "coordination" / "session-loop-config.json"
    if not config_path.exists():
        return None

    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    if config.get("state", {}).get("status") != "running":
        return None

    state = config["state"]
    signals = config.get("signals", {})
    prompts = config.get("prompts", {})

    alfred_done_path = RUDY_DATA.parent / signals.get("alfred_done", "")
    lucius_done_path = RUDY_DATA.parent / signals.get("lucius_done", "")
    halt_path = RUDY_DATA.parent / signals.get("halt", "")

    # Check for halt
    if halt_path.exists():
        log.info("[SessionLoop] Halt signal detected. Stopping loop.")
        state["status"] = "halted"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
        return {"action": "halted"}

    # Determine next action based on signals
    alfred_done = alfred_done_path.exists()
    lucius_done = lucius_done_path.exists()

    if alfred_done and not lucius_done:
        # Alfred finished, need to start Lucius
        log.info("[SessionLoop] Alfred done signal found. Starting Lucius session.")
        try:
            signal = json.loads(alfred_done_path.read_text(encoding="utf-8"))
            session_num = signal.get("session", "?")
        except (json.JSONDecodeError, OSError):
            session_num = "?"

        # Write the Lucius prompt as next-session-prompt.md
        lucius_template = RUDY_DATA.parent / prompts.get("lucius_template", "")
        next_prompt = RUDY_DATA / "coordination" / "next-session-prompt.md"
        if lucius_template.exists():
            next_prompt.write_text(lucius_template.read_text(encoding="utf-8"), encoding="utf-8")
            log.info("[SessionLoop] Wrote Lucius prompt to %s", next_prompt)

        # Update state
        state["current_agent"] = "lucius"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        # Launch Claude app
        from rudy.robin_wake_alfred import wake_via_claude_app
        launched = wake_via_claude_app()
        log.info("[SessionLoop] Claude app launched for Lucius: %s", launched)
        return {"action": "started_lucius", "session": session_num, "launched": launched}

    elif lucius_done:
        # Lucius finished, check grade and possibly start next Alfred
        log.info("[SessionLoop] Lucius done signal found. Evaluating next iteration.")
        try:
            signal = json.loads(lucius_done_path.read_text(encoding="utf-8"))
            grade = signal.get("grade", "?")
            score = signal.get("score", 0)
        except (json.JSONDecodeError, OSError):
            grade = "?"
            score = 0

        halt_below = config.get("config", {}).get("halt_on_grade_below", "D-")
        max_iter = config.get("config", {}).get("max_iterations", 5)

        # Check halt conditions
        grade_order = ["F", "D-", "D", "D+", "C-", "C", "C+", "B-", "B", "B+", "A-", "A", "A+"]
        if grade in grade_order and halt_below in grade_order:
            if grade_order.index(grade) < grade_order.index(halt_below):
                log.info("[SessionLoop] Grade %s below threshold %s. Halting.", grade, halt_below)
                state["status"] = "halted"
                state["halt_reason"] = f"Grade {grade} below {halt_below}"
                config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
                return {"action": "halted", "reason": f"grade_{grade}"}

        state["current_iteration"] = state.get("current_iteration", 0) + 1
        if state["current_iteration"] >= max_iter:
            log.info("[SessionLoop] Max iterations reached (%d). Halting.", max_iter)
            state["status"] = "completed"
            config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            return {"action": "completed", "iterations": state["current_iteration"]}

        # Clean up signal files for next cycle
        alfred_done_path.unlink(missing_ok=True)
        lucius_done_path.unlink(missing_ok=True)

        # Write Alfred prompt
        alfred_template = RUDY_DATA.parent / prompts.get("alfred_template", "")
        next_prompt = RUDY_DATA / "coordination" / "next-session-prompt.md"
        if alfred_template.exists():
            next_prompt.write_text(alfred_template.read_text(encoding="utf-8"), encoding="utf-8")
            log.info("[SessionLoop] Wrote Alfred prompt to %s", next_prompt)

        state["current_agent"] = "alfred"
        state["last_completed_agent"] = "lucius"
        config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")

        from rudy.robin_wake_alfred import wake_via_claude_app
        launched = wake_via_claude_app()
        log.info("[SessionLoop] Claude app launched for Alfred: %s", launched)
        return {"action": "started_alfred", "iteration": state["current_iteration"], "launched": launched}

    else:
        # No signals yet -- waiting
        return None


def _run_autonomy_tick():
    """Run one cycle of the AutonomyEngine (decide + execute).

    This is the key integration: when Robin has no pending delegations,
    it uses AutonomyEngine to decide what to do autonomously --
    whether that's following a directive, responding to Alfred's messages
    collaboratively, or taking initiative on system improvements.
    """
    try:
        from rudy.robin_autonomy import AutonomyEngine

        engine = AutonomyEngine()
        plan = engine.decide()
        mode = plan.get("mode", "none")
        action = plan.get("action", "idle")
        rationale = plan.get("rationale", "")[:120]

        log.info("[Autonomy] decide: mode=%s action=%s rationale=%s",
                 mode, action, rationale)

        if action == "idle" or action == "skip":
            return {"mode": mode, "action": action, "executed": False}

        # Execute the plan
        def _make_agent():
            """Factory for Robin's MCP agent (if available)."""
            try:
                from rudy.robin_mcp_client import MCPServerRegistry
                from rudy.robin_agent_loader import RobinAgent
                secrets_file = RUDY_DATA / "robin-secrets.json"
                secrets = {}
                if secrets_file.exists():
                    try:
                        secrets = json.loads(secrets_file.read_text(encoding="utf-8"))
                    except Exception:
                        pass
                registry = MCPServerRegistry(secrets)
                registry.connect_all()
                agent = RobinAgent(
                    registry=registry,
                    ollama_host=secrets.get("ollama_host", "http://localhost:11434"),
                    model=secrets.get("ollama_model", "qwen2.5:7b"),
                )
                return agent
            except ImportError:
                return None

        result = engine.execute(plan, agent_factory=_make_agent)
        log.info("[Autonomy] execute: success=%s", result.get("success"))
        return {"mode": mode, "action": action, "executed": True, "result": result}

    except ImportError as e:
        log.warning("[Autonomy] Engine not available: %s", e)
        return {"error": str(e)}
    except Exception as e:
        log.error("[Autonomy] Error: %s", e)
        return {"error": str(e)}


# =========================================================================
# Main loop -- bridge polling + autonomy
# =========================================================================

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Peers Bridge + Autonomy Runner")
    parser.add_argument("--interval", type=int, default=DEFAULT_INTERVAL,
                        help="Poll interval in seconds")
    parser.add_argument("--max", type=int, default=0,
                        help="Max iterations (0=infinite)")
    parser.add_argument("--health", action="store_true",
                        help="Check health and exit")
    parser.add_argument("--no-autonomy", action="store_true",
                        help="Disable autonomy (bridge-only mode)")
    args = parser.parse_args()

    if args.health:
        ok, msg = check_health()
        print(f"{'OK' if ok else 'FAIL'}: {msg}")
        sys.exit(0 if ok else 1)

    setup_logging()

    # Singleton enforcement: only one bridge_runner at a time
    if not _acquire_lock():
        log.warning("Another bridge_runner is already running (lock: %s). Exiting.", LOCK_FILE)
        print("ALREADY_RUNNING: Another bridge_runner instance holds the lock. Exiting.")
        sys.exit(0)

    log.info("=" * 60)
    log.info("Bridge + Autonomy Runner starting (PID %d, interval %ds, autonomy=%s)",
             os.getpid(), args.interval, not args.no_autonomy)

    # Graceful shutdown
    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)

    # Register Robin with the broker
    robin_id = register_peer(
        pid=os.getpid(),
        cwd=str(REPO_ROOT),
        summary="Robin Bridge + Autonomy Runner (scheduled task)",
    )
    log.info("Registered as peer: %s", robin_id)
    write_heartbeat(robin_id)

    # Update Robin status to online
    try:
        from rudy.robin_alfred_protocol import RobinMailbox
        _mailbox = RobinMailbox()  # Sets status to "online"
        log.info("Robin mailbox initialized, status: online")
    except ImportError:
        log.warning("robin_alfred_protocol not available -- no mailbox")

    # Counters
    iteration = 0
    last_heartbeat = time.time()
    total_autonomy_runs = 0
    total_inbox_msgs = 0

    try:
        while True:
            iteration += 1
            if args.max and iteration > args.max:
                break

            # --- Phase 1: Bridge poll (every cycle) ---
            try:
                count = poll_once(robin_id)
                if count:
                    log.info("Processed %d delegation(s) in iteration %d",
                             count, iteration)
            except Exception as e:
                log.error("Poll error: %s", e)

            # --- Phase 2: Inbox check (every INBOX_CHECK_EVERY cycles) ---
            if not args.no_autonomy and iteration % INBOX_CHECK_EVERY == 0:
                try:
                    msgs = _check_inbox()
                    if msgs:
                        total_inbox_msgs += msgs
                        log.info("Inbox: processed %d message(s)", msgs)
                except Exception as e:
                    log.error("Inbox check error: %s", e)

            # --- Phase 3: Alfred struggle detection (every STRUGGLE_CHECK_EVERY) ---
            if not args.no_autonomy and iteration % STRUGGLE_CHECK_EVERY == 0:
                try:
                    offered = _detect_and_offer_help()
                    if offered:
                        log.info("Offered help to Alfred (struggle detected)")
                except Exception as e:
                    log.error("Struggle detection error: %s", e)

            # --- Phase 4: Autonomy engine (every AUTONOMY_CHECK_EVERY) ---
            if not args.no_autonomy and iteration % AUTONOMY_CHECK_EVERY == 0:
                try:
                    result = _run_autonomy_tick()
                    total_autonomy_runs += 1
                    if result.get("executed"):
                        log.info("Autonomy executed: mode=%s action=%s",
                                 result.get("mode"), result.get("action"))
                except Exception as e:
                    log.error("Autonomy tick error: %s", e)

            # --- Phase 5: Wake Alfred check (every WAKE_CHECK_EVERY) ---
            if not args.no_autonomy and iteration % WAKE_CHECK_EVERY == 0:
                try:
                    from rudy.robin_wake_alfred import wake_alfred
                    wake_result = wake_alfred()
                    if wake_result.get("woke"):
                        log.info("Woke Alfred: %s (methods: %s)",
                                 wake_result.get("reason", ""),
                                 wake_result.get("methods_tried", []))
                except ImportError:
                    pass  # wake module not yet available
                except Exception as e:
                    log.error("Wake check error: %s", e)

            # --- Phase 6: Session loop orchestrator (every SESSION_LOOP_CHECK_EVERY) ---
            if not args.no_autonomy and iteration % SESSION_LOOP_CHECK_EVERY == 0:
                try:
                    loop_result = _check_session_loop()
                    if loop_result:
                        log.info("[SessionLoop] Result: %s", loop_result.get("action"))
                except Exception as e:
                    log.error("[SessionLoop] Error: %s", e)

            # --- Heartbeat refresh ---
            if time.time() - last_heartbeat >= HEARTBEAT_INTERVAL:
                write_heartbeat(robin_id, iterations=iteration,
                                autonomy_runs=total_autonomy_runs,
                                inbox_msgs=total_inbox_msgs)
                last_heartbeat = time.time()

            time.sleep(args.interval)

    except KeyboardInterrupt:
        log.info("Interrupted, exiting")
    except Exception as e:
        log.error("Fatal error: %s", e, exc_info=True)
        sys.exit(1)
    finally:
        _release_lock()
        log.info("Bridge + Autonomy Runner stopped after %d iterations "
                 "(autonomy_runs=%d, inbox_msgs=%d)",
                 iteration, total_autonomy_runs, total_inbox_msgs)


if __name__ == "__main__":
    main()
