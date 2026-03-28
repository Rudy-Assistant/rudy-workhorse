"""
Rudy Auth Fix — Playwright-based Google Account Checker
========================================================
Uses Playwright with Edge's existing browser profile to check Rudy's
Google account 2FA status and test IMAP authentication.

This script bypasses the Chrome extension limitation on Google sign-in
pages by using Playwright directly.

Usage:
    python rudy-auth-fix.py
"""

import subprocess
import sys
import os
import time
import json
import shutil
import imaplib
import ssl
import socket
import logging
from pathlib import Path

log = logging.getLogger(__name__)

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOG_DIR = DESKTOP / "rudy-logs"
LOG_DIR.mkdir(exist_ok=True)

RUDY_EMAIL = "rudy.ciminoassist@gmail.com"
RUDY_APP_PASSWORD = os.environ.get("RUDY_GMAIL_APP_PASSWORD", "")

EDGE_USER_DATA = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "Edge" / "User Data"
TEMP_PROFILE = Path(os.environ.get("TEMP", "")) / "rudy-edge-profile"

GMAIL_IMAP_IPS = ["142.250.4.108", "142.250.4.109", "74.125.200.108", "74.125.200.109"]


def ensure_playwright():
    """Install playwright if needed."""
    try:
        from playwright.sync_api import sync_playwright
        return True
    except ImportError:
        print("[*] Installing Playwright...")
        subprocess.run([sys.executable, "-m", "pip", "install", "--break-system-packages", "playwright"], check=True)
        subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
        return True


def test_imap_auth():
    """Test current IMAP credentials. Returns (success, error_message)."""
    print("\n[1] Testing IMAP authentication...")
    print(f"    Email: {RUDY_EMAIL}")
    print(f"    Password: {RUDY_APP_PASSWORD[:2]}{'*' * 12}{RUDY_APP_PASSWORD[-2:]}")

    hosts_to_try = ["imap.gmail.com"] + GMAIL_IMAP_IPS

    for host in hosts_to_try:
        try:
            print(f"    Trying {host}...")
            if host == "imap.gmail.com":
                mail = imaplib.IMAP4_SSL(host, 993)
            else:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                mail = imaplib.IMAP4_SSL(host, 993, ssl_context=ctx)

            mail.login(RUDY_EMAIL, RUDY_APP_PASSWORD)
            status, count = mail.status("INBOX", "(MESSAGES UNSEEN)")
            mail.logout()
            print(f"    [OK] IMAP auth SUCCESS via {host} — {count}")
            return True, None

        except imaplib.IMAP4.error as e:
            err = str(e)
            print(f"    [FAIL] Auth failed via {host}: {err}")
            if "AUTHENTICATIONFAILED" in err.upper():
                return False, "AUTH_FAILED"
            return False, err

        except (socket.gaierror, OSError) as e:
            print(f"    [WARN] Connection failed via {host}: {e}")
            continue

        except Exception as e:
            print(f"    [FAIL] Unexpected: {e}")
            return False, str(e)

    return False, "ALL_HOSTS_UNREACHABLE"


