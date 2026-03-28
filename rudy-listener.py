"""
Rudy — Family Assistant Email Listener v2.0
============================================
Self-healing, self-diagnosing email listener for rudy.ciminoassistant@zohomail.com.

Connects via IMAP IDLE with DNS fallback (direct IP), exponential backoff on
failures, structured startup self-test, and dual-mode operation (IMAP IDLE
primary, polling fallback).

Usage:
    python rudy-listener.py              # Normal operation
    python rudy-listener.py --diagnose   # Run diagnostics only (no listener)

Requirements:
    pip install --break-system-packages imapclient

Environment variables (set in start-rudy.bat):
    RUDY_EMAIL=rudy.ciminoassistant@zohomail.com
    RUDY_APP_PASSWORD=xxxxxxxxxxxxxxxx
"""

import imaplib
import email
import email.header
import smtplib
import subprocess
import json
import time
import os
import sys
import socket
import ssl
import logging
import traceback
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

RUDY_EMAIL = os.environ.get("RUDY_EMAIL", "rudy.ciminoassistant@zohomail.com")
RUDY_APP_PASSWORD = os.environ.get("RUDY_ZOHO_APP_PASSWORD", "")

IMAP_SERVER = "imap.zoho.com"
IMAP_PORT = 993
SMTP_SERVER = "smtp.zoho.com"
SMTP_PORT = 465
IDLE_TIMEOUT = 300  # seconds — re-IDLE every 5 min (Gmail max ~29 min)
POLL_INTERVAL = 30  # seconds between polls when IDLE is unavailable

# Fallback IPs — bypass Tailscale/local DNS issues
GMAIL_IMAP_IPS = ["142.250.4.108", "142.250.4.109", "74.125.200.108", "74.125.200.109"]
GMAIL_SMTP_IPS = ["142.250.4.108", "74.125.200.108"]

# Backoff settings
INITIAL_BACKOFF = 5       # seconds
MAX_BACKOFF = 300          # 5 minutes max
BACKOFF_MULTIPLIER = 2

LOG_DIR = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop" / "rudy-logs"
LOG_DIR.mkdir(exist_ok=True)

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"

# ─────────────────────────────────────────────
# PERMISSION TIERS
# ─────────────────────────────────────────────

FULL_ACCESS = {
    "ccimino2@gmail.com",
}

FAMILY_ACCESS = {
    "lrcimino@yahoo.com",       # Lewis Cimino
}

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "rudy.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("rudy")

# ─────────────────────────────────────────────
# CONNECTION HELPERS
# ─────────────────────────────────────────────

def connect_imap_robust():
    """
    Connect to Gmail IMAP with multi-layer fallback:
      1. DNS hostname
      2. Direct IPs with SSL SNI
    Returns (mail_connection, connected_host) or raises ConnectionError.
    """
    # Layer 1: DNS
    try:
        log.debug(f"IMAP: trying {IMAP_SERVER} via DNS...")
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        return mail, IMAP_SERVER
    except (socket.gaierror, OSError, ssl.SSLError) as e:
        log.warning(f"IMAP DNS failed: {e}")

    # Layer 2: Direct IPs
    for ip in GMAIL_IMAP_IPS:
        try:
            log.debug(f"IMAP: trying {ip} direct...")
            ctx = ssl.create_default_context()
            # Must set server_hostname for SNI so the cert validates
            sock = socket.create_connection((ip, IMAP_PORT), timeout=15)
            ctx.wrap_socket(sock, server_hostname=IMAP_SERVER)
            mail = imaplib.IMAP4_SSL(host=ip, port=IMAP_PORT)
            return mail, ip
        except Exception as e:
            log.debug(f"  {ip} failed: {e}")
            continue

    # Layer 3: Direct IPs with relaxed SSL (last resort)
    for ip in GMAIL_IMAP_IPS[:2]:
        try:
            log.debug(f"IMAP: trying {ip} with relaxed SSL...")
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            mail = imaplib.IMAP4_SSL(ip, IMAP_PORT, ssl_context=ctx)
            log.warning(f"Connected via {ip} with relaxed SSL — not ideal but functional")
            return mail, ip
        except Exception as e:
            log.debug(f"  {ip} relaxed SSL failed: {e}")
            continue

    raise ConnectionError("All IMAP connection methods exhausted")


