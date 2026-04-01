"""
Base Agent — common infrastructure for all Workhorse agents.
Each agent writes structured status to rudy-logs/<agent>-status.json
and produces human-readable output via the command runner result protocol.

Crash dumps: On unhandled exceptions, writes detailed state to
rudy-logs/crash-dumps/<agent>-<timestamp>.json for Sentinel to pick up
and include in session briefings. This closes the cascade failure gap
where agent crashes caused memory loss between sessions.
"""
import json
import logging
import sys
import traceback as tb_module
from datetime import datetime
from pathlib import Path
from rudy.paths import RUDY_LOGS

LOGS_DIR = RUDY_LOGS
LOGS_DIR.mkdir(exist_ok=True)

# Add rudy package to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))


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
        """Entry point — wraps run() with status management and error handling.

        On crash: writes a detailed dump to rudy-logs/crash-dumps/ so Sentinel
        can surface it in the next session briefing. This prevents memory loss
        when an agent dies between Cowork sessions.
        """
        self.log.info(f"=== {self.name} v{self.version} starting ===")
        try:
            self.status["status"] = "running"
            result = self.run(**kwargs)
            self.status["status"] = "healthy"
            return result
        except Exception as e:
            self.status["status"] = "error"
            self.status["critical_alerts"].append(str(e))
            self.log.error(f"Agent error: {e}", exc_info=True)
            self._write_crash_dump(e, kwargs)
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

    def _write_crash_dump(self, error: Exception, kwargs: dict):
        """Write a detailed crash dump for Sentinel to pick up.

        Dumps go to rudy-logs/crash-dumps/<agent>-<timestamp>.json.
        Contains: error details, full traceback, agent state at crash time,
        kwargs that were passed, and recent log lines for context.
        """
        try:
            crash_dir = LOGS_DIR / "crash-dumps"
            crash_dir.mkdir(exist_ok=True)

            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            crash_file = crash_dir / f"{self.name}-{timestamp}.json"

            # Collect recent log lines for context
            recent_log = []
            log_file = LOGS_DIR / f"{self.name}.log"
            if log_file.exists():
                try:
                    lines = log_file.read_text(encoding="utf-8", errors="replace").splitlines()
                    recent_log = lines[-20:]  # Last 20 lines
                except Exception:
                    recent_log = ["(could not read log)"]

            # Sanitize kwargs (remove anything non-serializable)
            safe_kwargs = {}
            for k, v in kwargs.items():
                try:
                    json.dumps(v)
                    safe_kwargs[k] = v
                except (TypeError, ValueError):
                    safe_kwargs[k] = str(v)

            dump = {
                "agent": self.name,
                "version": self.version,
                "crash_time": datetime.now().isoformat(),
                "error_type": type(error).__name__,
                "error_message": str(error),
                "traceback": tb_module.format_exc(),
                "kwargs": safe_kwargs,
                "status_at_crash": self.status,
                "recent_log_lines": recent_log,
                "uptime_seconds": round((datetime.now() - self.start_time).total_seconds(), 1),
            }

            with open(crash_file, "w", encoding="utf-8") as f:
                json.dump(dump, f, indent=2, default=str)

            self.log.error(f"Crash dump written to {crash_file}")

            # Also write a marker file for quick detection
            marker = LOGS_DIR / "CRASH-DETECTED.txt"
            with open(marker, "w") as f:
                f.write(f"{self.name} crashed at {datetime.now().isoformat()}\n")
                f.write(f"Error: {error}\n")
                f.write(f"Dump: {crash_file}\n")

        except Exception as dump_error:
            # If even the crash dump fails, at least log it
            self.log.error(f"Failed to write crash dump: {dump_error}")

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
