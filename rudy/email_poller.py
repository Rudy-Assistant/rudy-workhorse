"""
Rudy -- Email Poller v1.0
==========================
Polls for new emails using multiple backends:
  1. Zoho SMTP (sending only -- free plan has no IMAP)
  2. Outlook.com IMAP (free tier, recommended for receiving)
  3. Gmail API (if OAuth configured)

This replaces the IMAP IDLE listener for environments where
IMAP is unavailable (Zoho free plan limitation).

Usage:
    python -m rudy.email_poller              # Poll once
    python -m rudy.email_poller --daemon     # Continuous polling
    python -m rudy.email_poller --status     # Check backend health

Architecture:
    - Polls inbox every POLL_INTERVAL seconds
    - Tracks processed message IDs in state file
    - Routes to command handler (same as listener v2)
    - Sends replies via Zoho SMTP (working)
"""

import imaplib
import email
import email.header
import smtplib
import json
import time
import os
import sys
import logging
import traceback
from datetime import datetime
from email.mime.text import MIMEText

# ------------------------------------
# CONFIGURATION
# ------------------------------------

from rudy.paths import RUDY_LOGS, DESKTOP  # noqa: E402

LOG_DIR = RUDY_LOGS
LOG_DIR.mkdir(exist_ok=True)
STATE_FILE = LOG_DIR / "email-poller-state.json"

# Backend configs -- filled from env or defaults
BACKENDS = {
    "outlook": {
        "enabled": True,
        "imap_server": "imap-mail.outlook.com",
        "imap_port": 993,
        "smtp_server": "smtp-mail.outlook.com",
        "smtp_port": 587,
        "smtp_starttls": True,
        "email": os.environ.get("RUDY_OUTLOOK_EMAIL", ""),
        "password": os.environ.get("RUDY_OUTLOOK_PASSWORD", ""),
    },
    "zoho": {
        "enabled": True,
        "imap_server": "imap.zoho.com",
        "imap_port": 993,
        "smtp_server": "smtp.zoho.com",
        "smtp_port": 465,
        "smtp_starttls": False,
        "email": "rudy.ciminoassistant@zohomail.com",
        "password": os.environ.get("RUDY_APP_PASSWORD", "CMCPassTemp7508!"),
        "imap_available": False,  # Free plan -- SMTP only
    },
}

# Sending backend (Zoho works for SMTP)
SEND_BACKEND = "zoho"

# Receiving backend priority
RECEIVE_PRIORITY = ["outlook", "zoho"]

POLL_INTERVAL = 30  # seconds
MAX_PROCESS_PER_POLL = 5

# Permission tiers (same as listener v2)
FULL_ACCESS = {"ccimino2@gmail.com"}
FAMILY_ACCESS = {"lrcimino@yahoo.com"}

# ------------------------------------
# LOGGING
# ------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "email-poller.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("rudy.poller")


# ------------------------------------
# STATE MANAGEMENT
# ------------------------------------

def load_state():
    """Load processed message IDs and backend health."""
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {
        "processed_ids": [],
        "last_poll": None,
        "backend_health": {},
        "total_processed": 0,
    }


def save_state(state):
    """Persist state. Keep only last 500 message IDs."""
    state["processed_ids"] = state["processed_ids"][-500:]
    STATE_FILE.write_text(json.dumps(state, indent=2))


# ------------------------------------
# EMAIL HELPERS
# ------------------------------------

def decode_header_value(raw):
    if not raw:
        return ""
    parts = email.header.decode_header(raw)
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def extract_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                payload = part.get_payload(decode=True)
                if payload:
                    return payload.decode("utf-8", errors="replace")
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            return payload.decode("utf-8", errors="replace")
    return ""


def get_sender_email(msg):
    from_header = msg.get("From", "")
    if "<" in from_header and ">" in from_header:
        return from_header.split("<")[1].split(">")[0].strip().lower()
    return from_header.strip().lower()


def get_sender_name(msg):
    from_header = decode_header_value(msg.get("From", ""))
    if "<" in from_header:
        return from_header.split("<")[0].strip().strip('"')
    return from_header