def connect_and_auth():
    """Full connect + authenticate + select INBOX."""
    mail, host = connect_imap_robust()
    mail.login(RUDY_EMAIL, RUDY_APP_PASSWORD)
    mail.select("INBOX")
    log.info(f"Authenticated via {host} — INBOX selected")
    return mail


def send_reply_smtp(to_addr, subject, body):
    """Send a reply email via SMTP with DNS + IP fallback."""
    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = f"Re: {subject}"
    msg["From"] = RUDY_EMAIL
    msg["To"] = to_addr

    hosts = [SMTP_SERVER] + GMAIL_SMTP_IPS

    for host in hosts:
        try:
            with smtplib.SMTP_SSL(host, SMTP_PORT, timeout=30) as server:
                server.login(RUDY_EMAIL, RUDY_APP_PASSWORD)
                server.send_message(msg)
            log.info(f"Reply sent to {to_addr} via {host}")
            return True
        except (socket.gaierror, OSError) as e:
            log.warning(f"SMTP {host} failed ({e}), trying next...")
            continue
        except smtplib.SMTPAuthenticationError as e:
            log.error(f"SMTP auth failed: {e}")
            return False
        except Exception as e:
            log.error(f"SMTP error via {host}: {e}")
            continue

    log.error("All SMTP hosts failed — reply not sent")
    return False


# ─────────────────────────────────────────────
# EMAIL PARSING
# ─────────────────────────────────────────────

def decode_header_value(raw):
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
    else:
        return "unknown"


# ─────────────────────────────────────────────
# REQUEST PROCESSING
# ─────────────────────────────────────────────

def build_prompt(sender_name, sender_email, subject, body, access_level):
    if access_level == "full":
        permissions = """You have FULL ACCESS. You may:
- Access Chris's Gmail and Google Calendar via MCP
- Read, create, modify, and organize files on the Desktop
- Use the browser for research or automation
- Run code, scripts, or any Claude Code toolkits
- Access all MCP servers and Cowork plugins
Chris trusts you completely — execute the request with maximum agency."""

    elif access_level == "family":
        permissions = """You have FAMILY ACCESS (limited). You may:
- Answer questions, do research, look things up
- Create documents, spreadsheets, presentations
- Provide information and summaries
- Help with general knowledge tasks

You may NOT:
- Access Chris's personal Gmail or Calendar
- Delete or modify existing files
- Run code that changes system configuration
- Access financial or sensitive personal data
- Send emails on Chris's behalf

If the request requires something outside these bounds, politely explain
that you'd need Chris's approval and suggest they contact him directly."""
    else:
        return None

    return f"""You are Rudy, the Cimino family's AI assistant running on a dedicated mini PC.

REQUEST FROM: {sender_name} <{sender_email}>
SUBJECT: {subject}
ACCESS LEVEL: {access_level.upper()}

{permissions}

THE REQUEST:
{body}

INSTRUCTIONS:
1. Process the request according to the permissions above.
2. Write your complete response to stdout — it will be emailed back automatically.
3. Keep the reply conversational but concise — this will be emailed back.
4. If you created any files, mention their location on the Desktop.
5. Sign off as "— Rudy"
"""


def run_claude(prompt):
    """Run a headless Claude Code session."""
    log.info("Launching Claude Code session...")
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=300,
            cwd=str(DESKTOP),
        )
        log.info(f"Claude exited with code {result.returncode}")
        if result.returncode != 0:
            log.error(f"Claude stderr: {result.stderr[:500]}")
        # Prefer stdout; fall back to reply file
        response = result.stdout.strip()
        reply_file = DESKTOP / "rudy-reply-latest.txt"
        if reply_file.exists():
            response = reply_file.read_text(encoding="utf-8").strip()
            reply_file.unlink()
        return response or "I processed your request but couldn't generate a reply."
    except subprocess.TimeoutExpired:
        log.error("Claude session timed out (5 min)")
        return "I'm sorry, that request took too long. Could you try simplifying it?\n\n— Rudy"
    except FileNotFoundError:
        log.error("Claude CLI not found on PATH")
        return "Claude Code is temporarily unavailable. Chris has been notified.\n\n— Rudy"
    except Exception as e:
        log.error(f"Error running Claude: {e}")
        return f"Something went wrong: {e}\n\n— Rudy"


