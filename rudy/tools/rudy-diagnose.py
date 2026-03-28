"""
Rudy Diagnostic Tool
====================
Self-diagnosing script that tests every component of the Rudy email
listener pipeline and reports exactly what's working, what's broken,
and how to fix it — no manual browser investigation needed.

Usage:
    python rudy-diagnose.py
    python rudy-diagnose.py --fix   (attempt auto-fixes where possible)
    python rudy-diagnose.py --send-test   (send a test email after diagnostics pass)

Exit codes:
    0 = All checks passed
    1 = Fixable issues found (re-run with --fix)
    2 = Manual intervention required (instructions printed)
"""

import imaplib
import smtplib
import socket
import ssl
import os
import sys
import json
import ctypes
import subprocess
import logging
from datetime import datetime
from pathlib import Path
from email.mime.text import MIMEText

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# CONFIGURATION (mirrors rudy-listener.py)
# ─────────────────────────────────────────────

RUDY_EMAIL = os.environ.get("RUDY_EMAIL", "rudy.ciminoassist@gmail.com")
RUDY_APP_PASSWORD = os.environ.get("RUDY_APP_PASSWORD", "")

IMAP_SERVER = "imap.gmail.com"
IMAP_PORT = 993
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 465

GMAIL_IMAP_IPS = ["142.250.4.108", "142.250.4.109", "74.125.200.108", "74.125.200.109"]
GMAIL_SMTP_IPS = ["142.250.4.108", "74.125.200.108"]

HOSTS_FILE = r"C:\Windows\System32\drivers\etc\hosts"
DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOG_DIR = DESKTOP / "rudy-logs"
REPORT_FILE = LOG_DIR / f"diagnostic-{datetime.now().strftime('%Y%m%d-%H%M%S')}.txt"

# ─────────────────────────────────────────────
# PRETTY OUTPUT
# ─────────────────────────────────────────────

class DiagReport:
    def __init__(self):
        self.lines = []
        self.passed = 0
        self.failed = 0
        self.warnings = 0
        self.fixes = []

    def header(self, text):
        line = f"\n{'='*60}\n  {text}\n{'='*60}"
        print(line)
        self.lines.append(line)

    def ok(self, text):
        self.passed += 1
        line = f"  [PASS] {text}"
        print(line)
        self.lines.append(line)

    def fail(self, text, fix=None):
        self.failed += 1
        line = f"  [FAIL] {text}"
        print(line)
        self.lines.append(line)
        if fix:
            fix_line = f"         FIX: {fix}"
            print(fix_line)
            self.lines.append(fix_line)
            self.fixes.append(fix)

    def warn(self, text):
        self.warnings += 1
        line = f"  [WARN] {text}"
        print(line)
        self.lines.append(line)

    def info(self, text):
        line = f"  [INFO] {text}"
        print(line)
        self.lines.append(line)

    def summary(self):
        self.header("SUMMARY")
        line = f"  Passed: {self.passed}  |  Failed: {self.failed}  |  Warnings: {self.warnings}"
        print(line)
        self.lines.append(line)

        if self.failed == 0:
            msg = "\n  ALL CHECKS PASSED — Rudy should be operational."
            print(msg)
            self.lines.append(msg)
        else:
            msg = f"\n  {self.failed} issue(s) found. Fixes needed:"
            print(msg)
            self.lines.append(msg)
            for i, fix in enumerate(self.fixes, 1):
                fix_msg = f"    {i}. {fix}"
                print(fix_msg)
                self.lines.append(fix_msg)

    def save(self):
        LOG_DIR.mkdir(exist_ok=True)
        with open(REPORT_FILE, "w", encoding="utf-8") as f:
            f.write(f"Rudy Diagnostic Report — {datetime.now().isoformat()}\n")
            f.write("\n".join(self.lines))
        print(f"\n  Report saved: {REPORT_FILE}")


