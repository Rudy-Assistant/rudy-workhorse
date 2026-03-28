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

**GitHub:** MCP connector is UNAUTHORIZED. The host machine has git creds in Windows Credential Manager for `github.com/Rudy-Assistant/rudy-workhorse` (PAT expires 2026-04-25). Use command bridge for git operations.

**Mounted directories:**
- `/mnt/Downloads/` = `%USERPROFILE%\Downloads\` on host
- `/mnt/claude-commands/` = `%USERPROFILE%\claude-commands\` on host
- `/mnt/claude-results/` = `%USERPROFILE%\claude-results\` on host
- `/mnt/Desktop/` = `%USERPROFILE%\Desktop\` on host

**Chris's rules:** Do the work, don't describe it. Exhaust all technical paths before asking. Never create scripts for Chris to run when you can execute via bridge. Just proceed on obvious next steps.

**Current state as of 2026-03-28:**
- 7 n8n seed workflows created in `~/Downloads/Claude Stuff/n8n-workflows/`
- n8n setup script ready: `rudy-n8n-setup.ps1`
- Bridge v2 deployed to host filesystem but scheduled task may reference v1
- USB drive (D:\) has Windows installer + drivers + Batcave restore scripts
- Repo NOT yet cloned on host (git clone hangs on credential prompt via bridge)
- `deploy-phase1.ps1` created as one-shot fix for all pending items

**Immediate next steps:**
1. Chris runs `deploy-phase1.ps1` as admin (fixes bridge, clones repo, stages USB)
2. Run `rudy-n8n-setup.ps1` on host to install n8n
3. Configure n8n credentials (Gmail OAuth2, Claude API key)
4. Import seed workflows into n8n
5. Begin Phase 2: family member communication channels

**Reference docs (read only if needed):**
- `RUDY_CODEBASE_ANALYSIS.md` — Existing repo structure and agent patterns
- `RUDY_CODE_SNIPPETS_AND_ARCHITECTURE.md` — Code snippets from existing agents
- `QUICK_REFERENCE_AND_INTEGRATION_GUIDE.md` — Quick facts and integration methods
