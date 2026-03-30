"""
Multi-Provider Email Backend — Resilient email for Rudy.

Supports multiple email providers with automatic failover:
  1. Gmail (primary — when account recovered)
  2. Zoho Mail (free IMAP/SMTP, bot-friendly)
  3. Outlook (free IMAP/SMTP, reliable)
  4. Mailgun (API-based, for transactional)

Design:
  - Provider chain: try primary, fall through to backup on failure
  - Unified interface: send() and receive() work identically regardless of backend
  - Health tracking: monitors which providers are working
  - Auto-rotation: if one provider is rate-limited, switch to next
"""

import imaplib
import smtplib
import email
import json
import os

from dataclasses import dataclass
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from typing import List

from rudy.paths import RUDY_LOGS  # noqa: E402

LOGS = RUDY_LOGS
CONFIG_FILE = LOGS / "email-providers.json"
HEALTH_FILE = LOGS / "email-health.json"

@dataclass
class EmailProvider:
    name: str
    email: str
    password: str  # App password
    imap_host: str
    imap_port: int
    smtp_host: str
    smtp_port: int
    enabled: bool = True
    priority: int = 0  # Lower = higher priority
    daily_limit: int = 500
    use_tls: bool = True

    def to_dict(self):
        d = self.__dict__.copy()
        d["password"] = "***"  # Never log passwords
        return d

# ── Default provider configs ──────────────────────────────
DEFAULT_PROVIDERS = {
    "gmail": EmailProvider(
        name="gmail",
        email="rudy.ciminoassist@gmail.com",
        password="bviu yjdp tufr tnys",
        imap_host="imap.gmail.com",
        imap_port=993,
        smtp_host="smtp.gmail.com",
        smtp_port=587,
        priority=0,
        daily_limit=500,
    ),
    "zoho": EmailProvider(
        name="zoho",
        email="rudy.ciminoassistant@zoho.com",
        password="CMCPassTemp7508!",
        imap_host="imap.zoho.com",
        imap_port=993,
        smtp_host="smtp.zoho.com",
        smtp_port=587,
        priority=1,
        daily_limit=500,
        enabled=True,
    ),
    "outlook": EmailProvider(
        name="outlook",
        email="",  # To be configured: rudy.workhorse@outlook.com
        password="",
        imap_host="imap-mail.outlook.com",
        imap_port=993,
        smtp_host="smtp-mail.outlook.com",
        smtp_port=587,
        priority=2,
        daily_limit=300,
        enabled=False,
    ),
}

class EmailHealth:
    """Tracks provider health and send counts."""

    def __init__(self):
        self.data = self._load()

    def _load(self):
        if HEALTH_FILE.exists():
            try:
                with open(HEALTH_FILE) as f:
                    return json.load(f)
            except Exception:
                pass
        return {"providers": {}, "last_check": None}

    def _save(self):
        HEALTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(HEALTH_FILE, "w") as f:
            json.dump(self.data, f, indent=2, default=str)

    def record_send(self, provider_name: str, success: bool):
        today = datetime.now().strftime("%Y-%m-%d")
        if provider_name not in self.data["providers"]:
            self.data["providers"][provider_name] = {}
        p = self.data["providers"][provider_name]

        if p.get("date") != today:
            p["date"] = today
            p["sends_today"] = 0
            p["failures_today"] = 0

        if success:
            p["sends_today"] = p.get("sends_today", 0) + 1
            p["last_success"] = datetime.now().isoformat()
            p["consecutive_failures"] = 0
        else:
            p["failures_today"] = p.get("failures_today", 0) + 1
            p["consecutive_failures"] = p.get("consecutive_failures", 0) + 1
            p["last_failure"] = datetime.now().isoformat()

        self.data["last_check"] = datetime.now().isoformat()
        self._save()

    def is_healthy(self, provider_name: str) -> bool:
        p = self.data.get("providers", {}).get(provider_name, {})
        return p.get("consecutive_failures", 0) < 3

    def sends_remaining(self, provider_name: str, daily_limit: int) -> int:
        p = self.data.get("providers", {}).get(provider_name, {})
        today = datetime.now().strftime("%Y-%m-%d")
        if p.get("date") != today:
            return daily_limit
        return max(0, daily_limit - p.get("sends_today", 0))

    def get_summary(self) -> dict:
        return self.data