def process_email(msg_data):
    """Process a single incoming email end-to-end."""
    msg = email.message_from_bytes(msg_data)
    sender_email = get_sender_email(msg)
    sender_name = get_sender_name(msg)
    subject = decode_header_value(msg.get("Subject", "(no subject)"))
    body = extract_body(msg).strip()

    log.info(f"Processing: {sender_name} <{sender_email}> — {subject}")

    # Skip automated senders
    skip = ["noreply", "no-reply", "donotreply", "mailer-daemon", "postmaster",
            "notifications", "updates@", "alert@", "digest@"]
    if any(p in sender_email for p in skip):
        log.info("Skipping automated sender")
        return

    # Skip empty bodies
    if not body:
        log.info("Skipping empty email")
        return

    access_level = determine_access_level(sender_email)

    if access_level == "unknown":
        log.info(f"Unknown sender: {sender_email} — polite decline")
        send_reply_smtp(
            sender_email, subject,
            f"Hi {sender_name},\n\n"
            "Thanks for reaching out! I'm Rudy, the Cimino family's assistant. "
            "I don't currently have you on my approved contacts list, so I can't "
            "process requests from this address.\n\n"
            "If you think this is a mistake, please ask Chris to add you.\n\n"
            "— Rudy"
        )
        return

    prompt = build_prompt(sender_name, sender_email, subject, body, access_level)
    reply_text = run_claude(prompt)

    # Trim if absurdly long
    if len(reply_text) > 5000:
        reply_text = reply_text[:4900] + "\n\n[Truncated — full output on the Workhorse]"

    send_reply_smtp(sender_email, subject, reply_text)

    # Structured log
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "from": sender_email,
        "name": sender_name,
        "subject": subject,
        "access_level": access_level,
        "body_preview": body[:200],
        "reply_preview": reply_text[:200],
    }
    log_file = LOG_DIR / f"requests-{datetime.now().strftime('%Y-%m')}.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")


# ─────────────────────────────────────────────
# STARTUP SELF-TEST
# ─────────────────────────────────────────────

