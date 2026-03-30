#!/usr/bin/env python3
"""
Robin Autonomy Engine - Self-directed intelligence for when Batman is away.

This is NOT a task queue. This is Robin's capacity for independent thought.
When the task queue is empty and no directive is active, Robin evaluates
what is genuinely most valuable to work on, formulates a plan, and
coordinates with Alfred through the mailbox protocol.

Three Operating Modes:
  1. DIRECTIVE MODE - Batman gave a specific directive with a time budget.
     Robin and Alfred coordinate on that directive, with checkpoints.
  2. COLLABORATIVE MODE - Alfred has messages in the inbox. Robin reads,
     thinks, responds. They iterate like colleagues on a shift.
  3. INITIATIVE MODE - No directives, no messages. Robin evaluates system
     state, identifies the highest-value improvement, and pursues it.
     NOT busywork - deliberate, prioritized development.

Integration:
  Called from _run_nightwatch() when the task queue is empty and
  Robin's mode is ACTIVE or NIGHTSHIFT.

Usage:
    from rudy.robin_autonomy import AutonomyEngine
    engine = AutonomyEngine()
    action = engine.decide()  # Returns what Robin should do next
    engine.execute(action)     # Carries it out
"""

import json
import logging
import os
import time as _time
from datetime import datetime, timedelta
from pathlib import Path

try:
    from rudy.robin_sentinel import SentinelObserver
    _HAS_SENTINEL = True
except ImportError:
    _HAS_SENTINEL = False

log = logging.getLogger("robin_autonomy")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

from rudy.paths import REPO_ROOT, RUDY_DATA, RUDY_LOGS  # noqa: E402

COORD_DIR = RUDY_DATA / "coordination"
ALFRED_INBOX = RUDY_DATA / "alfred-inbox"
ROBIN_INBOX = RUDY_DATA / "robin-inbox"
ARCHIVE_DIR = COORD_DIR / "archive"
DIRECTIVE_FILE = COORD_DIR / "active-directive.json"
AUTONOMY_LOG = RUDY_LOGS / "robin-autonomy.log"
INITIATIVE_JOURNAL = RUDY_DATA / "robin-initiative-journal.json"

for d in [COORD_DIR, ALFRED_INBOX, ROBIN_INBOX, ARCHIVE_DIR, RUDY_LOGS]:
    d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Directive Tracker
# ---------------------------------------------------------------------------

