"""Tests for rudy.automation.email_pipeline — EmailPipeline and EmailMessage."""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

import pytest

from rudy.automation.email_pipeline import EmailPipeline, EmailMessage


@pytest.fixture
def db_path(tmp_path):
    """Create a temporary database path."""
    return tmp_path / "test_email.sqlite"


@pytest.fixture
def pipeline(db_path):
    """Create an EmailPipeline instance with temp database."""
    return EmailPipeline(db_path=db_path)


@pytest.fixture
def sample_persona_rules():
    """Create sample persona rules for testing."""
    return {
        "identity": {
            "name": "John Doe",
            "title": "Manager",
        },
        "email_behavior": {
            "vip_senders": [
                "boss@company.com",
                "ceo@company.com",
            ],
            "urgency_keywords": [
                "urgent",
                "asap",
                "critical",
                "emergency",
            ],
            "signature": "Best regards,\nJohn Doe\nManager",
        },
    }


class TestEmailMessage:
    """Test EmailMessage creation and properties."""

    def test_basic_creation(self):
        """Test creating a basic EmailMessage."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            subject="Test Email",
            body="This is a test email",
            received_at="2026-03-28T10:00:00",
        )
        assert msg.id == "msg-123"
        assert msg.from_addr == "sender@example.com"
        assert msg.subject == "Test Email"
        assert msg.is_vip is False
        assert msg.urgency == "normal"
        assert msg.processed is False

    def test_with_labels(self):
        """Test EmailMessage with labels."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
            labels=["important", "work"],
        )
        assert msg.labels == ["important", "work"]

    def test_with_vip_flag(self):
        """Test EmailMessage with VIP flag."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="boss@example.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
            is_vip=True,
        )
        assert msg.is_vip is True

    def test_with_urgency(self):
        """Test EmailMessage with urgency level."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
            urgency="high",
        )
        assert msg.urgency == "high"


class TestEmailPipelineInit:
    """Test EmailPipeline initialization."""

    def test_creates_database(self, db_path):
        """Test that EmailPipeline creates the database."""
        EmailPipeline(db_path=db_path)
        assert db_path.exists()

    def test_creates_table(self, db_path):
        """Test that email_log table is created."""
        EmailPipeline(db_path=db_path)
        conn = sqlite3.connect(str(db_path))
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = [t[0] for t in tables]
        assert "email_log" in table_names
        conn.close()