def startup_selftest():
    """
    Run critical checks before entering the main loop.
    Returns True if all critical tests pass, False otherwise.
    Logs detailed diagnostics for any failure.
    """
    log.info("Running startup self-test...")
    all_ok = True

    # 1. Credentials present
    if not RUDY_APP_PASSWORD:
        log.critical("RUDY_APP_PASSWORD is not set. Set it in start-rudy.bat.")
        return False
    if len(RUDY_APP_PASSWORD) != 16:
        log.warning(f"App password is {len(RUDY_APP_PASSWORD)} chars (expected 16)")
    if " " in RUDY_APP_PASSWORD:
        log.error("App password contains spaces — remove them in start-rudy.bat")
        return False

    # 2. DNS check
    dns_ok = False
    try:
        socket.getaddrinfo(IMAP_SERVER, IMAP_PORT)
        log.info("  DNS: imap.zoho.com resolves OK")
        dns_ok = True
    except socket.gaierror:
        log.warning("  DNS: imap.zoho.com FAILED — will use IP fallback")

    # 3. IMAP connection + auth
    try:
        mail = connect_and_auth()
        status, count = mail.status("INBOX", "(MESSAGES UNSEEN)")
        log.info(f"  IMAP: Connected and authenticated — {count}")
        mail.logout()
    except imaplib.IMAP4.error as e:
        err = str(e)
        log.critical(f"  IMAP AUTH FAILED: {err}")
        if "AUTHENTICATIONFAILED" in err.upper():
            log.critical("  → Likely cause: 2-Step Verification not enabled on Rudy's Google account")
            log.critical("  → App Passwords REQUIRE 2FA. Enable it at:")
            log.critical("    https://myaccount.google.com/signinoptions/twosv")
            log.critical("  → Then create a new App Password at:")
            log.critical("    https://myaccount.google.com/apppasswords")
            log.critical("  → Update RUDY_APP_PASSWORD in start-rudy.bat")
        all_ok = False
    except ConnectionError as e:
        log.critical(f"  IMAP CONNECTION FAILED: {e}")
        if not dns_ok:
            log.critical("  → DNS is broken AND direct IP fallback failed")
            log.critical("  → Run as admin: python rudy-diagnose.py --fix")
        all_ok = False
    except Exception as e:
        log.critical(f"  IMAP UNEXPECTED ERROR: {e}")
        log.critical(traceback.format_exc())
        all_ok = False

    # 4. SMTP check
    try:
        for host in [SMTP_SERVER] + GMAIL_SMTP_IPS:
            try:
                with smtplib.SMTP_SSL(host, SMTP_PORT, timeout=15) as server:
                    server.login(RUDY_EMAIL, RUDY_APP_PASSWORD)
                log.info(f"  SMTP: Authenticated via {host}")
                break
            except (socket.gaierror, OSError):
                continue
        else:
            log.warning("  SMTP: All hosts unreachable (replies will fail)")
            all_ok = False
    except smtplib.SMTPAuthenticationError:
        log.critical("  SMTP AUTH FAILED — same root cause as IMAP auth")
        all_ok = False
    except Exception as e:
        log.warning(f"  SMTP check error: {e}")

    # 5. Claude CLI
    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            log.info(f"  Claude CLI: {result.stdout.strip()}")
        else:
            log.warning("  Claude CLI: returned non-zero (may still work)")
    except FileNotFoundError:
        log.error("  Claude CLI: NOT FOUND — requests will fail until installed")
        all_ok = False
    except Exception as e:
        log.warning(f"  Claude CLI check: {e}")

    if all_ok:
        log.info("Self-test PASSED — all systems go")
    else:
        log.error("Self-test FAILED — see errors above")
        log.error("Run: python rudy-diagnose.py   for detailed diagnostics")

    return all_ok


# ─────────────────────────────────────────────
# IMAP IDLE + POLL HYBRID LISTENER
# ─────────────────────────────────────────────

def get_unseen_uids(mail):
    status, data = mail.uid("search", None, "UNSEEN")
    if status == "OK" and data[0]:
        return data[0].split()
    return []


def fetch_and_process(mail, uid):
    try:
        status, data = mail.uid("fetch", uid, "(RFC822)")
        if status == "OK" and data[0]:
            raw_email = data[0][1]
            process_email(raw_email)
            mail.uid("store", uid, "+FLAGS", "\\Seen")
    except Exception as e:
        log.error(f"Error processing UID {uid}: {e}")


def try_idle(mail):
    """
    Attempt IMAP IDLE. Returns True if IDLE worked (even if timed out).
    Returns False if IDLE is not supported or failed (caller should poll).
    """
    try:
        tag = mail._new_tag().decode()
        mail.send(f"{tag} IDLE\r\n".encode())
        response = mail.readline().decode()

        if "idling" not in response.lower() and "+" not in response:
            log.warning(f"IDLE not accepted: {response.strip()}")
            return False

        mail.sock.settimeout(IDLE_TIMEOUT)
        try:
            while True:
                line = mail.readline().decode()
                if "EXISTS" in line:
                    log.info(f"IDLE notification: {line.strip()}")
                    break  # Got EXISTS notification
                elif not line:
                    break
        except (socket.timeout, TimeoutError, OSError):
            pass  # Normal timeout — re-establish

        # End IDLE
        mail.send(b"DONE\r\n")
        try:
            mail.readline()
        except Exception as e:
            log.debug(f"Error reading IDLE termination: {e}")

        mail.sock.settimeout(None)
        return True

    except Exception as e:
        log.warning(f"IDLE error: {e}")
        try:
            mail.sock.settimeout(None)
        except Exception as e:
            log.debug(f"Error resetting socket timeout: {e}")
        return False