class DirectiveTracker:
    """
    Tracks Batman's active directive - what he told Robin and Alfred to
    work on while he's away, with time budget and checkpoints.
    """

    def __init__(self):
        self.directive = self._load()

    def _load(self):
        if DIRECTIVE_FILE.exists():
            try:
                with open(DIRECTIVE_FILE) as f:
                    d = json.load(f)
                if d.get("status") == "active":
                    return d
            except (json.JSONDecodeError, OSError):
                pass
        return None

    def _save(self):
        if self.directive:
            with open(DIRECTIVE_FILE, "w") as f:
                json.dump(self.directive, f, indent=2)

    def has_active_directive(self):
        if not self.directive:
            return False
        expires = self.directive.get("expires_at")
        if expires and datetime.fromisoformat(expires) < datetime.now():
            self.directive["status"] = "expired"
            self._save()
            log.info("Directive expired: %s", self.directive.get("directive", "?"))
            return False
        return True

    def get_directive(self):
        if self.has_active_directive():
            return self.directive
        return None

    def get_time_remaining(self):
        if not self.has_active_directive():
            return None
        expires = self.directive.get("expires_at")
        if expires:
            return datetime.fromisoformat(expires) - datetime.now()
        return None

    def get_progress_pct(self):
        if not self.directive:
            return 0.0
        given = datetime.fromisoformat(self.directive["given_at"])
        expires = self.directive.get("expires_at")
        if not expires:
            return 0.0
        total = (datetime.fromisoformat(expires) - given).total_seconds()
        elapsed = (datetime.now() - given).total_seconds()
        return min(100.0, (elapsed / total) * 100) if total > 0 else 100.0

    def get_current_checkpoint(self):
        pct = self.get_progress_pct()
        checkpoints = self.directive.get("checkpoints", []) if self.directive else []
        completed_pcts = {p.get("checkpoint_pct") for p in (self.directive or {}).get("progress", [])}
        for cp in checkpoints:
            if pct >= cp["at_pct"] and cp["at_pct"] not in completed_pcts:
                return cp
        return None

    def record_progress(self, checkpoint_pct, summary):
        if not self.directive:
            return
        self.directive.setdefault("progress", []).append({
            "checkpoint_pct": checkpoint_pct,
            "timestamp": datetime.now().isoformat(),
            "summary": summary,
        })
        self._save()
        log.info("Directive checkpoint %.0f%%: %s", checkpoint_pct, summary)

    @staticmethod
    def create_directive(directive, hours, checkpoints=None):
        """Create a new directive (called by Alfred or Batman)."""
        now = datetime.now()
        expires = now + timedelta(hours=hours)
        if not checkpoints:
            checkpoints = [
                {"at_pct": 25, "note": "Initial assessment and plan"},
                {"at_pct": 50, "note": "Core work in progress"},
                {"at_pct": 75, "note": "Testing and validation"},
                {"at_pct": 100, "note": "Results documented"},
            ]
        d = {
            "directive": directive,
            "given_by": "batman",
            "given_at": now.isoformat(),
            "time_budget_hours": hours,
            "expires_at": expires.isoformat(),
            "checkpoints": checkpoints,
            "progress": [],
            "status": "active",
        }
        with open(DIRECTIVE_FILE, "w") as f:
            json.dump(d, f, indent=2)
        log.info("New directive created: %s (%.1fh budget)", directive, hours)
        return d

# ---------------------------------------------------------------------------
# Alfred Coordinator
# ---------------------------------------------------------------------------

class AlfredCoordinator:
    """Manages the Robin-Alfred conversation through the mailbox protocol."""

    def __init__(self):
        pass

    def check_alfred_messages(self):
        """Check for unread messages from Alfred."""
        messages = []
        for f in sorted(ROBIN_INBOX.glob("*.json")):
            try:
                with open(f) as fh:
                    msg = json.load(fh)
                if msg.get("status") == "unread":
                    messages.append(msg)
            except (json.JSONDecodeError, OSError):
                continue
        return messages

    def send_to_alfred(self, msg_type, payload, priority="normal"):
        """Send a message to Alfred's inbox."""
        msg_id = f"{int(_time.time())}-{msg_type}"
        message = {
            "id": msg_id,
            "from": "robin",
            "to": "alfred",
            "type": msg_type,
            "priority": priority,
            "timestamp": datetime.now().isoformat(),
            "payload": payload,
            "status": "unread",
        }
        filepath = ALFRED_INBOX / f"{msg_id}.json"
        with open(filepath, "w") as f:
            json.dump(message, f, indent=2)
        log.info("Sent to Alfred [%s]: %s", msg_type, payload.get("subject", "")[:80])
        return msg_id

    def mark_read(self, msg_id):
        """Mark an Alfred message as read and archive it."""
        for f in ROBIN_INBOX.glob(f"{msg_id}*.json"):
            try:
                with open(f) as fh:
                    msg = json.load(fh)
                msg["status"] = "read"
                msg["read_at"] = datetime.now().isoformat()
                archive_path = ARCHIVE_DIR / f.name
                with open(archive_path, "w") as fh:
                    json.dump(msg, fh, indent=2)
                f.unlink()
            except Exception:
                continue

    def prompt_alfred(self, subject, question, context=""):
        """Send a thoughtful prompt to Alfred, expecting a response."""
        return self.send_to_alfred("request", {
            "subject": subject, "question": question,
            "context": context, "expects_response": True,
        })

    def report_to_alfred(self, subject, summary, findings=None):
        """Report completed work or findings to Alfred."""
        return self.send_to_alfred("report", {
            "subject": subject, "summary": summary,
            "findings": findings or {},
        })

    def send_checkpoint(self, directive, pct, summary, next_steps):
        """Send a directive checkpoint update to Alfred."""
        return self.send_to_alfred("report", {
            "subject": f"Directive Checkpoint ({pct:.0f}%): {directive[:50]}",
            "summary": summary, "next_steps": next_steps,
            "checkpoint_pct": pct,
        }, priority="high")