# ─────────────────────────────────────────────
# CHECKS
# ─────────────────────────────────────────────

def check_env_vars(report):
    """Check that credentials are set."""
    report.header("1. ENVIRONMENT / CREDENTIALS")

    if RUDY_EMAIL:
        report.ok(f"RUDY_EMAIL = {RUDY_EMAIL}")
    else:
        report.fail("RUDY_EMAIL not set", "Set RUDY_EMAIL in start-rudy.bat or environment")

    if RUDY_APP_PASSWORD:
        masked = RUDY_APP_PASSWORD[:2] + "*" * (len(RUDY_APP_PASSWORD) - 4) + RUDY_APP_PASSWORD[-2:]
        report.ok(f"RUDY_APP_PASSWORD = {masked} ({len(RUDY_APP_PASSWORD)} chars)")
        if len(RUDY_APP_PASSWORD) != 16:
            report.warn(f"App password is {len(RUDY_APP_PASSWORD)} chars (expected 16). "
                        "Google App Passwords are exactly 16 characters with no spaces.")
        if " " in RUDY_APP_PASSWORD:
            report.fail("App password contains spaces",
                        "Remove spaces from RUDY_APP_PASSWORD in start-rudy.bat")
    else:
        report.fail("RUDY_APP_PASSWORD not set",
                     "Set RUDY_APP_PASSWORD in start-rudy.bat (16-char Google App Password)")

    # Check if Claude CLI is available
    try:
        result = subprocess.run(["claude", "--version"], capture_output=True, text=True, timeout=10)
        if result.returncode == 0:
            report.ok(f"Claude CLI available: {result.stdout.strip()}")
        else:
            report.warn("Claude CLI returned non-zero exit code")
    except FileNotFoundError:
        report.fail("Claude CLI not found on PATH",
                     "Install: npm install -g @anthropic-ai/claude-code")
    except Exception as e:
        report.warn(f"Could not check Claude CLI: {e}")


def check_dns(report):
    """Test DNS resolution for Gmail servers."""
    report.header("2. DNS RESOLUTION")

    for host in [IMAP_SERVER, SMTP_SERVER]:
        try:
            ips = socket.getaddrinfo(host, None)
            resolved = set(addr[4][0] for addr in ips)
            report.ok(f"{host} resolves to {', '.join(list(resolved)[:3])}")
        except socket.gaierror as e:
            report.fail(f"{host} DNS resolution failed: {e}",
                        f"Add '{GMAIL_IMAP_IPS[0]} {host}' to {HOSTS_FILE} "
                        "(run rudy-diagnose.py --fix as admin)")


def check_tcp_connectivity(report):
    """Test raw TCP connections to Gmail."""
    report.header("3. TCP CONNECTIVITY")

    # Test via DNS name
    for host, port, label in [
        (IMAP_SERVER, IMAP_PORT, "IMAP"),
        (SMTP_SERVER, SMTP_PORT, "SMTP"),
    ]:
        try:
            sock = socket.create_connection((host, port), timeout=10)
            sock.close()
            report.ok(f"{label} ({host}:{port}) — TCP connection OK")
        except (socket.gaierror, OSError) as e:
            report.warn(f"{label} ({host}:{port}) — DNS/TCP failed: {e}")
            # Try direct IP fallback
            ip = GMAIL_IMAP_IPS[0] if "imap" in label.lower() else GMAIL_SMTP_IPS[0]
            try:
                sock = socket.create_connection((ip, port), timeout=10)
                sock.close()
                report.ok(f"{label} ({ip}:{port}) — Direct IP fallback OK")
            except Exception as e2:
                log.debug(f"Direct IP connection failed: {e2}")
                report.fail(f"{label} — All connection methods failed: {e2}",
                            "Check firewall/antivirus settings; ensure port 993/465 not blocked")


