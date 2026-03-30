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
import subprocess
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

from rudy.paths import (  # noqa: E402
    BATCAVE_VAULT, GIT_EXE, HANDOFFS_DIR, LUCIUS_AUDITS, REPO_ROOT,
    RUDY_DATA, RUDY_LOGS,
)

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
# Situational Awareness — Robin looks around before deciding what to do
# ---------------------------------------------------------------------------

class SituationalAwareness:
    """
    Gathers state from multiple Batcave sources so Robin can infer priorities
    without depending on any single signal (like a handoff file).

    Robin should be able to wake up with zero instructions and figure out
    what matters by reading the room — git log, Lucius findings, system
    health, coordination state, open PRs, stale files, and the vault.
    """

    # Key vault documents Robin should read for grounding and context.
    # Paths relative to BATCAVE_VAULT. Ordered by importance.
    # The mission doc grounds Robin's identity. Standing orders are law.
    # Session log and ops log give recent history. Trackers show gaps.
    VAULT_KEY_DOCS = [
        ("mission", "Architecture/Mission.md"),
        ("standing_orders", "Directives/Standing-Orders.md"),
        ("session_log", "Briefings/Alfred-Session-Log.md"),
        ("robin_ops_log", "Briefings/Robin-Operations-Log.md"),
        ("gap_closers", "Trackers/Gap-Closers.md"),
        ("improvement_log", "Trackers/Improvement-Log.md"),
    ]

    def gather(self) -> dict:
        """Collect all available signals into a single state dict."""
        state = {
            "gathered_at": datetime.now().isoformat(),
            "signals": {},
        }
        # Each gatherer is wrapped in try/except — partial state is fine.
        # A missing signal is itself a signal (e.g. "no handoff" = new setup).
        for name, fn in [
            ("git_recent", self._git_recent_activity),
            ("alfred_status", self._alfred_session_state),
            ("handoff", self._latest_handoff),
            ("lucius_findings", self._lucius_latest),
            ("open_prs", self._open_pull_requests),
            ("robin_health", self._robin_system_health),
            ("coordination", self._coordination_state),
            ("vault", self._vault_key_documents),
        ]:
            try:
                state["signals"][name] = fn()
            except Exception as e:
                state["signals"][name] = {"error": str(e)}
                log.debug("[SitAware] %s failed: %s", name, e)
        return state

    def summarize(self) -> str:
        """Human-readable summary for Ollama to reason over."""
        state = self.gather()
        signals = state["signals"]
        lines = ["=== BATCAVE SITUATIONAL AWARENESS ===", ""]

        # Git activity
        git = signals.get("git_recent", {})
        if git.get("recent_commits"):
            lines.append("RECENT GIT ACTIVITY:")
            for c in git["recent_commits"][:5]:
                lines.append(f"  {c}")
            lines.append("")
        if git.get("uncommitted_changes"):
            lines.append(f"UNCOMMITTED CHANGES: {git['uncommitted_changes']}")
            lines.append("")

        # Alfred session
        alfred = signals.get("alfred_status", {})
        if alfred:
            lines.append(f"ALFRED STATUS: {alfred.get('state', 'unknown')}")
            if alfred.get("session_number"):
                lines.append(f"  Last session: {alfred['session_number']}")
            if alfred.get("age_hours") is not None:
                lines.append(f"  Status age: {alfred['age_hours']:.1f} hours")
            if alfred.get("recommendation"):
                lines.append(f"  Recommendation: {alfred['recommendation']}")
            lines.append("")

        # Handoff
        handoff = signals.get("handoff", {})
        if handoff.get("has_handoff"):
            lines.append(f"LATEST HANDOFF: Session {handoff.get('session_number')}")
            if handoff.get("priorities"):
                lines.append("  PRIORITIES:")
                for p in handoff["priorities"]:
                    lines.append(f"    - {p}")
            if handoff.get("findings"):
                lines.append("  OPEN FINDINGS:")
                for f in handoff["findings"]:
                    lines.append(f"    - {f}")
            lines.append("")
        else:
            lines.append("NO HANDOFF FILE FOUND — infer priorities from other signals.")
            lines.append("")

        # Lucius
        lucius = signals.get("lucius_findings", {})
        if lucius.get("total_findings"):
            lines.append(f"LUCIUS AUDIT: {lucius['total_findings']} findings")
            for f in lucius.get("findings", [])[:5]:
                lines.append(f"  [{f.get('severity', '?')}] {f.get('title', '?')}")
            lines.append("")

        # Open PRs
        prs = signals.get("open_prs", {})
        if prs.get("count", 0) > 0:
            lines.append(f"OPEN PULL REQUESTS: {prs['count']}")
            for pr in prs.get("prs", [])[:5]:
                lines.append(f"  PR #{pr['number']}: {pr['title']}")
            lines.append("")

        # System health
        health = signals.get("robin_health", {})
        if health.get("degraded"):
            lines.append("SYSTEM HEALTH: DEGRADED")
            for item in health.get("degraded_items", []):
                lines.append(f"  - {item}")
            lines.append("")

        # Vault — institutional memory
        vault = signals.get("vault", {})
        if vault.get("available"):
            # Mission is Robin's identity grounding — always include
            if vault.get("mission"):
                lines.append("BATCAVE MISSION (from vault):")
                lines.append(f"  {vault['mission'][:500]}")
                lines.append("")
            # Standing orders are law
            if vault.get("standing_orders"):
                lines.append("STANDING ORDERS (from vault):")
                lines.append(f"  {vault['standing_orders'][:400]}")
                lines.append("")
            # Recent session history (tail of Alfred's session log)
            if vault.get("recent_session_history"):
                lines.append("RECENT SESSION HISTORY (from vault):")
                lines.append(f"  {vault['recent_session_history'][:600]}")
                lines.append("")
            # Tracked gaps and improvements
            if vault.get("gap_closers"):
                lines.append("GAP CLOSERS TRACKER (from vault):")
                lines.append(f"  {vault['gap_closers'][:400]}")
                lines.append("")
            if vault.get("improvement_log"):
                lines.append("IMPROVEMENT LOG (from vault):")
                lines.append(f"  {vault['improvement_log'][:400]}")
                lines.append("")
        elif vault.get("error"):
            lines.append(f"VAULT: unavailable ({vault['error']})")
            lines.append("")

        # Coordination
        coord = signals.get("coordination", {})
        if coord.get("unread_alfred_inbox"):
            lines.append(
                f"ALFRED INBOX: {coord['unread_alfred_inbox']} unread messages"
            )
            lines.append("")

        lines.append("=== END SITUATIONAL AWARENESS ===")
        return "\n".join(lines)

    # --- Individual signal gatherers ---

    def _git_recent_activity(self) -> dict:
        """Recent commits and uncommitted changes."""
        result = {}
        try:
            r = subprocess.run(
                [GIT_EXE, "log", "--oneline", "-10"],
                capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=10,
            )
            if r.returncode == 0:
                result["recent_commits"] = r.stdout.strip().splitlines()
        except Exception:
            pass
        try:
            r = subprocess.run(
                [GIT_EXE, "status", "--porcelain"],
                capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=10,
            )
            if r.returncode == 0 and r.stdout.strip():
                result["uncommitted_changes"] = len(r.stdout.strip().splitlines())
        except Exception:
            pass
        return result

    def _alfred_session_state(self) -> dict:
        """Read Alfred's coordination status file."""
        status_file = COORD_DIR / "alfred-status.json"
        if not status_file.exists():
            return {"state": "no_status_file"}
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            result = {
                "state": data.get("state", "unknown"),
                "session_number": data.get("session_number"),
                "recommendation": data.get("recommendation"),
            }
            updated = data.get("updated_at")
            if updated:
                age = datetime.now() - datetime.fromisoformat(updated)
                result["age_hours"] = age.total_seconds() / 3600
            return result
        except Exception:
            return {"state": "unreadable"}

    def _latest_handoff(self) -> dict:
        """Check for the latest handoff brief — but don't require it."""
        sidecars = sorted(HANDOFFS_DIR.glob("session-*-handoff.json"), reverse=True)
        if not sidecars:
            return {"has_handoff": False}
        try:
            data = json.loads(sidecars[0].read_text(encoding="utf-8"))
            return {
                "has_handoff": True,
                "session_number": data.get("session_number"),
                "context_estimate": data.get("context_estimate"),
                "priorities": data.get("next_priorities", []),
                "findings": data.get("findings", []),
                "accomplishments": data.get("accomplishments", []),
            }
        except Exception:
            return {"has_handoff": False, "error": "parse_failed"}

    def _lucius_latest(self) -> dict:
        """Most recent Lucius audit findings."""
        audits = sorted(LUCIUS_AUDITS.glob("audit-*.json"), reverse=True)
        if not audits:
            return {"total_findings": 0}
        try:
            data = json.loads(audits[0].read_text(encoding="utf-8"))
            return {
                "total_findings": data.get("summary", {}).get("total_findings", 0),
                "by_severity": data.get("summary", {}).get("by_severity", {}),
                "findings": data.get("findings", [])[:10],
                "audit_file": str(audits[0].name),
            }
        except Exception:
            return {"total_findings": 0, "error": "parse_failed"}

    def _open_pull_requests(self) -> dict:
        """Check GitHub for open PRs (uses API, tolerates failure)."""
        try:
            secrets_file = RUDY_DATA / "robin-secrets.json"
            if not secrets_file.exists():
                return {"count": 0, "note": "no secrets file"}
            secrets = json.loads(secrets_file.read_text(encoding="utf-8"))
            pat = secrets.get("github_pat", "")
            if not pat:
                return {"count": 0, "note": "no PAT"}
            import urllib.request
            url = "https://api.github.com/repos/Rudy-Assistant/rudy-workhorse/pulls?state=open&per_page=10"
            req = urllib.request.Request(url, headers={
                "Authorization": f"Bearer {pat}",
                "Accept": "application/vnd.github.v3+json",
            })
            with urllib.request.urlopen(req, timeout=15) as resp:  # nosec B310 — GitHub API
                prs = json.loads(resp.read())
            return {
                "count": len(prs),
                "prs": [{"number": p["number"], "title": p["title"],
                          "branch": p["head"]["ref"]} for p in prs],
            }
        except Exception as e:
            return {"count": 0, "error": str(e)}

    def _robin_system_health(self) -> dict:
        """Read Robin's own health state."""
        from rudy.paths import ROBIN_STATE
        if not ROBIN_STATE.exists():
            return {"degraded": True, "degraded_items": ["No robin-state.json"]}
        try:
            data = json.loads(ROBIN_STATE.read_text(encoding="utf-8"))
            degraded_items = []
            health = data.get("health", data.get("boot", {}))
            for phase_name, phase in health.get("phases", {}).items():
                if not phase.get("healthy", True):
                    for svc, info in phase.get("services", {}).items():
                        if not info.get("ok"):
                            degraded_items.append(
                                f"{svc}: {info.get('state', info.get('error', 'unhealthy'))}"
                            )
                    for check, info in phase.get("checks", {}).items():
                        if not info.get("ok"):
                            degraded_items.append(
                                f"{check}: {info.get('state', info.get('error', 'unhealthy'))}"
                            )
            last_check = data.get("last_health_check", "")
            stale = False
            if last_check:
                age = (datetime.now() - datetime.fromisoformat(last_check))
                stale = age.total_seconds() > 1800  # 30 min
                if stale:
                    degraded_items.append(
                        f"Health check stale ({age.total_seconds()/60:.0f} min old)"
                    )
            return {
                "degraded": bool(degraded_items),
                "degraded_items": degraded_items,
                "recommendation": health.get("recommendation", "unknown"),
                "stale_heartbeat": stale,
            }
        except Exception as e:
            return {"degraded": True, "degraded_items": [f"Parse error: {e}"]}

    def _coordination_state(self) -> dict:
        """Summary of coordination directory."""
        result = {}
        inbox_count = len(list(ALFRED_INBOX.glob("*.json")))
        if inbox_count:
            result["unread_alfred_inbox"] = inbox_count
        robin_inbox_count = len(list(ROBIN_INBOX.glob("*.json")))
        if robin_inbox_count:
            result["unread_robin_inbox"] = robin_inbox_count
        return result

    def _vault_key_documents(self) -> dict:
        """Read key BatcaveVault documents for institutional memory.

        The vault is Robin's persistent memory — mission, standing orders,
        session history, and trackers. Robin reads it the same way a deputy
        reads the team's shared drive when they come on shift.

        Note: BATCAVE_VAULT is per-Oracle (gitignored). If the vault
        doesn't exist on this Oracle, Robin operates without it — degraded
        but functional, like every other signal in SituationalAwareness.
        """
        if not BATCAVE_VAULT.exists():
            return {"available": False, "error": "vault directory missing"}

        result = {"available": True}

        for key, rel_path in self.VAULT_KEY_DOCS:
            filepath = BATCAVE_VAULT / rel_path
            if not filepath.exists():
                continue
            try:
                content = filepath.read_text(encoding="utf-8")
                if key == "session_log":
                    # Session log grows — only include the last ~2000 chars
                    # (most recent sessions) to keep context manageable.
                    result["recent_session_history"] = content[-2000:]
                elif key == "mission":
                    # Extract the core mission, skip the ASCII art stack
                    # diagram that Ollama doesn't need.
                    result["mission"] = self._extract_mission_core(content)
                else:
                    result[key] = content[:1500]
            except Exception as e:
                log.debug("[SitAware] vault %s unreadable: %s", key, e)

        # Semantic search bonus: if ChromaDB has a vault collection indexed,
        # pull the most relevant chunks for "current priorities and gaps".
        try:
            from rudy.knowledge_base import KnowledgeBase
            kb = KnowledgeBase()
            if kb._collection_exists("vault"):
                hits = kb.search(
                    "current priorities gaps improvements needed",
                    collection="vault", n_results=3,
                )
                if hits:
                    result["semantic_context"] = [
                        f"[{h['source']}] {h['text'][:200]}" for h in hits
                    ]
        except Exception:
            pass  # ChromaDB/sentence-transformers not available — fine

        return result

    @staticmethod
    def _extract_mission_core(mission_text: str) -> str:
        """Extract the narrative core from Mission.md, skip diagrams."""
        lines = mission_text.splitlines()
        core_lines = []
        skip_code_block = False
        for line in lines:
            if line.strip().startswith("```"):
                skip_code_block = not skip_code_block
                continue
            if skip_code_block:
                continue
            core_lines.append(line)
        return "\n".join(core_lines).strip()[:800]


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
        """Choose what to work on next.

        Strategy: Gather situational awareness first. If we have enough
        signal, ask Ollama to reason about priorities (situation-driven).
        Fall back to the static priority list if Ollama is unavailable
        or situational awareness gathering fails entirely.
        """
        # --- Situation-driven path (preferred) ---
        try:
            sit = SituationalAwareness()
            summary = sit.summarize()
            # If we got meaningful signal, use Ollama to reason
            if len(summary) > 200:  # More than just the header
                initiative = self._choose_from_situation(summary)
                if initiative:
                    self.journal.append(initiative)
                    self._save_journal()
                    return initiative
        except Exception as e:
            log.warning("[Initiative] Situational awareness failed: %s", e)

        # --- Static fallback (original logic) ---
        return self._choose_from_static_priorities()

    def _choose_from_situation(self, situation_summary: str) -> dict | None:
        """Ask Ollama to reason about what matters most right now."""
        recent_areas = {}
        for entry in self.journal[-20:]:
            area = entry.get("area", "")
            started = entry.get("started_at", "")
            if area and started:
                recent_areas[area] = started

        recent_str = "\n".join(
            f"  - {a}: last worked {t}" for a, t in recent_areas.items()
        ) if recent_areas else "  (none)"

        prompt = f"""{situation_summary}

RECENT ROBIN INITIATIVES (avoid repeating within 4 hours):
{recent_str}

You are Robin, the Batcave's local AI deputy. Batman may be away.
Based on the situational awareness above, decide the SINGLE most
valuable thing to work on right now.

RULES:
- If there are handoff priorities, weight them heavily but don't
  follow them blindly if system state shows something more urgent.
- If there is NO handoff, infer priorities from git activity,
  Lucius findings, system health, and open PRs.
- Avoid repeating work you did recently (check the initiative list above).
- Prefer concrete, actionable items over vague improvements.
- If nothing urgent, do a system health check.

Respond in EXACTLY this JSON format (no other text):
{{"area": "<category>", "action": "<specific_action>", "rationale": "<one sentence why>", "description": "<what you will do>"}}

Valid areas: reliability, alfred_coordination, environment_health,
codebase_quality, capability_expansion, documentation, branch_governance,
pr_review, finding_fix, health_check"""

        try:
            import urllib.request
            model = "qwen2.5:7b"
            try:
                secrets_file = RUDY_DATA / "robin-secrets.json"
                with open(secrets_file) as f:
                    model = json.load(f).get("ollama_model", model)
            except Exception:
                pass

            data = json.dumps({
                "model": model, "prompt": prompt, "stream": False,
                "options": {"temperature": 0.3, "num_predict": 256},
            }).encode()
            req = urllib.request.Request(
                "http://localhost:11434/api/generate",
                data=data, headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=90) as resp:  # nosec B310 — localhost Ollama
                result = json.loads(resp.read().decode())

            response_text = result.get("response", "").strip()
            # Extract JSON from response (Ollama may wrap it in markdown)
            json_start = response_text.find("{")
            json_end = response_text.rfind("}") + 1
            if json_start >= 0 and json_end > json_start:
                parsed = json.loads(response_text[json_start:json_end])
                if parsed.get("area") and parsed.get("action"):
                    parsed["started_at"] = datetime.now().isoformat()
                    parsed["source"] = "situational_awareness"
                    log.info(
                        "[Initiative] Situation-driven: [%s] %s — %s",
                        parsed["area"], parsed["action"],
                        parsed.get("rationale", ""),
                    )
                    return parsed
        except Exception as e:
            log.warning("[Initiative] Ollama reasoning failed: %s", e)

        return None  # Fall through to static priorities

    def _choose_from_static_priorities(self) -> dict:
        """Original static priority fallback."""
        for priority in self.INITIATIVE_PRIORITIES:
            area = priority["area"]
            recent = self._recent_initiatives(area, hours=4)
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
                        "action": assessment["action"],
                        "rationale": assessment["rationale"],
                        "started_at": datetime.now().isoformat(),
                        "source": "static_fallback",
                    }
                    self.journal.append(initiative)
                    self._save_journal()
                    return initiative
        return {
            "area": "health_check",
            "description": "Periodic system health verification",
            "action": "run_health_check",
            "rationale": "All initiative areas recently addressed; "
                         "performing routine health check",
            "started_at": datetime.now().isoformat(),
            "source": "static_fallback",
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
        rationale = details.get("rationale", "")
        description = details.get("description", "")

        # Known quick-actions that don't need an agent
        if action == "ping_alfred":
            self.alfred.send_to_alfred("health", {
                "subject": "Robin status update", "model": self._get_model(),
                "system_time": datetime.now().isoformat(),
                "mode": "initiative", "rationale": rationale,
            })
            self.initiative.record_completion(area, "Sent health ping to Alfred")
            return {"success": True, "summary": "Sent status ping to Alfred"}
        if action == "review_unanswered_messages":
            count = len(list(ALFRED_INBOX.glob("*.json")))
            self.initiative.record_completion(
                area, f"Reviewed {count} messages in Alfred inbox"
            )
            return {"success": True, "summary": f"Alfred inbox has {count} messages"}

        # Known action → specific prompt mapping
        known_prompts = {
            "analyze_recent_errors": "Review Robin's recent error logs in rudy-logs/. Identify the top 3 failure patterns, their root causes, and propose specific fixes. Write findings to rudy-data/error-analysis.json",
            "validate_python_files": "Run py_compile on all Python files in rudy-workhorse/rudy/. Report any that fail to compile. For each failure, identify the issue.",
            "system_health_check": "Run a system health check: CPU usage, RAM usage, disk free space, Ollama status (curl localhost:11434/api/tags), and report any concerns.",
            "git_status_and_quality": f"Check git status of {REPO_ROOT}. Report uncommitted changes, current branch, and any files that look problematic.",
            "research_improvements": "Analyze the current Batcave architecture. Identify the single highest-impact improvement. Write a brief proposal to rudy-data/improvement-proposal.txt",
            "update_documentation": "Review rudy-workhorse/rudy/ and write an updated architecture summary to rudy-data/architecture-summary.txt covering the current state of all modules.",
            "run_health_check": "Run a quick health check: verify Ollama is responding, disk space is adequate, and no Python processes are consuming excessive memory.",
        }

        # For situation-driven actions, build a prompt from the action
        # description and rationale — Robin's Ollama reasoning already
        # identified what to do, so we just need to execute it.
        if action in known_prompts:
            prompt = known_prompts[action]
        elif details.get("source") == "situational_awareness":
            prompt = (
                f"You are Robin, executing a self-directed initiative.\n"
                f"Area: {area}\n"
                f"Action: {action}\n"
                f"Description: {description}\n"
                f"Rationale: {rationale}\n\n"
                f"Execute this action. Be concrete and thorough. "
                f"Report what you accomplished and any findings."
            )
        else:
            prompt = f"Execute initiative: {action} - {rationale}"

        result = self._run_agent(prompt, agent_factory)
        if result.get("success") and area != "health_check":
            self.alfred.report_to_alfred(
                f"Initiative: {area}",
                result.get("summary", f"Completed {action}"),
                {"area": area, "action": action, "source": details.get("source")},
            )
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
            with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310 — localhost Ollama
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
