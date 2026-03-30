"""
Rudy Stealth Browser - reusable module for bot-resistant Playwright automation.
"""
import time

import random
import re
from pathlib import Path
from playwright.sync_api import sync_playwright
from playwright_stealth import stealth

SESSION_DIR = Path(r"C:\Users\C\Desktop\rudy-sessions")
SESSION_DIR.mkdir(exist_ok=True)

VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1366, "height": 768},
    {"width": 1536, "height": 864},
    {"width": 1440, "height": 900},
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
]

def create_stealth_page(pw, session_name=None, headless=True):
    browser = pw.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"]
    )
    vp = random.choice(VIEWPORTS)
    ua = random.choice(USER_AGENTS)
    opts = {"viewport": vp, "user_agent": ua, "locale": "en-US",
            "timezone_id": "America/Los_Angeles", "screen": vp}
    sf = SESSION_DIR / f"{session_name}.json" if session_name else None
    if sf and sf.exists():
        opts["storage_state"] = str(sf)
    context = browser.new_context(**opts)
    page = context.new_page()
    stealth(page)
    page.set_default_timeout(20000)
    return page, context, browser

def save_session(context, session_name):
    sf = SESSION_DIR / f"{session_name}.json"
    context.storage_state(path=str(sf))
    return sf

def session_exists(name):
    return (SESSION_DIR / f"{name}.json").exists()

def human_delay(lo=500, hi=2000):
    time.sleep(random.uniform(lo / 1000, hi / 1000))

def safe_click(page, sel, timeout=5000):
    human_delay(300, 800)
    try:
        page.click(sel, timeout=timeout)
        human_delay(500, 1500)
        return True
    except Exception:
        return False

def check_captcha(page):
    for sel in ['iframe[src*="recaptcha"]', 'iframe[src*="hcaptcha"]',
                'div[class*="captcha"]', '[data-sitekey]']:
        if page.query_selector(sel):
            return True
    return False

def solve_captcha(page, api_key):
    from twocaptcha import TwoCaptcha
    site_key = None
    el = page.query_selector('[data-sitekey]')
    if el:
        site_key = el.get_attribute("data-sitekey")
    if not site_key:
        iframe = page.query_selector('iframe[src*="recaptcha"]')
        if iframe:
            m = re.search(r'k=([A-Za-z0-9_-]+)', iframe.get_attribute("src") or "")
            if m:
                site_key = m.group(1)
    if not site_key:
        raise ValueError("reCAPTCHA site key not found")
    solver = TwoCaptcha(api_key)
    result = solver.recaptcha(sitekey=site_key, url=page.url)
    page.evaluate(f'document.getElementById("g-recaptcha-response").innerHTML = \"{result["code"]}\"')
    return result["code"]

def google_sign_in(page, email, password):
    page.goto("https://accounts.google.com/ServiceLogin?flowName=GlifWebSignIn&flowEntry=ServiceLogin")
    human_delay(1500, 3000)
    page.fill('input[type="email"]', email)
    human_delay(500, 1000)
    safe_click(page, '#identifierNext')
    human_delay(2000, 4000)
    page.fill('input[type="password"]', password)
    human_delay(500, 1000)
    safe_click(page, '#passwordNext')
    human_delay(3000, 5000)
    return page

def is_2fa(page):
    if "challenge" in page.url:
        return True
    text = page.inner_text("body")[:500].lower()
    return "verification" in text or "2-step" in text

def enter_totp(page, secret):
    import pyotp
    safe_click(page, 'text="Try another way"', timeout=3000)
    human_delay(1000, 2000)
    for sel in ['div:has-text("Google Authenticator")', 'div:has-text("authenticator")']:
        if safe_click(page, sel, timeout=3000):
            human_delay(1000, 2000)
            break
    code = pyotp.TOTP(secret).now()
    ci = page.query_selector('input[type="tel"]:visible')
    if ci:
        ci.fill(code)
        safe_click(page, 'button:has-text("Next")', timeout=3000)
        human_delay(3000, 5000)
        return True
    return False

def enter_sms(page, code):
    digits = re.sub(r'\\D', '', str(code))
    ci = page.query_selector('input#idvPin') or page.query_selector('input[type="tel"]:visible')
    if not ci:
        for inp in page.query_selector_all('input:visible'):
            t = inp.get_attribute("type") or ""
            if t in ("tel", "text", "number", ""):
                r = inp.get_attribute("role") or ""
                if r != "combobox":
                    ci = inp
                    break
    if ci:
        ci.click()
        ci.fill("")
        time.sleep(0.2)
        ci.fill(digits)
        try:
            cb = page.query_selector('input[type="checkbox"]')
            if cb and not cb.is_checked():
                cb.check()
        except Exception:
            pass
        safe_click(page, 'button:has-text("Next")', timeout=3000)
        human_delay(4000, 6000)
        return True
    return False
