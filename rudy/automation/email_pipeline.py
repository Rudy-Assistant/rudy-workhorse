"""
EmailPipeline — Persona-aware email processing and classification

Features:
- Email classification based on sender, subject, urgency
- VIP detection from persona rules
- Urgency scoring from keywords
- Response context generation for LLM drafting
- Signature building from persona config
- Processing log with audit trail
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any
import uuid

log = logging.getLogger(__name__)

# Default database path
DESKTOP = Path(__file__).resolve().parent.parent.parent / "Desktop" if not Path(__file__).resolve().parent.parent.parent.name == "push-staging" else Path(__file__).resolve().parent.parent.parent
if str(DESKTOP) == str(Path(__file__).resolve().parent.parent.parent):
    DESKTOP = Path(__file__).resolve().parent.parent.parent / "Desktop"
DEFAULT_DB_PATH = DESKTOP / "rudy-data" / "memory.sqlite"


@dataclass
class EmailMessage:
    """Represents an email message to be processed."""
    id: str
    from_addr: str
    to_addr: str
    subject: str
    body: str
    received_at: str
    labels: List[str] = field(default_factory=list)
    is_vip: bool = False
    urgency: str = "normal"  # immediate | high | normal | low
    processed: bool = False


class EmailPipeline:
    """Persona-aware email processing and classification pipeline.

    Classifies emails based on persona rules (VIP senders, urgency keywords)
    and generates response context for LLM drafting.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize EmailPipeline.

        Args:
            db_path: Path to memory.sqlite
        """
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._init_db()
        log.info(f"EmailPipeline initialized with db: {self._db_path}")

    def _init_db(self) -> None:
        """Initialize SQLite table for email processing log."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS email_log (
                    id TEXT PRIMARY KEY,
                    email_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    persona TEXT,
                    classification TEXT,
                    response_draft TEXT,
                    processed_at TEXT NOT NULL
                )
            """)

            conn.commit()
            conn.close()
            log.debug("Email log table initialized")
        except Exception as e:
            log.error(f"Failed to initialize email log: {e}")

    def classify_email(
        self,
        email: EmailMessage,
        persona_rules: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Classify an email based on persona rules.

        Args:
            email: EmailMessage to classify
            persona_rules: Persona configuration dict (from YAML)

        Returns:
            Classification dict with: vip_sender, urgency, action, priority
        """
        classification = {
            "email_id": email.id,
            "vip_sender": False,
            "urgency": "normal",
            "action": "draft",  # draft | send | flag | auto_respond
            "priority": "medium",
            "confidence": 0.5,
        }

        # Check VIP status
        email.is_vip = self.is_vip_sender(email, persona_rules)
        classification["vip_sender"] = email.is_vip

        # Determine urgency
        urgency = self.determine_urgency(email, persona_rules)
        email.urgency = urgency
        classification["urgency"] = urgency

        # Set action based on classification
        if email.is_vip and urgency in ["immediate", "high"]:
            classification["action"] = "send"  # Auto-send for VIP urgent
            classification["priority"] = "high"
        elif urgency == "immediate":
            classification["action"] = "flag"  # Flag for manual review if immediate
            classification["priority"] = "high"
        else:
            classification["action"] = "draft"  # Draft for review otherwise

        log.debug(f"Email classified: {email.from_addr} -> {classification['action']}")
        return classification

    def determine_urgency(
        self,
        email: EmailMessage,
        rules: Dict[str, Any],
    ) -> str:
        """Determine email urgency from keywords and metadata.

        Args:
            email: EmailMessage
            rules: Persona rules with urgency_keywords list

        Returns:
            Urgency level: "immediate" | "high" | "normal" | "low"
        """
        urgency_keywords = rules.get("email_behavior", {}).get("urgency_keywords", [])

        # Check subject and body for urgency keywords
        subject_lower = email.subject.lower()
        body_lower = email.body.lower()

        keyword_matches = 0
        for keyword in urgency_keywords:
            if keyword.lower() in subject_lower or keyword.lower() in body_lower:
                keyword_matches += 1

        # Scoring
        if keyword_matches >= 2:
            return "immediate"
        elif keyword_matches == 1:
            return "high"
        else:
            return "normal"

    def is_vip_sender(
        self,
        email: EmailMessage,
        rules: Dict[str, Any],
    ) -> bool:
        """Check if sender is a VIP.

        Args:
            email: EmailMessage
            rules: Persona rules with vip_senders list

        Returns:
            True if sender is VIP
        """
        vip_senders = rules.get("email_behavior", {}).get("vip_senders", [])
        return email.from_addr.lower() in [v.lower() for v in vip_senders]

    def generate_response_context(
        self,
        email: EmailMessage,
        classification: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Generate context for LLM to draft a response.

        Args:
            email: EmailMessage
            classification: Classification dict from classify_email()

        Returns:
            Context dict for LLM prompt
        """
        context = {
            "email_id": email.id,
            "from": email.from_addr,
            "subject": email.subject,
            "body": email.body,
            "vip_sender": classification.get("vip_sender", False),
            "urgency": classification.get("urgency", "normal"),
            "tone_guidance": self._get_tone_guidance(email),
            "length_suggestion": self._get_length_suggestion(email),
        }

        return context

    def _get_tone_guidance(self, email: EmailMessage) -> str:
        """Determine appropriate tone for response."""
        # Very simple: match formality of original
        if any(formal in email.subject for formal in ["Proposal", "Contract", "Agreement"]):
            return "formal"
        elif "urgent" in email.subject.lower() or email.urgency in ["immediate", "high"]:
            return "direct"
        else:
            return "friendly"

    def _get_length_suggestion(self, email: EmailMessage) -> str:
        """Suggest response length."""
        body_len = len(email.body)
        if body_len < 100:
            return "brief (one paragraph)"
        elif body_len < 500:
            return "moderate (2-3 paragraphs)"
        else:
            return "detailed (as needed)"

    def build_signature(self, persona_rules: Dict[str, Any]) -> str:
        """Build email signature from persona rules.

        Args:
            persona_rules: Persona configuration dict

        Returns:
            Signature string
        """
        signature = persona_rules.get("email_behavior", {}).get("signature", "")
        if not signature:
            # Fallback
            identity = persona_rules.get("identity", {})
            name = identity.get("name", "Assistant")
            signature = f"Best,\n{name}"

        return signature

    def process_incoming(
        self,
        emails: List[EmailMessage],
        persona: str,
        persona_rules: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Process a batch of incoming emails.

        Args:
            emails: List of EmailMessage objects
            persona: Persona name
            persona_rules: Persona configuration dict

        Returns:
            List of processing results
        """
        results = []

        for email in emails:
            try:
                # Classify
                classification = self.classify_email(email, persona_rules)

                # Generate response context
                response_context = self.generate_response_context(email, classification)

                # Log to database
                log_entry = {
                    "log_id": str(uuid.uuid4()),
                    "email_id": email.id,
                    "action": classification["action"],
                    "persona": persona,
                    "classification": json.dumps(classification),
                    "response_context": json.dumps(response_context),
                    "processed_at": datetime.now().isoformat(),
                }

                self._log_email(log_entry)

                email.processed = True

                results.append({
                    "email_id": email.id,
                    "status": "processed",
                    "classification": classification,
                    "response_context": response_context,
                    "signature": self.build_signature(persona_rules),
                })

                log.info(f"Email processed: {email.from_addr} ({classification['action']})")

            except Exception as e:
                log.error(f"Failed to process email {email.id}: {e}")
                results.append({
                    "email_id": email.id,
                    "status": "error",
                    "error": str(e),
                })

        return results

    def _log_email(self, log_entry: Dict[str, Any]) -> None:
        """Persist email processing to database."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO email_log
                (id, email_id, action, persona, classification, response_draft, processed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                log_entry["log_id"],
                log_entry["email_id"],
                log_entry["action"],
                log_entry["persona"],
                log_entry["classification"],
                log_entry.get("response_context", ""),
                log_entry["processed_at"],
            ))
            conn.commit()
            conn.close()
        except Exception as e:
            log.error(f"Failed to log email: {e}")

    def get_processing_log(
        self,
        email_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get email processing log entries.

        Args:
            email_id: Filter by email ID (optional)
            limit: Max results

        Returns:
            List of log entries
        """
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()

            if email_id:
                cursor.execute("""
                    SELECT * FROM email_log
                    WHERE email_id = ?
                    ORDER BY processed_at DESC
                """, (email_id,))
            else:
                cursor.execute("""
                    SELECT * FROM email_log
                    ORDER BY processed_at DESC
                    LIMIT ?
                """, (limit,))

            rows = cursor.fetchall()
            conn.close()

            entries = []
            for row in rows:
                entries.append({
                    "log_id": row[0],
                    "email_id": row[1],
                    "action": row[2],
                    "persona": row[3],
                    "classification": json.loads(row[4]) if row[4] else {},
                    "processed_at": row[6],
                })

            return entries
        except Exception as e:
            log.error(f"Failed to retrieve processing log: {e}")
            return []