def check_imap_auth(report):
    """Test IMAP authentication — this is the critical test."""
    report.header("4. IMAP AUTHENTICATION")

    if not RUDY_APP_PASSWORD:
        report.fail("Skipped — no password available")
        return False

    mail = None
    connected_via = None

    # Try DNS first
    try:
        mail = imaplib.IMAP4_SSL(IMAP_SERVER, IMAP_PORT)
        connected_via = IMAP_SERVER
    except (socket.gaierror, OSError) as e:
        report.warn(f"DNS connection failed: {e} — trying IP fallback")
        for ip in GMAIL_IMAP_IPS:
            try:
                ctx = ssl.create_default_context()
                mail = imaplib.IMAP4_SSL(ip, IMAP_PORT, ssl_context=ctx)
                connected_via = ip
                break
            except Exception as e:
                log.debug(f"IMAP IP fallback attempt failed for {ip}: {e}")
                continue

    if mail is None:
        report.fail("Cannot connect to Gmail IMAP (DNS + all IP fallbacks failed)",
                     "Check network connectivity and firewall rules")
        return False

    report.ok(f"Connected to IMAP via {connected_via}")

    # Now test authentication
    try:
        mail.login(RUDY_EMAIL, RUDY_APP_PASSWORD)
        report.ok(f"IMAP login successful as {RUDY_EMAIL}")
        # Check INBOX
        status, data = mail.select("INBOX")
        if status == "OK":
            report.ok(f"INBOX accessible — {data[0].decode()} messages")
        mail.logout()
        return True
    except imaplib.IMAP4.error as e:
        error_msg = str(e)
        report.fail(f"IMAP login FAILED: {error_msg}")

        if "AUTHENTICATIONFAILED" in error_msg.upper() or "Invalid credentials" in error_msg:
            report.info("This usually means one of:")
            report.info("  (a) 2-Step Verification is NOT enabled on Rudy's Google account")
            report.info("      → App Passwords only work when 2FA is ON")
            report.info(f"      → Fix: Sign into {RUDY_EMAIL} in a browser, go to:")
            report.info("        https://myaccount.google.com/signinoptions/twosv")
            report.info("        Enable 2-Step Verification, then regenerate the App Password at:")
            report.info("        https://myaccount.google.com/apppasswords")
            report.info("")
            report.info("  (b) The App Password is wrong or expired")
            report.info("      → Fix: Go to https://myaccount.google.com/apppasswords")
            report.info(f"        (signed in as {RUDY_EMAIL}), create a new one,")
            report.info("        and update RUDY_APP_PASSWORD in start-rudy.bat")
            report.info("")
            report.info("  (c) 'Less secure app access' needs to be enabled (legacy accounts)")
            report.info("      → This is deprecated; use App Passwords instead")
        return False
    except Exception as e:
        report.fail(f"Unexpected IMAP error: {e}")
        return False


def check_smtp(report):
    """Test SMTP send capability."""
    report.header("5. SMTP (OUTBOUND EMAIL)")

    if not RUDY_APP_PASSWORD:
        report.fail("Skipped — no password available")
        return False

    for host in [SMTP_SERVER] + GMAIL_SMTP_IPS:
        try:
            with smtplib.SMTP_SSL(host, SMTP_PORT) as server:
                server.login(RUDY_EMAIL, RUDY_APP_PASSWORD)
                report.ok(f"SMTP login successful via {host}")
                return True
        except smtplib.SMTPAuthenticationError as e:
            report.fail(f"SMTP auth failed via {host}: {e}",
                        "Same fix as IMAP auth — check 2FA + App Password")
            return False
        except (socket.gaierror, OSError) as e:
            report.warn(f"SMTP {host} unreachable: {e}")
            continue
        except Exception as e:
            report.fail(f"SMTP error via {host}: {e}")
            return False

    report.fail("All SMTP hosts unreachable", "Check network/firewall")
    return False