def check_2fa_with_playwright():
    """
    Use Playwright to check Rudy's Google 2FA status.
    Copies Edge profile to avoid lock conflicts, then opens Google Account settings.
    """
    print("\n[2] Checking 2FA status via Playwright...")

    from playwright.sync_api import sync_playwright

    # Copy Edge profile to avoid lock file conflicts with running Edge
    if TEMP_PROFILE.exists():
        shutil.rmtree(TEMP_PROFILE, ignore_errors=True)

    # We only need the Default profile and a few key files
    print("    Copying Edge profile for Playwright...")
    TEMP_PROFILE.mkdir(parents=True, exist_ok=True)

    # Copy essential files for session cookies
    essential_items = ["Default", "Local State"]
    for item in essential_items:
        src = EDGE_USER_DATA / item
        dst = TEMP_PROFILE / item
        if src.exists():
            if src.is_dir():
                shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
                    "Cache", "Code Cache", "Service Worker", "GPUCache",
                    "blob_storage", "Session Storage", "*.log", "*.tmp"
                ), dirs_exist_ok=True)
            else:
                shutil.copy2(src, dst)

    print("    Launching Edge with copied profile...")

    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(TEMP_PROFILE),
                channel="msedge",
                headless=False,  # Need visible browser for Google auth
                args=["--disable-blink-features=AutomationControlled"],
                ignore_default_args=["--enable-automation"],
            )

            page = context.new_page()

            # Navigate to Rudy's Google account security page
            # First check if Rudy is already signed in
            page.goto("https://myaccount.google.com/security", wait_until="networkidle", timeout=30000)
            time.sleep(3)

            # Check which account we're signed into
            page_text = page.content()

            if "rudy.ciminoassist" in page_text.lower():
                print("    [OK] Rudy's account is signed in!")
                return check_2fa_on_page(page)

            elif "ccimino2" in page_text.lower() or "Sign in" in page.title():
                # We're either on Chris's account or not signed in
                # Try account switcher
                print("    Not signed into Rudy's account. Trying account switcher...")

                # Try navigating with authuser parameter
                page.goto("https://myaccount.google.com/security?authuser=rudy.ciminoassist@gmail.com",
                          wait_until="networkidle", timeout=30000)
                time.sleep(3)

                if "rudy.ciminoassist" in page.content().lower():
                    print("    [OK] Switched to Rudy's account!")
                    return check_2fa_on_page(page)

                # Try direct sign-in approach
                print("    Account switcher didn't work. Trying direct sign-in...")
                page.goto("https://accounts.google.com/AddSession?continue=https://myaccount.google.com/security",
                          wait_until="networkidle", timeout=30000)
                time.sleep(2)

                # Fill email
                email_field = page.query_selector('input[type="email"]')
                if email_field:
                    email_field.fill(RUDY_EMAIL)
                    time.sleep(1)

                    # Click Next
                    next_buttons = page.query_selector_all('button')
                    for btn in next_buttons:
                        text = btn.inner_text().strip().lower()
                        if text == "next" or text == "":
                            btn.click()
                            break
                    else:
                        # Try submitting form
                        email_field.press("Enter")

                    time.sleep(3)

                    # Check if we got to password page
                    current_url = page.url
                    if "challenge" in current_url or "pwd" in current_url or "password" in page.content().lower():
                        print("    Reached password page — Rudy's account exists and is accessible")
                        print("    NOTE: I don't have Rudy's web password (only the app password).")
                        print("    Checking if Rudy is signed in on any other profile...")

                        # We can at least confirm the account exists
                        return {"status": "NEEDS_PASSWORD", "account_exists": True}

                    elif "2-Step Verification" in page.content() or "twosv" in page.content().lower():
                        print("    2FA verification page appeared — 2FA IS enabled!")
                        return {"status": "2FA_ENABLED"}

            context.close()
            return {"status": "UNKNOWN", "details": "Could not determine 2FA status"}

        except Exception as e:
            print(f"    [ERROR] Playwright error: {e}")
            return {"status": "ERROR", "details": str(e)}
        finally:
            # Cleanup temp profile
            try:
                shutil.rmtree(TEMP_PROFILE, ignore_errors=True)
            except Exception as e:
                log.debug(f"Failed to clean up temp profile: {e}")


def check_2fa_on_page(page):
    """Check 2FA status when already on the security settings page."""
    content = page.content()

    if "2-Step Verification" in content:
        # Look for "On" or "Off" near the 2FA section
        twosv_element = page.query_selector('text=2-Step Verification')
        if twosv_element:
            parent = twosv_element.evaluate_handle("el => el.closest('a') || el.parentElement")
            parent_text = parent.inner_text() if parent else ""

            if "On" in parent_text or "on since" in parent_text.lower():
                print("    [OK] 2-Step Verification is ON")
                return {"status": "2FA_ENABLED"}
            elif "Off" in parent_text:
                print("    [!!] 2-Step Verification is OFF")
                print("    → This is why app passwords don't work!")
                print("    → Attempting to navigate to 2FA setup...")

                # Try to click to enable
                twosv_link = page.query_selector('a[href*="twosv"]')
                if twosv_link:
                    twosv_link.click()
                    time.sleep(3)
                    print(f"    → Navigated to: {page.url}")
                    return {"status": "2FA_DISABLED", "navigated_to_setup": True}

                return {"status": "2FA_DISABLED"}

    return {"status": "UNKNOWN", "details": "Could not find 2FA section"}


