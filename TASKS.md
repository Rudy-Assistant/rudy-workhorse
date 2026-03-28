# Tasks

## In Progress
- [ ] Complete mini PC setup as 24/7 Claude automation hub
  - [x] Windows always-on config (power, sleep, lock screen, auto-login)
  - [x] RustDesk unattended access (password-only, no manual accept)
  - [x] Claude Code CLI + Git installed
  - [x] Superpowers + Everything-Claude-Code plugins installed
  - [x] MCP servers (Context7, Sequential Thinking, Playwright)
  - [x] Gmail + Google Calendar connectors
  - [x] Cowork plugins (Engineering, Productivity, Operations, Plugin Mgmt)
  - [ ] BIOS: AC Power Recovery → Power On (needs USB keyboard or skip)
  - [ ] Smart plug for remote power cycling
- [ ] Deploy safeguarded USB quarantine when Workhorse comes back online
  - Replace `usb_quarantine.py` with safeguarded version (commit `7d3453b`)
  - Verify kill switch file exists: `Desktop\rudy-data\SECURITY-DISABLED`
  - Keep deployment at Phase 1 (log-only) until 30+ days incident-free

## Upcoming
- [ ] Create first coding project on the mini PC
- [ ] Test overnight automation (nightly QA scheduled task)
- [ ] Harvey Associate Commercial Counsel — apply this weekend (deadline: ASAP)

## Completed
- [x] Initial OS + RustDesk setup
- [x] Tailscale configured (100.83.49.9)
- [x] Node.js v24.14.1 installed
- [x] Execution policy set to RemoteSigned
- [x] Git for Windows installed
- [x] All Cowork scheduled tasks created (daily health check, weekly dep audit)
- [x] Set up GitHub fine-grained PAT (Read+Write Contents, expires 2026-06-26)
- [x] Security lockout audit — identified Fortress Paradox in USB quarantine
- [x] Implemented all 5 Fortress Paradox safeguards in usb_quarantine.py
- [x] Full code review: security_agent.py (safe), network_defense.py (safe, bug fixed)
- [x] Corrected SECURITY-LOCKOUT-AUDIT.md with accurate risk assessments
- [x] Pushed all changes to GitHub (commits 7d3453b, 302dce4)
- [x] Cowork scheduled tasks: morning briefing (7:30 AM daily), Workhorse watchdog (every 6h)
