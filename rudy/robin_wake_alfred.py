"""Robin Wake Alfred -- Close the autonomy feedback loop.

The #1 architectural gap in the Batcave: Robin could write to alfred-inbox
all day, but nothing actually wakes Alfred up. Messages pile up unread.

This module gives Robin the ability to:
  1. Send an email to Batman saying "Robin has work for Alfred"
  2. Open the Claude desktop app on Oracle to start a new session
  3. Track wake attempts to avoid spamming (cooldown period)

Called from bridge_runner.py when:
  - Alfred has been offline > WAKE_THRESHOLD_MINUTES
  - There are pending items in alfred-inbox or night shift findings
  - Robin hasn't sent a wake in the last COOLDOWN_MINUTES

Session 34: Built to fix the zero-feedback-loop problem.
"""

import json
import logging
import smtplib
import subprocess
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from rudy.paths import RUDY_DATA

log = logging.getLogger("robin.wake_alfred")

COORD_DIR = RUDY_DATA / "coordination"
ALFRED_INBOX = RUDY_DATA / "alfred-inbox"
WAKE_STATE_FILE = COORD_DIR / "wake-alfred-state.json"

# Configuration
WAKE_THRESHOLD_MINUTES = 30     # Alfred offline this long = consider waking
COOLDOWN_MINUTES = 120          # Don't wake more than once per 2 hours
BATMAN_EMAIL = "ccimino2@gmail.com"
RUDY_EMAIL = "rudy.ciminoassist@gmail.com"


