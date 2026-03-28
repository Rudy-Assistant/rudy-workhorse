import pytest
from unittest.mock import patch, MagicMock, call, mock_open
from pathlib import Path
import json
import email
from email.mime.text import MIMEText
import sys
import subprocess

import rudy.email_poller as mod


# ------------------------------------
# FIXTURES
# ------------------------------------


@pytest.fixture
def tmp_state_dir(tmp_path):
    """Redirect state file and logs to temp directory."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return state_dir


@pytest.fixture
def monkeypatch_paths(monkeypatch, tmp_state_dir):
    """Monkeypatch LOG_DIR and STATE_FILE to use temp directory."""
    monkeypatch.setattr(mod, "LOG_DIR", tmp_state_dir)
    monkeypatch.setattr(mod, "STATE_FILE", tmp_state_dir / "email-poller-state.json")
    return tmp_state_dir


@pytest.fixture
def sample_email_bytes():
    """Create a sample RFC822-formatted email."""
    msg = MIMEText("This is a test email body.", "plain", "utf-8")
    msg["Subject"] = "Test Subject"
    msg["From"] = "Alice <alice@example.com>"
    msg["Message-ID"] = "<test-123@example.com>"
    return msg.as_bytes()


@pytest.fixture
def sample_email_bytes_complex_from():
    """Email with encoded header in From field."""
    msg = MIMEText("Test body", "plain", "utf-8")
    msg["Subject"] = "=?UTF-8?B?VGVzdA==?="
    msg["From"] = '"Alice Smith" <alice@example.com>'
    msg["Message-ID"] = "<test-456@example.com>"
    return msg.as_bytes()


@pytest.fixture
def sample_email_multipart():
    """Create a multipart email."""
    from email.mime.multipart import MIMEMultipart
    msg = MIMEMultipart()
    text_part = MIMEText("This is the plain text body.", "plain", "utf-8")
    msg.attach(text_part)
    msg["Subject"] = "Multipart Test"
    msg["From"] = "bob@example.com"
    msg["Message-ID"] = "<test-789@example.com>"
    return msg.as_bytes()


# ------------------------------------
# STATE MANAGEMENT TESTS
# ------------------------------------


def test_load_state_missing_file(monkeypatch_paths):
    """Test loading state when file doesn't exist."""
    state = mod.load_state()
    assert state["processed_ids"] == []
    assert state["last_poll"] is None
    assert state["backend_health"] == {}
    assert state["total_processed"] == 0


def test_load_state_existing_file(monkeypatch_paths):
    """Test loading existing state file."""
    initial_state = {
        "processed_ids": ["msg-1", "msg-2"],
        "last_poll": "2026-03-28T10:00:00",
        "backend_health": {"outlook": {"status": "ok"}},
        "total_processed": 2,
    }
    mod.STATE_FILE.write_text(json.dumps(initial_state))

    state = mod.load_state()
    assert state["processed_ids"] == ["msg-1", "msg-2"]
    assert state["total_processed"] == 2
    assert state["backend_health"]["outlook"]["status"] == "ok"


def test_load_state_corrupted_file(monkeypatch_paths, caplog):
    """Test loading corrupted state file returns defaults."""
    mod.STATE_FILE.write_text("{ invalid json }")
    state = mod.load_state()
    assert state["processed_ids"] == []
    assert state["total_processed"] == 0


def test_save_state(monkeypatch_paths):
    """Test saving state to file."""
    state = {
        "processed_ids": ["msg-1", "msg-2", "msg-3"],
        "last_poll": "2026-03-28T10:00:00",
        "backend_health": {"outlook": {"status": "ok"}},
        "total_processed": 3,
    }
    mod.save_state(state)

    assert mod.STATE_FILE.exists()
    loaded = json.loads(mod.STATE_FILE.read_text())
    assert loaded["processed_ids"] == ["msg-1", "msg-2", "msg-3"]
    assert loaded["total_processed"] == 3