def determine_access_level(sender_email):
    if sender_email in FULL_ACCESS:
        return "full"
    elif sender_email in FAMILY_ACCESS:
        return "family"
    return "unknown"


# ------------------------------------
# IMAP POLLING
# ------------------------------------

def poll_imap(backend_name):
    """Poll a single IMAP backend for unseen messages. Returns list of (uid, msg_bytes)."""
    cfg = BACKENDS.get(backend_name, {})
    if not cfg.get("enabled") or cfg.get("imap_available") is False:
        return []
    if not cfg.get("email") or not cfg.get("password"):
        return []

    try:
        mail = imaplib.IMAP4_SSL(cfg["imap_server"], cfg["imap_port"])
        mail.login(cfg["email"], cfg["password"])
        mail.select("INBOX")

        status, data = mail.search(None, "UNSEEN")
        if status != "OK":
            mail.logout()
            return []

        messages = []
        uids = data[0].split()
        for uid in uids[-MAX_PROCESS_PER_POLL:]:  # Limit per poll
            status, msg_data = mail.fetch(uid, "(RFC822)")
            if status == "OK" and msg_data[0]:
                messages.append((uid.decode(), msg_data[0][1]))

        mail.logout()
        log.info(f"[{backend_name}] Found {len(messages)} unseen messages")
        return messages

    except Exception as e:
        log.warning(f"[{backend_name}] IMAP poll failed: {e}")
        return []


# ------------------------------------
# SMTP SENDING
# ------------------------------------

def send_reply(to_addr, subject, body):
    """Send reply via configured SMTP backend."""
    cfg = BACKENDS.get(SEND_BACKEND, {})
    if not cfg:
        log.error("No send backend configured")
        return False

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"Re: {subject}"
    msg["From"] = cfg["email"]
    msg["To"] = to_addr

    try:
        if cfg.get("smtp_starttls"):
            with smtplib.SMTP(cfg["smtp_server"], cfg["smtp_port"], timeout=30) as server:
                server.starttls()
                server.login(cfg["email"], cfg["password"])
                server.send_message(msg)
        else:
            with smtplib.SMTP_SSL(cfg["smtp_server"], cfg["smtp_port"], timeout=30) as server:
                server.login(cfg["email"], cfg["password"])
                server.send_message(msg)

        log.info(f"Reply sent to {to_addr} via {SEND_BACKEND}")
        return True
    except Exception as e:
        log.error(f"SMTP send failed: {e}")
        return False


# ------------------------------------
# REQUEST PROCESSING
# ------------------------------------

def build_prompt(sender_name, sender_email, subject, body, access_level):
    """Build Claude prompt (same logic as listener v2)."""
    if access_level == "full":
        perms = "FULL ACCESS -- execute with maximum agency."
    elif access_level == "family":
        perms = "FAMILY ACCESS -- research, docs, Q&A only. No personal data."
    else:
        return None

    return (
        f"You are Rudy, the Cimino family AI assistant.\n\n"
        f"FROM: {sender_name} <{sender_email}>\n"
        f"SUBJECT: {subject}\n"
        f"ACCESS: {access_level.upper()}\n"
        f"PERMISSIONS: {perms}\n\n"
        f"REQUEST:\n{body}\n\n"
        f"Reply concisely. Sign off as -- Rudy"
    )


def run_claude(prompt):
    """Run headless Claude Code session."""
    import subprocess
    log.info("Launching Claude Code session...")
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=300,
            cwd=str(DESKTOP),
        )
        response = result.stdout.strip()
        if not response:
            response = "I processed your request but couldn't generate a response.\n\n-- Rudy"
        return response[:5000]
    except subprocess.TimeoutExpired:
        return "That request took too long. Try simplifying it?\n\n-- Rudy"
    except FileNotFoundError:
        return "Claude Code is temporarily unavailable.\n\n-- Rudy"
    except Exception as e:
        return f"Error: {e}\n\n-- Rudy"


