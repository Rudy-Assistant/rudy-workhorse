"""Tests for rudy.automation.cron — CronScheduler and CronJob."""

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from rudy.automation.cron import CronScheduler, CronJob


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database path."""
    return tmp_path / "test_cron.sqlite"


@pytest.fixture
def scheduler(db_path):
    """Create a CronScheduler instance with temp database."""
    return CronScheduler(db_path=db_path)


class TestCronJob:
    """Test CronJob dataclass."""

    def test_basic_creation(self):
        """Test creating a basic CronJob."""
        job = CronJob(
            id="job-123",
            name="daily report",
            schedule="0 9 * * *",
            task_type="report",
            task_config={"report_type": "daily"},
            enabled=True,
            created_at="2026-03-28T10:00:00",
        )
        assert job.id == "job-123"
        assert job.name == "daily report"
        assert job.schedule == "0 9 * * *"
        assert job.enabled is True

    def test_with_run_tracking(self):
        """Test CronJob with run tracking."""
        job = CronJob(
            id="job-123",
            name="daily report",
            schedule="0 9 * * *",
            task_type="report",
            task_config={},
            enabled=True,
            created_at="2026-03-28T10:00:00",
            last_run="2026-03-28T09:00:00",
            next_run="2026-03-29T09:00:00",
            run_count=5,
        )
        assert job.run_count == 5
        assert job.last_run == "2026-03-28T09:00:00"
        assert job.next_run == "2026-03-29T09:00:00"


class TestCronSchedulerInit:
    """Test CronScheduler initialization."""

    def test_creates_database(self, db_path):
        """Test that CronScheduler creates the database."""
        CronScheduler(db_path=db_path)
        assert db_path.exists()

    def test_creates_table(self, db_path):
        """Test that cron_jobs table is created."""
        CronScheduler(db_path=db_path)
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "cron_jobs" in table_names
        conn.close()

    def test_initializes_jobs(self, scheduler):
        """Test that jobs dict is initialized."""
        assert isinstance(scheduler._jobs, dict)
        assert len(scheduler._jobs) == 0

    def test_initializes_executors(self, scheduler):
        """Test that executors dict is initialized."""
        assert isinstance(scheduler._executors, dict)


class TestAddJob:
    """Test add_job method."""

    def test_add_simple_job(self, scheduler):
        """Test adding a simple cron job."""
        job_id = scheduler.add_job(
            name="daily report",
            schedule="0 9 * * *",
            task_type="report",
            task_config={"report_type": "daily"},
        )
        assert job_id != ""
        assert job_id in scheduler._jobs

    def test_add_job_persists(self, scheduler, db_path):
        """Test that added job is persisted to database."""
        job_id = scheduler.add_job(
            name="test job",
            schedule="0 9 * * *",
            task_type="report",
            task_config={"test": "config"},
        )

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT id, name, schedule FROM cron_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        assert row is not None
        assert row[1] == "test job"
        assert row[2] == "0 9 * * *"
        conn.close()

    def test_add_job_sets_enabled(self, scheduler):
        """Test that newly added job is enabled."""
        job_id = scheduler.add_job(
            name="job",
            schedule="0 9 * * *",
            task_type="report",
            task_config={},
        )
        assert scheduler._jobs[job_id].enabled is True

    def test_add_job_calculates_next_run(self, scheduler):
        """Test that next_run is calculated."""
        job_id = scheduler.add_job(
            name="job",
            schedule="0 9 * * *",
            task_type="report",
            task_config={},
        )
        job = scheduler._jobs[job_id]
        assert job.next_run is not None

    def test_add_multiple_jobs(self, scheduler):
        """Test adding multiple jobs."""
        id1 = scheduler.add_job("job1", "0 9 * * *", "report", {})
        id2 = scheduler.add_job("job2", "@daily", "report", {})
        id3 = scheduler.add_job("job3", "@hourly", "scan", {})

        assert id1 != id2 != id3
        assert len(scheduler._jobs) == 3


class TestRemoveJob:
    """Test remove_job method."""

    def test_remove_existing_job(self, scheduler):
        """Test removing an existing job."""
        job_id = scheduler.add_job("job", "0 9 * * *", "report", {})
        success = scheduler.remove_job(job_id)
        assert success is True
        assert job_id not in scheduler._jobs

    def test_remove_nonexistent_job(self, scheduler):
        """Test removing a nonexistent job."""
        success = scheduler.remove_job("unknown-id")
        assert success is False

    def test_remove_deletes_from_database(self, scheduler, db_path):
        """Test that remove deletes from database."""
        job_id = scheduler.add_job("job", "0 9 * * *", "report", {})
        scheduler.remove_job(job_id)

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT id FROM cron_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        assert row is None
        conn.close()


class TestEnableDisableJob:
    """Test enable_job and disable_job methods."""

    def test_enable_job(self, scheduler):
        """Test enabling a job."""
        job_id = scheduler.add_job("job", "0 9 * * *", "report", {})
        scheduler.disable_job(job_id)

        success = scheduler.enable_job(job_id)
        assert success is True
        assert scheduler._jobs[job_id].enabled is True

    def test_disable_job(self, scheduler):
        """Test disabling a job."""
        job_id = scheduler.add_job("job", "0 9 * * *", "report", {})
        success = scheduler.disable_job(job_id)
        assert success is True
        assert scheduler._jobs[job_id].enabled is False

    def test_enable_nonexistent_job(self, scheduler):
        """Test enabling a nonexistent job."""
        success = scheduler.enable_job("unknown-id")
        assert success is False

    def test_disable_nonexistent_job(self, scheduler):
        """Test disabling a nonexistent job."""
        success = scheduler.disable_job("unknown-id")
        assert success is False


class TestGetDueJobs:
    """Test get_due_jobs method."""

    def test_get_due_jobs_empty(self, scheduler):
        """Test getting due jobs when none exist."""
        due = scheduler.get_due_jobs()
        assert due == []

    def test_ignores_disabled_jobs(self, scheduler):
        """Test that disabled jobs are not returned."""
        job_id = scheduler.add_job("job", "0 9 * * *", "report", {})
        scheduler.disable_job(job_id)

        due = scheduler.get_due_jobs()
        assert len(due) == 0

    def test_ignores_future_jobs(self, scheduler):
        """Test that future jobs are not returned."""
        # Add a job with next_run far in the future
        job_id = scheduler.add_job("job", "0 9 * * *", "report", {})
        future_time = (datetime.now() + timedelta(days=1)).isoformat()
        scheduler._jobs[job_id].next_run = future_time

        due = scheduler.get_due_jobs()
        assert len(due) == 0

    def test_returns_overdue_jobs(self, scheduler):
        """Test that overdue jobs are returned."""
        job_id = scheduler.add_job("job", "0 9 * * *", "report", {})
        # Set next_run to the past
        past_time = (datetime.now() - timedelta(hours=1)).isoformat()
        scheduler._jobs[job_id].next_run = past_time

        due = scheduler.get_due_jobs()
        assert len(due) == 1
        assert due[0].id == job_id


class TestParseCron:
    """Test cron expression parsing."""

    def test_parse_daily_shortcut(self, scheduler):
        """Test parsing @daily shortcut."""
        next_run = scheduler._calculate_next_run("@daily", datetime.now())
        assert next_run is not None
        assert isinstance(next_run, datetime)

    def test_parse_hourly_shortcut(self, scheduler):
        """Test parsing @hourly shortcut."""
        next_run = scheduler._calculate_next_run("@hourly", datetime.now())
        assert next_run is not None

    def test_parse_weekly_shortcut(self, scheduler):
        """Test parsing @weekly shortcut."""
        next_run = scheduler._calculate_next_run("@weekly", datetime.now())
        assert next_run is not None

    def test_parse_monthly_shortcut(self, scheduler):
        """Test parsing @monthly shortcut."""
        next_run = scheduler._calculate_next_run("@monthly", datetime.now())
        assert next_run is not None

    def test_parse_5_field_expression(self, scheduler):
        """Test parsing 5-field cron expression."""
        next_run = scheduler._calculate_next_run("0 9 * * *", datetime.now())
        assert next_run is not None

    def test_parse_every_5_minutes(self, scheduler):
        """Test parsing */5 expression."""
        next_run = scheduler._calculate_next_run("*/5 * * * *", datetime.now())
        assert next_run is not None

    def test_parse_invalid_expression(self, scheduler):
        """Test parsing invalid cron expression."""
        next_run = scheduler._calculate_next_run("invalid cron", datetime.now())
        assert next_run is None

    def test_parse_too_few_fields(self, scheduler):
        """Test parsing expression with too few fields."""
        next_run = scheduler._calculate_next_run("0 9 *", datetime.now())
        assert next_run is None


class TestCalculateNextRun:
    """Test _calculate_next_run method."""

    def test_calculate_next_run_returns_future(self, scheduler):
        """Test that next_run is always in the future."""
        now = datetime.now()
        next_run = scheduler._calculate_next_run("0 9 * * *", now)
        if next_run:
            assert next_run > now or next_run.date() > now.date()

    def test_calculate_next_run_hourly(self, scheduler):
        """Test calculating next run for hourly job."""
        now = datetime.now()
        next_run = scheduler._calculate_next_run("@hourly", now)
        if next_run:
            # Next run should be roughly 1 hour in future
            delta = (next_run - now).total_seconds()
            assert 0 < delta < 3600 * 2  # Within 2 hours

    def test_calculate_next_run_daily(self, scheduler):
        """Test calculating next run for daily job."""
        now = datetime.now()
        next_run = scheduler._calculate_next_run("@daily", now)
        if next_run:
            delta = (next_run - now).total_seconds()
            assert delta > 0


class TestRegisterExecutor:
    """Test register_executor method."""

    def test_register_executor(self, scheduler):
        """Test registering a task executor."""
        def my_executor(job):
            return {"status": "executed"}

        scheduler.register_executor("report", my_executor)
        assert "report" in scheduler._executors
        assert scheduler._executors["report"] is my_executor

    def test_register_multiple_executors(self, scheduler):
        """Test registering multiple executors."""
        def executor1(job):
            return {}
        def executor2(job):
            return {}

        scheduler.register_executor("report", executor1)
        scheduler.register_executor("scan", executor2)

        assert "report" in scheduler._executors
        assert "scan" in scheduler._executors


class TestExecuteDueJobs:
    """Test execute_due_jobs method."""

    def test_execute_due_jobs_empty(self, scheduler):
        """Test executing when no jobs are due."""
        results = scheduler.execute_due_jobs()
        assert results == []

    def test_execute_due_job_with_executor(self, scheduler):
        """Test executing a due job with registered executor."""
        executed = []

        def my_executor(job):
            executed.append(job.id)
            return {"status": "success"}

        scheduler.register_executor("report", my_executor)
        job_id = scheduler.add_job("job", "0 9 * * *", "report", {})

        # Make job due
        past_time = (datetime.now() - timedelta(hours=1)).isoformat()
        scheduler._jobs[job_id].next_run = past_time

        results = scheduler.execute_due_jobs()
        assert len(results) == 1
        assert len(executed) == 1
        assert executed[0] == job_id

    def test_execute_job_without_executor(self, scheduler):
        """Test executing a job with no registered executor."""
        job_id = scheduler.add_job("job", "0 9 * * *", "unknown_type", {})

        # Make job due
        past_time = (datetime.now() - timedelta(hours=1)).isoformat()
        scheduler._jobs[job_id].next_run = past_time

        results = scheduler.execute_due_jobs()
        assert len(results) == 1
        assert results[0]["status"] == "error"

    def test_execute_job_updates_run_count(self, scheduler):
        """Test that executing a job increments run_count."""
        def my_executor(job):
            return {"status": "success"}

        scheduler.register_executor("report", my_executor)
        job_id = scheduler.add_job("job", "0 9 * * *", "report", {})

        # Make job due
        past_time = (datetime.now() - timedelta(hours=1)).isoformat()
        scheduler._jobs[job_id].next_run = past_time

        scheduler.execute_due_jobs()
        assert scheduler._jobs[job_id].run_count == 1

    def test_execute_job_updates_last_run(self, scheduler):
        """Test that executing a job updates last_run timestamp."""
        def my_executor(job):
            return {}

        scheduler.register_executor("report", my_executor)
        job_id = scheduler.add_job("job", "0 9 * * *", "report", {})

        # Make job due
        past_time = (datetime.now() - timedelta(hours=1)).isoformat()
        scheduler._jobs[job_id].next_run = past_time

        scheduler.execute_due_jobs()
        job = scheduler._jobs[job_id]
        assert job.last_run is not None

    def test_execute_job_updates_next_run(self, scheduler):
        """Test that executing a job recalculates next_run."""
        def my_executor(job):
            return {}

        scheduler.register_executor("report", my_executor)
        job_id = scheduler.add_job("job", "0 9 * * *", "report", {})

        # Make job due
        past_time = (datetime.now() - timedelta(hours=1)).isoformat()
        scheduler._jobs[job_id].next_run = past_time
        old_next_run = scheduler._jobs[job_id].next_run

        scheduler.execute_due_jobs()
        new_next_run = scheduler._jobs[job_id].next_run

        # The next_run should be recalculated after execution
        assert new_next_run is not None
        assert new_next_run > old_next_run or new_next_run != old_next_run

    def test_execute_job_error_handling(self, scheduler):
        """Test that executor errors are captured."""
        def failing_executor(job):
            raise RuntimeError("Executor failed")

        scheduler.register_executor("report", failing_executor)
        job_id = scheduler.add_job("job", "0 9 * * *", "report", {})

        # Make job due
        past_time = (datetime.now() - timedelta(hours=1)).isoformat()
        scheduler._jobs[job_id].next_run = past_time

        results = scheduler.execute_due_jobs()
        assert len(results) == 1
        assert results[0]["status"] == "error"
        assert "result" in results[0]


class TestPersistence:
    """Test database persistence."""

    def test_jobs_survive_restart(self, db_path):
        """Test that jobs survive scheduler restart."""
        scheduler1 = CronScheduler(db_path=db_path)
        job_id = scheduler1.add_job("job", "0 9 * * *", "report", {})

        scheduler2 = CronScheduler(db_path=db_path)
        assert job_id in scheduler2._jobs
        assert scheduler2._jobs[job_id].name == "job"

    def test_run_count_survives_restart(self, db_path):
        """Test that run_count survives restart."""
        scheduler1 = CronScheduler(db_path=db_path)
        job_id = scheduler1.add_job("job", "0 9 * * *", "report", {})

        def executor(job):
            return {}

        scheduler1.register_executor("report", executor)

        # Make job due and execute
        past = (datetime.now() - timedelta(hours=1)).isoformat()
        scheduler1._jobs[job_id].next_run = past
        scheduler1.execute_due_jobs()

        # Restart and check
        scheduler2 = CronScheduler(db_path=db_path)
        assert scheduler2._jobs[job_id].run_count == 1

    def test_job_config_survives_restart(self, db_path):
        """Test that job config is preserved."""
        scheduler1 = CronScheduler(db_path=db_path)
        config = {"report_type": "daily", "email": "admin@example.com"}
        job_id = scheduler1.add_job("job", "0 9 * * *", "report", config)

        scheduler2 = CronScheduler(db_path=db_path)
        assert scheduler2._jobs[job_id].task_config == config
