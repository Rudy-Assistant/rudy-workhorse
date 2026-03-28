"""
Rudy — Gmail API Listener (IMAP-free alternative)
===================================================
Uses Google's Gmail API over HTTPS instead of IMAP. This avoids:
  - DNS resolution issues (Tailscale interference)
  - App Password authentication issues
  - IMAP IDLE complexity

Setup (one-time):
    1. Run: python rudy-gmail-api.py --setup
       This opens a browser to create Google Cloud credentials.
    2. Follow the prompts to authorize Rudy's Gmail account.
    3. Run: python rudy-gmail-api.py
       Normal operation — polls every 15 seconds via HTTPS.

Requirements:
    pip install --break-system-packages google-auth-oauthlib google-api-python-client
"""

import os
import sys
import json
import time
import base64
import logging
import subprocess
import traceback
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText

# ─────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────

RUDY_EMAIL = "rudy.ciminoassist@gmail.com"
POLL_INTERVAL = 15  # seconds

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOG_DIR = DESKTOP / "rudy-logs"
LOG_DIR.mkdir(exist_ok=True)
CREDS_DIR = DESKTOP / "rudy-config"
CREDS_DIR.mkdir(exist_ok=True)

TOKEN_FILE = CREDS_DIR / "token.json"
CLIENT_SECRET_FILE = CREDS_DIR / "client_secret.json"

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
    "https://www.googleapis.com/auth/gmail.modify",
]

FULL_ACCESS = {"ccimino2@gmail.com"}
FAMILY_ACCESS = {"lrcimino@yahoo.com"}

# ─────────────────────────────────────────────
# LOGGING
# ─────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "rudy-api.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("rudy-api")

# ─────────────────────────────────────────────
# GOOGLE API AUTH
# ─────────────────────────────────────────────

def get_gmail_service():
    """Authenticate and return a Gmail API service object."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    creds = None

    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            log.info("Refreshing expired token...")
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET_FILE.exists():
                log.critical(f"No client_secret.json found at {CLIENT_SECRET_FILE}")
                log.critical("Run: python rudy-gmail-api.py --setup")
                sys.exit(1)

            flow = InstalledAppFlow.from_client_secrets_file(
                str(CLIENT_SECRET_FILE), SCOPES
            )
            creds = flow.run_local_server(port=0)

        # Save token for next run
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())
        log.info("Token saved")

    return build("gmail", "v1", credentials=creds)


# ─────────────────────────────────────────────
# SETUP WIZARD
# ─────────────────────────────────────────────

def run_setup():
    """Guide user through Google Cloud project + OAuth setup."""
    print()
    print("=" * 60)
    print("  RUDY Gmail API Setup Wizard")
    print("=" * 60)
    print()
    print("This replaces the IMAP listener with Google's Gmail API.")
    print("You need a Google Cloud project with Gmail API enabled.")
    print()
    print("STEP 1: Create a Google Cloud project")
    print("  → Go to: https://console.cloud.google.com/projectcreate")
    print("  → Name it: 'Rudy Family Assistant'")
    print()
    print("STEP 2: Enable the Gmail API")
    print("  → Go to: https://console.cloud.google.com/apis/library/gmail.googleapis.com")
    print("  → Click 'Enable'")
    print()
    print("STEP 3: Create OAuth credentials")
    print("  → Go to: https://console.cloud.google.com/apis/credentials")
    print("  → Click 'Create Credentials' → 'OAuth client ID'")
    print("  → Application type: 'Desktop app'")
    print("  → Name: 'Rudy'")
    print("  → Download the JSON file")
    print()
    print("STEP 4: Configure consent screen")
    print("  → Go to: https://console.cloud.google.com/apis/credentials/consent")
    print("  → Choose 'External' → Create")
    print("  → App name: 'Rudy', email: your email")
    print("  → Add scopes: Gmail API (all)")
    print("  → Add test user: rudy.ciminoassist@gmail.com")
    print()
    print("STEP 5: Save the downloaded JSON as:")
    print(f"  {CLIENT_SECRET_FILE}")
    print()

    if CLIENT_SECRET_FILE.exists():
        print("client_secret.json found! Proceeding with authorization...")
        print()
        try:
            service = get_gmail_service()
            profile = service.users().getProfile(userId="me").execute()
            print(f"Authorized as: {profile['emailAddress']}")
            print(f"Messages: {profile['messagesTotal']}")
            print()
            print("Setup complete! Run: python rudy-gmail-api.py")
        except Exception as e:
            print(f"Authorization failed: {e}")
            print("Check that client_secret.json is correct and try again.")
    else:
        print("Waiting for client_secret.json...")
        print("Once you've completed steps 1-5, run this setup again.")


# ─────────────────────────────────────────────
# EMAIL PROCESSING (same logic as IMAP version)
# ─────────────────────────────────────────────

def determine_access_level(sender_email):
    if sender_email in FULL_ACCESS:
        return "full"
    elif sender_email in FAMILY_ACCESS:
        return "family"
    return "unknown"


def build_prompt(sender_name, sender_email, subject, body, access_level):
    if access_level == "full":
        permissions = """You have FULL ACCESS. You may:
