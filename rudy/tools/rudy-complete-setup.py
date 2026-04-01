"""
Rudy Complete Setup — Run this after enabling IMAP in Gmail settings.

Steps to complete before running:
1. Log into rudy.ciminoassist@gmail.com in a browser
2. Go to Gmail > Settings (gear icon) > See all settings > Forwarding and POP/IMAP
3. Under "IMAP access", select "Enable IMAP"
4. Click "Save Changes"
5. Run this script: python rudy-complete-setup.py

This script will:
- Test IMAP connection with the app password
- Test SMTP connection
- Update credentials in rudy-totp-secret.json
- Optionally start the email listener
"""
from rudy.paths import RUDY_LOGS
import imaplib
import smtplib
import json
import sys

from email.mime.text import MIMEText

EMAIL = "rudy.ciminoassist@gmail.com"
APP_PW = "bviuyjdptufrtnys"
SECRET = RUDY_LOGS / "rudy-totp-secret.json"

print("=" * 50)
print("  Rudy Complete Setup")
print("=" * 50)

# Test IMAP
print("\n[1] Testing IMAP...")
try:
    mail = imaplib.IMAP4_SSL("imap.gmail.com", 993)
    resp = mail.login(EMAIL, APP_PW)
    print(f"    SUCCESS: {resp}")
    mail.select("INBOX")
    _, msgs = mail.search(None, "ALL")
    count = len(msgs[0].split()) if msgs[0] else 0
    print(f"    Inbox: {count} messages")
    mail.logout()
    imap_ok = True
except Exception as e:
    print(f"    FAILED: {e}")
    print("\n    Make sure you enabled IMAP in Gmail settings!")
    print("    Gmail > Settings > Forwarding and POP/IMAP > Enable IMAP > Save")
    imap_ok = False

# Test SMTP
print("\n[2] Testing SMTP...")
try:
    smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465)
    smtp.login(EMAIL, APP_PW)
    print("    SUCCESS")
    smtp_ok = True

    # Send test email to self
    msg = MIMEText("Rudy is online and operational! IMAP and SMTP verified.")
    msg["Subject"] = "Rudy Setup Complete"
    msg["From"] = EMAIL
    msg["To"] = EMAIL
    smtp.send_message(msg)
    print("    Sent test email to self")
    smtp.quit()
except Exception as e:
    print(f"    FAILED: {e}")
    smtp_ok = False

# Update secret file
if imap_ok:
    print("\n[3] Saving verified credentials...")
    data = json.loads(SECRET.read_text()) if SECRET.exists() else {"email": EMAIL}
    data["app_password"] = APP_PW
    data["imap_verified"] = True
    data["smtp_verified"] = smtp_ok
    SECRET.write_text(json.dumps(data, indent=2))
    print(f"    Saved to {SECRET}")

    # Offer to start listener
    print("\n[4] Ready to start the email listener!")
    print("    Run: python start-rudy.bat")
    print("    Or:  python rudy-listener.py")
else:
    print("\n[!] IMAP not working. Complete the Gmail IMAP setup first.")
    sys.exit(1)

print("\n" + "=" * 50)
print("  Setup", "COMPLETE" if imap_ok and smtp_ok else "INCOMPLETE")
print("=" * 50)
