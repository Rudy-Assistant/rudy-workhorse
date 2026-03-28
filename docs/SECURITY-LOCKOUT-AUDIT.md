# Security Lockout Audit — Fortress Paradox Compliance

**Date:** 2026-03-28
**Auditor:** Claude (Cowork session)
**Context:** USB quarantine + security agent previously bricked the machine by distrusting input devices (keyboard/mouse blocked). Chris could not input commands.

---

## CRITICAL FINDINGS

### 1. USB Quarantine (usb_quarantine.py) — HIGH RISK OF LOCKOUT

**Problem:** The quarantine system classifies HID devices (keyboards, mice) as CRITICAL threat (score 90-95) with action `block_and_alert`. If this runs on boot or periodically, it WILL block any USB keyboard/mouse that hasn't been explicitly whitelisted.

**Specific dangers:**
- `Keyboard` class: score 95, action `block_and_alert`
- `HIDClass`: score 90, action `block_and_alert`
- Even the built-in USB hub on the mini-PC could trigger profiling
- Chris's USB keyboard for recovery would be BLOCKED
- A new mouse after hardware swap would be BLOCKED

**The whitelist file** (`rudy-data/usb-whitelist.json`) is the ONLY thing preventing lockout. If this file is missing, corrupt, or the device serial changes, the machine bricks.

**RECOMMENDATION: DISABLE until Phase 3+.** The quarantine system has no safe fallback. It should NOT run until:
1. All Chris's devices are in the whitelist
2. There's a guaranteed override mechanism (e.g., "if no HID device is whitelisted AND connected, don't block anything")
3. A time-based safety valve exists (e.g., "never block HID in the first 10 minutes after boot")

### 2. Security Agent (security_agent.py) — ✅ SAFE (CORRECTED)

**Status:** Full review completed (543 lines). This file is NOT truncated — the v0.1.0 release note was misleading. The module is purely passive/observational: monitors network connections, listening ports, processes, file integrity, Windows event logs, breach databases, WiFi presence, and wellness. **It never blocks anything.** Safe to run.

**RECOMMENDATION: Safe to enable. No Fortress Paradox concerns — no blocking behavior.**

### 3. Network Defense (network_defense.py) — ✅ SAFE (CORRECTED)

**Status:** Full review completed (696 lines). This module is entirely read-only and observational. It uses only passive commands (`arp -a`, `nslookup`, `net share`, `net session`, `reg query`, `netstat -ano`, `tasklist`). **No blocking, no firewall modification, no device disabling.** The original "MEDIUM RISK" assessment was incorrect.

**Minor bug:** Line 357 has `list(all_known)[-5000]` — should be `[-5000:]` (missing slice notation for the cap).

**RECOMMENDATION: Safe to enable. No Fortress Paradox concerns — no blocking behavior.**

### 4. Intruder Profiler (intruder_profiler.py) — LOW RISK

**Status:** Passive/read-only by design. Observes and logs but doesn't block. This is safe.

### 5. Surveillance (surveillance.py) — LOW RISK

**Status:** Camera capture only. No blocking behavior. Safe.

### 6. Enforce RustDesk Config (enforce-rustdesk-config.ps1) — SAFE

**Status:** Ensures RustDesk stays running with password set. This is a GOOD thing — it maintains remote access. Keep running.

---

## CURRENT STATE (GOOD NEWS)

- **No security/quarantine scheduled tasks found** — none of the dangerous modules are currently running on a schedule
- **No custom firewall block rules** — no "rudy" or "quarantine" firewall rules exist
- **No security-related processes running** — only Windows built-in security (MicrosoftSecurityApp, SecurityHealthService)
- **RustDesk enforcement is running** — good, maintains remote access

---

## MANDATORY SAFEGUARDS BEFORE ENABLING SECURITY MODULES

### Rule 1: Never Block HID Without Override
```python
# Add to usb_quarantine.py before any block action:
def should_block_device(fingerprint):
    # FORTRESS PARADOX: Never block HID if no whitelisted HID exists
    if fingerprint.device_class in ('HIDClass', 'Keyboard', 'Mouse'):
        whitelisted_hid = [d for d in load_whitelist()
                          if d.get('class') in ('HIDClass', 'Keyboard', 'Mouse')]
        if not whitelisted_hid:
            log.warning("FORTRESS: No whitelisted HID devices. Allowing all HID.")
            return False
        # Even with whitelist, never block in first 10 min after boot
        if system_uptime_minutes() < 10:
            log.warning("FORTRESS: Boot grace period. Allowing HID.")
            return False
    return True  # OK to block non-HID devices
```

### Rule 2: Boot Grace Period
No security module should take ANY blocking action within 10 minutes of system boot. This gives Chris time to connect and whitelist devices if needed.

### Rule 3: Remote Access is SACRED
Never block or interfere with: Tailscale, RustDesk, RDP, SSH, or the n8n web interface. These are Chris's lifelines.

### Rule 4: Emergency Disable Switch
Create a file-based kill switch: if `rudy-data/SECURITY-DISABLED` exists, ALL security blocking is bypassed. Chris can create this file via remote access to instantly disable all quarantine.

### Rule 5: Graduated Deployment
- Phase 1: Logging only (observe, report, never block)
- Phase 2: Prompt before blocking (email Chris, wait for approval)
- Phase 3: Auto-block with whitelist + boot grace + kill switch
- Phase 4: Full autonomous security (only after 30+ days incident-free)

---

## IMMEDIATE ACTIONS

1. **DO NOT** enable usb_quarantine.py, security_agent.py, or network_defense.py in n8n workflows
2. **DO NOT** create scheduled tasks for these modules
3. **KEEP** enforce-rustdesk-config.ps1 running (it's protective, not restrictive)
4. Add the SECURITY-DISABLED kill switch mechanism to the n8n watchdog
5. Update CLAUDE.md in the repo with these rules

---

## Files That Are Safe to Run
- surveillance.py (passive observation only)
- intruder_profiler.py (passive observation only)
- security_agent.py (passive observation only — full review confirmed safe)
- network_defense.py (passive observation only — full review confirmed safe, bug fixed)
- enforce-rustdesk-config.ps1 (protective)
- All n8n seed workflows (01-07) — none have blocking behavior

## Files That Must NOT Run Until Safeguarded
- usb_quarantine.py — use `usb_quarantine_safeguarded.py` instead (Fortress Paradox safeguards applied)
