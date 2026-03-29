"""Tests for rudy.persona.message_bus — Inter-Agent Messaging."""

import sqlite3
import json
from pathlib import Path
from uuid import uuid4
import time

import pytest

from rudy.persona.message_bus import MessageBus, Message, MessageType


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database path."""
    return tmp_path / "test_message_bus.sqlite"


@pytest.fixture
def bus(db_path):
    """Create a MessageBus instance with temp database."""
    return MessageBus(db_path=db_path)


class TestMessageType:
    """Test MessageType enum."""

    def test_all_types_present(self):
        """Test that all expected message types exist."""
        types = [MessageType.REQUEST, MessageType.RESPONSE, MessageType.BROADCAST,
                 MessageType.ALERT, MessageType.HEARTBEAT]
        assert len(types) == 5

    def test_type_values(self):
        """Test message type values."""
        assert MessageType.REQUEST.value == "REQUEST"
        assert MessageType.RESPONSE.value == "RESPONSE"
        assert MessageType.BROADCAST.value == "BROADCAST"


class TestMessageCreation:
    """Test Message dataclass creation."""

    def test_basic_creation(self):
        """Test creating a basic message."""
        msg = Message(
            from_agent="agent1",
            to_agent="agent2",
            msg_type=MessageType.REQUEST,
            payload={"key": "value"},
        )
        assert msg.from_agent == "agent1"
        assert msg.to_agent == "agent2"
        assert msg.msg_type == MessageType.REQUEST

    def test_id_auto_generated(self):
        """Test that message ID is auto-generated."""
        msg = Message(from_agent="a1", to_agent="a2")
        assert len(msg.id) > 0
        assert msg.id != str(uuid4())  # Unique each time

    def test_timestamp_auto_generated(self):
        """Test that timestamp is auto-generated."""
        msg = Message(from_agent="a1", to_agent="a2")
        assert "T" in msg.timestamp  # ISO format

    def test_priority_default(self):
        """Test default priority."""
        msg = Message(from_agent="a1", to_agent="a2")
        assert msg.priority == 3

    def test_custom_priority(self):
        """Test custom priority."""
        msg = Message(from_agent="a1", to_agent="a2", priority=1)
        assert msg.priority == 1

    def test_correlation_id_optional(self):
        """Test correlation ID is optional."""
        msg = Message(from_agent="a1", to_agent="a2")
        assert msg.correlation_id is None

    def test_with_correlation_id(self):
        """Test message with correlation ID."""
        corr_id = str(uuid4())
        msg = Message(
            from_agent="a1",
            to_agent="a2",
            correlation_id=corr_id,
        )
        assert msg.correlation_id == corr_id

    def test_to_dict(self):
        """Test converting message to dict."""
        msg = Message(
            from_agent="agent1",
            to_agent="agent2",
            msg_type=MessageType.REQUEST,
            payload={"key": "value"},
        )
        d = msg.to_dict()
        assert d["from_agent"] == "agent1"
        assert d["to_agent"] == "agent2"
        assert d["msg_type"] == "REQUEST"
        assert d["payload"]["key"] == "value"


class TestMessageBusInit:
    """Test MessageBus initialization."""

    def test_creates_database(self, db_path):
        """Test that database is created."""
        MessageBus(db_path=db_path)
        assert db_path.exists()

    def test_creates_schema(self, db_path):
        """Test that database schema is created."""
        bus = MessageBus(db_path=db_path)
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "messages" in table_names
        assert "subscriptions" in table_names
        assert "message_reads" in table_names
        conn.close()

    def test_creates_indexes(self, db_path):
        """Test that indexes are created."""
        MessageBus(db_path=db_path)
        conn = sqlite3.connect(str(db_path))
        indexes = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = [i[0] for i in indexes]
        assert "idx_messages_to_agent" in index_names
        conn.close()

    def test_parent_directories_created(self, tmp_path):
        """Test that parent directories are created."""
        deep_path = tmp_path / "a" / "b" / "c" / "messages.sqlite"
        MessageBus(db_path=deep_path)
        assert deep_path.exists()


class TestPublish:
    """Test publish method."""

    def test_publish_message(self, bus):
        """Test publishing a message."""
        msg = Message(
            from_agent="agent1",
            to_agent="agent2",
            msg_type=MessageType.REQUEST,
            payload={"task": "scan"},
        )
        msg_id = bus.publish(msg)
        assert msg_id == msg.id

    def test_publish_persists_to_database(self, bus, db_path):
        """Test that published message is persisted."""
        msg = Message(
            from_agent="agent1",
            to_agent="agent2",
            msg_type=MessageType.REQUEST,
        )
        bus.publish(msg)
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT id FROM messages WHERE id = ?", (msg.id,)
        ).fetchone()
        assert row is not None
        conn.close()

    def test_publish_with_json_payload(self, bus):
        """Test publishing message with complex payload."""
        payload = {"nested": {"key": "value"}, "list": [1, 2, 3]}
        msg = Message(
            from_agent="agent1",
            to_agent="agent2",
            payload=payload,
        )
        msg_id = bus.publish(msg)
        assert msg_id is not None


class TestBroadcast:
    """Test broadcast method."""

    def test_broadcast_message(self, bus):
        """Test broadcasting a message."""
        msg_id = bus.broadcast(
            from_agent="oracle",
            msg_type=MessageType.ALERT,
            payload={"alert": "threat detected"},
        )
        assert msg_id is not None

    def test_broadcast_to_agent_is_wildcard(self, bus, db_path):
        """Test that broadcast uses wildcard for to_agent."""
        bus.broadcast("oracle", MessageType.ALERT, {})
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT to_agent FROM messages ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        assert row[0] == "*"
        conn.close()

    def test_broadcast_high_priority(self, bus, db_path):
        """Test that broadcast has high priority."""
        bus.broadcast("oracle", MessageType.ALERT, {})
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT priority FROM messages ORDER BY rowid DESC LIMIT 1"
        ).fetchone()
        assert row[0] == 1
        conn.close()


class TestGetMessages:
    """Test get_messages method."""

    def test_get_messages_for_agent(self, bus):
        """Test retrieving messages for specific agent."""
        msg = Message(
            from_agent="agent1",
            to_agent="agent2",
            msg_type=MessageType.REQUEST,
        )
        bus.publish(msg)
        messages = bus.get_messages("agent2")
        assert len(messages) > 0
        assert messages[0].to_agent == "agent2"

    def test_get_messages_includes_broadcasts(self, bus):
        """Test that get_messages includes broadcast messages."""
        bus.broadcast("oracle", MessageType.ALERT, {})
        messages = bus.get_messages("agent1")
        assert len(messages) > 0

    def test_get_messages_by_type(self, bus):
        """Test filtering messages by type."""
        bus.publish(Message(from_agent="a1", to_agent="a2", msg_type=MessageType.REQUEST))
        bus.publish(Message(from_agent="a1", to_agent="a2", msg_type=MessageType.RESPONSE))
        messages = bus.get_messages(
            "a2",
            msg_types=[MessageType.REQUEST],
        )
        assert all(m.msg_type == MessageType.REQUEST for m in messages)

    def test_get_messages_ordered_by_priority(self, bus):
        """Test that messages are ordered by priority."""
        bus.publish(Message(from_agent="a1", to_agent="a2", priority=5))
        bus.publish(Message(from_agent="a1", to_agent="a2", priority=1))
        messages = bus.get_messages("a2")
        assert messages[0].priority <= messages[-1].priority

    def test_get_messages_since_timestamp(self, bus):
        """Test filtering messages by timestamp."""
        msg1 = Message(from_agent="a1", to_agent="a2")
        bus.publish(msg1)
        time.sleep(0.1)
        msg2 = Message(from_agent="a1", to_agent="a2")
        bus.publish(msg2)
        messages = bus.get_messages("a2", since=msg2.timestamp)
        assert len(messages) >= 1

    def test_get_messages_empty(self, bus):
        """Test get_messages when none exist."""
        messages = bus.get_messages("nonexistent_agent")
        assert messages == []


class TestGetPending:
    """Test get_pending method."""

    def test_get_pending_unread_messages(self, bus):
        """Test getting unread messages."""
        msg = Message(from_agent="a1", to_agent="a2")
        bus.publish(msg)
        pending = bus.get_pending("a2")
        assert len(pending) > 0
        assert pending[0].id == msg.id

    def test_get_pending_excludes_acknowledged(self, bus):
        """Test that acknowledged messages are excluded."""
        msg = Message(from_agent="a1", to_agent="a2")
        msg_id = bus.publish(msg)
        bus.acknowledge(msg_id, "a2")
        pending = bus.get_pending("a2")
        assert msg_id not in [m.id for m in pending]

    def test_get_pending_empty(self, bus):
        """Test get_pending when no messages."""
        pending = bus.get_pending("a1")
        assert pending == []


class TestAcknowledge:
    """Test acknowledge method."""

    def test_acknowledge_message(self, bus):
        """Test acknowledging a message."""
        msg = Message(from_agent="a1", to_agent="a2")
        msg_id = bus.publish(msg)
        success = bus.acknowledge(msg_id, "a2")
        assert success is True

    def test_acknowledged_message_not_pending(self, bus):
        """Test that acknowledged message is not pending."""
        msg = Message(from_agent="a1", to_agent="a2")
        msg_id = bus.publish(msg)
        bus.acknowledge(msg_id, "a2")
        pending = bus.get_pending("a2")
        assert msg_id not in [m.id for m in pending]

    def test_acknowledge_twice_fails(self, bus):
        """Test that acknowledging twice fails."""
        msg = Message(from_agent="a1", to_agent="a2")
        msg_id = bus.publish(msg)
        bus.acknowledge(msg_id, "a2")
        success = bus.acknowledge(msg_id, "a2")
        assert success is False


class TestSubscribe:
    """Test subscribe method."""

    def test_subscribe_agent(self, bus):
        """Test subscribing an agent."""
        sub_id = bus.subscribe("agent1", [MessageType.REQUEST])
        assert sub_id is not None
        assert len(sub_id) > 0

    def test_subscribe_to_multiple_types(self, bus):
        """Test subscribing to multiple message types."""
        sub_id = bus.subscribe(
            "agent1",
            [MessageType.REQUEST, MessageType.RESPONSE],
        )
        assert sub_id is not None

    def test_subscribe_to_all_types(self, bus):
        """Test subscribing to all message types."""
        sub_id = bus.subscribe("agent1", None)
        assert sub_id is not None

    def test_subscribe_persists(self, bus, db_path):
        """Test that subscription is persisted."""
        sub_id = bus.subscribe("agent1", [MessageType.REQUEST])
        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT id FROM subscriptions WHERE id = ?", (sub_id,)
        ).fetchone()
        assert row is not None
        conn.close()


class TestUnsubscribe:
    """Test unsubscribe method."""

    def test_unsubscribe(self, bus):
        """Test unsubscribing."""
        sub_id = bus.subscribe("agent1", [MessageType.REQUEST])
        success = bus.unsubscribe(sub_id)
        assert success is True

    def test_unsubscribe_nonexistent(self, bus):
        """Test unsubscribing nonexistent subscription."""
        success = bus.unsubscribe("nonexistent")
        assert success is False


class TestRequestResponse:
    """Test request_response method."""

    def test_request_response_timeout(self, bus):
        """Test request/response with timeout."""
        # No one will respond, so should timeout
        response = bus.request_response(
            "agent1",
            "agent2",
            {"query": "status"},
            timeout_seconds=1,
        )
        assert response is None

    def test_request_response_with_responder(self, bus):
        """Test request/response when response is posted."""
        # Send request
        request = Message(
            from_agent="agent1",
            to_agent="agent2",
            msg_type=MessageType.REQUEST,
            correlation_id="test-corr-id",
        )
        bus.publish(request)

        # In test, manually post response
        response = Message(
            from_agent="agent2",
            to_agent="agent1",
            msg_type=MessageType.RESPONSE,
            correlation_id="test-corr-id",
            payload={"status": "ok"},
        )
        bus.publish(response)

        # Check we can get it
        messages = bus.get_messages("agent1", msg_types=[MessageType.RESPONSE])
        assert len(messages) > 0


class TestGetConversation:
    """Test get_conversation method."""

    def test_get_conversation_empty(self, bus):
        """Test getting conversation with no messages."""
        messages = bus.get_conversation("nonexistent-corr-id")
        assert messages == []

    def test_get_conversation_single_message(self, bus):
        """Test getting conversation with single message."""
        corr_id = str(uuid4())
        msg = Message(
            from_agent="a1",
            to_agent="a2",
            correlation_id=corr_id,
        )
        bus.publish(msg)
        messages = bus.get_conversation(corr_id)
        assert len(messages) == 1
        assert messages[0].correlation_id == corr_id

    def test_get_conversation_multiple_messages(self, bus):
        """Test getting conversation with multiple related messages."""
        corr_id = str(uuid4())
        for i in range(3):
            msg = Message(
                from_agent="a1",
                to_agent="a2",
                correlation_id=corr_id,
                payload={"seq": i},
            )
            bus.publish(msg)
        messages = bus.get_conversation(corr_id)
        assert len(messages) == 3

    def test_get_conversation_ordered_by_timestamp(self, bus):
        """Test that conversation messages are ordered by timestamp."""
        corr_id = str(uuid4())
        bus.publish(Message(from_agent="a1", to_agent="a2", correlation_id=corr_id))
        time.sleep(0.01)
        bus.publish(Message(from_agent="a1", to_agent="a2", correlation_id=corr_id))
        messages = bus.get_conversation(corr_id)
        assert messages[0].timestamp <= messages[1].timestamp


class TestPrune:
    """Test prune method."""

    def test_prune_old_messages(self, bus, db_path):
        """Test pruning old messages."""
        # Publish message
        msg = Message(from_agent="a1", to_agent="a2")
        bus.publish(msg)

        # Manually modify timestamp to be old
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE messages SET timestamp = '2020-01-01T00:00:00'",
        )
        conn.commit()
        conn.close()

        # Prune messages older than 1 hour
        deleted = bus.prune(older_than_hours=1)
        assert deleted > 0

    def test_prune_recent_messages_untouched(self, bus):
        """Test that recent messages are not pruned."""
        msg = Message(from_agent="a1", to_agent="a2")
        bus.publish(msg)

        deleted = bus.prune(older_than_hours=24)
        assert deleted == 0

    def test_prune_returns_count(self, bus, db_path):
        """Test that prune returns count of deleted messages."""
        # Add old message
        msg = Message(from_agent="a1", to_agent="a2")
        bus.publish(msg)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "UPDATE messages SET timestamp = '2020-01-01T00:00:00'",
        )
        conn.commit()
        conn.close()

        deleted = bus.prune(older_than_hours=1)
        assert isinstance(deleted, int)


class TestGetStats:
    """Test get_stats method."""

    def test_stats_empty_bus(self, bus):
        """Test stats for empty message bus."""
        stats = bus.get_stats()
        assert stats["total_messages"] == 0
        assert stats["unread_messages"] == 0

    def test_stats_with_messages(self, bus):
        """Test stats with published messages."""
        bus.publish(Message(from_agent="a1", to_agent="a2"))
        bus.publish(Message(from_agent="a1", to_agent="a2"))
        stats = bus.get_stats()
        assert stats["total_messages"] == 2
        assert stats["unread_messages"] == 2

    def test_stats_with_acknowledged(self, bus):
        """Test stats with acknowledged messages."""
        msg = Message(from_agent="a1", to_agent="a2")
        msg_id = bus.publish(msg)
        bus.acknowledge(msg_id, "a2")
        stats = bus.get_stats()
        assert stats["total_messages"] == 1
        assert stats["unread_messages"] == 0

    def test_stats_includes_subscribers(self, bus):
        """Test that stats includes subscriber count."""
        bus.subscribe("agent1", [MessageType.REQUEST])
        bus.subscribe("agent2", [MessageType.RESPONSE])
        stats = bus.get_stats()
        assert "active_subscribers" in stats
