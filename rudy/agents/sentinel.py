"""
Sentinel — The Trickle Agent.
Runs every 15 minutes. Lightweight. Curious.

Unlike the Four Horsemen who each own a domain:
  - SystemMaster → health
  - OperationsMonitor → maintenance
  - ResearchIntel → intelligence
  - TaskMaster → coordination

The Sentinel owns *awareness*. It:
  1. Scans for changes since last run (new files, config drift, environment shifts)
  2. Notices opportunities (package updates, stale state, idle resources)
  3. Queues micro-improvements for the other agents or itself
  4. Learns from what happened (reads agent statuses, spots patterns)
  5. Takes small, safe actions (never destructive, never heavy)

Design principles:
  - Never run longer than 30 seconds
  - Never use more than trivial CPU/disk
  - Never modify critical files
  - Always log what it noticed, even if it takes no action
  - Think of it as a heartbeat with curiosity
"""
import json
import os
import subprocess
import time
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from . import AgentBase, DESKTOP, LOGS_DIR


class Sentinel(AgentBase):
    name = "sentinel"
    version = "1.0"

    STATE_FILE = LOGS_DIR / "sentinel-state.json"
    OBSERVATIONS_FILE = LOGS_DIR / "sentinel-observations.json"
    MAX_RUNTIME = 30  # seconds — hard cap

    def run(self, **kwargs):
        self.start = time.time()
        self.observations = []

        state = self._load_state()

        # Each scan is cheap and fast — bail if we're running too long
        self._scan_agent_health(state)
        if not self._time_ok(): return self._finalize(state)

        self._scan_environment(state)
        if not self._time_ok(): return self._finalize(state)

        self._scan_for_opportunities(state)
        if not self._time_ok(): return self._finalize(state)

        self._scan_work_queue(state)
        if not self._time_ok(): return self._finalize(state)

        self._scan_presence_analytics(state)
        if not self._time_ok(): return self._finalize(state)

        self._micro_improve(state)
        self._finalize(state)

    def _time_ok(self) -> bool:
        return (time.time() - self.start) < self.MAX_RUNTIME

    def _observe(self, category: str, observation: str, actionable: bool = False):
        """Record something noticed."""
        entry = {
            "time": datetime.now().isoformat(),
            "category": category,
            "observation": observation,
            "actionable": actionable,
        }
        self.observations.append(entry)
        self.log.info(f"[{category}] {observation}")

    def _load_state(self) -> dict:
        if self.STATE_FILE.exists():
            try:
                with open(self.STATE_FILE) as f:
                    return json.load(f)
            except:
                pass
        return {
            "run_count": 0,
            "last_run": None,
            "file_hashes": {},
            "last_agent_statuses": {},
            "improvement_log": [],
            "streak": 0,  # consecutive healthy runs
        }

    def _save_state(self, state: dict):
        state["last_run"] = datetime.now().isoformat()
        state["run_count"] = state.get("run_count", 0) + 1
        with open(self.STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, default=str)


    def _scan_presence_analytics(self, state):
        """Ensure presence analytics are fresh; re-run if stale."""
        try:
            analytics_file = LOGS_DIR / "presence-analytics.json"
            if analytics_file.exists():
                with open(analytics_file) as f:
                    data = json.load(f)
                ts = data.get("timestamp", "")
                if ts:
                    age = (datetime.now() - datetime.fromisoformat(ts)).total_seconds()
                    if age > 3600:
                        self._observe("analytics", f"Presence analytics stale ({age/60:.0f}m old), refreshing")
                        from rudy.presence_analytics import PresenceAnalytics
                        PresenceAnalytics().run()
                    else:
                        scan_count = data.get("scan_count", 0)
                        device_count = data.get("device_count", 0)
                        clusters = len(data.get("clusters", []))
                        self._observe("analytics", f"Analytics healthy: {device_count} devices, {clusters} clusters, {scan_count} scans")
            else:
                self._observe("analytics", "No presence analytics yet — will initialize on next presence scan")
        except Exception as e:
            self._observe("analytics_error", str(e))

    def _finalize(self, state):
        """Save state and observations."""
        # Update streak
        has_alerts = len(self.status.get("critical_alerts", [])) > 0
        if has_alerts:
            state["streak"] = 0
        else:
            state["streak"] = state.get("streak", 0) + 1

        self._save_state(state)

        # Save recent observations (keep last 100)
        all_obs = []
        if self.OBSERVATIONS_FILE.exists():
            try:
                with open(self.OBSERVATIONS_FILE) as f:
                    all_obs = json.load(f)
            except:
                pass
        all_obs.extend(self.observations)
        all_obs = all_obs[-100:]
        with open(self.OBSERVATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(all_obs, f, indent=2, default=str)

        actionable = sum(1 for o in self.observations if o.get("actionable"))
        self.summarize(
            f"Noticed {len(self.observations)} things ({actionable} actionable). "
            f"Streak: {state.get('streak', 0)} healthy runs."
        )

    # === SCAN MODULES ===

    def _scan_agent_health(self, state):
        """Check if any agent has gone stale or errored since last check."""
        agents = ["system_master", "operations_monitor", "research_intel", "task_master"]
        prev = state.get("last_agent_statuses", {})

        for agent_name in agents:
            status = self.read_status(agent_name)
            agent_status = status.get("status", "unknown")
            last_run = status.get("last_run", "never")

            # Detect status change
            prev_status = prev.get(agent_name, {}).get("status", "unknown")
            if agent_status != prev_status and prev_status != "unknown":
                self._observe("agent_change",
                    f"{agent_name}: {prev_status} → {agent_status}",
                    actionable=(agent_status == "error"))

            # Detect staleness (agent hasn't run when expected)
            if last_run != "never":
                try:
                    last_dt = datetime.fromisoformat(last_run)
                    age_hours = (datetime.now() - last_dt).total_seconds() / 3600
                    # SystemMaster should run every 5min, others less frequently
                    if agent_name == "system_master" and age_hours > 1:
                        self._observe("staleness",
                            f"{agent_name} hasn't run in {age_hours:.1f} hours",
                            actionable=True)
                except:
                    pass

            prev[agent_name] = {"status": agent_status, "last_run": last_run}

        state["last_agent_statuses"] = prev

    def _scan_environment(self, state):
        """Check for environmental changes."""
        # Monitor critical config files for unexpected changes
        critical_files = {
            "CLAUDE.md": DESKTOP / "CLAUDE.md",
            "command_runner": DESKTOP / "rudy-command-runner.py",
            "healthcheck": DESKTOP / "workhorse-healthcheck.ps1",
        }

        prev_hashes = state.get("file_hashes", {})
        for name, path in critical_files.items():
            if path.exists():
                try:
                    current_hash = hashlib.md5(
                        path.read_bytes()
                    ).hexdigest()[:12]
                    prev_hash = prev_hashes.get(name)
                    if prev_hash and current_hash != prev_hash:
                        self._observe("config_change",
                            f"{name} was modified since last check",
                            actionable=False)
                    prev_hashes[name] = current_hash
                except:
                    pass

        state["file_hashes"] = prev_hashes

        # Check disk space trend
        import shutil
        total, used, free = shutil.disk_usage("C:\\")
        free_gb = round(free / (1024**3), 1)
        prev_free = state.get("last_disk_free_gb")
        if prev_free is not None:
            delta = free_gb - prev_free
            if delta < -1:  # Lost more than 1GB since last check
                self._observe("disk_trend",
                    f"Disk shrinking: {prev_free} → {free_gb} GB free ({delta:+.1f} GB)",
                    actionable=(free_gb < 50))
        state["last_disk_free_gb"] = free_gb

    def _scan_for_opportunities(self, state):
        """Look for improvement opportunities."""
        # Check if there are stale files in rudy-commands
        cmd_dir = DESKTOP / "rudy-commands"
        stale_results = 0
        for f in cmd_dir.glob("*.result"):
            age_hours = (datetime.now().timestamp() - f.stat().st_mtime) / 3600
            if age_hours > 24:
                stale_results += 1
        if stale_results > 5:
            self._observe("cleanup_opportunity",
                f"{stale_results} result files older than 24h in rudy-commands/",
                actionable=True)

        # Check if logs are growing large
        total_log_mb = 0
        for f in LOGS_DIR.glob("*.log"):
            total_log_mb += f.stat().st_size / (1024 * 1024)
        if total_log_mb > 50:
            self._observe("logs_growing",
                f"Total log size: {total_log_mb:.1f} MB — rotation may be needed",
                actionable=True)

        # Check alert file
        alert_file = LOGS_DIR / "ALERT-ACTIVE.txt"
        if alert_file.exists():
            try:
                content = alert_file.read_text().strip()
                self._observe("active_alert",
                    f"Unresolved alert: {content}",
                    actionable=True)
            except:
                pass

    def _scan_work_queue(self, state):
        """Check if the work queue has stale items."""
        queue_file = LOGS_DIR / "task-queue.json"
        if queue_file.exists():
            try:
                with open(queue_file) as f:
                    queue = json.load(f)
                pending = len(queue.get("pending", []))
                if pending > 0:
                    self._observe("work_pending",
                        f"{pending} items in work queue",
                        actionable=False)
            except:
                pass

    def _micro_improve(self, state):
        """Take small, safe improvement actions."""
        # Only attempt micro-improvements every 4th run (~hourly)
        run_count = state.get("run_count", 0)
        if run_count % 4 != 0:
            return

        # Clean up any stale lock files
        lock_file = DESKTOP / "rudy-commands" / "_runner.lock"
        if lock_file.exists():
            try:
                pid = int(lock_file.read_text().strip())
                result = subprocess.run(
                    f'tasklist /FI "PID eq {pid}" /NH',
                    shell=True, capture_output=True, text=True, timeout=5
                )
                if str(pid) not in result.stdout:
                    lock_file.unlink()
                    self._observe("micro_fix",
                        f"Cleaned stale lock file (PID {pid} gone)",
                        actionable=False)
                    self.action("Cleaned stale runner lock file")
            except:
                pass

        # Remove empty __pycache__ dirs (harmless cleanup)
        cleaned = 0
        for root, dirs, files in os.walk(str(DESKTOP)):
            for d in list(dirs):
                full = os.path.join(root, d)
                if d == "__pycache__":
                    try:
                        if not os.listdir(full):  # Only empty ones
                            os.rmdir(full)
                            cleaned += 1
                    except:
                        pass
            if cleaned >= 3:
                break  # Don't spend too long
        if cleaned:
            self.action(f"Removed {cleaned} empty __pycache__ dirs")


if __name__ == "__main__":
    agent = Sentinel()
    agent.execute()


    def _check_knowledge_base(self):
        """Check if knowledge base needs re-indexing."""
        try:
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from rudy.knowledge_base import KnowledgeBase
            kb = KnowledgeBase()
            stats = kb.get_stats()
            last_index = stats.get("last_full_index")
            if not last_index:
                return {"action": "needs_initial_index"}
            from datetime import datetime, timedelta
            last_dt = datetime.fromisoformat(last_index)
            if datetime.now() - last_dt > timedelta(hours=24):
                return {"action": "stale_index", "hours_old": (datetime.now() - last_dt).total_seconds() / 3600}
            return {"status": "fresh", "chunks": stats.get("total_chunks", 0)}
        except Exception as e:
            return {"error": str(e)[:100]}

    def _check_api_server(self):
        """Check if the Rudy API server is responding."""
        try:
            import requests
            resp = requests.get("http://127.0.0.1:8000/health", timeout=5)
            return {"status": "up" if resp.status_code == 200 else "degraded"}
        except Exception:
            return {"status": "down"}
