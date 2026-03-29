"""
WebhookHandler — Receive and process webhooks from n8n and external services

Features:
- Webhook event validation with HMAC-SHA256 signatures
- Endpoint registration and management
- SQLite persistence for event audit trail
- N8nWebhookClient for triggering n8n workflows
"""

import hashlib
import hmac
import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, asdict, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

log = logging.getLogger(__name__)

# Default database path
DESKTOP = Path(__file__).resolve().parent.parent.parent / "Desktop" if not Path(__file__).resolve().parent.parent.parent.name == "push-staging" else Path(__file__).resolve().parent.parent.parent
if str(DESKTOP) == str(Path(__file__).resolve().parent.parent.parent):
    DESKTOP = Path(__file__).resolve().parent.parent.parent / "Desktop"
DEFAULT_DB_PATH = DESKTOP / "rudy-data" / "memory.sqlite"


@dataclass
class WebhookEvent:
    """Represents a single webhook event."""
    id: str
    source: str
    event_type: str
    payload: Dict[str, Any]
    headers: Dict[str, str]
    received_at: str
    processed: bool = False
    process_error: Optional[str] = None


class WebhookHandler:
    """Handle webhook reception, validation, and routing."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize WebhookHandler.

        Args:
            db_path: Path to memory.sqlite
        """
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Registered endpoints: {path: {handler, secret, endpoint_id}}
        self._endpoints: Dict[str, Dict[str, Any]] = {}

        self._init_db()
        log.info(f"WebhookHandler initialized with db: {self._db_path}")

    def _init_db(self) -> None:
        """Initialize SQLite table for webhook events."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS webhook_events (
                    id TEXT PRIMARY KEY,
                    source TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    headers TEXT NOT NULL,
                    received_at TEXT NOT NULL,
                    processed BOOLEAN DEFAULT 0,
                    process_error TEXT
                )
            """)

            conn.commit()
            conn.close()
            log.debug("Webhook events table initialized")
        except Exception as e:
            log.error(f"Failed to initialize webhook table: {e}")

    def register_endpoint(
        self,
        path: str,
        handler_fn: Callable,
        secret: str,
    ) -> str:
        """Register a webhook endpoint.

        Args:
            path: URL path (e.g., "/webhooks/n8n/trigger")
            handler_fn: Function to call with (event: WebhookEvent) -> result
            secret: HMAC secret for signature validation

        Returns:
            endpoint_id (UUID)
        """
        endpoint_id = str(uuid.uuid4())

        self._endpoints[path] = {
            "endpoint_id": endpoint_id,
            "handler": handler_fn,
            "secret": secret,
            "registered_at": datetime.now().isoformat(),
        }

        log.info(f"Webhook endpoint registered: {path} ({endpoint_id})")
        return endpoint_id

    def validate_signature(
        self,
        payload: str,
        signature: str,
        secret: str,
    ) -> bool:
        """Validate webhook signature using HMAC-SHA256.

        Args:
            payload: Raw request body as string
            signature: Signature from X-Signature header
            secret: HMAC secret

        Returns:
            True if signature is valid
        """
        try:
            expected = hmac.new(
                secret.encode(),
                payload.encode(),
                hashlib.sha256,
            ).hexdigest()
            return hmac.compare_digest(signature, expected)
        except Exception as e:
            log.error(f"Signature validation failed: {e}")
            return False

    def process_webhook(
        self,
        path: str,
        payload_str: str,
        headers: Dict[str, str],
    ) -> Optional[WebhookEvent]:
        """Process an incoming webhook.

        Args:
            path: Endpoint path
            payload_str: Raw request body
            headers: Request headers (case-insensitive)

        Returns:
            WebhookEvent if successful, None if validation failed

        Validates signature, executes handler, and persists to database.
        """
        # Normalize headers to lowercase
        headers_lower = {k.lower(): v for k, v in headers.items()}

        # Find endpoint
        if path not in self._endpoints:
            log.warning(f"Webhook received on unregistered path: {path}")
            return None

        endpoint = self._endpoints[path]

        # Validate signature if present
        sig = headers_lower.get("x-signature")
        if sig:
            if not self.validate_signature(payload_str, sig, endpoint["secret"]):
                log.warning(f"Invalid webhook signature on {path}")
                return None

        # Parse payload
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            log.error(f"Invalid JSON payload on {path}")
            return None

        # Create event
        event = WebhookEvent(
            id=str(uuid.uuid4()),
            source=headers_lower.get("x-source", "unknown"),
            event_type=headers_lower.get("x-event-type", "generic"),
            payload=payload,
            headers=dict(headers_lower),
            received_at=datetime.now().isoformat(),
        )

        # Call handler
        try:
            handler_result = endpoint["handler"](event)
            event.processed = True
            log.info(f"Webhook processed: {path} (event_id={event.id})")
        except Exception as e:
            event.process_error = str(e)
            log.error(f"Webhook handler failed: {e}")

        # Persist to database
        self._persist_event(event)

        return event

    def _persist_event(self, event: WebhookEvent) -> None:
        """Save webhook event to database."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO webhook_events
                (id, source, event_type, payload, headers, received_at, processed, process_error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                event.id,
                event.source,
                event.event_type,
                json.dumps(event.payload),
                json.dumps(event.headers),
                event.received_at,
                1 if event.processed else 0,
                event.process_error,
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Failed to persist webhook event: {e}")

    def get_recent_events(self, limit: int = 50) -> List[WebhookEvent]:
        """Get recent webhook events from database.

        Args:
            limit: Max events to return

        Returns:
            List of WebhookEvent objects
        """
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM webhook_events
                ORDER BY received_at DESC
                LIMIT ?
            """, (limit,))

            rows = cursor.fetchall()
            conn.close()

            events = []
            for row in rows:
                events.append(WebhookEvent(
                    id=row[0],
                    source=row[1],
                    event_type=row[2],
                    payload=json.loads(row[3]),
                    headers=json.loads(row[4]),
                    received_at=row[5],
                    processed=bool(row[6]),
                    process_error=row[7],
                ))

            return events
        except Exception as e:
            log.error(f"Failed to retrieve webhook events: {e}")
            return []