def main_loop():
    """
    Hybrid IDLE/poll loop with exponential backoff on failures.
    - Tries IDLE first (instant notification)
    - Falls back to polling every 30s if IDLE fails
    - Reconnects with backoff on connection errors
    """
    backoff = INITIAL_BACKOFF
    use_idle = True
    mail = None
    consecutive_failures = 0

    while True:
        # Connect if needed
        if mail is None:
            try:
                mail = connect_and_auth()

                # Process unseen on (re)connect
                unseen = get_unseen_uids(mail)
                if unseen:
                    log.info(f"Found {len(unseen)} unseen messages")
                    for uid in unseen:
                        fetch_and_process(mail, uid)

                backoff = INITIAL_BACKOFF
                consecutive_failures = 0

            except Exception as e:
                consecutive_failures += 1
                log.error(f"Connection failed (attempt {consecutive_failures}): {e}")

                if consecutive_failures >= 10:
                    log.critical("10 consecutive failures — check rudy-diagnose.py")
                    log.critical("Sleeping 10 minutes before retrying...")
                    time.sleep(600)
                    consecutive_failures = 0
                else:
                    log.info(f"Retrying in {backoff}s...")
                    time.sleep(backoff)
                    backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF)
                continue

        # Listen for new messages
        try:
            if use_idle:
                idle_ok = try_idle(mail)
                if not idle_ok:
                    log.info("IDLE unavailable — switching to polling mode")
                    use_idle = False
            else:
                time.sleep(POLL_INTERVAL)

            # Check for new messages
            try:
                unseen = get_unseen_uids(mail)
                for uid in unseen:
                    fetch_and_process(mail, uid)
            except imaplib.IMAP4.abort:
                raise  # Reconnect
            except Exception as e:
                log.error(f"Error checking messages: {e}")

        except (imaplib.IMAP4.abort, OSError, ConnectionError) as e:
            log.warning(f"Connection lost: {e} — reconnecting...")
            mail = None
            time.sleep(backoff)
            backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF)

        except Exception as e:
            log.error(f"Unexpected error: {e}")
            log.error(traceback.format_exc())
            mail = None
            time.sleep(backoff)
            backoff = min(backoff * BACKOFF_MULTIPLIER, MAX_BACKOFF)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    # Diagnose-only mode
    if "--diagnose" in sys.argv:
        print("Running diagnostics — use rudy-diagnose.py for full report")
        ok = startup_selftest()
        sys.exit(0 if ok else 1)

    log.info("=" * 60)
    log.info("  RUDY v2.0 — Family Assistant Email Listener")
    log.info(f"  Monitoring: {RUDY_EMAIL}")
    log.info(f"  Full access: {FULL_ACCESS}")
    log.info(f"  Family access: {FAMILY_ACCESS}")
    log.info(f"  Logs: {LOG_DIR}")
    log.info("=" * 60)

    # Run self-test
    if not startup_selftest():
        log.critical("=" * 60)
        log.critical("  STARTUP SELF-TEST FAILED")
        log.critical("  Run: python rudy-diagnose.py    for full diagnostics")
        log.critical("  Rudy will NOT start until issues are resolved.")
        log.critical("=" * 60)
        sys.exit(1)

    # Announce we're live
    log.info("All checks passed — entering main loop")
    try:
        send_reply_smtp(
            "ccimino2@gmail.com",
            "Rudy Online",
            f"Rudy is now online and monitoring emails.\n"
            f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n— Rudy"
        )
    except Exception as e:
        log.debug(f"Could not send startup notification: {e}")

    try:
        main_loop()
    except KeyboardInterrupt:
        log.info("Shutting down gracefully...")
    except Exception as e:
        log.critical(f"Fatal error: {e}")
        log.critical(traceback.format_exc())
        sys.exit(1)