# ---------------------------------------------------------------------------
# Initiative Engine
# ---------------------------------------------------------------------------

class InitiativeEngine:
    """
    When no directive is active and no Alfred messages are pending,
    Robin evaluates what is genuinely most valuable to work on.
    Maintains a journal of past initiatives to avoid repetition.
    """

    INITIATIVE_PRIORITIES = [
        {"area": "reliability", "description": "Improve Robin's tool-calling reliability and error handling", "assess": "_assess_reliability", "value": 10},
        {"area": "alfred_coordination", "description": "Strengthen Robin-Alfred communication protocol", "assess": "_assess_alfred_coordination", "value": 9},
        {"area": "environment_health", "description": "Maintain Oracle's system health and catch issues early", "assess": "_assess_environment", "value": 8},
        {"area": "codebase_quality", "description": "Improve code quality, fix bugs, add missing error handling", "assess": "_assess_codebase", "value": 7},
        {"area": "capability_expansion", "description": "Research and prototype new capabilities for the Batcave", "assess": "_assess_capabilities", "value": 6},
        {"area": "documentation", "description": "Document architecture decisions, operational procedures", "assess": "_assess_documentation", "value": 5},
    ]

    def __init__(self):
        self.journal = self._load_journal()

    def _load_journal(self):
        if INITIATIVE_JOURNAL.exists():
            try:
                with open(INITIATIVE_JOURNAL) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save_journal(self):
        with open(INITIATIVE_JOURNAL, "w") as f:
            json.dump(self.journal[-100:], f, indent=2)

    def _recent_initiatives(self, area, hours=24):
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        return [j for j in self.journal
                if j.get("area") == area and j.get("started_at", "") > cutoff]

    def choose_initiative(self):
        for priority in self.INITIATIVE_PRIORITIES:
            area = priority["area"]
            recent = self._recent_initiatives(area, hours=4)
            # Sentinel observation boost (more signals = higher effective priority)
            boost = 0
            if hasattr(self, '_sentinel_ref') and self._sentinel_ref:
                boost = self._sentinel_ref.get_priority_boost(area)
            if len(recent) >= 2 and boost < 3:
                continue
            assess_method = getattr(self, priority["assess"], None)
            if assess_method:
                assessment = assess_method()
                if assessment.get("needs_work"):
                    initiative = {
                        "area": area, "description": priority["description"],
                        "action": assessment["action"], "rationale": assessment["rationale"],
                        "started_at": datetime.now().isoformat(),
                    }
                    self.journal.append(initiative)
                    self._save_journal()
                    return initiative
        return {
            "area": "health_check", "description": "Periodic system health verification",
            "action": "run_health_check",
            "rationale": "All initiative areas recently addressed; performing routine health check",
            "started_at": datetime.now().isoformat(),
        }

    def _assess_reliability(self):
        error_log = RUDY_LOGS / "robin-agent.log"
        recent_errors = 0
        if error_log.exists():
            try:
                lines = error_log.read_text().splitlines()
                for line in lines[-200:]:
                    if "ERROR" in line or "FAIL" in line:
                        recent_errors += 1
            except Exception:
                pass
        if recent_errors > 5:
            return {"needs_work": True, "action": "analyze_recent_errors",
                    "rationale": f"Found {recent_errors} recent errors in Robin agent logs"}
        return {"needs_work": True, "action": "validate_python_files",
                "rationale": "Proactive syntax and import validation of all Robin modules"}

    def _assess_alfred_coordination(self):
        alfred_status = COORD_DIR / "alfred-status.json"
        if not alfred_status.exists():
            return {"needs_work": True, "action": "ping_alfred",
                    "rationale": "No Alfred status file - need to establish communication channel"}
        try:
            with open(alfred_status) as f:
                status = json.load(f)
            updated = status.get("updated_at", "")
            if updated:
                age = (datetime.now() - datetime.fromisoformat(updated)).total_seconds() / 3600
                if age > 6:
                    return {"needs_work": True, "action": "ping_alfred",
                            "rationale": f"Alfred status is {age:.1f}h old - sending status update"}
        except Exception:
            pass
        outbox_count = len(list(ALFRED_INBOX.glob("*.json")))
        if outbox_count > 5:
            return {"needs_work": True, "action": "review_unanswered_messages",
                    "rationale": f"{outbox_count} messages in Alfred's inbox unanswered"}
        return {"needs_work": False}

    def _assess_environment(self):
        recent_health = self._recent_initiatives("environment_health", hours=2)
        if not recent_health:
            return {"needs_work": True, "action": "system_health_check",
                    "rationale": "No environment health check in the last 2 hours"}
        return {"needs_work": False}

    def _assess_codebase(self):
        rudy_dir = REPO_ROOT / "rudy"
        if not rudy_dir.exists():
            return {"needs_work": False}
        return {"needs_work": True, "action": "git_status_and_quality",
                "rationale": "Checking for uncommitted changes and running basic code quality assessment"}

    def _assess_capabilities(self):
        recent = self._recent_initiatives("capability_expansion", hours=8)
        if not recent:
            return {"needs_work": True, "action": "research_improvements",
                    "rationale": "No capability research in the last 8 hours"}
        return {"needs_work": False}

    def _assess_documentation(self):
        recent = self._recent_initiatives("documentation", hours=12)
        if not recent:
            return {"needs_work": True, "action": "update_documentation",
                    "rationale": "No documentation work in the last 12 hours"}
        return {"needs_work": False}

    def record_completion(self, area, result):
        for entry in reversed(self.journal):
            if entry.get("area") == area and "completed_at" not in entry:
                entry["completed_at"] = datetime.now().isoformat()
                entry["result"] = result
                break
        self._save_journal()

