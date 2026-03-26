"""
Base Agent — common infrastructure for all Workhorse agents.
Each agent writes structured status to rudy-logs/<agent>-status.json
and produces human-readable output via the command runner result protocol.
"""
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS_DIR = DESKTOP / "rudy-logs"
LOGS_DIR.mkdir(exist_ok=True)

# Add rudy package to path
sys.path.insert(0, str(DESKTOP))


class AgentBase:
    """Base class for all Workhorse sub-agents."""

    name: str = "unnamed"
    version: str = "1.0"

    def __init__(self):
        self.start_time = datetime.now()
        self.status = {
            "agent": self.name,
            "version": self.version,
            "last_run": self.start_time.isoformat(),
            "status": "starting",
            "duration_seconds": 0,
            "critical_alerts": [],
            "warnings": [],
            "actions_taken": [],
            "summary": "",
        }

        # Set up logging
        log_file = LOGS_DIR / f"{self.name}.log"
        self.log = logging.getLogger(self.name)
        self.log.setLevel(logging.INFO)
        if not self.log.handlers:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(message)s"))
            self.log.addHandler(fh)
            sh = logging.StreamHandler(sys.stdout)
            sh.setFormatter(logging.Formatter("[%(name)s] %(message)s"))
            self.log.addHandler(sh)

    def run(self, **kwargs):
        """Override this in subclasses."""
        raise NotImplementedError

    def execute(self, **kwargs):
        """Entry point — wraps run() with status management and error handling."""
        self.log.info(f"=== {self.name} v{self.version} starting ===")
        try:
            self.status["status"] = "running"
            self.run(**kwargs)
            self.status["status"] = "healthy"
        except Exception as e:
            self.status["status"] = "error"
            self.status["critical_alerts"].append(str(e))
            self.log.error(f"Agent error: {e}", exc_info=True)
        finally:
            elapsed = (datetime.now() - self.start_time).total_seconds()
            self.status["duration_seconds"] = round(elapsed, 1)
            self._write_status()
            self._trim_log()
            self.log.info(f"=== {self.name} complete ({elapsed:.1f}s) ===")

    def alert(self, message: str):
        """Record a critical alert."""
        self.status["critical_alerts"].append(message)
        self.log.warning(f"ALERT: {message}")

    def warn(self, message: str):
        """Record a warning."""
        self.status["warnings"].append(message)
        self.log.info(f"WARN: {message}")

    def action(self, message: str):
        """Record an action taken."""
        self.status["actions_taken"].append(message)
        self.log.info(f"ACTION: {message}")

    def summarize(self, text: str):
        """Set the human-readable summary."""
        self.status["summary"] = text

    def _write_status(self):
        """Write agent status to JSON file."""
        status_file = LOGS_DIR / f"{self.name}-status.json"
        try:
            with open(status_file, "w", encoding="utf-8") as f:
                json.dump(self.status, f, indent=2, default=str)
        except Exception as e:
            self.log.error(f"Failed to write status: {e}")

    def _trim_log(self, max_lines=500):
        """Keep log file from growing unbounded."""
        log_file = LOGS_DIR / f"{self.name}.log"
        try:
            if log_file.exists():
                lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                if len(lines) > max_lines:
                    log_file.write_text("\n".join(lines[-max_lines:]) + "\n", encoding="utf-8")
        except Exception:
            pass

    def read_status(self, agent_name: str) -> dict:
        """Read another agent's last status."""
        status_file = LOGS_DIR / f"{agent_name}-status.json"
        try:
            if status_file.exists():
                with open(status_file) as f:
                    return json.load(f)
        except Exception:
            pass
        return {"status": "unknown", "last_run": "never"}