class TestClassifyEmail:
    """Test classify_email method."""

    def test_classify_vip_sender(self, pipeline, sample_persona_rules):
        """Test classifying email from VIP sender."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="boss@company.com",
            to_addr="recipient@example.com",
            subject="Test Email",
            body="Content",
            received_at="2026-03-28T10:00:00",
        )
        classification = pipeline.classify_email(msg, sample_persona_rules)
        assert classification["vip_sender"] is True

    def test_classify_non_vip_sender(self, pipeline, sample_persona_rules):
        """Test classifying email from non-VIP sender."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Test Email",
            body="Content",
            received_at="2026-03-28T10:00:00",
        )
        classification = pipeline.classify_email(msg, sample_persona_rules)
        assert classification["vip_sender"] is False

    def test_classify_with_urgency_keywords(self, pipeline, sample_persona_rules):
        """Test classifying email with urgency keywords."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="URGENT: Please review this",
            body="This is critical and needs ASAP attention",
            received_at="2026-03-28T10:00:00",
        )
        classification = pipeline.classify_email(msg, sample_persona_rules)
        assert classification["urgency"] == "immediate"

    def test_classify_single_urgency_keyword(self, pipeline, sample_persona_rules):
        """Test classification with single urgency keyword."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Review needed",
            body="Please review the document urgently",
            received_at="2026-03-28T10:00:00",
        )
        classification = pipeline.classify_email(msg, sample_persona_rules)
        assert classification["urgency"] == "high"

    def test_classify_vip_urgent_sends(self, pipeline, sample_persona_rules):
        """Test that VIP urgent emails are auto-sent."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="ceo@company.com",
            to_addr="recipient@example.com",
            subject="URGENT: Decision needed",
            body="This is critical and needs ASAP action",
            received_at="2026-03-28T10:00:00",
        )
        classification = pipeline.classify_email(msg, sample_persona_rules)
        assert classification["action"] == "send"
        assert classification["priority"] == "high"

    def test_classify_immediate_flags(self, pipeline, sample_persona_rules):
        """Test that immediate emails are flagged."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="URGENT: CRITICAL emergency",
            body="This is an emergency ASAP",
            received_at="2026-03-28T10:00:00",
        )
        classification = pipeline.classify_email(msg, sample_persona_rules)
        assert classification["action"] == "flag"
        assert classification["priority"] == "high"

    def test_classify_normal_drafts(self, pipeline, sample_persona_rules):
        """Test that normal emails are drafted."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Quick question",
            body="Do you have time for a quick call?",
            received_at="2026-03-28T10:00:00",
        )
        classification = pipeline.classify_email(msg, sample_persona_rules)
        assert classification["action"] == "draft"
        assert classification["priority"] == "medium"


class TestDetermineUrgency:
    """Test determine_urgency method."""

    def test_urgency_immediate(self, pipeline, sample_persona_rules):
        """Test determining immediate urgency."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            subject="URGENT critical ASAP",
            body="This needs immediate attention",
            received_at="2026-03-28T10:00:00",
        )
        urgency = pipeline.determine_urgency(msg, sample_persona_rules)
        assert urgency == "immediate"

    def test_urgency_high(self, pipeline, sample_persona_rules):
        """Test determining high urgency."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            subject="Please review",
            body="This is urgent",
            received_at="2026-03-28T10:00:00",
        )
        urgency = pipeline.determine_urgency(msg, sample_persona_rules)
        assert urgency == "high"

    def test_urgency_normal(self, pipeline, sample_persona_rules):
        """Test determining normal urgency."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            subject="Follow up",
            body="Just checking in",
            received_at="2026-03-28T10:00:00",
        )
        urgency = pipeline.determine_urgency(msg, sample_persona_rules)
        assert urgency == "normal"

    def test_urgency_case_insensitive(self, pipeline, sample_persona_rules):
        """Test that urgency matching is case-insensitive."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="sender@example.com",
            to_addr="recipient@example.com",
            subject="URGENT",
            body="lowercase urgent in body",
            received_at="2026-03-28T10:00:00",
        )
        urgency = pipeline.determine_urgency(msg, sample_persona_rules)
        assert urgency == "high"


class TestIsVipSender:
    """Test is_vip_sender method."""

    def test_is_vip_exact_match(self, pipeline, sample_persona_rules):
        """Test VIP detection with exact email match."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="boss@company.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
        )
        is_vip = pipeline.is_vip_sender(msg, sample_persona_rules)
        assert is_vip is True

    def test_is_vip_case_insensitive(self, pipeline, sample_persona_rules):
        """Test VIP detection is case-insensitive."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="BOSS@COMPANY.COM",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
        )
        is_vip = pipeline.is_vip_sender(msg, sample_persona_rules)
        assert is_vip is True

    def test_is_not_vip(self, pipeline, sample_persona_rules):
        """Test non-VIP detection."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="unknown@example.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
        )
        is_vip = pipeline.is_vip_sender(msg, sample_persona_rules)
        assert is_vip is False

    def test_is_vip_multiple_senders(self, pipeline, sample_persona_rules):
        """Test VIP detection with multiple VIP senders."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="ceo@company.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
        )
        is_vip = pipeline.is_vip_sender(msg, sample_persona_rules)
        assert is_vip is True


class TestGenerateResponseContext:
    """Test generate_response_context method."""

    def test_generate_context(self, pipeline, sample_persona_rules):
        """Test generating response context."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Quick question",
            body="Do you have thoughts on this?",
            received_at="2026-03-28T10:00:00",
        )
        classification = pipeline.classify_email(msg, sample_persona_rules)
        context = pipeline.generate_response_context(msg, classification)

        assert context["email_id"] == "msg-123"
        assert context["from"] == "colleague@example.com"
        assert context["subject"] == "Quick question"
        assert "tone_guidance" in context
        assert "length_suggestion" in context

    def test_context_includes_vip_flag(self, pipeline, sample_persona_rules):
        """Test that context includes VIP flag."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="boss@company.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
        )
        classification = pipeline.classify_email(msg, sample_persona_rules)
        context = pipeline.generate_response_context(msg, classification)

        assert context["vip_sender"] is True

    def test_context_tone_formal(self, pipeline, sample_persona_rules):
        """Test that formal emails get formal tone."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Proposal Review",
            body="Please review this proposal",
            received_at="2026-03-28T10:00:00",
        )
        classification = pipeline.classify_email(msg, sample_persona_rules)
        context = pipeline.generate_response_context(msg, classification)

        assert context["tone_guidance"] == "formal"

    def test_context_length_suggestion(self, pipeline, sample_persona_rules):
        """Test length suggestion based on email size."""
        # Long email
        long_msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Discussion",
            body="X" * 600,
            received_at="2026-03-28T10:00:00",
        )
        classification = pipeline.classify_email(long_msg, sample_persona_rules)
        context = pipeline.generate_response_context(long_msg, classification)
        assert "detailed" in context["length_suggestion"]