def check_imap_idle(report):
    """Test IMAP IDLE capability."""
    report.header("6. IMAP IDLE SUPPORT")

    if not RUDY_APP_PASSWORD:
        report.fail("Skipped — no password available")
        return

    try:
        mail = None
        for host in [IMAP_SERVER] + GMAIL_IMAP_IPS:
            try:
                if host == IMAP_SERVER:
                    mail = imaplib.IMAP4_SSL(host, IMAP_PORT)
                else:
                    ctx = ssl.create_default_context()
                    mail = imaplib.IMAP4_SSL(host, IMAP_PORT, ssl_context=ctx)
                break
            except Exception as e:
                log.debug(f"IMAP connection attempt failed: {e}")
                continue

        if mail is None:
            report.fail("Cannot connect for IDLE test")
            return

        mail.login(RUDY_EMAIL, RUDY_APP_PASSWORD)
        mail.select("INBOX")

        # Check IDLE capability
        typ, data = mail.capability()
        caps = data[0].decode().upper() if data[0] else ""
        if "IDLE" in caps:
            report.ok("Server supports IMAP IDLE")
        else:
            report.warn("Server does not advertise IDLE capability")
            report.info(f"Capabilities: {caps[:200]}")

        mail.logout()
    except Exception as e:
        report.warn(f"IDLE check failed: {e}")


def check_listener_process(report):
    """Check if the Rudy listener is currently running."""
    report.header("7. LISTENER PROCESS STATUS")

    try:
        result = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq python.exe", "/FO", "CSV"],
            capture_output=True, text=True, timeout=10
        )
        python_procs = [line for line in result.stdout.strip().split("\n") if "python" in line.lower()]
        if python_procs:
            report.info(f"Found {len(python_procs)} Python process(es) running")
        else:
            report.warn("No Python processes found — listener may not be running")
    except Exception as e:
        log.debug(f"Process check failed: {e}")
        report.warn(f"Could not check processes: {e}")

    # Check scheduled task
    try:
        result = subprocess.run(
            ["schtasks", "/Query", "/TN", "Rudy-FamilyAssistant", "/FO", "CSV", "/V"],
            capture_output=True, text=True, timeout=10
        )
        if "Rudy-FamilyAssistant" in result.stdout:
            if "Running" in result.stdout:
                report.ok("Scheduled task 'Rudy-FamilyAssistant' is Running")
            elif "Ready" in result.stdout:
                report.warn("Scheduled task exists but is in 'Ready' state (not running)")
            else:
                report.info("Scheduled task status: check Task Scheduler")
        else:
            report.warn("Scheduled task 'Rudy-FamilyAssistant' not found")
    except Exception as e:
        report.warn(f"Could not check scheduled task: {e}")

    # Check recent logs
    log_file = LOG_DIR / "rudy.log"
    if log_file.exists():
        try:
            content = log_file.read_text(encoding="utf-8", errors="replace")
            lines = content.strip().split("\n")
            last_lines = lines[-5:] if len(lines) >= 5 else lines
            report.info("Last log entries:")
            for line in last_lines:
                report.info(f"  {line.strip()[:120]}")
        except Exception as e:
            report.warn(f"Could not read log: {e}")
    else:
        report.info("No rudy.log found yet (listener hasn't run)")


def check_files(report):
    """Verify all Rudy files are present and correct."""
    report.header("8. FILE INTEGRITY")

    files = {
        "rudy-listener.py": DESKTOP / "rudy-listener.py",
        "start-rudy.bat": DESKTOP / "start-rudy.bat",
        "install-rudy-service.ps1": DESKTOP / "install-rudy-service.ps1",
    }

    for name, path in files.items():
        if path.exists():
            size = path.stat().st_size
            report.ok(f"{name} exists ({size:,} bytes)")
        else:
            report.fail(f"{name} missing", f"Re-create {path}")


# ─────────────────────────────────────────────
# AUTO-FIX
# ─────────────────────────────────────────────