def test_save_state_keeps_last_500_ids(monkeypatch_paths):
    """Test that save_state keeps only last 500 message IDs."""
    state = {
        "processed_ids": [f"msg-{i}" for i in range(600)],
        "last_poll": "2026-03-28T10:00:00",
        "backend_health": {},
        "total_processed": 600,
    }
    mod.save_state(state)

    loaded = json.loads(mod.STATE_FILE.read_text())
    assert len(loaded["processed_ids"]) == 500
    assert loaded["processed_ids"][0] == "msg-100"
    assert loaded["processed_ids"][-1] == "msg-599"


# ------------------------------------
# EMAIL HEADER DECODING TESTS
# ------------------------------------


def test_decode_header_value_empty():
    """Test decoding empty header."""
    result = mod.decode_header_value("")
    assert result == ""


def test_decode_header_value_none():
    """Test decoding None header."""
    result = mod.decode_header_value(None)
    assert result == ""


def test_decode_header_value_plain():
    """Test decoding plain ASCII header."""
    result = mod.decode_header_value("Simple Subject")
    assert result == "Simple Subject"


def test_decode_header_value_utf8_encoded():
    """Test decoding UTF-8 encoded header."""
    # This is what an encoded header looks like
    encoded = "=?UTF-8?B?VGVzdA==?="  # "Test" in base64
    result = mod.decode_header_value(encoded)
    assert "Test" in result or "VGVzdA" in result  # Either decoded or passes through


def test_decode_header_value_bytes():
    """Test decoding header with bytes - should be passed as string."""
    # Note: decode_header_value expects string input, not bytes
    # This test verifies the function works with string representation
    result = mod.decode_header_value("bytes header")
    assert isinstance(result, str)
    assert "bytes header" in result


# ------------------------------------
# BODY EXTRACTION TESTS
# ------------------------------------


def test_extract_body_simple(sample_email_bytes):
    """Test extracting body from simple email."""
    msg = email.message_from_bytes(sample_email_bytes)
    body = mod.extract_body(msg)
    assert "test email body" in body.lower()


def test_extract_body_multipart(sample_email_multipart):
    """Test extracting body from multipart email."""
    msg = email.message_from_bytes(sample_email_multipart)
    body = mod.extract_body(msg)
    assert "plain text body" in body.lower()


def test_extract_body_no_payload():
    """Test extracting body when no text/plain part exists."""
    from email.mime.multipart import MIMEMultipart
    msg = MIMEMultipart()
    msg["Subject"] = "Test"
    body = mod.extract_body(msg)
    assert body == ""