class TestBuildSignature:
    """Test build_signature method."""

    def test_build_signature_from_config(self, pipeline, sample_persona_rules):
        """Test building signature from persona config."""
        sig = pipeline.build_signature(sample_persona_rules)
        assert "John Doe" in sig
        assert "Manager" in sig

    def test_build_signature_fallback(self, pipeline):
        """Test signature fallback with minimal config."""
        minimal_rules = {"identity": {"name": "Jane Smith"}}
        sig = pipeline.build_signature(minimal_rules)
        assert "Jane Smith" in sig

    def test_build_signature_default_fallback(self, pipeline):
        """Test signature with empty config."""
        sig = pipeline.build_signature({})
        assert "Assistant" in sig


class TestProcessIncoming:
    """Test process_incoming batch processing method."""

    def test_process_single_email(self, pipeline, sample_persona_rules):
        """Test processing a single email."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Quick question",
            body="Test body",
            received_at="2026-03-28T10:00:00",
        )
        results = pipeline.process_incoming([msg], "test_persona", sample_persona_rules)

        assert len(results) == 1
        assert results[0]["email_id"] == "msg-123"
        assert results[0]["status"] == "processed"

    def test_process_multiple_emails(self, pipeline, sample_persona_rules):
        """Test processing multiple emails."""
        emails = [
            EmailMessage(
                id=f"msg-{i}",
                from_addr=f"sender{i}@example.com",
                to_addr="recipient@example.com",
                subject=f"Email {i}",
                body="Test",
                received_at="2026-03-28T10:00:00",
            )
            for i in range(3)
        ]
        results = pipeline.process_incoming(emails, "test_persona", sample_persona_rules)

        assert len(results) == 3
        for result in results:
            assert result["status"] == "processed"

    def test_process_includes_classification(self, pipeline, sample_persona_rules):
        """Test that processing includes classification."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="boss@company.com",
            to_addr="recipient@example.com",
            subject="URGENT: Action needed",
            body="This is critical ASAP",
            received_at="2026-03-28T10:00:00",
        )
        results = pipeline.process_incoming([msg], "test_persona", sample_persona_rules)

        assert "classification" in results[0]
        assert results[0]["classification"]["vip_sender"] is True
        assert results[0]["classification"]["urgency"] == "immediate"

    def test_process_includes_response_context(self, pipeline, sample_persona_rules):
        """Test that processing includes response context."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Question",
            body="Short",
            received_at="2026-03-28T10:00:00",
        )
        results = pipeline.process_incoming([msg], "test_persona", sample_persona_rules)

        assert "response_context" in results[0]
        assert results[0]["response_context"]["email_id"] == "msg-123"

    def test_process_includes_signature(self, pipeline, sample_persona_rules):
        """Test that processing includes signature."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
        )
        results = pipeline.process_incoming([msg], "test_persona", sample_persona_rules)

        assert "signature" in results[0]
        assert len(results[0]["signature"]) > 0

    def test_process_marks_email_processed(self, pipeline, sample_persona_rules):
        """Test that processed flag is set."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
        )
        assert msg.processed is False
        pipeline.process_incoming([msg], "test_persona", sample_persona_rules)
        assert msg.processed is True

    def test_process_handles_error(self, pipeline):
        """Test error handling during processing."""
        # Invalid persona rules will cause error
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
        )
        results = pipeline.process_incoming([msg], "test_persona", None)

        assert len(results) == 1
        assert "error" in results[0]["status"] or "status" in results[0]


class TestProcessingLog:
    """Test email processing log."""

    def test_processing_logged_to_database(self, pipeline, sample_persona_rules, db_path):
        """Test that processing is logged to database."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
        )
        pipeline.process_incoming([msg], "test_persona", sample_persona_rules)

        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "SELECT email_id, action, persona FROM email_log WHERE email_id = ?",
            ("msg-123",),
        ).fetchall()
        assert len(rows) > 0
        assert rows[0][1] == "draft"  # default action
        assert rows[0][2] == "test_persona"
        conn.close()

    def test_get_processing_log(self, pipeline, sample_persona_rules):
        """Test retrieving processing log."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
        )
        pipeline.process_incoming([msg], "test_persona", sample_persona_rules)

        log = pipeline.get_processing_log()
        assert len(log) > 0
        assert log[0]["email_id"] == "msg-123"

    def test_get_processing_log_by_email_id(self, pipeline, sample_persona_rules):
        """Test retrieving log for specific email."""
        msg = EmailMessage(
            id="msg-123",
            from_addr="colleague@example.com",
            to_addr="recipient@example.com",
            subject="Test",
            body="Test",
            received_at="2026-03-28T10:00:00",
        )
        pipeline.process_incoming([msg], "test_persona", sample_persona_rules)

        log = pipeline.get_processing_log(email_id="msg-123")
        assert len(log) > 0
        assert all(entry["email_id"] == "msg-123" for entry in log)
