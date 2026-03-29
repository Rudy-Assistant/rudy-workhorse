"""
Message Bus — Pub/sub inter-agent messaging system.

SQLite-backed message queue for routing messages between agents with
support for request/response patterns, broadcasting, and message
prioritization.
"""

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any
from uuid import uuid4

log = logging.getLogger(__name__)


class MessageType(Enum):
    """Message type enumeration."""

    REQUEST = "REQUEST"
    RESPONSE = "RESPONSE"
    BROADCAST = "BROADCAST"
    ALERT = "ALERT"
    HEARTBEAT = "HEARTBEAT"


@dataclass
class Message:
    """Inter-agent message.

    Messages can be one-to-one (REQUEST, RESPONSE) or one-to-many
    (BROADCAST). Correlation IDs track request/response pairs.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    from_agent: str = ""
    to_agent: str = ""  # "*" for broadcast
    msg_type: MessageType = MessageType.REQUEST
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    correlation_id: Optional[str] = None  # For request/response pairs
    priority: int = 3  # 1=highest, 5=lowest

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "msg_type": self.msg_type.value,
            "payload": self.payload,
            "timestamp": self.timestamp,
            "correlation_id": self.correlation_id,
            "priority": self.priority,
        }


class MessageBus:
    """SQLite-backed message queue for inter-agent communication.

    Provides:
    - Pub/sub with subscriptions
    - Request/response pattern with timeout
    - Broadcasting to multiple agents
    - Message prioritization
    - Conversation threading via correlation_id
    - Automatic message pruning

    Usage:
        bus = MessageBus()

        # Subscribe
        sub_id = bus.subscribe("agent1", [MessageType.REQUEST])

        # Publish
        msg = Message(from_agent="oracle", to_agent="agent1",
                      msg_type=MessageType.REQUEST,
                      payload={"task": "scan network"})
        msg_id = bus.publish(msg)

        # Get messages
        messages = bus.get_pending("agent1")
        for msg in messages:
            bus.acknowledge(msg.id, "agent1")

        # Request/response
        reply = bus.request_response("oracle", "sentinel",
                                     {"query": "threat status"},
                                     timeout_seconds=30)
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize message bus.

        Args:
            db_path: Path to SQLite database (uses memory.sqlite by default)
        """
        if db_path is None:
            import os

            desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
            db_path = desktop / "rudy-data" / "memory.sqlite"

        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

        log.info(f"MessageBus initialized with database: {self._db_path}")

    def _init_db(self) -> None:
        """Create tables if they don't exist."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    from_agent TEXT NOT NULL,
                    to_agent TEXT NOT NULL,
                    msg_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    correlation_id TEXT,
                    priority INT DEFAULT 3,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE TABLE IF NOT EXISTS message_reads (
                    message_id TEXT NOT NULL,
                    agent_name TEXT NOT NULL,
                    read_at TEXT NOT NULL,
                    PRIMARY KEY (message_id, agent_name),
                    FOREIGN KEY (message_id) REFERENCES messages(id)
                );

                CREATE TABLE IF NOT EXISTS subscriptions (
                    id TEXT PRIMARY KEY,
                    agent_name TEXT NOT NULL,
                    msg_types TEXT NOT NULL,
                    subscribed_at TEXT DEFAULT CURRENT_TIMESTAMP
                );

                CREATE INDEX IF NOT EXISTS idx_messages_to_agent
                    ON messages(to_agent);
                CREATE INDEX IF NOT EXISTS idx_messages_timestamp
                    ON messages(timestamp);
                CREATE INDEX IF NOT EXISTS idx_messages_correlation
                    ON messages(correlation_id);
                """
            )

    def _connect(self) -> sqlite3.Connection:
        """Create a database connection."""
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    # ── Subscriptions ───────────────────────────────────────────

    def subscribe(
        self,
        agent_name: str,
        msg_types: Optional[List[MessageType]] = None,
    ) -> str:
        """Subscribe an agent to message types.

        Args:
            agent_name: Name of agent to subscribe
            msg_types: List of message types to subscribe to
                      (None = all types)

        Returns:
            Subscription ID
        """
        sub_id = str(uuid4())
        msg_types = msg_types or list(MessageType)

        types_json = json.dumps([mt.value for mt in msg_types])

        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO subscriptions (id, agent_name, msg_types)
                       VALUES (?, ?, ?)""",
                    (sub_id, agent_name, types_json),
                )
                conn.commit()

        log.debug(f"Subscribed {agent_name} to {len(msg_types)} message types")
        return sub_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Unsubscribe from messages.

        Args:
            subscription_id: ID returned from subscribe()

        Returns:
            True if unsubscribed, False if not found
        """
        with self._lock:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM subscriptions WHERE id = ?",
                    (subscription_id,),
                )
                conn.commit()
                return cursor.rowcount > 0

    # ── Publishing ──────────────────────────────────────────────

    def publish(self, message: Message) -> str:
        """Publish a message to the bus.

        Args:
            message: Message to publish

        Returns:
            Message ID
        """
        with self._lock:
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO messages
                       (id, from_agent, to_agent, msg_type, payload,
                        timestamp, correlation_id, priority)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        message.id,
                        message.from_agent,
                        message.to_agent,
                        message.msg_type.value,
                        json.dumps(message.payload, default=str),
                        message.timestamp,
                        message.correlation_id,
                        message.priority,
                    ),
                )
                conn.commit()

        log.debug(
            f"Published {message.msg_type.value} from {message.from_agent} "
            f"to {message.to_agent}"
        )
        return message.id

    def broadcast(
        self,
        from_agent: str,
        msg_type: MessageType,
        payload: Dict[str, Any],
    ) -> str:
        """Broadcast a message to all agents.

        Args:
            from_agent: Sender
            msg_type: Message type
            payload: Message payload

        Returns:
            Message ID
        """
        message = Message(
            from_agent=from_agent,
            to_agent="*",
            msg_type=msg_type,
            payload=payload,
            priority=1,  # Broadcast is high priority
        )
        return self.publish(message)

    # ── Retrieval ───────────────────────────────────────────────

    def get_messages(
        self,
        agent_name: str,
        since: Optional[str] = None,
        msg_types: Optional[List[MessageType]] = None,
    ) -> List[Message]:
        """Get messages for an agent.

        Args:
            agent_name: Agent to get messages for
            since: Optional ISO timestamp filter
            msg_types: Optional list of message types to filter

        Returns:
            List of Message objects
        """
        with self._lock:
            with self._connect() as conn:
                query = """
                    SELECT id, from_agent, to_agent, msg_type, payload,
                           timestamp, correlation_id, priority
                    FROM messages
                    WHERE (to_agent = ? OR to_agent = '*')
                """
                params = [agent_name]

                if since:
                    query += " AND timestamp >= ?"
                    params.append(since)

                if msg_types:
                    types = [mt.value for mt in msg_types]
                    placeholders = ",".join("?" * len(types))
                    query += f" AND msg_type IN ({placeholders})"
                    params.extend(types)

                query += " ORDER BY priority ASC, timestamp DESC"

                rows = conn.execute(query, params).fetchall()

        messages = []
        for row in rows:
            payload = row[4]
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                pass

            messages.append(
                Message(
                    id=row[0],
                    from_agent=row[1],
                    to_agent=row[2],
                    msg_type=MessageType[row[3]],
                    payload=payload,
                    timestamp=row[5],
                    correlation_id=row[6],
                    priority=row[7],
                )
            )

        return messages

    def get_pending(self, agent_name: str) -> List[Message]:
        """Get unread messages for an agent.

        Args:
            agent_name: Agent name

        Returns:
            List of unread Message objects
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, from_agent, to_agent, msg_type, payload,
                           timestamp, correlation_id, priority
                    FROM messages
                    WHERE (to_agent = ? OR to_agent = '*')
                    AND id NOT IN (
                        SELECT message_id FROM message_reads
                        WHERE agent_name = ?
                    )
                    ORDER BY priority ASC, timestamp DESC
                    """,
                    (agent_name, agent_name),
                ).fetchall()

        messages = []
        for row in rows:
            payload = row[4]
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                pass

            messages.append(
                Message(
                    id=row[0],
                    from_agent=row[1],
                    to_agent=row[2],
                    msg_type=MessageType[row[3]],
                    payload=payload,
                    timestamp=row[5],
                    correlation_id=row[6],
                    priority=row[7],
                )
            )

        return messages

    def acknowledge(self, message_id: str, agent_name: str) -> bool:
        """Mark a message as read by an agent.

        Args:
            message_id: Message ID
            agent_name: Agent reading the message

        Returns:
            True if acknowledged, False if already acknowledged
        """
        with self._lock:
            with self._connect() as conn:
                try:
                    conn.execute(
                        """INSERT INTO message_reads (message_id, agent_name, read_at)
                           VALUES (?, ?, ?)""",
                        (message_id, agent_name, datetime.now().isoformat()),
                    )
                    conn.commit()
                    return True
                except sqlite3.IntegrityError:
                    return False

    # ── Request/Response Pattern ────────────────────────────────

    def request_response(
        self,
        from_agent: str,
        to_agent: str,
        payload: Dict[str, Any],
        timeout_seconds: int = 30,
    ) -> Optional[Message]:
        """Send a request and wait for response.

        Args:
            from_agent: Sender
            to_agent: Recipient
            payload: Request payload
            timeout_seconds: How long to wait for response

        Returns:
            Response Message or None if timeout
        """
        correlation_id = str(uuid4())

        # Send request
        request = Message(
            from_agent=from_agent,
            to_agent=to_agent,
            msg_type=MessageType.REQUEST,
            payload=payload,
            correlation_id=correlation_id,
            priority=1,
        )
        self.publish(request)

        # Wait for response
        import time

        deadline = time.time() + timeout_seconds
        while time.time() < deadline:
            responses = self.get_messages(
                from_agent,
                msg_types=[MessageType.RESPONSE],
            )

            for response in responses:
                if response.correlation_id == correlation_id:
                    return response

            time.sleep(0.5)

        log.warning(
            f"Request/response timeout: {from_agent} → {to_agent} "
            f"(correlation_id={correlation_id})"
        )
        return None

    # ── Conversation Threading ──────────────────────────────────

    def get_conversation(self, correlation_id: str) -> List[Message]:
        """Get all messages in a conversation thread.

        Args:
            correlation_id: Correlation ID to thread on

        Returns:
            List of messages in conversation order
        """
        with self._lock:
            with self._connect() as conn:
                rows = conn.execute(
                    """
                    SELECT id, from_agent, to_agent, msg_type, payload,
                           timestamp, correlation_id, priority
                    FROM messages
                    WHERE correlation_id = ?
                    ORDER BY timestamp ASC
                    """,
                    (correlation_id,),
                ).fetchall()

        messages = []
        for row in rows:
            payload = row[4]
            try:
                payload = json.loads(payload)
            except (json.JSONDecodeError, TypeError):
                pass

            messages.append(
                Message(
                    id=row[0],
                    from_agent=row[1],
                    to_agent=row[2],
                    msg_type=MessageType[row[3]],
                    payload=payload,
                    timestamp=row[5],
                    correlation_id=row[6],
                    priority=row[7],
                )
            )

        return messages

    # ── Maintenance ─────────────────────────────────────────────

    def prune(self, older_than_hours: int = 24) -> int:
        """Delete old messages.

        Args:
            older_than_hours: Delete messages older than this

        Returns:
            Count of deleted messages
        """
        from datetime import timedelta

        cutoff = (datetime.now() - timedelta(hours=older_than_hours)).isoformat()

        with self._lock:
            with self._connect() as conn:
                # Delete message reads first (foreign key constraint)
                conn.execute(
                    """DELETE FROM message_reads
                       WHERE message_id IN (
                           SELECT id FROM messages WHERE timestamp < ?
                       )""",
                    (cutoff,),
                )

                # Delete messages
                cursor = conn.execute(
                    "DELETE FROM messages WHERE timestamp < ?",
                    (cutoff,),
                )
                deleted = cursor.rowcount
                conn.commit()

        if deleted > 0:
            log.info(f"Pruned {deleted} messages older than {older_than_hours}h")

        return deleted

    def get_stats(self) -> Dict[str, Any]:
        """Get message bus statistics.

        Returns:
            Dict with message counts and stats
        """
        with self._lock:
            with self._connect() as conn:
                total_msgs = conn.execute(
                    "SELECT COUNT(*) FROM messages"
                ).fetchone()[0]
                unread = conn.execute(
                    """
                    SELECT COUNT(DISTINCT m.id) FROM messages m
                    WHERE m.id NOT IN (
                        SELECT message_id FROM message_reads
                    )
                    """
                ).fetchone()[0]
                subscriptions = conn.execute(
                    "SELECT COUNT(DISTINCT agent_name) FROM subscriptions"
                ).fetchone()[0]

        return {
            "total_messages": total_msgs,
            "unread_messages": unread,
            "active_subscribers": subscriptions,
        }
