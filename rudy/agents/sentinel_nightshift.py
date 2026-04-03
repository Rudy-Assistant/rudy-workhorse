"""
Sentinel NightShift -- Autonomous night shift operator.

Extracted from robin_sentinel.py (Session 79, ADR-005 Phase 2b).
When Batman is AFK, Robin drives improvement forward.
"""

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from rudy.paths import (
    REPO_ROOT as RUDY_ROOT,
    RUDY_DATA,
    RUDY_LOGS,
    RUDY_COMMANDS,
)

# Task queue for autonomous operation
try:
    from rudy.robin_taskqueue import seed_standard_nightwatch, seed_deep_work, process_all
    TASKQUEUE_AVAILABLE = True
except ImportError:
    TASKQUEUE_AVAILABLE = False

NIGHT_SHIFT_LOG = RUDY_LOGS / "robin-night-shift.log"
IMMUNE_MEMORY = RUDY_DATA / "robin-immune-memory.json"

class NightShift:
    """
    When Batman is AFK, Robin drives improvement forward.

    Triggers:
    - Sentinel detects no Cowork session, no emails, no commands for N hours
    - Alfred explicitly hands off at end of session
    - Time-based: after configurable hour (e.g., 11 PM local)
    - Manual: --night-shift flag

    Night shift activities (priority order):
    1. Process robin-tasks from alfred-skills repo (highest priority — Alfred asked for these)
    2. Run pending improvement tasks from overnight schedule
    3. Self-improvement: review immune memory, optimize recovery playbooks
    4. Research and learning: pull from RSS feeds, check for tool updates
    5. Prepare morning briefing for Batman
    6. Code quality: run linters, tests, dependency checks on rudy-workhorse
    """

    # Away-mode: activate after 15 min of inactivity (was 2h).
    # Override via directive file or ROBIN_INACTIVITY_MINUTES env var.
    INACTIVITY_THRESHOLD_HOURS = float(os.environ.get(
        "ROBIN_INACTIVITY_MINUTES", "15")) / 60
    NIGHT_HOURS = (23, 6)  # 11 PM to 6 AM = automatic night shift consideration

    def __init__(self, state: dict, online: bool = False):
        self.state = state
        self.online = online
        self.log = logging.getLogger("robin_nightshift")

    def should_activate(self) -> bool:
        """Determine if night shift should activate."""
        now = datetime.now()

        # Check if it's nighttime
        hour = now.hour
        is_night = hour >= self.NIGHT_HOURS[0] or hour < self.NIGHT_HOURS[1]

        # Check Batman inactivity (look for recent command files, session markers)
        last_activity = self._detect_last_batman_activity()
        inactive_hours = (now - last_activity).total_seconds() / 3600 if last_activity else float("inf")
        is_inactive = inactive_hours >= self.INACTIVITY_THRESHOLD_HOURS

        self.log.info(
            "Night shift check: night=%s inactive=%.1fh (threshold=%dh)",
            is_night, inactive_hours, self.INACTIVITY_THRESHOLD_HOURS,
        )

        return is_night or is_inactive

    def _detect_last_batman_activity(self) -> Optional[datetime]:
        """Detect when Batman was last active by checking various signals.

        S76 FIX: Added HID (keyboard/mouse) detection via GetLastInputInfo.
        Previously only checked command files, returning None after reboot
        which made inactive_hours=inf and NightShift activate instantly.
        """
        signals = []

        # PRIMARY: HID (keyboard/mouse) activity via Win32 API
        try:
            from rudy.robin_presence_guard import get_idle_seconds
            idle = get_idle_seconds()
            if idle < float("inf"):
                signals.append(
                    datetime.now() - timedelta(seconds=idle))
        except ImportError:
            pass

        # SECONDARY: Check rudy-commands for recent files
        if RUDY_COMMANDS.exists():
            for f in RUDY_COMMANDS.iterdir():
                if f.suffix in (".py", ".ps1", ".result"):
                    signals.append(datetime.fromtimestamp(f.stat().st_mtime))

        # TERTIARY: Check cowork activity marker
        cowork_marker = RUDY_LOGS / "last-cowork-activity.txt"
        if cowork_marker.exists():
            signals.append(datetime.fromtimestamp(cowork_marker.stat().st_mtime))

        return max(signals) if signals else None

    def run(self) -> dict:
        """Execute the night shift using the task queue for autonomous operation."""
        self.log.info("=== ROBIN NIGHT SHIFT ACTIVATED ===")
        results = {"started": datetime.now().isoformat(), "tasks_completed": [], "errors": []}

        try:
            # Phase 1: Seed and run the task queue (primary work engine)
            if TASKQUEUE_AVAILABLE:
                self.log.info("Step 1: Seeding task queue (nightwatch + deep work)")
                seed_standard_nightwatch()
                if self.online:
                    seed_deep_work()
                self.log.info("Step 2: Processing task queue (max 30 min)")
                tq_count = process_all(max_tasks=20, max_minutes=30)
                # process_all returns int (number of tasks processed)
                results["taskqueue"] = tq_count
                self.log.info("Task queue: %d tasks processed", tq_count)
            else:
                self.log.warning("Task queue not available — falling back to legacy steps")
                # Legacy fallback: hardcoded steps
                if self.online:
                    results["bridge_tasks"] = self._run_bridge_tasks()
                results["improvements"] = self._review_immune_memory()
                results["code_quality"] = self._run_code_quality()
                if self.online:
                    results["morning_briefing"] = self._prepare_morning_briefing()

            # Phase 2: Prepare morning briefing (always, task queue or not)
            if self.online:
                self.log.info("Step 3: Preparing morning briefing")
                briefing = self._prepare_morning_briefing()
                results["morning_briefing"] = briefing

        except Exception as e:
            self.log.error("Night shift error: %s", e)
            results["errors"].append(str(e))

        results["ended"] = datetime.now().isoformat()
        self.log.info("=== NIGHT SHIFT COMPLETE ===")

        # Write night shift log
        with open(NIGHT_SHIFT_LOG, "a") as f:
            f.write(json.dumps(results, indent=2) + "\n---\n")

        return results

    def _run_bridge_tasks(self) -> dict:
        """Invoke robin_bridge to process pending tasks from alfred-skills."""
        try:
            from rudy.agents.robin_bridge import RobinBridge
            bridge = RobinBridge()
            return bridge.poll_and_execute()
        except ImportError:
            self.log.warning("robin_bridge not yet available")
            return {"status": "bridge_not_implemented"}
        except Exception as e:
            self.log.error("Bridge task error: %s", e)
            return {"status": "error", "error": str(e)}

    def _review_immune_memory(self) -> dict:
        """Review past failures and see if any patterns suggest preventive action."""
        memory = load_immune_memory()
        fixes = memory.get("fixes", [])
        if not fixes:
            return {"status": "no_history"}

        # Count recurring problems
        problem_counts: dict[str, int] = {}
        for fix in fixes:
            p = fix.get("problem", "unknown")
            problem_counts[p] = problem_counts.get(p, 0) + 1

        recurring = {k: v for k, v in problem_counts.items() if v >= 3}
        if recurring:
            self.log.warning("Recurring problems detected: %s", recurring)
            # TODO: Consult Ollama for deeper analysis of recurring issues
            return {"status": "recurring_issues", "recurring": recurring}

        return {"status": "healthy", "total_fixes": len(fixes)}

    def _run_code_quality(self) -> dict:
        """Run basic code quality checks on rudy-workhorse."""
        rudy_dir = RUDY_ROOT / "rudy"
        if not rudy_dir.exists():
            return {"status": "rudy_dir_not_found"}

        results = {}

        # Try ruff lint
        try:
            result = subprocess.run(
                ["python", "-m", "ruff", "check", str(rudy_dir), "--statistics", "--quiet"],
                capture_output=True, text=True, timeout=60,
            )
            results["ruff"] = {
                "return_code": result.returncode,
                "issues": result.stdout.strip() if result.stdout else "clean",
            }
        except Exception as e:
            results["ruff"] = {"error": str(e)}

        return results

    def _prepare_morning_briefing(self) -> dict:
        """Prepare a morning briefing for Batman."""
        briefing = {
            "timestamp": datetime.now().isoformat(),
            "system_status": "Will be populated by Sentinel assessment",
            "robin_tasks_completed": [],
            "alerts": [],
        }

        # The actual briefing content will be enriched by:
        # - Sentinel health status
        # - Bridge task results
        # - Email check (via email_poller or listener)
        # - Calendar check (if we have API access)
        # For now, write a placeholder that the morning briefing agent can pick up
        briefing_file = RUDY_LOGS / "morning-briefing-draft.json"
        with open(briefing_file, "w") as f:
            json.dump(briefing, f, indent=2)
        return {"status": "draft_prepared", "file": str(briefing_file)}