def process_message(uid, msg_bytes, state):
    """Process a single email message."""
    msg_id = uid
    if msg_id in state["processed_ids"]:
        return

    msg = email.message_from_bytes(msg_bytes)
    real_id = msg.get("Message-ID", uid)
    if real_id in state["processed_ids"]:
        return

    sender_email = get_sender_email(msg)
    sender_name = get_sender_name(msg)
    subject = decode_header_value(msg.get("Subject", "(no subject)"))
    body = extract_body(msg).strip()

    log.info(f"Processing: {sender_name} <{sender_email}> -- {subject}")

    # Skip automated
    skip_patterns = ["noreply", "no-reply", "donotreply", "mailer-daemon",
                     "postmaster", "notifications", "updates@", "alert@"]
    if any(p in sender_email for p in skip_patterns) or not body:
        state["processed_ids"].append(real_id)
        return

    access_level = determine_access_level(sender_email)

    if access_level == "unknown":
        send_reply(sender_email, subject,
            f"Hi {sender_name},\n\n"
            "I'm Rudy, the Cimino family assistant. "
            "I don't have you on my approved contacts list.\n"
            "Please ask Chris to add you.\n\n-- Rudy"
        )
    else:
        prompt = build_prompt(sender_name, sender_email, subject, body, access_level)
        if prompt:
            reply = run_claude(prompt)
            send_reply(sender_email, subject, reply)

    # Log
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "from": sender_email,
        "subject": subject,
        "access_level": access_level,
        "body_preview": body[:200],
    }
    log_file = LOG_DIR / f"requests-{datetime.now().strftime('%Y-%m')}.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")

    state["processed_ids"].append(real_id)
    state["total_processed"] = state.get("total_processed", 0) + 1


# ------------------------------------
# MAIN POLL LOOP
# ------------------------------------

def poll_once():
    """Single poll cycle across all backends."""
    state = load_state()

    for backend in RECEIVE_PRIORITY:
        try:
            messages = poll_imap(backend)
            if messages:
                state["backend_health"][backend] = {
                    "status": "ok",
                    "last_success": datetime.now().isoformat(),
                }
                for uid, msg_bytes in messages:
                    process_message(uid, msg_bytes, state)
                break  # Got messages from this backend, skip others
            else:
                state["backend_health"][backend] = {
                    "status": "ok",
                    "last_success": datetime.now().isoformat(),
                    "note": "no new messages",
                }
        except Exception as e:
            state["backend_health"][backend] = {
                "status": "error",
                "error": str(e)[:200],
                "last_error": datetime.now().isoformat(),
            }

    state["last_poll"] = datetime.now().isoformat()
    save_state(state)


def daemon():
    """Continuous polling loop with exponential backoff on errors."""
    log.info("Email poller daemon starting...")
    backoff = POLL_INTERVAL
    consecutive_errors = 0

    while True:
        try:
            poll_once()
            consecutive_errors = 0
            backoff = POLL_INTERVAL
        except Exception as e:
            consecutive_errors += 1
            backoff = min(backoff * 2, 300)
            log.error(f"Poll error (#{consecutive_errors}): {e}")
            log.debug(traceback.format_exc())

        time.sleep(backoff)


def status():
    """Print backend health status."""
    state = load_state()
    print(f"Last poll: {state.get('last_poll', 'never')}")
    print(f"Total processed: {state.get('total_processed', 0)}")
    print(f"Tracked message IDs: {len(state.get('processed_ids', []))}")
    for name, health in state.get("backend_health", {}).items():
        print(f"  {name}: {health.get('status', 'unknown')} - {health.get('note', health.get('error', ''))}")

    # Check backend configs
    for name, cfg in BACKENDS.items():
        has_creds = bool(cfg.get("email")) and bool(cfg.get("password"))
        imap_ok = cfg.get("imap_available", True)
        print(f"  {name} config: creds={'yes' if has_creds else 'MISSING'}, imap={'yes' if imap_ok else 'no (SMTP only)'}")


# ------------------------------------
# CLI
# ------------------------------------

if __name__ == "__main__":
    if "--daemon" in sys.argv:
        daemon()
    elif "--status" in sys.argv:
        status()
    else:
        poll_once()
        print("Poll complete.")
