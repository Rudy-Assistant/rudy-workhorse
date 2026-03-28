# Rudy/Batcave Session Handoff Prompt

**Last updated:** 2026-03-28
**Use this:** Paste into a new Cowork session when continuing work on Rudy or the Batcave infrastructure.

---

## Handoff Prompt (copy everything below this line)

---

You are resuming work on the Rudy project for Chris Cimino. Read these files FIRST before doing anything else:

1. `~/Downloads/Claude Stuff/BATCAVE-CLAUDE.md` — Working memory (user profile, machine specs, command bridge usage, USB layout, Phase 1 status)
2. `~/Downloads/Claude Stuff/RUDY-ARCHITECTURE.md` — Master architecture (Oracle/Alfred identity, 6 layers, Fortress Paradox, n8n orchestration)
3. `~/Downloads/Claude Stuff/RUDY-PHASE1-PLAN.md` — Day-by-day implementation plan

Critical context that's NOT in those files:

**Command Bridge:** Write `.ps1`/`.cmd`/`.bat`/`.py` files to `/mnt/claude-commands/` and read results from `/mnt/claude-results/<name>.log`. Pure ASCII only. The bridge runner v2 has a 5-min timeout per command. KNOWN ISSUE: the scheduled task on the host may still run v1 (no timeout). Run `deploy-phase1.ps1` to fix.

**GitHub:** MCP connector is UNAUTHORIZED from Cowork (built-in server config issue). Fine-grained PAT `rudy-workhorse` has Read+Write Contents (expires 2026-06-26). Workaround from Cowork: `git clone` the public repo via bash, push with PAT in URL. From the host: git creds in Windows Credential Manager.

**Mounted directories:**
- `/mnt/Downloads/` = `%USERPROFILE%\Downloads\` on host
- `/mnt/claude-commands/` = `%USERPROFILE%\claude-commands\` on host
- `/mnt/claude-results/` = `%USERPROFILE%\claude-results\` on host
- `/mnt/Desktop/` = `%USERPROFILE%\Desktop\` on host

**Chris's rules:** Do the work, don't describe it. Exhaust all technical paths before asking. Never create scripts for Chris to run when you can execute via bridge. Just proceed on obvious next steps.

**Current state as of 2026-03-28 (evening):**
- Workhorse is OFFLINE — awaiting USB clean install + UNROLL.cmd bootstrap
- Kill switch deployed: `Desktop\rudy-data\SECURITY-DISABLED` exists on the machine
- USB quarantine safeguarded (all 5 Fortress Paradox safeguards) — pushed to GitHub
- All security modules reviewed: `security_agent.py` and `network_defense.py` confirmed safe (passive only)
- 8 n8n seed workflows in repo (`n8n/workflows/01-08`)
- GitHub repo: 14 commits on main, latest `91121cc`
- Cowork scheduled tasks running: morning briefing (7:30 AM daily), Workhorse watchdog (every 6h)

**Immediate next steps:**
1. When Workhorse comes back online: replace `usb_quarantine.py` with safeguarded version, verify kill switch file exists
2. Harvey application — apply this weekend (time-sensitive, prep doc ready)
3. Axiom profile update — deadline March 31
4. Deploy n8n on Workhorse (`rudy-n8n-setup.ps1`)
5. Configure n8n credentials (Gmail OAuth2, Claude API key)
6. Import seed workflows into n8n
7. Continue Detective Agent + Security Hardening from prior sprint

**Reference docs (read only if needed):**
- `RUDY_CODEBASE_ANALYSIS.md` — Existing repo structure and agent patterns
- `RUDY_CODE_SNIPPETS_AND_ARCHITECTURE.md` — Code snippets from existing agents
- `QUICK_REFERENCE_AND_INTEGRATION_GUIDE.md` — Quick facts and integration methods
