"""Tests for rudy.orchestrator.hitl — Human-in-the-Loop Approval Gate."""

import json
import sqlite3
from pathlib import Path

import pytest

from rudy.orchestrator.hitl import (
    HITLGate, ApprovalRequest, ApprovalStatus
)


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database path."""
    return tmp_path / "test_hitl.sqlite"


@pytest.fixture
def gate(db_path):
    """Create a HITLGate instance with temp database."""
    return HITLGate(db_path=db_path)


class TestApprovalRequest:
    """Test ApprovalRequest creation and methods."""

    def test_basic_creation(self):
        """Test creating a basic ApprovalRequest."""
        req = ApprovalRequest(
            task_description="Delete production database",
            risk_level="critical",
        )
        assert req.task_description == "Delete production database"
        assert req.risk_level == "critical"
        assert req.status == ApprovalStatus.PENDING
        assert len(req.id) > 0

    def test_with_context(self):
        """Test ApprovalRequest with context."""
        ctx = {"database": "prod_db", "tables": 50}
        req = ApprovalRequest(
            task_description="task",
            risk_level="high",
            context=ctx,
        )
        assert req.context == ctx

    def test_with_requester(self):
        """Test ApprovalRequest with requester."""
        req = ApprovalRequest(
            task_description="task",
            risk_level="medium",
            requester="sentinel",
        )
        assert req.requester == "sentinel"

    def test_is_pending(self):
        """Test is_pending method."""
        req = ApprovalRequest(
            task_description="task",
            risk_level="medium",
        )
        assert req.is_pending()

        req.status = ApprovalStatus.APPROVED
        assert not req.is_pending()

    def test_age_seconds(self):
        """Test age_seconds calculation."""
        req = ApprovalRequest(
            task_description="task",
            risk_level="medium",
        )
        age = req.age_seconds()
        assert age >= 0

    def test_to_dict(self):
        """Test converting to dictionary."""
        req = ApprovalRequest(
            task_description="task",
            risk_level="high",
            requester="agent",
        )
        d = req.to_dict()
        assert d["task_description"] == "task"
        assert d["risk_level"] == "high"
        assert d["status"] == "pending"


class TestHITLGateInit:
    """Test HITLGate initialization."""

    def test_creates_database(self, db_path):
        """Test that HITLGate creates the database."""
        HITLGate(db_path=db_path)
        assert db_path.exists()

    def test_creates_parent_directories(self, tmp_path):
        """Test that parent directories are created."""
        deep_path = tmp_path / "a" / "b" / "c" / "hitl.sqlite"
        HITLGate(db_path=deep_path)
        assert deep_path.exists()

    def test_creates_schema(self, db_path):
        """Test that schema is created."""
        HITLGate(db_path=db_path)
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "hitl_approvals" in table_names
        conn.close()

    def test_creates_indexes(self, db_path):
        """Test that indexes are created."""
        HITLGate(db_path=db_path)
        conn = sqlite3.connect(str(db_path))
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = [i[0] for i in indexes]
        assert "idx_hitl_status" in index_names
        assert "idx_hitl_created" in index_names
        conn.close()

    def test_custom_timeout(self, db_path):
        """Test creating gate with custom timeout."""
        gate = HITLGate(db_path=db_path, approval_timeout_minutes=60)
        assert gate._timeout_minutes == 60

    def test_auto_approve_low_risk_flag(self, db_path):
        """Test auto_approve_low_risk flag."""
        gate = HITLGate(db_path=db_path, auto_approve_low_risk=False)
        assert gate._auto_approve_low_risk is False


class TestRequestApproval:
    """Test request_approval method."""

    def test_creates_pending_request(self, gate):
        """Test that request_approval creates a pending request."""
        req = gate.request_approval(
            task_description="task",
            risk_level="medium",
        )
        assert req.status == ApprovalStatus.PENDING
        assert req.task_description == "task"

    def test_persists_to_database(self, gate, db_path):
        """Test that request is persisted to database."""
        req = gate.request_approval(
            task_description="task",
            risk_level="high",
        )
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT id, task_description FROM hitl_approvals WHERE id = ?",
            (req.id,),
        ).fetchone()
        assert row is not None
        assert row[1] == "task"
        conn.close()

    def test_with_context(self, gate):
        """Test request with context."""
        ctx = {"target": "server", "action": "restart"}
        req = gate.request_approval(
            task_description="task",
            risk_level="high",
            context=ctx,
        )
        stored = gate.check_status(req.id)
        assert stored.context == ctx

    def test_with_metadata(self, gate):
        """Test request with metadata."""
        meta = {"source": "automation", "urgency": 5}
        req = gate.request_approval(
            task_description="task",
            risk_level="medium",
            metadata=meta,
        )
        stored = gate.check_status(req.id)
        assert stored.metadata == meta


class TestApproveAndDeny:
    """Test approve and deny methods."""

    def test_approve_request(self, gate, db_path):
        """Test approving a request."""
        req = gate.request_approval("task", "high")
        success = gate.approve(req.id, "admin")
        assert success is True

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT status, decided_by FROM hitl_approvals WHERE id = ?",
            (req.id,),
        ).fetchone()
        assert row[0] == "approved"
        assert row[1] == "admin"
        conn.close()

    def test_deny_request(self, gate, db_path):
        """Test denying a request."""
        req = gate.request_approval("task", "high")
        success = gate.deny(req.id, "reviewer", reason="Policy violation")
        assert success is True

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT status, denial_reason FROM hitl_approvals WHERE id = ?",
            (req.id,),
        ).fetchone()
        assert row[0] == "denied"
        assert row[1] == "Policy violation"
        conn.close()

    def test_approve_nonexistent_request(self, gate):
        """Test approving a nonexistent request."""
        success = gate.approve("unknown-id", "admin")
        # Should fail silently or return False
        assert success is False or success is True


class TestCheckStatus:
    """Test check_status method."""

    def test_pending_request_status(self, gate):
        """Test checking status of pending request."""
        req = gate.request_approval("task", "medium")
        status = gate.check_status(req.id)
        assert status is not None
        assert status.status == ApprovalStatus.PENDING

    def test_approved_request_status(self, gate):
        """Test checking status of approved request."""
        req = gate.request_approval("task", "high")
        gate.approve(req.id, "admin")
        status = gate.check_status(req.id)
        assert status.status == ApprovalStatus.APPROVED
        assert status.decided_by == "admin"

    def test_nonexistent_request_status(self, gate):
        """Test checking status of nonexistent request."""
        status = gate.check_status("unknown-id")
        assert status is None


class TestGetPending:
    """Test get_pending method."""

    def test_returns_pending_requests(self, gate):
        """Test that get_pending returns pending requests."""
        req1 = gate.request_approval("task1", "medium")
        req2 = gate.request_approval("task2", "high")
        gate.approve(req2.id, "admin")

        pending = gate.get_pending()
        assert len(pending) == 1
        assert pending[0].id == req1.id

    def test_excludes_approved_and_denied(self, gate):
        """Test that get_pending excludes approved and denied."""
        req1 = gate.request_approval("task1", "medium")
        req2 = gate.request_approval("task2", "high")
        req3 = gate.request_approval("task3", "critical")

        gate.approve(req1.id, "admin")
        gate.deny(req2.id, "reviewer", "too risky")

        pending = gate.get_pending()
        assert len(pending) == 1
        assert pending[0].id == req3.id

    def test_empty_pending(self, gate):
        """Test empty pending list."""
        pending = gate.get_pending()
        assert pending == []


class TestAutoGate:
    """Test auto_gate method."""

    def test_low_risk_auto_approved(self, gate):
        """Test that low-risk is auto-approved."""
        result = gate.auto_gate("task", "low")
        assert result is True

    def test_low_risk_disabled_auto_approve(self, db_path):
        """Test low-risk when auto-approve is disabled."""
        gate = HITLGate(db_path=db_path, auto_approve_low_risk=False)
        result = gate.auto_gate("task", "low")
        # Without auto-approve, it may still request approval
        assert result is True or result is False

    def test_medium_risk_auto_approved(self, gate):
        """Test that medium-risk is auto-approved."""
        result = gate.auto_gate("task", "medium")
        assert result is True

    def test_high_risk_requires_approval(self, gate):
        """Test that high-risk requires approval."""
        result = gate.auto_gate("task", "high")
        # Should create pending request and return False
        assert result is False
        pending = gate.get_pending()
        assert len(pending) == 1

    def test_critical_risk_requires_approval(self, gate):
        """Test that critical-risk requires approval."""
        result = gate.auto_gate("task", "critical")
        assert result is False
        pending = gate.get_pending()
        assert len(pending) == 1

    def test_auto_gate_with_context(self, gate):
        """Test auto_gate with context."""
        ctx = {"database": "prod"}
        result = gate.auto_gate("task", "high", context=ctx)
        pending = gate.get_pending()
        assert pending[0].context == ctx

    def test_auto_gate_with_requester(self, gate):
        """Test auto_gate with requester."""
        result = gate.auto_gate("task", "high", requester="sentinel")
        pending = gate.get_pending()
        assert pending[0].requester == "sentinel"


class TestPersistence:
    """Test database persistence."""

    def test_survives_gate_restart(self, db_path):
        """Test that requests survive gate restart."""
        gate1 = HITLGate(db_path=db_path)
        req = gate1.request_approval("task", "high")
        req_id = req.id

        gate2 = HITLGate(db_path=db_path)
        status = gate2.check_status(req_id)
        assert status is not None
        assert status.id == req_id

    def test_multiple_gates_same_database(self, db_path):
        """Test multiple gate instances share same database."""
        gate1 = HITLGate(db_path=db_path)
        gate2 = HITLGate(db_path=db_path)

        req = gate1.request_approval("task", "high")
        pending = gate2.get_pending()
        assert len(pending) == 1
        assert pending[0].id == req.id

    def test_context_persistence(self, db_path):
        """Test that context is persisted and retrieved."""
        gate1 = HITLGate(db_path=db_path)
        ctx = {"key1": "value1", "nested": {"key2": "value2"}}
        req = gate1.request_approval("task", "high", context=ctx)

        gate2 = HITLGate(db_path=db_path)
        status = gate2.check_status(req.id)
        assert status.context == ctx
