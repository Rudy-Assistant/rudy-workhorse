"""
TaskMaster — Work Execution & Coordination Agent.
Manages the work queue, generates daily briefings, and monitors
all other agents for health and progress.
"""
import json
import os
from datetime import datetime
from . import AgentBase, DESKTOP, LOGS_DIR


class TaskMaster(AgentBase):
    name = "task_master"
    version = "1.0"

    QUEUE_FILE = LOGS_DIR / "task-queue.json"

    def run(self, **kwargs):
        mode = kwargs.get("mode", "briefing")

        if mode in ("briefing", "full"):
            self._generate_briefing()

        if mode in ("status", "full"):
            self._check_agent_health()

        if mode in ("queue", "full"):
            self._process_queue()

        self.summarize(f"TaskMaster cycle complete (mode={mode})")

    def _load_queue(self) -> dict:
        """Load work queue from disk."""
        if self.QUEUE_FILE.exists():
            try:
                with open(self.QUEUE_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return {"pending": [], "in_progress": [], "completed": [], "last_updated": None}

    def _save_queue(self, queue: dict):
        """Save work queue to disk."""
        queue["last_updated"] = datetime.now().isoformat()
        with open(self.QUEUE_FILE, "w", encoding="utf-8") as f:
            json.dump(queue, f, indent=2, default=str)

    def _generate_briefing(self):
        """Generate daily morning briefing from all agent statuses."""
        self.log.info("Generating morning briefing...")
        briefing = []
        briefing.append("=" * 50)
        briefing.append(f"  WORKHORSE BRIEFING — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        briefing.append("=" * 50)

        # System health
        sys_status = self.read_status("system_master")
        briefing.append(f"\n  System: {sys_status.get('status', 'unknown').upper()}")
        if sys_status.get("disk_free_gb"):
            briefing.append(f"  Disk: {sys_status['disk_free_gb']} GB free ({sys_status.get('disk_pct_used', '?')}% used)")
        for alert in sys_status.get("critical_alerts", []):
            briefing.append(f"  ⚠ {alert}")

        # Operations
        ops_status = self.read_status("operations_monitor")
        briefing.append(f"\n  Operations: {ops_status.get('status', 'unknown').upper()}")
        if ops_status.get("last_run") and ops_status["last_run"] != "never":
            briefing.append(f"  Last maintenance: {ops_status['last_run'][:16]}")

        # Research
        research_status = self.read_status("research_intel")
        briefing.append(f"\n  Research: {research_status.get('status', 'unknown').upper()}")
        recs = research_status.get("recommendations", [])
        if recs:
            briefing.append(f"  Recommendations: {len(recs)} pending")
            for r in recs[:3]:
                briefing.append(f"    - {r}")

        # Work queue
        queue = self._load_queue()
        pending = len(queue.get("pending", []))
        in_progress = len(queue.get("in_progress", []))
        completed = len(queue.get("completed", []))
        briefing.append(f"\n  Work Queue: {pending} pending, {in_progress} active, {completed} completed")

        # Agent health summary
        briefing.append("\n  Agent Status:")
        for agent_name in ["system_master", "operations_monitor", "research_intel", "task_master"]:
            status = self.read_status(agent_name)
            last = status.get("last_run", "never")
            if last != "never":
                last = last[:16]
            briefing.append(f"    {agent_name}: {status.get('status', 'unknown')} (last: {last})")

        briefing.append("\n" + "=" * 50)

        briefing_text = "\n".join(briefing)
        print(briefing_text)

        # Save briefing to file
        briefing_file = LOGS_DIR / f"briefing-{datetime.now().strftime('%Y%m%d')}.txt"
        with open(briefing_file, "w", encoding="utf-8") as f:
            f.write(briefing_text)

        self.action("Generated morning briefing")
        self.summarize(f"Briefing: sys={sys_status.get('status', '?')}, queue={pending}p/{in_progress}a/{completed}c")

    def _check_agent_health(self):
        """Monitor all agent statuses and flag issues."""
        self.log.info("Checking agent health...")
        for agent_name in ["system_master", "operations_monitor", "research_intel"]:
            status = self.read_status(agent_name)
            if status.get("status") == "error":
                self.warn(f"Agent {agent_name} is in error state")
            if status.get("critical_alerts"):
                for alert in status["critical_alerts"]:
                    self.warn(f"{agent_name} alert: {alert}")

    def _process_queue(self):
        """Process pending work items (placeholder for future expansion)."""
        queue = self._load_queue()
        # For now, just report queue state
        self.log.info(f"Queue: {len(queue.get('pending', []))} pending, "
                      f"{len(queue.get('in_progress', []))} active")
        self._save_queue(queue)


if __name__ == "__main__":
    import sys
    mode = sys.argv[1] if len(sys.argv) > 1 else "briefing"
    agent = TaskMaster()
    agent.execute(mode=mode)


    def _run_financial_briefing(self):
        """Generate financial snapshot for morning briefing."""
        try:
            from pathlib import Path
            sys.path.insert(0, str(Path(__file__).parent.parent.parent))
            from rudy.financial import FinancialIntelligence
            fi = FinancialIntelligence()
            snapshot = fi.watchlist.get_dashboard()
            alerts = fi.alerts.check_alerts()
            return {
                "tickers_checked": len(snapshot.get("quotes", [])),
                "alerts_triggered": len(alerts),
            }
        except Exception as e:
            return {"error": str(e)[:100]}
