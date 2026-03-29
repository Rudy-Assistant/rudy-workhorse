"""
CronScheduler — Schedule and execute recurring tasks

Features:
- Cron expression parsing (5-field format)
- Support for @daily, @hourly, @weekly, @monthly shortcuts
- Due job discovery and execution
- SQLite persistence for job definitions
"""

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable
import uuid

log = logging.getLogger(__name__)

# Default database path
DESKTOP = Path(__file__).resolve().parent.parent.parent / "Desktop" if not Path(__file__).resolve().parent.parent.parent.name == "push-staging" else Path(__file__).resolve().parent.parent.parent
if str(DESKTOP) == str(Path(__file__).resolve().parent.parent.parent):
    DESKTOP = Path(__file__).resolve().parent.parent.parent / "Desktop"
DEFAULT_DB_PATH = DESKTOP / "rudy-data" / "memory.sqlite"


@dataclass
class CronJob:
    """Represents a scheduled cron job."""
    id: str
    name: str
    schedule: str
    task_type: str
    task_config: Dict[str, Any]
    enabled: bool
    created_at: str
    last_run: Optional[str] = None
    next_run: Optional[str] = None
    run_count: int = 0


class CronScheduler:
    """Schedule and execute recurring tasks based on cron expressions."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize CronScheduler.

        Args:
            db_path: Path to memory.sqlite
        """
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory job cache
        self._jobs: Dict[str, CronJob] = {}

        # Task executors: {task_type: callable}
        self._executors: Dict[str, Callable] = {}

        self._init_db()
        self._load_jobs()
        log.info(f"CronScheduler initialized with db: {self._db_path}")

    def _init_db(self) -> None:
        """Initialize SQLite table for cron jobs."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS cron_jobs (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    schedule TEXT NOT NULL,
                    task_type TEXT NOT NULL,
                    task_config TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_run TEXT,
                    next_run TEXT,
                    run_count INTEGER DEFAULT 0
                )
            """)

            conn.commit()
            conn.close()
            log.debug("Cron jobs table initialized")
        except Exception as e:
            log.error(f"Failed to initialize cron table: {e}")

    def _load_jobs(self) -> None:
        """Load all jobs from database."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM cron_jobs")
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                job = CronJob(
                    id=row[0],
                    name=row[1],
                    schedule=row[2],
                    task_type=row[3],
                    task_config=json.loads(row[4]),
                    enabled=bool(row[5]),
                    created_at=row[6],
                    last_run=row[7],
                    next_run=row[8],
                    run_count=row[9],
                )
                self._jobs[job.id] = job

            log.debug(f"Loaded {len(self._jobs)} cron jobs")
        except Exception as e:
            log.error(f"Failed to load jobs: {e}")

    def register_executor(self, task_type: str, executor: Callable) -> None:
        """Register an executor for a task type.

        Args:
            task_type: Type identifier (e.g., "report", "scan")
            executor: Callable that takes (job: CronJob) -> result
        """
        self._executors[task_type] = executor
        log.info(f"Executor registered: {task_type}")

    def add_job(
        self,
        name: str,
        schedule: str,
        task_type: str,
        task_config: Dict[str, Any],
    ) -> str:
        """Add a new cron job.

        Args:
            name: Human-readable job name
            schedule: Cron expression (5-field) or @shortcut
            task_type: Task type identifier
            task_config: Configuration dict for the task

        Returns:
            job_id (UUID)

        Example:
            scheduler.add_job(
                "Daily report",
                "0 9 * * *",
                "report",
                {"report_type": "daily_standup"}
            )
        """
        job_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        # Calculate next run
        next_run = self._calculate_next_run(schedule, datetime.now())

        job = CronJob(
            id=job_id,
            name=name,
            schedule=schedule,
            task_type=task_type,
            task_config=task_config,
            enabled=True,
            created_at=now,
            next_run=next_run.isoformat() if next_run else None,
        )

        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO cron_jobs
                (id, name, schedule, task_type, task_config, enabled, created_at, next_run)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                job.id,
                job.name,
                job.schedule,
                job.task_type,
                json.dumps(job.task_config),
                1,
                job.created_at,
                job.next_run,
            ))
            conn.commit()
            conn.close()

            self._jobs[job_id] = job
            log.info(f"Job added: {job_id} ({name})")
            return job_id

        except Exception as e:
            log.error(f"Failed to add job: {e}")
            return ""

    def remove_job(self, job_id: str) -> bool:
        """Remove a cron job.

        Args:
            job_id: Job ID to remove

        Returns:
            True if removed, False if not found
        """
        if job_id not in self._jobs:
            return False

        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("DELETE FROM cron_jobs WHERE id = ?", (job_id,))
            conn.commit()
            conn.close()

            del self._jobs[job_id]
            log.info(f"Job removed: {job_id}")
            return True

        except Exception as e:
            log.error(f"Failed to remove job: {e}")
            return False

    def enable_job(self, job_id: str) -> bool:
        """Enable a job.

        Args:
            job_id: Job ID

        Returns:
            True if successful
        """
        if job_id not in self._jobs:
            return False

        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("UPDATE cron_jobs SET enabled = 1 WHERE id = ?", (job_id,))
            conn.commit()
            conn.close()

            self._jobs[job_id].enabled = True
            return True
        except Exception as e:
            log.error(f"Failed to enable job: {e}")
            return False

    def disable_job(self, job_id: str) -> bool:
        """Disable a job.

        Args:
            job_id: Job ID

        Returns:
            True if successful
        """
        if job_id not in self._jobs:
            return False

        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("UPDATE cron_jobs SET enabled = 0 WHERE id = ?", (job_id,))
            conn.commit()
            conn.close()

            self._jobs[job_id].enabled = False
            return True
        except Exception as e:
            log.error(f"Failed to disable job: {e}")
            return False

    def get_due_jobs(self) -> List[CronJob]:
        """Get all jobs that are due to run.

        Returns:
            List of CronJob objects where next_run <= now
        """
        now = datetime.now()
        due = []

        for job in self._jobs.values():
            if not job.enabled:
                continue
            if not job.next_run:
                continue

            try:
                next_run = datetime.fromisoformat(job.next_run)
                if next_run <= now:
                    due.append(job)
            except ValueError:
                log.warning(f"Invalid next_run for job {job.id}: {job.next_run}")

        return due

    def execute_due_jobs(self) -> List[Dict[str, Any]]:
        """Execute all due jobs.

        Returns:
            List of execution results
        """
        due_jobs = self.get_due_jobs()
        results = []

        for job in due_jobs:
            try:
                result = self._execute_job(job)
                results.append(result)
            except Exception as e:
                log.error(f"Failed to execute job {job.id}: {e}")
                results.append({
                    "job_id": job.id,
                    "status": "error",
                    "error": str(e),
                })

        return results

    def _execute_job(self, job: CronJob) -> Dict[str, Any]:
        """Execute a single job.

        Args:
            job: CronJob to execute

        Returns:
            Execution result dict
        """
        # Find executor
        executor = self._executors.get(job.task_type)
        if not executor:
            log.warning(f"No executor for task type: {job.task_type}")
            return {
                "job_id": job.id,
                "status": "error",
                "error": f"No executor for {job.task_type}",
            }

        # Execute
        try:
            result = executor(job)
            success = True
        except Exception as e:
            result = {"error": str(e)}
            success = False

        # Update job metadata
        now = datetime.now()
        next_run = self._calculate_next_run(job.schedule, now)

        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            job.last_run = now.isoformat()
            job.next_run = next_run.isoformat() if next_run else None
            job.run_count += 1

            cursor.execute("""
                UPDATE cron_jobs
                SET last_run = ?, next_run = ?, run_count = ?
                WHERE id = ?
            """, (job.last_run, job.next_run, job.run_count, job.id))
            conn.commit()
            conn.close()

            self._jobs[job.id] = job
        except Exception as e:
            log.error(f"Failed to update job metadata: {e}")

        log.info(f"Job executed: {job.id} ({job.name})")
        return {
            "job_id": job.id,
            "status": "success" if success else "error",
            "result": result,
            "last_run": job.last_run,
            "next_run": job.next_run,
        }

    def _calculate_next_run(self, schedule: str, from_time: datetime) -> Optional[datetime]:
        """Calculate next run time from cron expression.

        Simple parser supporting:
        - 5-field cron format: minute hour day month dayofweek
        - @hourly, @daily, @weekly, @monthly shortcuts
        - */5 * * * * (every 5 minutes)

        Args:
            schedule: Cron expression string
            from_time: Base time to calculate from

        Returns:
            Next run datetime or None if invalid
        """
        # Handle shortcuts
        shortcuts = {
            "@hourly": "0 * * * *",
            "@daily": "0 0 * * *",
            "@weekly": "0 0 * * 0",
            "@monthly": "0 0 1 * *",
        }

        if schedule in shortcuts:
            schedule = shortcuts[schedule]

        # Simple validation
        parts = schedule.split()
        if len(parts) != 5:
            log.warning(f"Invalid cron expression: {schedule}")
            return None

        minute_str, hour_str, day_str, month_str, dow_str = parts

        # Very basic next run calculation
        # This is simplified and doesn't handle all cron syntax
        try:
            # For now, just add 1 minute if using */5, else add 1 hour
            if "*/5" in minute_str:
                return from_time + timedelta(minutes=5)
            elif "*" in hour_str:
                return from_time + timedelta(hours=1)
            else:
                # Try to parse hour
                hour = int(hour_str)
                next_run = from_time.replace(hour=hour, minute=0, second=0, microsecond=0)
                if next_run <= from_time:
                    next_run += timedelta(days=1)
                return next_run
        except (ValueError, AttributeError):
            log.warning(f"Could not parse cron expression: {schedule}")
            return None