def _load_wake_state() -> dict:
    """Load wake state (last wake time, attempts, etc.)."""
    if WAKE_STATE_FILE.exists():
        try:
            return json.loads(WAKE_STATE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {"last_wake": None, "total_wakes": 0, "last_method": None}


def _save_wake_state(state: dict):
    """Persist wake state."""
    COORD_DIR.mkdir(parents=True, exist_ok=True)
    WAKE_STATE_FILE.write_text(
        json.dumps(state, indent=2, default=str), encoding="utf-8"
    )


def _alfred_offline_minutes() -> float:
    """How long has Alfred been offline (or stale)?

    IMPORTANT: A stale 'online' status is NOT online. If Alfred crashed,
    the status file stays 'online' forever. We must check the AGE of the
    claim, not just the claimed state. (LF-S52-002 fix)
    """
    status_file = COORD_DIR / "alfred-status.json"
    if not status_file.exists():
        return 9999  # Never seen = very offline
    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
        updated = data.get("updated_at", "")
        if not updated:
            return 9999
        last = datetime.fromisoformat(updated)
        age_minutes = (datetime.now() - last).total_seconds() / 60
        # A fresh "online" status (< 15 min) means Alfred is actually active
        if data.get("state") == "online" and age_minutes < 15:
            return 0
        # Anything older than 15 min is stale -- treat as offline regardless
        # of claimed state. Active Alfred sessions update status frequently.
        return age_minutes
    except Exception:
        pass
    return 9999


def _pending_work_summary() -> dict:
    """Summarize what's waiting for Alfred."""
    summary = {"inbox_count": 0, "inbox_types": [], "findings": []}
    # Count unread messages Robin sent to Alfred
    if ALFRED_INBOX.exists():
        for f in ALFRED_INBOX.glob("*.json"):
            try:
                msg = json.loads(f.read_text(encoding="utf-8"))
                if msg.get("status") == "unread":
                    summary["inbox_count"] += 1
                    summary["inbox_types"].append(msg.get("type", "?"))
            except Exception:
                continue

    # Check for night shift findings
    findings_dir = RUDY_DATA / "findings"
    if findings_dir.exists():
        for f in findings_dir.glob("*.json"):
            try:
                finding = json.loads(f.read_text(encoding="utf-8"))
                if finding.get("status") != "resolved":
                    summary["findings"].append(finding.get("title", "?"))
            except Exception:
                continue
    return summary


def should_wake_alfred() -> tuple[bool, str]:
    """Decide whether Robin should wake Alfred.

    Returns (should_wake, reason).
    """
    state = _load_wake_state()

    # Cooldown check
    if state.get("last_wake"):
        try:
            last = datetime.fromisoformat(state["last_wake"])
            since = (datetime.now() - last).total_seconds() / 60
            if since < COOLDOWN_MINUTES:
                return False, f"Cooldown: {COOLDOWN_MINUTES - since:.0f}min remaining"
        except (ValueError, TypeError):
            pass

    # Is Alfred actually offline long enough?
    offline_min = _alfred_offline_minutes()
    if offline_min < WAKE_THRESHOLD_MINUTES:
        return False, f"Alfred offline only {offline_min:.0f}min (threshold={WAKE_THRESHOLD_MINUTES})"

    # Is there work waiting?
    work = _pending_work_summary()
    if work["inbox_count"] == 0 and not work["findings"]:
        return False, "No pending work for Alfred"

    reason = (
        f"Alfred offline {offline_min:.0f}min. "
        f"Pending: {work['inbox_count']} inbox msgs, "
        f"{len(work['findings'])} findings"
    )
    return True, reason


def _build_wake_email(reason: str, work: dict) -> str:
    """Build the wake-up email body."""
    lines = [
        "Robin here. Alfred has been offline and there's work waiting.",
        "",
        f"Reason: {reason}",
        "",
        "--- Pending Work ---",
        f"Inbox messages: {work.get('inbox_count', 0)}",
    ]
    if work.get("inbox_types"):
        from collections import Counter
        type_counts = Counter(work["inbox_types"])
        lines.append(f"  Types: {dict(type_counts)}")

    if work.get("findings"):
        lines.append(f"Open findings: {len(work['findings'])}")
        for f in work["findings"][:5]:
            lines.append(f"  - {f}")
    lines.extend([
        "",
        "--- Action Needed ---",
        "Open Cowork and start a new session. Robin has items",
        "that need Alfred's cloud reasoning to resolve.",
        "",
        "Read CLAUDE.md first. Then check alfred-inbox/ for details.",
        "",
        "-- Robin (autonomous agent on Oracle)",
    ])
    return "\n".join(lines)


def wake_via_email(reason: str) -> bool:
    """Send a wake-up email to Batman via Gmail SMTP.

    Uses Rudy's Gmail app password for sending.
    """
    work = _pending_work_summary()
    body = _build_wake_email(reason, work)

    msg = MIMEMultipart()
    msg["From"] = RUDY_EMAIL
    msg["To"] = BATMAN_EMAIL
    msg["Subject"] = f"[Robin] Alfred needed - {work.get('inbox_count', 0)} items waiting"
    msg.attach(MIMEText(body, "plain"))

    # Try Gmail SMTP (app password from secrets or env)
    password = None
    secrets_file = RUDY_DATA / "robin-secrets.json"
    if secrets_file.exists():
        try:
            secrets = json.loads(secrets_file.read_text(encoding="utf-8"))
            password = secrets.get("gmail_app_password", "")
        except Exception:
            pass
    if not password:
        import os
        password = os.environ.get("GMAIL_APP_PASSWORD", "")

    if not password:
        log.warning("No Gmail app password -- cannot send wake email")
        return False

    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(RUDY_EMAIL, password)
            server.send_message(msg)
        log.info("Wake email sent to %s", BATMAN_EMAIL)
        return True
    except Exception as e:
        log.error("Wake email failed: %s", e)
        return False


def wake_via_desktop_notification(reason: str) -> bool:
    """Show a Windows toast notification on Oracle's desktop."""
    try:
        # PowerShell toast notification
        ps_script = (
            '[Windows.UI.Notifications.ToastNotificationManager, '
            'Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null; '
            '$template = [Windows.UI.Notifications.ToastNotificationManager]::'
            'GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); '
            '$text = $template.GetElementsByTagName("text"); '
            f'$text[0].AppendChild($template.CreateTextNode("Robin needs Alfred")) | Out-Null; '
            f'$text[1].AppendChild($template.CreateTextNode("{reason[:200]}")) | Out-Null; '
            '$toast = [Windows.UI.Notifications.ToastNotification]::new($template); '
            '[Windows.UI.Notifications.ToastNotificationManager]::'
            'CreateToastNotifier("Batcave").Show($toast)'
        )
        subprocess.run(
            ["powershell", "-Command", ps_script],
            capture_output=True, timeout=10
        )
        log.info("Desktop notification shown")
        return True
    except Exception as e:
        log.warning("Desktop notification failed: %s", e)
        return False


def wake_via_claude_app() -> bool:
    """Open the Claude desktop app to prompt a new Cowork session."""
    try:
        # Find Claude executable
        import glob
        from rudy.paths import CLAUDE_APP_GLOBS
        candidates = []
        for pattern in CLAUDE_APP_GLOBS:
            candidates = glob.glob(pattern)
            if candidates:
                break
        if candidates:
            exe = candidates[-1]  # Latest version
            subprocess.Popen([exe], creationflags=0x00000008)
            log.info("Claude app launched: %s", exe)
            return True
        # Fallback: just use 'start' to open whatever's associated
        subprocess.Popen(
            ["cmd", "/c", "start", "claude://"],
            creationflags=0x00000008
        )
        log.info("Claude app launched via protocol handler")
        return True
    except Exception as e:
        log.warning("Claude app launch failed: %s", e)
        return False


def wake_alfred() -> dict:
    """Main entry point: decide whether to wake Alfred and do it.

    Called from bridge_runner.py's autonomy loop.

    Returns dict with results of the wake attempt.
    """
    should, reason = should_wake_alfred()
    if not should:
        return {"woke": False, "reason": reason}

    log.info("Waking Alfred: %s", reason)
    state = _load_wake_state()
    results = {"woke": False, "reason": reason, "methods_tried": []}

    # Method 1: Desktop notification (fastest, least intrusive)
    if wake_via_desktop_notification(reason):
        results["methods_tried"].append("notification")
        results["woke"] = True

    # Method 2: Email Batman (reliable, reaches phone)
    if wake_via_email(reason):
        results["methods_tried"].append("email")
        results["woke"] = True

    # Method 3: Open Claude app (if not already running many instances)
    # Skip if Claude is already running -- Batman may already be in a session
    try:
        r = subprocess.run(
            ["powershell", "-Command",
             "(Get-Process claude -ErrorAction SilentlyContinue).Count"],
            capture_output=True, text=True, timeout=5
        )
        claude_count = int(r.stdout.strip() or "0")
    except Exception:
        claude_count = 0

    if claude_count < 5:
        if wake_via_claude_app():
            results["methods_tried"].append("claude_app")
            results["woke"] = True

    # Update state
    state["last_wake"] = datetime.now().isoformat()
    state["total_wakes"] = state.get("total_wakes", 0) + 1
    state["last_method"] = results["methods_tried"]
    state["last_reason"] = reason
    _save_wake_state(state)

    log.info("Wake result: %s (methods: %s)",
             "success" if results["woke"] else "failed",
             results["methods_tried"])
    return results


# --- CLI for manual testing ---
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    if "--check" in sys.argv:
        should, reason = should_wake_alfred()
        print(f"Should wake: {should}")
        print(f"Reason: {reason}")
        work = _pending_work_summary()
        print(f"Pending: {json.dumps(work, indent=2)}")
    elif "--wake" in sys.argv:
        result = wake_alfred()
        print(json.dumps(result, indent=2, default=str))
    else:
        print("Usage: python robin_wake_alfred.py [--check | --wake]")
