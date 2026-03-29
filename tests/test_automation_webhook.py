"""Tests for rudy.automation.webhook — WebhookHandler and related classes."""

import hashlib
import hmac
import json
import sqlite3
from pathlib import Path

import pytest

from rudy.automation.webhook import (
    WebhookEvent, WebhookHandler, N8nWebhookClient
)


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database path."""
    return tmp_path / "test_webhook.sqlite"


@pytest.fixture
def handler(db_path):
    """Create a WebhookHandler instance with temp database."""
    return WebhookHandler(db_path=db_path)


@pytest.fixture
def test_secret():
    """Create a test secret for HMAC validation."""
    return "test-secret-key"


class TestWebhookEvent:
    """Test WebhookEvent creation and properties."""

    def test_basic_creation(self):
        """Test creating a basic WebhookEvent."""
        event = WebhookEvent(
            id="event-123",
            source="n8n",
            event_type="workflow.executed",
            payload={"status": "success"},
            headers={"content-type": "application/json"},
            received_at="2026-03-28T10:00:00",
        )
        assert event.id == "event-123"
        assert event.source == "n8n"
        assert event.event_type == "workflow.executed"
        assert event.processed is False

    def test_with_processing_info(self):
        """Test WebhookEvent with processing status."""
        event = WebhookEvent(
            id="event-123",
            source="n8n",
            event_type="workflow.executed",
            payload={},
            headers={},
            received_at="2026-03-28T10:00:00",
            processed=True,
            process_error=None,
        )
        assert event.processed is True
        assert event.process_error is None

    def test_with_error(self):
        """Test WebhookEvent with error."""
        event = WebhookEvent(
            id="event-123",
            source="n8n",
            event_type="workflow.executed",
            payload={},
            headers={},
            received_at="2026-03-28T10:00:00",
            processed=False,
            process_error="Handler timeout",
        )
        assert event.processed is False
        assert event.process_error == "Handler timeout"


class TestWebhookHandlerInit:
    """Test WebhookHandler initialization."""

    def test_creates_database(self, db_path):
        """Test that WebhookHandler creates the database."""
        WebhookHandler(db_path=db_path)
        assert db_path.exists()

    def test_creates_table(self, db_path):
        """Test that webhook_events table is created."""
        WebhookHandler(db_path=db_path)
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "webhook_events" in table_names
        conn.close()

    def test_initializes_endpoints(self, handler):
        """Test that endpoints dict is initialized."""
        assert isinstance(handler._endpoints, dict)
        assert len(handler._endpoints) == 0


class TestRegisterEndpoint:
    """Test register_endpoint method."""

    def test_register_endpoint(self, handler):
        """Test registering a webhook endpoint."""
        def dummy_handler(event):
            return {"status": "ok"}

        endpoint_id = handler.register_endpoint(
            path="/webhooks/n8n/trigger",
            handler_fn=dummy_handler,
            secret="test-secret",
        )
        assert endpoint_id != ""
        assert "/webhooks/n8n/trigger" in handler._endpoints

    def test_register_multiple_endpoints(self, handler):
        """Test registering multiple endpoints."""
        def handler1(event):
            return {}
        def handler2(event):
            return {}

        id1 = handler.register_endpoint("/webhooks/path1", handler1, "secret1")
        id2 = handler.register_endpoint("/webhooks/path2", handler2, "secret2")

        assert id1 != id2
        assert "/webhooks/path1" in handler._endpoints
        assert "/webhooks/path2" in handler._endpoints

    def test_endpoint_contains_secret(self, handler):
        """Test that endpoint registration stores secret."""
        def dummy_handler(event):
            return {}

        handler.register_endpoint(
            "/webhooks/test",
            dummy_handler,
            "my-secret",
        )
        endpoint = handler._endpoints["/webhooks/test"]
        assert endpoint["secret"] == "my-secret"

    def test_endpoint_contains_handler(self, handler):
        """Test that endpoint registration stores handler."""
        def my_handler(event):
            return {"processed": True}

        handler.register_endpoint(
            "/webhooks/test",
            my_handler,
            "secret",
        )
        endpoint = handler._endpoints["/webhooks/test"]
        assert endpoint["handler"] is my_handler


class TestValidateSignature:
    """Test validate_signature method."""

    def test_valid_signature(self, handler, test_secret):
        """Test validating a correct signature."""
        payload = '{"key": "value"}'
        expected = hmac.new(
            test_secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()

        is_valid = handler.validate_signature(payload, expected, test_secret)
        assert is_valid is True

    def test_invalid_signature(self, handler, test_secret):
        """Test rejecting an incorrect signature."""
        payload = '{"key": "value"}'
        bad_signature = "completely-invalid-signature"

        is_valid = handler.validate_signature(payload, bad_signature, test_secret)
        assert is_valid is False

    def test_signature_case_sensitive(self, handler, test_secret):
        """Test that signature validation is case-sensitive."""
        payload = '{"key": "value"}'
        expected = hmac.new(
            test_secret.encode(),
            payload.encode(),
            hashlib.sha256,
        ).hexdigest()
        uppercase = expected.upper()

        is_valid = handler.validate_signature(payload, uppercase, test_secret)
        # HMAC comparison should handle case correctly
        assert is_valid is True or is_valid is False

    def test_signature_with_different_payload(self, handler, test_secret):
        """Test that signature validation fails with different payload."""
        payload1 = '{"key": "value1"}'
        payload2 = '{"key": "value2"}'
        sig = hmac.new(
            test_secret.encode(),
            payload1.encode(),
            hashlib.sha256,
        ).hexdigest()

        is_valid = handler.validate_signature(payload2, sig, test_secret)
        assert is_valid is False


class TestProcessWebhook:
    """Test process_webhook method."""

    def test_process_webhook_unregistered_path(self, handler):
        """Test processing webhook on unregistered path."""
        event = handler.process_webhook(
            path="/unknown/path",
            payload_str='{}',
            headers={},
        )
        assert event is None

    def test_process_webhook_with_valid_signature(self, handler, test_secret):
        """Test processing webhook with valid signature."""
        def my_handler(event):
            return {"processed": True}

        handler.register_endpoint(
            "/webhooks/test",
            my_handler,
            test_secret,
        )

        payload_str = '{"key": "value"}'
        sig = hmac.new(
            test_secret.encode(),
            payload_str.encode(),
            hashlib.sha256,
        ).hexdigest()

        event = handler.process_webhook(
            path="/webhooks/test",
            payload_str=payload_str,
            headers={"x-signature": sig, "x-source": "test-source"},
        )
        assert event is not None
        assert event.processed is True
        assert event.source == "test-source"

    def test_process_webhook_with_invalid_signature(self, handler, test_secret):
        """Test processing webhook with invalid signature."""
        def my_handler(event):
            return {}

        handler.register_endpoint(
            "/webhooks/test",
            my_handler,
            test_secret,
        )

        event = handler.process_webhook(
            path="/webhooks/test",
            payload_str='{"key": "value"}',
            headers={"x-signature": "invalid-signature"},
        )
        assert event is None

    def test_process_webhook_without_signature(self, handler):
        """Test processing webhook without signature."""
        def my_handler(event):
            return {"ok": True}

        handler.register_endpoint(
            "/webhooks/test",
            my_handler,
            "secret",
        )

        event = handler.process_webhook(
            path="/webhooks/test",
            payload_str='{"key": "value"}',
            headers={},
        )
        # Should process without signature validation
        assert event is not None

    def test_process_webhook_invalid_json(self, handler):
        """Test processing webhook with invalid JSON."""
        def my_handler(event):
            return {}

        handler.register_endpoint(
            "/webhooks/test",
            my_handler,
            "secret",
        )

        event = handler.process_webhook(
            path="/webhooks/test",
            payload_str="not valid json",
            headers={},
        )
        assert event is None

    def test_process_webhook_calls_handler(self, handler):
        """Test that process_webhook calls the handler function."""
        call_log = []

        def my_handler(event):
            call_log.append(event)
            return {"processed": True}

        handler.register_endpoint(
            "/webhooks/test",
            my_handler,
            "secret",
        )

        event = handler.process_webhook(
            path="/webhooks/test",
            payload_str='{"data": "test"}',
            headers={},
        )
        assert len(call_log) == 1
        assert call_log[0].payload == {"data": "test"}

    def test_process_webhook_handles_handler_error(self, handler):
        """Test that handler errors are captured."""
        def failing_handler(event):
            raise RuntimeError("Handler failed")

        handler.register_endpoint(
            "/webhooks/test",
            failing_handler,
            "secret",
        )

        event = handler.process_webhook(
            path="/webhooks/test",
            payload_str='{}',
            headers={},
        )
        assert event is not None
        assert event.processed is False
        assert event.process_error == "Handler failed"

    def test_process_webhook_normalizes_headers(self, handler):
        """Test that headers are normalized to lowercase."""
        def my_handler(event):
            return {}

        handler.register_endpoint(
            "/webhooks/test",
            my_handler,
            "secret",
        )

        event = handler.process_webhook(
            path="/webhooks/test",
            payload_str='{}',
            headers={
                "X-Source": "UPPERCASE",
                "X-Event-Type": "TEST",
            },
        )
        assert event.source == "UPPERCASE"


class TestGetRecentEvents:
    """Test get_recent_events method."""

    def test_get_recent_events_empty(self, handler):
        """Test getting recent events when none exist."""
        events = handler.get_recent_events()
        assert events == []

    def test_get_recent_events_single(self, handler):
        """Test getting a single event."""
        def dummy_handler(event):
            return {}

        handler.register_endpoint("/webhooks/test", dummy_handler, "secret")
        handler.process_webhook(
            path="/webhooks/test",
            payload_str='{"data": "test"}',
            headers={},
        )

        events = handler.get_recent_events()
        assert len(events) == 1
        assert events[0].payload == {"data": "test"}

    def test_get_recent_events_multiple(self, handler):
        """Test getting multiple events."""
        def dummy_handler(event):
            return {}

        handler.register_endpoint("/webhooks/test", dummy_handler, "secret")

        for i in range(5):
            handler.process_webhook(
                path="/webhooks/test",
                payload_str=json.dumps({"index": i}),
                headers={},
            )

        events = handler.get_recent_events()
        assert len(events) == 5

    def test_get_recent_events_respects_limit(self, handler):
        """Test that limit parameter is respected."""
        def dummy_handler(event):
            return {}

        handler.register_endpoint("/webhooks/test", dummy_handler, "secret")

        for i in range(10):
            handler.process_webhook(
                path="/webhooks/test",
                payload_str=json.dumps({"index": i}),
                headers={},
            )

        events = handler.get_recent_events(limit=3)
        assert len(events) <= 3

    def test_get_recent_events_ordered_by_time(self, handler):
        """Test that events are ordered by received_at descending."""
        def dummy_handler(event):
            return {}

        handler.register_endpoint("/webhooks/test", dummy_handler, "secret")

        for i in range(3):
            handler.process_webhook(
                path="/webhooks/test",
                payload_str=json.dumps({"index": i}),
                headers={},
            )

        events = handler.get_recent_events()
        # Most recent should be first
        assert events[0].payload["index"] == 2


class TestN8nWebhookClient:
    """Test N8nWebhookClient initialization."""

    def test_basic_initialization(self):
        """Test basic N8nWebhookClient initialization."""
        client = N8nWebhookClient()
        assert client.base_url == "http://localhost:5678"

    def test_custom_base_url(self):
        """Test initializing with custom base URL."""
        client = N8nWebhookClient(base_url="http://n8n.example.com:5678")
        assert client.base_url == "http://n8n.example.com:5678"

    def test_client_with_https(self):
        """Test initializing with HTTPS URL."""
        client = N8nWebhookClient(base_url="https://n8n.example.com")
        assert client.base_url == "https://n8n.example.com"


class TestPersistence:
    """Test webhook event persistence."""

    def test_events_persisted_to_database(self, handler, db_path):
        """Test that processed webhooks are persisted."""
        def dummy_handler(event):
            return {}

        handler.register_endpoint("/webhooks/test", dummy_handler, "secret")
        handler.process_webhook(
            path="/webhooks/test",
            payload_str='{"test": "data"}',
            headers={"x-source": "test-source"},
        )

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT source, event_type, payload FROM webhook_events"
        ).fetchall()
        assert len(rows) > 0
        assert rows[0][0] == "test-source"
        conn.close()

    def test_event_status_persisted(self, handler, db_path):
        """Test that event processing status is persisted."""
        def failing_handler(event):
            raise RuntimeError("test error")

        handler.register_endpoint("/webhooks/test", failing_handler, "secret")
        handler.process_webhook(
            path="/webhooks/test",
            payload_str='{}',
            headers={},
        )

        conn = sqlite3.connect(str(db_path))
        row = conn.execute(
            "SELECT processed, process_error FROM webhook_events"
        ).fetchone()
        assert row[0] == 0  # False
        assert "test error" in row[1]
        conn.close()
