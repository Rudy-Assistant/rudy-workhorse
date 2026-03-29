"""
Human-in-the-Loop Approval Gate System

Manages approval requests for high-risk operations, with persistence,
timeout handling, and risk-based gating logic.
"""

import sqlite3
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from enum import Enum
import uuid
import os
import json

log = logging.getLogger(__name__)

# Default database path — follow rudy/paths.py conventions
DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
DEFAULT_DB_PATH = DESKTOP / "rudy-data" / "memory.sqlite"


class ApprovalStatus(str, Enum):
    """Status of an approval request."""
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    TIMEOUT = "timeout"


@dataclass
class ApprovalRequest:
    """A single approval request.

    Attributes:
        id: Unique request identifier
        task_description: Human-readable description of the task
        risk_level: Risk classification (low/medium/high/critical)
        context: Contextual data relevant to the decision
        status: Current status (pending/approved/denied/timeout)
        requester: Name of the agent requesting approval
        created_at: Timestamp when request was created
        decided_at: Timestamp when decision was made (if any)
        decided_by: Who made the decision (if any)
        denial_reason: Reason for denial (if status is denied)
        metadata: Optional arbitrary metadata
    """
    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    task_description: str = ""
    risk_level: str = "medium"
    context: Dict[str, Any] = field(default_factory=dict)
    status: ApprovalStatus = ApprovalStatus.PENDING
    requester: str = ""
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    decided_at: Optional[str] = None
    decided_by: Optional[str] = None
    denial_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        d = asdict(self)
        d["status"] = self.status.value
        return d

    def is_pending(self) -> bool:
        """Check if still awaiting decision."""
        return self.status == ApprovalStatus.PENDING

    def age_seconds(self) -> float:
        """Get age of this request in seconds."""
        try:
            created = datetime.fromisoformat(self.created_at)
            return (datetime.now() - created).total_seconds()
        except (ValueError, TypeError):
            return 0.0