# ---------------------------------------------------------------------------
# Autonomy Engine - The main decision-maker
# ---------------------------------------------------------------------------

class AutonomyEngine:
    """Robin's autonomous decision-making engine."""

    def __init__(self):
        self.directive_tracker = DirectiveTracker()
        self.alfred = AlfredCoordinator()
        self.initiative = InitiativeEngine()
        self.sentinel = SentinelObserver() if _HAS_SENTINEL else None
        self.initiative._sentinel_ref = self.sentinel

    def decide(self):
        # SENTINEL: Passive observation on EVERY cycle
        if self.sentinel:
            try:
                self.sentinel.observe()
            except Exception as e:
                log.debug("[Autonomy] Sentinel error: %s", e)

        # MODE 1: Active directive from Batman
        directive = self.directive_tracker.get_directive()
        if directive:
            remaining = self.directive_tracker.get_time_remaining()
            pct = self.directive_tracker.get_progress_pct()
            checkpoint = self.directive_tracker.get_current_checkpoint()
            log.info("[Autonomy] DIRECTIVE MODE: '%s' (%.0f%% elapsed, %s remaining)",
                     directive["directive"][:60], pct,
                     str(remaining).split(".")[0] if remaining else "?")
            action = {
                "mode": "directive", "action": "execute_directive",
                "details": {"directive": directive["directive"], "progress_pct": pct,
                            "time_remaining": str(remaining) if remaining else None,
                            "checkpoint": checkpoint},
                "rationale": f"Active directive: {directive['directive'][:80]}",
            }
            if checkpoint:
                action["details"]["checkpoint_due"] = True
            return action

        # MODE 2: Messages from Alfred waiting
        alfred_messages = self.alfred.check_alfred_messages()
        if alfred_messages:
            log.info("[Autonomy] COLLABORATIVE MODE: %d message(s) from Alfred", len(alfred_messages))
            return {
                "mode": "collaborative", "action": "process_alfred_messages",
                "details": {"message_count": len(alfred_messages), "messages": alfred_messages},
                "rationale": f"{len(alfred_messages)} unread message(s) from Alfred",
            }

        # MODE 3: Self-directed initiative
        initiative = self.initiative.choose_initiative()
        log.info("[Autonomy] INITIATIVE MODE: [%s] %s", initiative["area"], initiative["action"])
        return {
            "mode": "initiative", "action": initiative["action"],
            "details": initiative, "rationale": initiative["rationale"],
        }

    def execute(self, plan, agent_factory=None):
        mode = plan["mode"]
        action = plan["action"]
        log.info("[Autonomy] Executing: mode=%s, action=%s", mode, action)
        if mode == "directive":
            return self._execute_directive(plan, agent_factory)
        elif mode == "collaborative":
            return self._execute_collaborative(plan, agent_factory)
        elif mode == "initiative":
            return self._execute_initiative(plan, agent_factory)
        else:
            return {"success": False, "error": f"Unknown mode: {mode}"}

    def _execute_directive(self, plan, agent_factory=None):
        details = plan["details"]
        directive_text = details["directive"]
        pct = details["progress_pct"]
        checkpoint = details.get("checkpoint")
        prompt = f"You are working on a directive from Batman: '{directive_text}'\nProgress: {pct:.0f}% of time budget elapsed.\n"
        if details.get("time_remaining"):
            prompt += f"Time remaining: {details['time_remaining']}\n"
        if checkpoint:
            prompt += f"\nCurrent checkpoint ({checkpoint['at_pct']}%): {checkpoint['note']}\nYou should work toward meeting this checkpoint.\n"
        prompt += "\nTake the next concrete step toward completing this directive. Be deliberate - quality over quantity. Report what you accomplish."
        result = self._run_agent(prompt, agent_factory)
        if checkpoint and result.get("success"):
            self.directive_tracker.record_progress(checkpoint["at_pct"], result.get("summary", "Checkpoint reached"))
            self.alfred.send_checkpoint(directive_text, pct, result.get("summary", "Work in progress"), result.get("next_steps", "Continuing directive work"))
        return result

    def _execute_collaborative(self, plan, agent_factory=None):
        messages = plan["details"]["messages"]
        results = []
        for msg in messages:
            msg_type = msg.get("type", "unknown")
            payload = msg.get("payload", {})
            msg_id = msg.get("id", "unknown")
            log.info("[Autonomy] Processing Alfred message: [%s] %s", msg_type, payload.get("subject", payload.get("task", ""))[:60])
            if msg_type == "task":
                task_desc = payload.get("task", payload.get("details", ""))
                result = self._run_agent(f"Alfred has assigned you this task: {task_desc}\n\nComplete it and report your findings.", agent_factory)
                self.alfred.report_to_alfred(f"Task Complete: {payload.get('task', 'assigned task')[:50]}", result.get("summary", "Task attempted"), {"success": result.get("success"), "steps": result.get("total_steps")})
                results.append(result)
            elif msg_type == "request":
                result = self._run_agent(f"Alfred is requesting: {payload.get('subject', '')}\nDetails: {payload.get('details', payload.get('question', ''))}\nRespond with your findings.", agent_factory)
                self.alfred.report_to_alfred(f"Re: {payload.get('subject', 'your request')[:50]}", result.get("summary", "Request processed"))
                results.append(result)
            elif msg_type == "ack":
                log.info("[Autonomy] Alfred acknowledged: %s", payload.get("note", ""))
            self.alfred.mark_read(msg_id)
        success = any(r.get("success") for r in results) if results else True
        return {"success": success, "messages_processed": len(messages), "results": results}

    def _execute_initiative(self, plan, agent_factory=None):
        details = plan["details"]
        area = details["area"]
        action = details["action"]
        rationale = details["rationale"]
        prompts = {
            "analyze_recent_errors": "Review Robin's recent error logs in rudy-logs/. Identify the top 3 failure patterns, their root causes, and propose specific fixes. Write findings to rudy-data/error-analysis.json",
            "validate_python_files": "Run py_compile on all Python files in rudy-workhorse/rudy/. Report any that fail to compile. For each failure, identify the issue.",
            "ping_alfred": None,
            "review_unanswered_messages": None,
            "system_health_check": "Run a system health check: CPU usage, RAM usage, disk free space, Ollama status (curl localhost:11434/api/tags), and report any concerns.",
            "git_status_and_quality": f"Check git status of {REPO_ROOT}. Report uncommitted changes, current branch, and any files that look problematic.",
            "research_improvements": "Analyze the current Batcave architecture (robin_main.py, robin_agent.py, robin_presence.py, robin_autonomy.py, robin_alfred_protocol.py). Identify the single highest-impact improvement. Write a brief proposal to rudy-data/improvement-proposal.txt",
            "update_documentation": "Review rudy-workhorse/rudy/ and write an updated architecture summary to rudy-data/architecture-summary.txt covering the current state of all modules.",
            "run_health_check": "Run a quick health check: verify Ollama is responding, disk space is adequate, and no Python processes are consuming excessive memory.",
        }
        if action == "ping_alfred":
            self.alfred.send_to_alfred("health", {"subject": "Robin status update", "model": self._get_model(), "system_time": datetime.now().isoformat(), "mode": "initiative", "rationale": rationale})
            self.initiative.record_completion(area, "Sent health ping to Alfred")
            return {"success": True, "summary": "Sent status ping to Alfred"}
        if action == "review_unanswered_messages":
            count = len(list(ALFRED_INBOX.glob("*.json")))
            self.initiative.record_completion(area, f"Reviewed {count} messages in Alfred inbox")
            return {"success": True, "summary": f"Alfred inbox has {count} messages"}
        prompt = prompts.get(action, f"Execute initiative: {action} - {rationale}")
        result = self._run_agent(prompt, agent_factory)
        if result.get("success") and area != "health_check":
            self.alfred.report_to_alfred(f"Initiative: {area}", result.get("summary", f"Completed {action}"), {"area": area, "action": action})
        self.initiative.record_completion(area, result.get("summary", "completed"))
        return result

    def _run_agent(self, prompt, agent_factory=None):
        if agent_factory:
            try:
                agent = agent_factory()
                result = agent.run_with_report(prompt)
                return result
            except Exception as e:
                log.error("[Autonomy] Agent execution failed: %s", e)
                return {"success": False, "error": str(e)}
        else:
            return self._ollama_fallback(prompt)

    def _ollama_fallback(self, prompt):
        try:
            import urllib.request
            data = json.dumps({"model": self._get_model(), "prompt": prompt, "stream": False}).encode()
            req = urllib.request.Request("http://localhost:11434/api/generate", data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode())
            return {"success": True, "summary": result.get("response", "")[:500], "total_steps": 1}
        except Exception as e:
            log.error("[Autonomy] Ollama fallback failed: %s", e)
            return {"success": False, "error": str(e)}

    @staticmethod
    def _get_model():
        try:
            secrets_file = RUDY_DATA / "robin-secrets.json"
            with open(secrets_file) as f:
                return json.load(f).get("ollama_model", "qwen2.5:7b")
        except Exception:
            return "qwen2.5:7b"

# ---------------------------------------------------------------------------
# Entry point for direct testing
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [Autonomy] %(levelname)s %(message)s")
    engine = AutonomyEngine()
    plan = engine.decide()
    print(json.dumps(plan, indent=2, default=str))
