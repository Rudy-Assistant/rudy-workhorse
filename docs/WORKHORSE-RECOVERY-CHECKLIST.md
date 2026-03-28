# Workhorse Recovery Checklist

**Created:** 2026-03-28
**Context:** Workhorse is offline after USB quarantine bricked the machine by blocking HID devices. A clean install is pending.

---

## Pre-Boot Checklist

- [ ] Verify kill switch file exists: `Desktop\rudy-data\SECURITY-DISABLED`
  - If not, create it: `echo. > "%USERPROFILE%\Desktop\rudy-data\SECURITY-DISABLED"`
  - This prevents ALL security blocking regardless of quarantine state
- [ ] Verify no USB quarantine scheduled tasks exist: `schtasks /query | findstr -i quarantine`
- [ ] Verify no security agent scheduled tasks: `schtasks /query | findstr -i "security_agent"`

## After Boot

### 1. Verify Core Services (should auto-start)
- [ ] RustDesk running: `tasklist | findstr rustdesk`
- [ ] Tailscale running: `sc query Tailscale`
- [ ] Internet: `ping 8.8.8.8`
- [ ] Remote access works from another device

### 2. Deploy Safeguarded USB Quarantine
- [ ] Pull latest from GitHub: `cd Desktop\rudy-workhorse && git pull`
- [ ] Replace the original: `copy rudy\usb_quarantine.py rudy\usb_quarantine_ORIGINAL.py`
- [ ] Copy safeguarded version into place (it's already in the repo at `rudy/usb_quarantine.py` as of commit `7d3453b`)
- [ ] Verify deployment phase is 1 (log-only): `findstr "DEPLOYMENT_PHASE" rudy\usb_quarantine.py`
  - Should show `DEPLOYMENT_PHASE = 1`

### 3. Verify Audit Corrections
- [ ] `security_agent.py` — confirmed safe to run (passive observation only)
- [ ] `network_defense.py` — confirmed safe to run (passive observation only, bug fixed)
- [ ] `intruder_profiler.py` — confirmed safe (passive)
- [ ] `surveillance.py` — confirmed safe (camera capture only)
- [ ] `enforce-rustdesk-config.ps1` — confirmed safe (protective, keeps RustDesk alive)

### 4. Update Git Credentials
- [ ] Verify PAT in Windows Credential Manager: `cmdkey /list | findstr github`
  - Fine-grained PAT `rudy-workhorse` expires 2026-06-26
  - If missing, update: `git config --global credential.helper manager`

### 5. Optional: Deploy n8n
- [ ] Run `n8n\scripts\rudy-n8n-setup.ps1` to install n8n
- [ ] Configure credentials (Gmail OAuth2, Claude API key)
- [ ] Import seed workflows from `n8n\workflows\01-08`

## Safety Rules (Fortress Paradox)

**NEVER enable USB quarantine above Phase 1 without:**
1. All Chris's HID devices in the whitelist (`rudy-data/usb-whitelist.json`)
2. Kill switch file mechanism verified working
3. Boot grace period tested (10-minute window after boot)
4. At least one whitelisted HID device connected
5. Remote access (RustDesk/Tailscale) verified working

**Phase progression:**
- Phase 1: Log only (current, safe) — observe for 30+ days
- Phase 2: Alert before blocking — email Chris, wait for approval
- Phase 3: Auto-block with all safeguards active
- Phase 4: Full autonomous (only after 30+ days incident-free at Phase 3)