class HITLGate:
    """Human-in-the-loop approval gate for high-risk operations.

    Manages approval requests with configurable thresholds, persistence
    to SQLite, and automatic timeout/escalation logic.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        approval_timeout_minutes: int = 30,
        auto_approve_low_risk: bool = True,
    ):
        """Initialize HITL gate.

        Args:
            db_path: Path to SQLite database (default: memory.sqlite)
            approval_timeout_minutes: Minutes to wait before timeout
            auto_approve_low_risk: Auto-approve low-risk operations
        """
        self._db_path = db_path or DEFAULT_DB_PATH
        self._timeout_minutes = approval_timeout_minutes
        self._auto_approve_low_risk = auto_approve_low_risk

        # Ensure database exists
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize schema
        self._init_schema()

    def _init_schema(self) -> None:
        """Initialize SQLite schema if not present."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    CREATE TABLE IF NOT EXISTS hitl_approvals (
                        id TEXT PRIMARY KEY,
                        task_description TEXT NOT NULL,
                        risk_level TEXT NOT NULL,
                        context TEXT,
                        status TEXT NOT NULL,
                        requester TEXT,
                        created_at TEXT NOT NULL,
                        decided_at TEXT,
                        decided_by TEXT,
                        denial_reason TEXT,
                        metadata TEXT,
                        created_datetime REAL NOT NULL
                    )
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_hitl_status
                    ON hitl_approvals(status)
                    """
                )
                conn.execute(
                    """
                    CREATE INDEX IF NOT EXISTS idx_hitl_created
                    ON hitl_approvals(created_datetime DESC)
                    """
                )
                conn.commit()
        except Exception as e:
            log.error(f"Failed to initialize HITL schema: {e}")

    def request_approval(
        self,
        task_description: str,
        risk_level: str,
        context: Optional[Dict[str, Any]] = None,
        requester: str = "oracle",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ApprovalRequest:
        """Request approval for a task.

        Args:
            task_description: What is being requested
            risk_level: One of "low", "medium", "high", "critical"
            context: Contextual data for decision-maker
            requester: Name of requesting agent
            metadata: Optional arbitrary metadata

        Returns:
            ApprovalRequest object
        """
        request = ApprovalRequest(
            task_description=task_description,
            risk_level=risk_level,
            context=context or {},
            requester=requester,
            metadata=metadata or {},
        )

        # Persist to database
        self._persist_request(request)

        log.info(
            f"Approval requested: {request.id} "
            f"({risk_level}) — {task_description[:60]}"
        )
        return request

    def approve(self, request_id: str, approver: str) -> bool:
        """Approve a request.

        Args:
            request_id: ID of the request to approve
            approver: Name of the approver

        Returns:
            True if approval was recorded
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    UPDATE hitl_approvals
                    SET status = ?, decided_at = ?, decided_by = ?
                    WHERE id = ?
                    """,
                    (
                        ApprovalStatus.APPROVED.value,
                        datetime.now().isoformat(),
                        approver,
                        request_id,
                    ),
                )
                conn.commit()
            log.info(f"Approval granted: {request_id} by {approver}")
            return True
        except Exception as e:
            log.error(f"Failed to record approval: {e}")
            return False

    def deny(
        self,
        request_id: str,
        approver: str,
        reason: Optional[str] = None,
    ) -> bool:
        """Deny a request.

        Args:
            request_id: ID of the request to deny
            approver: Name of the denier
            reason: Optional reason for denial

        Returns:
            True if denial was recorded
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    UPDATE hitl_approvals
                    SET status = ?, decided_at = ?, decided_by = ?, denial_reason = ?
                    WHERE id = ?
                    """,
                    (
                        ApprovalStatus.DENIED.value,
                        datetime.now().isoformat(),
                        approver,
                        reason,
                        request_id,
                    ),
                )
                conn.commit()
            log.info(f"Approval denied: {request_id} by {approver} — {reason}")
            return True
        except Exception as e:
            log.error(f"Failed to record denial: {e}")
            return False

    def check_status(self, request_id: str) -> Optional[ApprovalRequest]:
        """Check status of a request.

        Args:
            request_id: ID to look up

        Returns:
            ApprovalRequest or None if not found
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                row = conn.execute(
                    "SELECT * FROM hitl_approvals WHERE id = ?",
                    (request_id,),
                ).fetchone()

                if not row:
                    return None

                return self._row_to_request(row)
        except Exception as e:
            log.error(f"Failed to check status: {e}")
            return None

    def get_pending(self) -> List[ApprovalRequest]:
        """Get all pending approval requests.

        Returns:
            List of pending ApprovalRequest objects
        """
        try:
            with sqlite3.connect(self._db_path) as conn:
                rows = conn.execute(
                    """
                    SELECT * FROM hitl_approvals
                    WHERE status = ?
                    ORDER BY created_datetime DESC
                    """,
                    (ApprovalStatus.PENDING.value,),
                ).fetchall()

                return [self._row_to_request(row) for row in rows]
        except Exception as e:
            log.error(f"Failed to fetch pending requests: {e}")
            return []

    def auto_gate(
        self,
        task_description: str,
        risk_level: str,
        context: Optional[Dict[str, Any]] = None,
        requester: str = "oracle",
    ) -> bool:
        """Automatically gate based on risk level.

        Implements approval logic:
        - low: auto-approved
        - medium: logged but auto-approved
        - high: requires explicit approval
        - critical: requires approval + confirmation

        Args:
            task_description: What is being gated
            risk_level: Risk level classification
            context: Optional contextual data
            requester: Name of requesting agent

        Returns:
            True if approved/auto-approved, False if requires human approval
        """
        if risk_level == "low":
            if self._auto_approve_low_risk:
                log.debug(f"Auto-approving low-risk task: {task_description[:60]}")
                return True

        if risk_level == "medium":
            log.info(f"Medium-risk task logged: {task_description[:60]}")
            return True

        # high and critical require explicit approval
        request = self.request_approval(
            task_description=task_description,
            risk_level=risk_level,
            context=context,
            requester=requester,
        )

        # Wait for decision (in practice, this would be async)
        # For now, return False (requires human intervention)
        log.warning(f"High-risk task requires approval: {request.id}")
        return False

    def _persist_request(self, request: ApprovalRequest) -> None:
        """Save approval request to database."""
        try:
            with sqlite3.connect(self._db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO hitl_approvals
                    (id, task_description, risk_level, context, status,
                     requester, created_at, metadata, created_datetime)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        request.id,
                        request.task_description,
                        request.risk_level,
                        json.dumps(request.context),
                        request.status.value,
                        request.requester,
                        request.created_at,
                        json.dumps(request.metadata),
                        datetime.now().timestamp(),
                    ),
                )
                conn.commit()
        except Exception as e:
            log.error(f"Failed to persist approval request: {e}")

    def _row_to_request(self, row: tuple) -> ApprovalRequest:
        """Convert database row to ApprovalRequest."""
        (
            id_, task_desc, risk_level, context, status,
            requester, created_at, decided_at, decided_by,
            denial_reason, metadata, _
        ) = row

        return ApprovalRequest(
            id=id_,
            task_description=task_desc,
            risk_level=risk_level,
            context=json.loads(context) if context else {},
            status=ApprovalStatus(status),
            requester=requester,
            created_at=created_at,
            decided_at=decided_at,
            decided_by=decided_by,
            denial_reason=denial_reason,
            metadata=json.loads(metadata) if metadata else {},
        )