- Access Chris's Gmail and Google Calendar via MCP
- Read, create, modify, and organize files on the Desktop
- Use the browser for research or automation
- Run code, scripts, or any Claude Code toolkits
Chris trusts you completely — execute the request with maximum agency."""
    elif access_level == "family":
        permissions = """You have FAMILY ACCESS (limited). You may:
- Answer questions, do research, look things up
- Create documents, spreadsheets, presentations
- Provide information and summaries

You may NOT:
- Access Chris's personal Gmail or Calendar
- Delete or modify existing files
- Access financial or sensitive personal data
- Send emails on Chris's behalf"""
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
3. Keep the reply conversational but concise.
4. If you created any files, mention their location on the Desktop.
5. Sign off as "— Rudy"
"""


def run_claude(prompt):
    log.info("Launching Claude Code session...")
    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "text"],
            capture_output=True, text=True, timeout=300, cwd=str(DESKTOP),
        )
        log.info(f"Claude exited: {result.returncode}")
        reply_file = DESKTOP / "rudy-reply-latest.txt"
        if reply_file.exists():
            resp = reply_file.read_text(encoding="utf-8").strip()
            reply_file.unlink()
            return resp
        return result.stdout.strip() or "I processed your request.\n\n— Rudy"
    except subprocess.TimeoutExpired:
        return "That request took too long. Could you simplify it?\n\n— Rudy"
    except FileNotFoundError:
        return "Claude Code is temporarily unavailable.\n\n— Rudy"
    except Exception as e:
        return f"Something went wrong: {e}\n\n— Rudy"


def process_message(service, msg_id):
    """Fetch and process a single Gmail message by ID."""
    msg = service.users().messages().get(
        userId="me", id=msg_id, format="full"
    ).execute()

    headers = {h["name"].lower(): h["value"] for h in msg["payload"]["headers"]}
    sender_full = headers.get("from", "")
    subject = headers.get("subject", "(no subject)")

    # Parse sender
    if "<" in sender_full:
        sender_name = sender_full.split("<")[0].strip().strip('"')
        sender_email = sender_full.split("<")[1].split(">")[0].strip().lower()
    else:
        sender_name = sender_full
        sender_email = sender_full.strip().lower()

    log.info(f"Processing: {sender_name} <{sender_email}> — {subject}")

    # Skip automated
    skip = ["noreply", "no-reply", "donotreply", "mailer-daemon", "notifications"]
    if any(p in sender_email for p in skip):
        log.info("Skipping automated sender")
        return

    # Extract body
    body = ""
    payload = msg["payload"]
    if "parts" in payload:
        for part in payload["parts"]:
            if part["mimeType"] == "text/plain" and "data" in part.get("body", {}):
                body = base64.urlsafe_b64decode(part["body"]["data"]).decode("utf-8", errors="replace")
                break
    elif "body" in payload and "data" in payload["body"]:
        body = base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    body = body.strip()
    if not body:
        log.info("Empty body — skipping")
        return

    access_level = determine_access_level(sender_email)

    if access_level == "unknown":
        reply_text = (
            f"Hi {sender_name},\n\n"
            "Thanks for reaching out! I'm Rudy, the Cimino family's assistant. "
            "I don't have you on my approved contacts list.\n\n"
            "If you think this is a mistake, please ask Chris to add you.\n\n"
            "— Rudy"
        )
    else:
        prompt = build_prompt(sender_name, sender_email, subject, body, access_level)
        reply_text = run_claude(prompt)

    # Trim
    if len(reply_text) > 5000:
        reply_text = reply_text[:4900] + "\n\n[Truncated]"

    # Send reply via Gmail API
    reply_msg = MIMEText(reply_text, "plain", "utf-8")
    reply_msg["To"] = sender_email
    reply_msg["From"] = RUDY_EMAIL
    reply_msg["Subject"] = f"Re: {subject}"
    # Thread the reply
    reply_msg["In-Reply-To"] = headers.get("message-id", "")
    reply_msg["References"] = headers.get("message-id", "")

    raw = base64.urlsafe_b64encode(reply_msg.as_bytes()).decode()
    send_body = {"raw": raw}
    if "threadId" in msg:
        send_body["threadId"] = msg["threadId"]

    service.users().messages().send(userId="me", body=send_body).execute()
    log.info(f"Reply sent to {sender_email}")

    # Mark as read
    service.users().messages().modify(
        userId="me", id=msg_id,
        body={"removeLabelIds": ["UNREAD"]}
    ).execute()

    # Log
    log_entry = {
        "timestamp": datetime.now().isoformat(),
        "from": sender_email,
        "subject": subject,
        "access_level": access_level,
        "body_preview": body[:200],
        "reply_preview": reply_text[:200],
    }
    log_file = LOG_DIR / f"requests-{datetime.now().strftime('%Y-%m')}.jsonl"
    with open(log_file, "a", encoding="utf-8") as f:
        f.write(json.dumps(log_entry) + "\n")


# ─────────────────────────────────────────────
# MAIN POLL LOOP
# ─────────────────────────────────────────────

def poll_loop(service):
    """Poll for unread messages every POLL_INTERVAL seconds."""
    log.info(f"Polling every {POLL_INTERVAL}s for new messages...")

    while True:
        try:
            # Get unread messages in INBOX
            results = service.users().messages().list(
                userId="me",
                labelIds=["INBOX", "UNREAD"],
                maxResults=10,
            ).execute()

            messages = results.get("messages", [])
            if messages:
                log.info(f"Found {len(messages)} unread message(s)")
                for msg_meta in messages:
                    try:
                        process_message(service, msg_meta["id"])
                    except Exception as e:
                        log.error(f"Error processing {msg_meta['id']}: {e}")

        except Exception as e:
            log.error(f"Poll error: {e}")
            # Re-auth if token expired
            if "invalid_grant" in str(e).lower() or "expired" in str(e).lower():
                log.info("Token expired — re-authenticating...")
                if TOKEN_FILE.exists():
                    TOKEN_FILE.unlink()
                service = get_gmail_service()

        time.sleep(POLL_INTERVAL)


# ─────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────

if __name__ == "__main__":
    if "--setup" in sys.argv:
        run_setup()
        sys.exit(0)

    log.info("=" * 60)
    log.info("  RUDY v2.0 — Gmail API Listener")
    log.info(f"  Monitoring: {RUDY_EMAIL}")
    log.info(f"  Poll interval: {POLL_INTERVAL}s")
    log.info("=" * 60)

    try:
        service = get_gmail_service()
        profile = service.users().getProfile(userId="me").execute()
        log.info(f"Authenticated as: {profile['emailAddress']}")
    except Exception as e:
        log.critical(f"Auth failed: {e}")
        log.critical("Run: python rudy-gmail-api.py --setup")
        sys.exit(1)

    try:
        poll_loop(service)
    except KeyboardInterrupt:
        log.info("Shutting down...")
    except Exception as e:
        log.critical(f"Fatal: {e}")
        log.critical(traceback.format_exc())
        sys.exit(1)