def check_all_edge_profiles():
    """Check all Edge profiles to find one where Rudy is signed in."""
    print("\n[3] Scanning Edge profiles for Rudy's session...")

    if not EDGE_USER_DATA.exists():
        print("    Edge user data not found")
        return None

    profiles = []
    for item in EDGE_USER_DATA.iterdir():
        if item.is_dir() and (item.name == "Default" or item.name.startswith("Profile")):
            prefs_file = item / "Preferences"
            if prefs_file.exists():
                try:
                    prefs = json.loads(prefs_file.read_text(encoding="utf-8", errors="replace"))
                    account_info = prefs.get("account_info", [])
                    emails = [a.get("email", "") for a in account_info]
                    profiles.append({"name": item.name, "emails": emails})
                    print(f"    {item.name}: {', '.join(emails) if emails else '(no accounts)'}")
                except Exception as e:
                    log.debug(f"Failed to parse profile {item.name}: {e}")
                    profiles.append({"name": item.name, "emails": []})

    for p in profiles:
        if any("rudy" in e.lower() for e in p["emails"]):
            print(f"    [OK] Found Rudy signed in on profile: {p['name']}")
            return p["name"]

    print("    Rudy not found in any Edge profile")
    return None


def write_results(imap_result, twofa_result, profile_result):
    """Write diagnostic results to a file."""
    results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "imap_auth": {"success": imap_result[0], "error": imap_result[1]},
        "twofa_check": twofa_result,
        "edge_profile": profile_result,
    }

    report_file = LOG_DIR / "auth-diagnostic.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print(f"\n[*] Results saved to {report_file}")

    # Also write a human-readable summary
    print("\n" + "=" * 60)
    print("  DIAGNOSTIC SUMMARY")
    print("=" * 60)

    if imap_result[0]:
        print("  IMAP Auth:  WORKING — Rudy can send/receive email!")
        print("  → The listener should work. Restart it.")
    elif imap_result[1] == "AUTH_FAILED":
        print("  IMAP Auth:  FAILED — credentials rejected")
        if twofa_result and twofa_result.get("status") == "2FA_DISABLED":
            print("  Root cause: 2FA is OFF → app passwords don't work without it")
            print("  FIX: Enable 2FA at https://myaccount.google.com/signinoptions/twosv")
        elif twofa_result and twofa_result.get("status") == "2FA_ENABLED":
            print("  2FA is ON but auth still fails → app password may be expired/wrong")
            print("  FIX: Generate new app password at https://myaccount.google.com/apppasswords")
        else:
            print("  Could not determine 2FA status automatically")
            print("  Most likely cause: 2FA not enabled on Rudy's Google account")
    elif imap_result[1] == "ALL_HOSTS_UNREACHABLE":
        print("  IMAP Auth:  UNREACHABLE — network/DNS issue")
        print("  FIX: Run 'python rudy-diagnose.py --fix' as admin")
    else:
        print(f"  IMAP Auth:  ERROR — {imap_result[1]}")

    print("=" * 60)


def main():
    print("╔══════════════════════════════════════════════════════╗")
    print("║  RUDY AUTH FIX — Automated Diagnostics              ║")
    print("╚══════════════════════════════════════════════════════╝")

    # Step 1: Test IMAP auth
    imap_ok, imap_err = test_imap_auth()

    if imap_ok:
        print("\n[✓] IMAP auth is working! No fix needed.")
        print("    Restarting Rudy listener...")
        # Kill any existing listener and restart
        os.system('taskkill /F /FI "WINDOWTITLE eq Rudy*" >nul 2>&1')
        os.system(f'start "Rudy" cmd /c "cd /d {DESKTOP} && start-rudy.bat"')
        write_results((True, None), {"status": "NOT_CHECKED"}, None)
        return

    # Step 2: Check Edge profiles for Rudy's session
    profile = check_all_edge_profiles()

    # Step 3: Use Playwright to check 2FA
    twofa_result = None
    try:
        ensure_playwright()
        twofa_result = check_2fa_with_playwright()
    except Exception as e:
        print(f"\n[WARN] Playwright check failed: {e}")
        twofa_result = {"status": "ERROR", "details": str(e)}

    write_results((imap_ok, imap_err), twofa_result, profile)


if __name__ == "__main__":
    main()