class N8nWebhookClient:
    """Client for triggering n8n workflows via API.

    N8n endpoints are exposed via HTTP, and we can trigger workflows
    by POSTing to their webhook URLs.
    """

    def __init__(self, base_url: str = "http://localhost:5678"):
        """Initialize N8n client.

        Args:
            base_url: Base URL of n8n instance (default: http://localhost:5678)
        """
        self.base_url = base_url
        log.info(f"N8nWebhookClient initialized with base: {base_url}")

    def trigger_workflow(
        self,
        workflow_id: str,
        data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Trigger an n8n workflow.

        Args:
            workflow_id: ID of the workflow to trigger
            data: Data to pass to the workflow

        Returns:
            Response dict from n8n
        """
        try:
            import requests
            url = f"{self.base_url}/webhook/{workflow_id}"
            response = requests.post(url, json=data, timeout=30)
            response.raise_for_status()

            log.info(f"Workflow triggered: {workflow_id}")
            return response.json()

        except ImportError:
            log.error("requests library not available for n8n trigger")
            return {"error": "requests library not installed"}
        except Exception as e:
            log.error(f"Failed to trigger workflow {workflow_id}: {e}")
            return {"error": str(e)}

    def get_workflow_status(self, execution_id: str) -> Dict[str, Any]:
        """Get status of a workflow execution.

        Args:
            execution_id: Execution ID from trigger response

        Returns:
            Status dict from n8n
        """
        try:
            import requests
            url = f"{self.base_url}/rest/executions/{execution_id}"
            response = requests.get(url, timeout=30)
            response.raise_for_status()

            log.debug(f"Workflow status retrieved: {execution_id}")
            return response.json()

        except ImportError:
            log.error("requests library not available")
            return {"error": "requests library not installed"}
        except Exception as e:
            log.error(f"Failed to get execution status {execution_id}: {e}")
            return {"error": str(e)}