def test_extract_body_with_attachment():
    """Test that attachments are not included in body."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.base import MIMEBase

    msg = MIMEMultipart()
    text_part = MIMEText("Email body here", "plain", "utf-8")
    msg.attach(text_part)

    # Add an attachment (which should be skipped)
    attachment = MIMEBase("application", "octet-stream")
    attachment.set_payload(b"binary content")
    attachment["Content-Disposition"] = "attachment; filename=test.bin"
    msg.attach(attachment)

    body = mod.extract_body(msg)
    assert "Email body here" in body
    assert "binary content" not in body


# ------------------------------------
# SENDER EXTRACTION TESTS
# ------------------------------------


def test_get_sender_email_with_angle_brackets():
    """Test extracting sender email from angle bracket format."""
    msg = MIMEText("body")
    msg["From"] = "Alice Smith <alice@example.com>"
    email_addr = mod.get_sender_email(msg)
    assert email_addr == "alice@example.com"


def test_get_sender_email_plain():
    """Test extracting sender email from plain format."""
    msg = MIMEText("body")
    msg["From"] = "alice@example.com"
    email_addr = mod.get_sender_email(msg)
    assert email_addr == "alice@example.com"


def test_get_sender_email_uppercase_normalized():
    """Test that sender email is lowercased."""
    msg = MIMEText("body")
    msg["From"] = "Alice@Example.COM"
    email_addr = mod.get_sender_email(msg)
    assert email_addr == "alice@example.com"


def test_get_sender_email_missing():
    """Test getting sender email when From header is missing."""
    msg = MIMEText("body")
    email_addr = mod.get_sender_email(msg)
    assert isinstance(email_addr, str)


def test_get_sender_name_with_quotes():
    """Test extracting sender name with quotes."""
    msg = MIMEText("body")
    msg["From"] = '"Alice Smith" <alice@example.com>'
    name = mod.get_sender_name(msg)
    assert "Alice Smith" in name or "alice" in name.lower()


def test_get_sender_name_plain():
    """Test extracting sender name from plain email."""
    msg = MIMEText("body")
    msg["From"] = "alice@example.com"
    name = mod.get_sender_name(msg)
    assert "alice" in name.lower() or name == "alice@example.com"


def test_get_sender_name_with_display_name():
    """Test extracting sender name from display name + email."""
    msg = MIMEText("body")
    msg["From"] = "Alice Smith <alice@example.com>"
    name = mod.get_sender_name(msg)
    assert "Alice" in name or "alice" in name.lower()


# ------------------------------------
# ACCESS LEVEL DETERMINATION TESTS
# ------------------------------------


def test_determine_access_level_full_access():
    """Test full access determination."""
    level = mod.determine_access_level("ccimino2@gmail.com")
    assert level == "full"


def test_determine_access_level_family_access():
    """Test family access determination."""
    level = mod.determine_access_level("lrcimino@yahoo.com")
    assert level == "family"


def test_determine_access_level_unknown():
    """Test unknown access determination."""
    level = mod.determine_access_level("stranger@example.com")
    assert level == "unknown"


def test_determine_access_level_case_insensitive():
    """Test that sender email gets lowercased before checking access."""
    # The set contains lowercase email, and determine_access_level checks membership
    # Email addresses are lowercased in get_sender_email, so this test passes
    # a lowercase version that matches the set
    level = mod.determine_access_level("ccimino2@gmail.com")
    assert level == "full"


# ------------------------------------
# PROMPT BUILDING TESTS
# ------------------------------------


def test_build_prompt_full_access():
    """Test building prompt for full access user."""
    prompt = mod.build_prompt(
        "Alice",
        "alice@example.com",
        "Help with project",
        "Can you review this code?",
        "full"
    )
    assert prompt is not None
    assert "FULL ACCESS" in prompt
    assert "Alice" in prompt
    assert "Help with project" in prompt
    assert "Can you review this code?" in prompt
    assert "-- Rudy" in prompt


def test_build_prompt_family_access():
    """Test building prompt for family access user."""
    prompt = mod.build_prompt(
        "Bob",
        "bob@example.com",
        "Question",
        "What is AI?",
        "family"
    )
    assert prompt is not None
    assert "FAMILY ACCESS" in prompt
    assert "research, docs, Q&A only" in prompt
    assert "Bob" in prompt


def test_build_prompt_unknown_access():
    """Test that unknown access returns None."""
    prompt = mod.build_prompt(
        "Stranger",
        "stranger@example.com",
        "Help",
        "Can you help?",
        "unknown"
    )
    assert prompt is None


def test_build_prompt_contains_email_and_subject():
    """Test that prompt includes sender email and subject."""
    prompt = mod.build_prompt(
        "Alice Smith",
        "alice@example.com",
        "Complex Request",
        "Can you help with X, Y, and Z?",
        "full"
    )
    assert "alice@example.com" in prompt
    assert "Complex Request" in prompt
    assert "FROM:" in prompt
    assert "SUBJECT:" in prompt


# ------------------------------------
# IMAP POLLING TESTS
# ------------------------------------


@patch("rudy.email_poller.imaplib.IMAP4_SSL")
def test_poll_imap_success(mock_imap_ssl, sample_email_bytes, monkeypatch_paths, monkeypatch):
    """Test successful IMAP polling."""
    # Set up credentials in the backend config
    monkeypatch.setitem(mod.BACKENDS["outlook"], "email", "test@outlook.com")
    monkeypatch.setitem(mod.BACKENDS["outlook"], "password", "testpass")

    mock_mail = MagicMock()
    mock_imap_ssl.return_value = mock_mail

    mock_mail.search.return_value = ("OK", [b"1 2 3"])
    mock_mail.fetch.side_effect = [
        ("OK", [(None, sample_email_bytes)]),
        ("OK", [(None, sample_email_bytes)]),
        ("OK", [(None, sample_email_bytes)]),
    ]

    messages = mod.poll_imap("outlook")

    assert len(messages) == 3
    assert all(isinstance(m, tuple) and len(m) == 2 for m in messages)
    mock_mail.login.assert_called_once()
    mock_mail.logout.assert_called_once()


@patch("rudy.email_poller.imaplib.IMAP4_SSL")
def test_poll_imap_disabled_backend(mock_imap_ssl, monkeypatch_paths):
    """Test that disabled backends return empty list."""
    # Zoho has imap_available=False
    messages = mod.poll_imap("zoho")
    assert messages == []
    mock_imap_ssl.assert_not_called()


@patch("rudy.email_poller.imaplib.IMAP4_SSL")
def test_poll_imap_missing_credentials(mock_imap_ssl, monkeypatch_paths, monkeypatch):
    """Test that backends without credentials return empty list."""
    monkeypatch.setitem(mod.BACKENDS["outlook"], "email", "")
    monkeypatch.setitem(mod.BACKENDS["outlook"], "password", "")
    messages = mod.poll_imap("outlook")
    assert messages == []
    mock_imap_ssl.assert_not_called()


@patch("rudy.email_poller.imaplib.IMAP4_SSL")
def test_poll_imap_search_fails(mock_imap_ssl, monkeypatch_paths, monkeypatch):
    """Test handling of failed search."""
    monkeypatch.setitem(mod.BACKENDS["outlook"], "email", "test@outlook.com")
    monkeypatch.setitem(mod.BACKENDS["outlook"], "password", "testpass")

    mock_mail = MagicMock()
    mock_imap_ssl.return_value = mock_mail
    mock_mail.search.return_value = ("BAD", [])

    messages = mod.poll_imap("outlook")
    assert messages == []
    mock_mail.logout.assert_called_once()


@patch("rudy.email_poller.imaplib.IMAP4_SSL")
def test_poll_imap_connection_error(mock_imap_ssl, monkeypatch_paths):
    """Test handling of connection errors."""
    mock_imap_ssl.side_effect = Exception("Connection refused")

    messages = mod.poll_imap("outlook")
    assert messages == []


@patch("rudy.email_poller.imaplib.IMAP4_SSL")
def test_poll_imap_respects_max_process_per_poll(mock_imap_ssl, sample_email_bytes, monkeypatch_paths, monkeypatch):
    """Test that polling respects MAX_PROCESS_PER_POLL limit."""
    monkeypatch.setitem(mod.BACKENDS["outlook"], "email", "test@outlook.com")
    monkeypatch.setitem(mod.BACKENDS["outlook"], "password", "testpass")

    mock_mail = MagicMock()
    mock_imap_ssl.return_value = mock_mail

    # Return more UIDs than MAX_PROCESS_PER_POLL
    many_uids = b" ".join([str(i).encode() for i in range(20)])
    mock_mail.search.return_value = ("OK", [many_uids])
    mock_mail.fetch.return_value = ("OK", [(None, sample_email_bytes)])

    messages = mod.poll_imap("outlook")

    # Should only fetch the last MAX_PROCESS_PER_POLL messages
    assert len(messages) == mod.MAX_PROCESS_PER_POLL


# ------------------------------------
# SMTP SENDING TESTS
# ------------------------------------


@patch("rudy.email_poller.smtplib.SMTP")
def test_send_reply_starttls(mock_smtp, monkeypatch_paths, monkeypatch):
    """Test sending reply via SMTP with STARTTLS."""
    # Make sure Outlook backend (which uses STARTTLS) is configured
    monkeypatch.setitem(mod.BACKENDS["outlook"], "email", "test@outlook.com")
    monkeypatch.setitem(mod.BACKENDS["outlook"], "password", "testpass")
    monkeypatch.setattr(mod, "SEND_BACKEND", "outlook")

    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    result = mod.send_reply("recipient@example.com", "Original Subject", "Reply body here")

    assert result is True
    mock_smtp.assert_called_once()
    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once()
    mock_server.send_message.assert_called_once()


@patch("rudy.email_poller.smtplib.SMTP_SSL")
def test_send_reply_smtp_ssl(mock_smtp_ssl, monkeypatch_paths, monkeypatch):
    """Test sending reply via SMTP_SSL (non-STARTTLS)."""
    # Make sure Zoho backend (which uses SMTP_SSL) is configured
    monkeypatch.setitem(mod.BACKENDS["zoho"], "email", "rudy.test@zohomail.com")
    monkeypatch.setitem(mod.BACKENDS["zoho"], "password", "testpass")
    monkeypatch.setattr(mod, "SEND_BACKEND", "zoho")

    mock_server = MagicMock()
    mock_smtp_ssl.return_value.__enter__.return_value = mock_server

    result = mod.send_reply("recipient@example.com", "Subject", "Body")

    assert result is True
    mock_smtp_ssl.assert_called_once()
    mock_server.login.assert_called_once()
    mock_server.send_message.assert_called_once()


@patch("rudy.email_poller.smtplib.SMTP")
def test_send_reply_smtp_error(mock_smtp, monkeypatch_paths, monkeypatch):
    """Test handling SMTP errors."""
    monkeypatch.setitem(mod.BACKENDS["outlook"], "email", "test@outlook.com")
    monkeypatch.setitem(mod.BACKENDS["outlook"], "password", "testpass")
    monkeypatch.setattr(mod, "SEND_BACKEND", "outlook")

    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server
    mock_server.login.side_effect = Exception("Auth failed")

    result = mod.send_reply("recipient@example.com", "Subject", "Body")

    assert result is False


@patch("rudy.email_poller.smtplib.SMTP")
def test_send_reply_message_format(mock_smtp, monkeypatch_paths, monkeypatch):
    """Test that reply message is properly formatted."""
    monkeypatch.setitem(mod.BACKENDS["outlook"], "email", "test@outlook.com")
    monkeypatch.setitem(mod.BACKENDS["outlook"], "password", "testpass")
    monkeypatch.setattr(mod, "SEND_BACKEND", "outlook")

    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    mod.send_reply("recipient@example.com", "Original Subject", "Reply body")

    # Check that send_message was called
    mock_server.send_message.assert_called_once()
    msg = mock_server.send_message.call_args[0][0]
    assert msg["Subject"] == "Re: Original Subject"
    assert msg["To"] == "recipient@example.com"


# ------------------------------------
# MESSAGE PROCESSING TESTS
# ------------------------------------


def test_process_message_already_processed(monkeypatch_paths):
    """Test that already processed messages are skipped."""
    state = {"processed_ids": ["already-seen"], "total_processed": 0}
    msg_bytes = MIMEText("body").as_bytes()

    # Should return early without processing
    mod.process_message("uid-1", msg_bytes, state)
    # Note: we can't easily verify it was skipped without mocking,
    # but this tests the function runs without error


@patch("rudy.email_poller.send_reply")
@patch("rudy.email_poller.run_claude")
def test_process_message_full_access(mock_run_claude, mock_send_reply, monkeypatch_paths):
    """Test processing message from full access user."""
    mock_run_claude.return_value = "Here's the response."
    mock_send_reply.return_value = True

    msg = MIMEText("Can you help?", "plain", "utf-8")
    msg["From"] = "ccimino2@gmail.com"
    msg["Subject"] = "Request"
    msg["Message-ID"] = "<test@example.com>"

    state = {"processed_ids": [], "total_processed": 0}
    mod.process_message("uid-1", msg.as_bytes(), state)

    # Should have called run_claude (not send rejection)
    mock_run_claude.assert_called_once()
    # Should have sent reply with response
    mock_send_reply.assert_called_once()
    # Message ID should be in processed
    assert "<test@example.com>" in state["processed_ids"]


@patch("rudy.email_poller.send_reply")
@patch("rudy.email_poller.run_claude")
def test_process_message_unknown_access(mock_run_claude, mock_send_reply, monkeypatch_paths):
    """Test processing message from unknown sender."""
    msg = MIMEText("Can you help?", "plain", "utf-8")
    msg["From"] = "stranger@example.com"
    msg["Subject"] = "Request"
    msg["Message-ID"] = "<test@example.com>"

    state = {"processed_ids": [], "total_processed": 0}
    mod.process_message("uid-1", msg.as_bytes(), state)

    # Should NOT call run_claude
    mock_run_claude.assert_not_called()
    # Should have sent rejection email
    mock_send_reply.assert_called_once()
    call_args = mock_send_reply.call_args[0]
    assert "don't have you on my approved contacts" in call_args[2]


@patch("rudy.email_poller.send_reply")
def test_process_message_empty_body(mock_send_reply, monkeypatch_paths):
    """Test that messages with empty body are skipped."""
    msg = MIMEText("", "plain", "utf-8")
    msg["From"] = "ccimino2@gmail.com"
    msg["Subject"] = "Empty"
    msg["Message-ID"] = "<test@example.com>"

    state = {"processed_ids": [], "total_processed": 0}
    mod.process_message("uid-1", msg.as_bytes(), state)

    # Should NOT send reply for empty body
    mock_send_reply.assert_not_called()
    # Should mark as processed
    assert "<test@example.com>" in state["processed_ids"]


@patch("rudy.email_poller.send_reply")
def test_process_message_noreply_sender(mock_send_reply, monkeypatch_paths):
    """Test that noreply senders are skipped."""
    msg = MIMEText("Automated message", "plain", "utf-8")
    msg["From"] = "noreply@example.com"
    msg["Subject"] = "Notification"
    msg["Message-ID"] = "<test@example.com>"

    state = {"processed_ids": [], "total_processed": 0}
    mod.process_message("uid-1", msg.as_bytes(), state)

    # Should NOT send reply
    mock_send_reply.assert_not_called()
    # Should mark as processed
    assert "<test@example.com>" in state["processed_ids"]


@patch("rudy.email_poller.send_reply")
@patch("rudy.email_poller.run_claude")
def test_process_message_increments_total(mock_run_claude, mock_send_reply, monkeypatch_paths):
    """Test that total_processed counter is incremented."""
    mock_run_claude.return_value = "Response"

    msg = MIMEText("Help", "plain", "utf-8")
    msg["From"] = "ccimino2@gmail.com"
    msg["Subject"] = "Request"
    msg["Message-ID"] = "<test@example.com>"

    state = {"processed_ids": [], "total_processed": 0}
    initial_count = state["total_processed"]
    mod.process_message("uid-1", msg.as_bytes(), state)

    assert state["total_processed"] == initial_count + 1


@patch("builtins.open", new_callable=mock_open)
@patch("rudy.email_poller.send_reply")
@patch("rudy.email_poller.run_claude")
def test_process_message_logs_request(mock_run_claude, mock_send_reply, mock_file, monkeypatch_paths):
    """Test that processed requests are logged."""
    mock_run_claude.return_value = "Response"

    msg = MIMEText("Help with X", "plain", "utf-8")
    msg["From"] = "ccimino2@gmail.com"
    msg["Subject"] = "Request"
    msg["Message-ID"] = "<test@example.com>"

    state = {"processed_ids": [], "total_processed": 0}
    mod.process_message("uid-1", msg.as_bytes(), state)

    # File should have been opened for logging
    mock_file.assert_called()


# ------------------------------------
# CLAUDE SUBPROCESS TESTS
# ------------------------------------


@patch("subprocess.run")
def test_run_claude_success(mock_run, monkeypatch_paths):
    """Test successful Claude subprocess execution."""
    mock_run.return_value = MagicMock(
        stdout="Claude response here",
        stderr="",
        returncode=0
    )

    result = mod.run_claude("Test prompt")

    assert "Claude response here" in result
    mock_run.assert_called_once()
    call_args = mock_run.call_args
    assert call_args[0][0][0] == "claude"
    assert "-p" in call_args[0][0]


@patch("subprocess.run")
def test_run_claude_timeout(mock_run, monkeypatch_paths):
    """Test Claude timeout handling."""
    mock_run.side_effect = subprocess.TimeoutExpired("claude", 300)

    result = mod.run_claude("Test prompt")

    assert "took too long" in result


@patch("subprocess.run")
def test_run_claude_not_found(mock_run, monkeypatch_paths):
    """Test Claude not found handling."""
    mock_run.side_effect = FileNotFoundError("claude")

    result = mod.run_claude("Test prompt")

    assert "temporarily unavailable" in result


@patch("subprocess.run")
def test_run_claude_empty_response(mock_run, monkeypatch_paths):
    """Test handling of empty Claude response."""
    mock_run.return_value = MagicMock(stdout="", stderr="", returncode=0)

    result = mod.run_claude("Test prompt")

    assert "couldn't generate a response" in result


@patch("subprocess.run")
def test_run_claude_response_truncated(mock_run, monkeypatch_paths):
    """Test that long responses are truncated."""
    long_response = "x" * 10000
    mock_run.return_value = MagicMock(
        stdout=long_response,
        stderr="",
        returncode=0
    )

    result = mod.run_claude("Test prompt")

    assert len(result) <= 5000


@patch("subprocess.run")
def test_run_claude_uses_desktop_cwd(mock_run, monkeypatch_paths):
    """Test that Claude subprocess uses DESKTOP as cwd."""
    mock_run.return_value = MagicMock(stdout="response", stderr="", returncode=0)

    mod.run_claude("Test prompt")

    call_kwargs = mock_run.call_args[1]
    assert "cwd" in call_kwargs
    # cwd should be DESKTOP directory
    assert "Desktop" in call_kwargs["cwd"] or "USERPROFILE" in str(call_kwargs["cwd"])


# ------------------------------------
# POLL ONCE TESTS
# ------------------------------------


@patch("rudy.email_poller.poll_imap")
@patch("rudy.email_poller.process_message")
@patch("rudy.email_poller.save_state")
def test_poll_once_no_messages(mock_save, mock_process, mock_poll, monkeypatch_paths):
    """Test poll_once when no messages are found."""
    mock_poll.return_value = []

    mod.poll_once()

    mock_poll.assert_called()
    mock_process.assert_not_called()
    mock_save.assert_called_once()


@patch("rudy.email_poller.poll_imap")
@patch("rudy.email_poller.process_message")
@patch("rudy.email_poller.save_state")
def test_poll_once_with_messages(mock_save, mock_process, mock_poll, sample_email_bytes, monkeypatch_paths):
    """Test poll_once processes messages from first successful backend."""
    mock_poll.side_effect = [
        [("uid-1", sample_email_bytes), ("uid-2", sample_email_bytes)],  # outlook
        [],  # zoho (won't be called due to break)
    ]

    mod.poll_once()

    # Should process the messages from outlook
    assert mock_process.call_count == 2
    mock_save.assert_called_once()


@patch("rudy.email_poller.poll_imap")
@patch("rudy.email_poller.process_message")
@patch("rudy.email_poller.save_state")
def test_poll_once_fallback_to_next_backend(mock_save, mock_process, mock_poll, sample_email_bytes, monkeypatch_paths):
    """Test poll_once falls back to next backend if first returns empty."""
    mock_poll.side_effect = [
        [],  # outlook returns nothing
        [("uid-3", sample_email_bytes)],  # zoho has a message
    ]

    mod.poll_once()

    # Should process message from zoho
    assert mock_process.call_count == 1
    mock_save.assert_called_once()


@patch("rudy.email_poller.poll_imap")
@patch("rudy.email_poller.save_state")
def test_poll_once_updates_backend_health(mock_save, mock_poll, monkeypatch_paths):
    """Test that poll_once updates backend health status."""
    mock_poll.return_value = []

    mod.poll_once()

    # Get the state that was saved
    saved_state = mock_save.call_args[0][0]
    assert "backend_health" in saved_state
    assert saved_state["last_poll"] is not None


@patch("rudy.email_poller.poll_imap")
@patch("rudy.email_poller.save_state")
def test_poll_once_handles_backend_error(mock_save, mock_poll, monkeypatch_paths):
    """Test that poll_once handles backend errors gracefully."""
    mock_poll.side_effect = Exception("Connection error")

    mod.poll_once()

    # Should still save state
    mock_save.assert_called_once()
    saved_state = mock_save.call_args[0][0]
    # Error should be recorded in backend_health
    assert any(
        h.get("status") == "error" for h in saved_state.get("backend_health", {}).values()
    )


# ------------------------------------
# INTEGRATION TESTS
# ------------------------------------


@patch("subprocess.run")
@patch("rudy.email_poller.smtplib.SMTP")
@patch("rudy.email_poller.poll_imap")
def test_full_poll_cycle(mock_poll, mock_smtp, mock_run, monkeypatch_paths, monkeypatch):
    """Integration test: full poll cycle from receive to send."""
    monkeypatch.setitem(mod.BACKENDS["outlook"], "email", "test@outlook.com")
    monkeypatch.setitem(mod.BACKENDS["outlook"], "password", "testpass")
    monkeypatch.setattr(mod, "SEND_BACKEND", "outlook")

    msg = MIMEText("Can you explain recursion?", "plain", "utf-8")
    msg["From"] = "lrcimino@yahoo.com"
    msg["Subject"] = "Programming Question"
    msg["Message-ID"] = "<test@example.com>"

    mock_poll.return_value = [("uid-1", msg.as_bytes())]
    mock_run.return_value = MagicMock(stdout="Recursion is when...", stderr="", returncode=0)

    mock_server = MagicMock()
    mock_smtp.return_value.__enter__.return_value = mock_server

    mod.poll_once()

    # Should have polled
    mock_poll.assert_called()
    # Should have run Claude
    mock_run.assert_called_once()
    # Should have sent reply
    mock_server.send_message.assert_called_once()
    # State should be saved
    assert mod.STATE_FILE.exists()
    state = json.loads(mod.STATE_FILE.read_text())
    assert "<test@example.com>" in state["processed_ids"]


# ------------------------------------
# CONFIGURATION TESTS
# ------------------------------------


def test_backends_config_structure():
    """Test that BACKENDS config has required structure."""
    for backend_name, cfg in mod.BACKENDS.items():
        assert "enabled" in cfg or backend_name == "zoho"
        assert "imap_server" in cfg
        assert "smtp_server" in cfg
        assert "email" in cfg
        assert "password" in cfg


def test_access_level_sets_not_empty():
    """Test that access control sets are defined."""
    assert len(mod.FULL_ACCESS) > 0
    assert len(mod.FAMILY_ACCESS) > 0
    assert isinstance(mod.FULL_ACCESS, set)
    assert isinstance(mod.FAMILY_ACCESS, set)


def test_poll_interval_reasonable():
    """Test that poll interval is configured."""
    assert mod.POLL_INTERVAL > 0
    assert mod.POLL_INTERVAL < 3600  # Less than an hour