def is_admin():
    """Check if running with admin privileges."""
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception as e:
        log.debug(f"Admin check failed: {e}")
        return False


def auto_fix_dns(report):
    """Add Gmail IPs to hosts file if DNS is broken."""
    report.header("AUTO-FIX: DNS (hosts file)")

    if not is_admin():
        report.fail("Need admin privileges to modify hosts file",
                     "Run: python rudy-diagnose.py --fix  (as Administrator)")
        return

    entries = [
        "142.250.4.108  imap.gmail.com",
        "142.250.4.109  smtp.gmail.com",
    ]

    try:
        existing = Path(HOSTS_FILE).read_text(encoding="utf-8")
        additions = []
        for entry in entries:
            hostname = entry.split()[-1]
            if hostname not in existing:
                additions.append(entry)

        if not additions:
            report.ok("Hosts file already has Gmail entries")
            return

        with open(HOSTS_FILE, "a", encoding="utf-8") as f:
            f.write("\n# Added by Rudy diagnostics for DNS fallback\n")
            for entry in additions:
                f.write(entry + "\n")

        report.ok(f"Added {len(additions)} entries to hosts file")

        # Flush DNS cache
        subprocess.run(["ipconfig", "/flushdns"], capture_output=True, timeout=10)
        report.ok("DNS cache flushed")

    except PermissionError:
        report.fail("Permission denied modifying hosts file",
                     "Run as Administrator")
    except Exception as e:
        report.fail(f"Could not modify hosts file: {e}")


def send_test_email(report):
    """Send a test email from Rudy to Chris to verify the full pipeline."""
    report.header("SENDING TEST EMAIL")

    try:
        msg = MIMEText(
            f"This is an automated test from Rudy's diagnostic tool.\n\n"
            f"Timestamp: {datetime.now().isoformat()}\n"
            f"All systems checked and operational.\n\n"
            f"— Rudy (automated diagnostic)",
            "plain", "utf-8"
        )
        msg["Subject"] = "Rudy Diagnostic: All Systems Go"
        msg["From"] = RUDY_EMAIL
        msg["To"] = "ccimino2@gmail.com"

        for host in [SMTP_SERVER] + GMAIL_SMTP_IPS:
            try:
                with smtplib.SMTP_SSL(host, SMTP_PORT) as server:
                    server.login(RUDY_EMAIL, RUDY_APP_PASSWORD)
                    server.send_message(msg)
                report.ok(f"Test email sent to ccimino2@gmail.com via {host}")
                return
            except (socket.gaierror, OSError):
                continue
            except Exception as e:
                report.fail(f"Send failed: {e}")
                return

        report.fail("All SMTP hosts failed")
    except Exception as e:
        report.fail(f"Test email error: {e}")


# ─────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────

def main():
    do_fix = "--fix" in sys.argv
    do_test = "--send-test" in sys.argv

    report = DiagReport()

    print()
    print("╔══════════════════════════════════════════════════════════╗")
    print("║         RUDY DIAGNOSTIC TOOL v1.0                      ║")
    print("║         Testing all systems...                          ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    # Run all checks
    check_env_vars(report)
    check_dns(report)
    check_tcp_connectivity(report)
    imap_ok = check_imap_auth(report)
    smtp_ok = check_smtp(report)
    if imap_ok:
        check_imap_idle(report)
    check_listener_process(report)
    check_files(report)

    # Auto-fix if requested
    if do_fix:
        auto_fix_dns(report)
        # Re-test after fixes
        report.header("RE-TESTING AFTER FIXES")
        check_dns(report)

    # Send test email if requested and SMTP works
    if do_test and smtp_ok:
        send_test_email(report)
    elif do_test and not smtp_ok:
        report.warn("Cannot send test email — SMTP check failed")

    # Summary
    report.summary()
    report.save()

    return 0 if report.failed == 0 else (1 if do_fix else 2)


if __name__ == "__main__":
    sys.exit(main())