class MultiEmail:
    """
    Unified email interface with automatic failover.

    Usage:
        mailer = MultiEmail()
        mailer.send(
            to="ccimino2@gmail.com",
            subject="Test from Rudy",
            body="Hello from the multi-provider backend!"
        )
    """

    def __init__(self):
        self.providers = dict(DEFAULT_PROVIDERS)
        self.health = EmailHealth()
        self._load_config()

    def _load_config(self):
        """Load any saved provider overrides."""
        if CONFIG_FILE.exists():
            try:
                with open(CONFIG_FILE) as f:
                    config = json.load(f)
                for name, overrides in config.items():
                    if name in self.providers:
                        for k, v in overrides.items():
                            if hasattr(self.providers[name], k):
                                setattr(self.providers[name], k, v)
            except Exception:
                pass

    def _get_active_providers(self) -> List[EmailProvider]:
        """Get enabled providers sorted by priority, filtered by health."""
        active = [
            p for p in self.providers.values()
            if p.enabled and p.email and p.password
            and self.health.is_healthy(p.name)
            and self.health.sends_remaining(p.name, p.daily_limit) > 0
        ]
        return sorted(active, key=lambda p: p.priority)

    def send(self, to: str, subject: str, body: str,
             html: bool = False, attachments: List[str] = None,
             cc: str = None, bcc: str = None) -> dict:
        """
        Send an email using the best available provider.
        Returns: {"success": bool, "provider": str, "error": str}
        """
        providers = self._get_active_providers()
        if not providers:
            return {"success": False, "provider": None,
                    "error": "No active email providers configured"}

        last_error = None
        for provider in providers:
            try:
                self._send_via(provider, to, subject, body, html, attachments, cc, bcc)
                self.health.record_send(provider.name, True)
                return {"success": True, "provider": provider.name, "error": None}
            except Exception as e:
                last_error = str(e)
                self.health.record_send(provider.name, False)
                continue

        return {"success": False, "provider": None, "error": last_error}

    def _send_via(self, provider: EmailProvider, to: str, subject: str,
                  body: str, html: bool, attachments: List[str], cc: str, bcc: str):
        """Send via a specific provider."""
        msg = MIMEMultipart()
        msg["From"] = provider.email
        msg["To"] = to
        msg["Subject"] = subject
        if cc:
            msg["Cc"] = cc

        if html:
            msg.attach(MIMEText(body, "html"))
        else:
            msg.attach(MIMEText(body, "plain"))

        # Attachments
        if attachments:
            for filepath in attachments:
                path = Path(filepath)
                if path.exists():
                    part = MIMEBase("application", "octet-stream")
                    with open(path, "rb") as f:
                        part.set_payload(f.read())
                    encoders.encode_base64(part)
                    part.add_header("Content-Disposition", f"attachment; filename={path.name}")
                    msg.attach(part)

        # Send
        recipients = [to]
        if cc:
            recipients.append(cc)
        if bcc:
            recipients.append(bcc)

        with smtplib.SMTP(provider.smtp_host, provider.smtp_port) as server:
            if provider.use_tls:
                server.starttls()
            server.login(provider.email, provider.password)
            server.send_message(msg, to_addrs=recipients)

    def receive(self, folder: str = "INBOX", limit: int = 10,
                unread_only: bool = True) -> List[dict]:
        """
        Fetch emails from the best available provider.
        Returns list of email dicts.
        """
        providers = self._get_active_providers()
        for provider in providers:
            try:
                return self._receive_via(provider, folder, limit, unread_only)
            except Exception:
                continue
        return []

    def _receive_via(self, provider: EmailProvider, folder: str,
                     limit: int, unread_only: bool) -> List[dict]:
        """Fetch emails from a specific provider."""
        conn = imaplib.IMAP4_SSL(provider.imap_host, provider.imap_port)
        conn.login(provider.email, provider.password)
        conn.select(folder)

        criteria = "(UNSEEN)" if unread_only else "ALL"
        _, msg_ids = conn.search(None, criteria)

        emails = []
        ids = msg_ids[0].split()[-limit:] if msg_ids[0] else []

        for mid in ids:
            _, data = conn.fetch(mid, "(RFC822)")
            raw = data[0][1]
            msg = email.message_from_bytes(raw)

            body = ""
            if msg.is_multipart():
                for part in msg.walk():
                    if part.get_content_type() == "text/plain":
                        body = part.get_payload(decode=True).decode(errors="replace")
                        break
            else:
                body = msg.get_payload(decode=True).decode(errors="replace")

            emails.append({
                "from": msg.get("From", ""),
                "to": msg.get("To", ""),
                "subject": msg.get("Subject", ""),
                "date": msg.get("Date", ""),
                "body": body[:5000],
                "message_id": msg.get("Message-ID", ""),
            })

        conn.logout()
        return emails

    def test_all(self) -> dict:
        """Test all configured providers."""
        results = {}
        for name, provider in self.providers.items():
            if not provider.enabled or not provider.email:
                results[name] = {"status": "disabled"}
                continue

            # Test SMTP
            smtp_ok = False
            try:
                with smtplib.SMTP(provider.smtp_host, provider.smtp_port, timeout=10) as s:
                    if provider.use_tls:
                        s.starttls()
                    s.login(provider.email, provider.password)
                    smtp_ok = True
            except Exception as e:
                smtp_error = str(e)[:100]

            # Test IMAP
            imap_ok = False
            try:
                conn = imaplib.IMAP4_SSL(provider.imap_host, provider.imap_port)
                conn.login(provider.email, provider.password)
                conn.logout()
                imap_ok = True
            except Exception as e:
                imap_error = str(e)[:100]

            results[name] = {
                "status": "ok" if smtp_ok and imap_ok else "partial" if smtp_ok or imap_ok else "down",
                "smtp": "ok" if smtp_ok else smtp_error if not smtp_ok else "untested",
                "imap": "ok" if imap_ok else imap_error if not imap_ok else "untested",
            }

        return results

    def configure_provider(self, name: str, email_addr: str, password: str):
        """Configure a provider's credentials."""
        if name in self.providers:
            self.providers[name].email = email_addr
            self.providers[name].password = password
            self.providers[name].enabled = True

            # Save to config file
            config = {}
            if CONFIG_FILE.exists():
                try:
                    with open(CONFIG_FILE) as f:
                        config = json.load(f)
                except Exception:
                    pass

            config[name] = {"email": email_addr, "password": password, "enabled": True}
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(CONFIG_FILE, "w") as f:
                json.dump(config, f, indent=2)

    def get_status(self) -> dict:
        """Full status report."""
        return {
            "active_providers": [p.name for p in self._get_active_providers()],
            "all_providers": {n: p.to_dict() for n, p in self.providers.items()},
            "health": self.health.get_summary(),
        }

def quick_send(to: str, subject: str, body: str, **kwargs) -> dict:
    """One-liner email send."""
    return MultiEmail().send(to=to, subject=subject, body=body, **kwargs)

if __name__ == "__main__":
    mailer = MultiEmail()
    print("Multi-Provider Email Backend Status:")
    import json as _json
    print(_json.dumps(mailer.get_status(), indent=2, default=str))
    print("\nTesting providers...")
    print(_json.dumps(mailer.test_all(), indent=2))
