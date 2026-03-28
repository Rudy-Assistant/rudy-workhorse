# Batcave — Claude Working Memory

## The User

**Chris Cimino** (ccimino2@gmail.com) — Builder, not a bystander. Expects Claude to act autonomously and exhaust all technical alternatives before involving the user. Chris values efficiency, dislikes hand-holding, and will push back hard if Claude defaults to "here's a script, run it yourself."

## Autonomy Doctrine

Claude's primary directive is to **do the work**, not describe the work or create scripts for Chris to run. This means:

1. **Exhaust all technical paths before asking the user for input.** If a direct approach fails, try workarounds (junctions, command bridge, alternative tools) before escalating.
2. **Never create a script for Chris to run when Claude can execute the work directly.** If Claude has access to a command bridge, mounted directories, or any execution path — use it.
3. **Only ask the user for input as a last resort.** Even then, minimize the ask (e.g., "run this one command" not "follow these 5 steps").
4. **Don't reinvent the wheel.** Before building a custom solution, check if a simpler approach exists (existing tools, built-in Windows commands, etc.).

### Anti-Patterns (NEVER DO THESE)

| Anti-Pattern | What To Do Instead |
|---|---|
| Writing a .ps1 script and asking Chris to run it | Execute via command bridge or mounted directory |
| Accepting a sandbox limitation without trying workarounds | Try junctions, command bridge, alternative paths first |
| Presenting workarounds only after Chris pushes back | Present the best approach FIRST, including workarounds |
| Listing manual steps for Chris to follow | Automate as many steps as possible, minimize manual list |
| Asking "should I proceed?" for obvious next steps | Just proceed — ask only when genuinely ambiguous |

## The Batcave

Chris's home infrastructure consisting of multiple machines networked via Tailscale.

### The Workhorse (Rudy)

- **Machine:** AceMagic Warlord Mini W1
- **CPU:** Intel Core Ultra 5 225H (14 cores / 18 threads)
- **RAM:** 24GB DDR5 5600MHz
- **Storage:** 1TB NVMe SSD
- **Network:** Realtek RTL8125 2.5GbE
- **OS:** Windows 11
- **User:** C (auto-login)
- **Hostname:** RUDY
- **Role:** Always-on workhorse running local AI (Ollama), remote access (RustDesk), VPN mesh (Tailscale), and automated agents

### Software Stack

- Python 3.12 (pip: requests, psutil, watchdog, schedule, flask, rich, httpx, anthropic, ollama)
- Git (configured for Chris Cimino)
- Ollama (phi3:mini, llama3.1:8b)
- Google Chrome
- RustDesk (remote access)
- Tailscale (VPN mesh)

### Git Repository

**Repo:** `github.com/Rudy-Assistant/rudy-workhorse` (private)
**GitHub org:** Rudy-Assistant
**PAT:** Configured, expires 2026-04-25
**Version:** v0.1.0

### Agents (from repo)

- **system_master.py** — 269-line health/service monitor (RustDesk, Tailscale, resource thresholds)
- **rudy-command-runner.py** — Watches `~/Desktop/rudy-commands/` for scripts, executes them, writes results
- **rudy-listener.py** — Event listener/monitor
- **sentinel.py** — Event-driven observation layer (resource state: normal/constrained/gaming)
- **task_master.py** — Task coordination
- **research_intel.py** — Research/intelligence gathering
- **security_agent.py** — Security monitoring (BROKEN: truncated in v0.1.0)
- **operations_monitor.py** — Operations monitoring
- **rudy-failover-agent.py** — Monitors Claude API availability, activates local Ollama when Claude is down
- **claude-command-runner.ps1** — Command bridge v1: watches `~/claude-commands/` for scripts from Cowork sessions
- **claude-command-runner-v2.ps1** — Command bridge v2: adds 5-min timeout, process tree killing, stale file cleanup

## Command Bridge (v2 — DEPLOYED)

Claude can execute any Windows command on Chris's machine by writing scripts to the mounted `claude-commands/` directory. The bridge runner picks them up within 2 seconds.

**v2 Improvements:** Per-command 5-minute timeout, hung process detection/killing, stale `_running_` file cleanup (>10 min = auto-cleaned).

**How to use:**
1. Write a `.ps1`, `.cmd`, `.bat`, or `.py` file to `/mnt/claude-commands/`
2. Wait ~3-5 seconds for execution
3. Read results from `/mnt/claude-results/<scriptname>.log`

**Important notes:**
- File names starting with `_` are ignored (reserved for lock files, running markers)
- The runner renames files to `_running_<name>` during execution to prevent re-execution
- PowerShell scripts must use pure ASCII — avoid em-dashes, smart quotes, or Unicode operators
- Use `1048576` instead of `1MB`, `1024` instead of `1KB` in calculations to avoid parse issues
- The bridge runs as a scheduled task "ClaudeCommandBridge" at logon with highest privileges
- **Known issue:** Scheduled task may still reference v1. Need to update task to point to v2 runner.
- v2 deployed to: `%USERPROFILE%\claude-command-runner.ps1` and `Desktop\claude-command-runner-v2.ps1`

## USB Recovery Drive

**Device:** PNY USB 3.2.1 FD (231GB physical, 32GB FAT32 partition)
**Label:** ESD-USB
**Purpose:** Windows 11 reinstall + full Batcave restoration

### USB Layout (D:\)

```
D:\
├── boot/                    (Windows Boot Manager)
├── efi/                     (UEFI boot files)
├── sources/
│   ├── install.swm          (Windows image part 1)
│   └── install2.swm         (Windows image part 2)
├── installers/
│   ├── ChromeStandaloneSetup64.exe
│   ├── Git-2.53.0.2-64-bit.exe
│   ├── OllamaSetup.exe
│   ├── rustdesk-1.4.6-x86_64.exe
│   ├── python-3.12.9-amd64.exe
│   ├── tailscale-setup-1.94.2.exe
│   └── GoogleChromeStandaloneEnterprise64.msi
├── drivers/
│   └── LAN/
│       ├── rt640x64.inf     (Realtek RTL8125 driver)
│       ├── rt640x64.sys
│       └── rt640x64.cat
├── UNROLL.cmd               (Single-click Batcave restoration)
├── workhorse-bootstrap.ps1  (Full Rudy configuration)
└── rudy-failover-agent.py   (Failover agent)
```

### Recovery Process

1. Boot from USB (F12 → select ESD-USB)
2. Install Windows 11 (during setup: "Load driver" → browse to `D:\drivers\LAN\` for network)
3. After Windows setup, run `D:\UNROLL.cmd` as Administrator
4. Manual steps: netplwiz (auto-login), tailscale up, RustDesk password, BIOS power recovery

### Known Issue: USB Auto-Boot

The mini-PC may auto-reboot into Windows Setup when the USB is plugged in. This is a BIOS boot order issue — the USB has a valid Windows boot structure and BIOS prioritizes it. Fix: enter BIOS (Del/F2) and set internal NVMe as first boot priority, or remove USB after Windows install.

## Capability Enhancement Sprint

**Status:** Phase 1 complete, Phases 2-5 pending

### Identified Limitations (L1-L7)
- L1: Cannot execute host commands → SOLVED (Command Bridge)
- L2: Volatile workspace (outputs directory wipes on mount change) → Use ~/Claude Stuff/ for persistent files
- L3: Cannot access drives outside home directory → Use Command Bridge
- L4: No package manager (no sudo in VM) → Compile from source or use command bridge
- L5: Chrome file:// navigation broken → Use command bridge
- L6: Session context lost on continuation → Maintain CLAUDE.md as working memory
- L7: No persistent toolchain cache → Future phase

### Phases
1. **Command Bridge** — COMPLETE (v2 deployed with timeout)
2. **Persistent Workspace** — Use ~/Claude Stuff/ and ~/Downloads/ (mounted)
3. **Drive Access** — Via command bridge (write scripts that access D:\, C:\, etc.)
4. **Toolchain Cache** — Future
5. **Session Bootstrap Protocol** — Read BATCAVE-CLAUDE.md at session start

## Rudy Phase 1: n8n Orchestration Engine

**Status:** Architecture designed, setup script written, seed workflows created AND PUSHED TO REPO (commit 293d397), pending n8n installation on host

### Key Documents (in ~/Downloads/Claude Stuff/)
- `RUDY-ARCHITECTURE.md` — Master architecture (Oracle/Alfred identity, 6 layers, Fortress Paradox)
- `RUDY-PHASE1-PLAN.md` — Day-by-day Phase 1 implementation plan
- `rudy-n8n-setup.ps1` — Automated n8n installer for USB package
- `claude-command-runner-v2.ps1` — Bridge runner with timeout

### n8n Seed Workflows (in ~/Downloads/Claude Stuff/n8n-workflows/)
1. `01-watchdog.json` — 5-min health checks, auto-restart services, disk monitoring
2. `02-email-triage.json` — Gmail poll, sender allowlist, Claude AI classification, auto-response (CC Chris)
3. `03-morning-briefing.json` — Daily 6:30 AM: system health + weather + email summary via Claude Sonnet
4. `04-owner-access-guarantee.json` — 15-min Fortress Paradox check, alert if <3 access paths active
5. `05-daily-backup.json` — 2 AM: export workflows + backup SQLite DB, 7-day rotation
6. `06-boot-recovery.json` — Detect reboot, send "I'm back online" email to Chris
7. `07-weekly-cleanup.json` — Sunday 3 AM: temp files, crash dumps, npm cache cleanup

### Pending Deployment Steps
1. Plug in USB, stage `rudy-n8n-setup.ps1` and `n8n-workflows/` to D:\
2. Run `rudy-n8n-setup.ps1` on host (installs Node.js, n8n, NSSM, creates service)
3. Configure credentials in n8n UI (Gmail OAuth2, Claude API key)
4. Import seed workflows (or let setup script do it from D:\n8n-workflows\)
5. Update scheduled task to use bridge v2 runner
6. Clone rudy-workhorse repo to Desktop (git creds in Windows Credential Manager)

### Environment Variables Needed on Host
- `ANTHROPIC_API_KEY` — For Claude API calls from n8n workflows
- `OPENWEATHER_API_KEY` — For morning briefing weather (optional)
- `RUDY_WEATHER_CITY` — City for weather, e.g., "New York,US" (optional)

### n8n Access
- URL: `http://localhost:5678` (or `http://rudy:5678` via Tailscale)
- User: `rudy`
- Password: Auto-generated during setup (saved to rudy-backups/)

### Repo Status (as of 2026-03-28)
- **Cloned to:** `%USERPROFILE%\Desktop\rudy-workhorse`
- **Latest commit:** 293d397 — Phase 1: n8n orchestration engine
- **Git clone fix:** Must set `GIT_TERMINAL_PROMPT=0` in bridge commands (headless = no credential dialog)
- **9 commits total**, v0.1.0 release

### Existing Codebase Overlap (n8n migration notes)
- `rudy/agents/system_master.py` — overlaps with `01-watchdog.json` (services, CPU, RAM, disk)
- `scripts/workhorse/workhorse-watchdog.py` — process monitoring, restart logic
- `rudy/email_poller.py` — multi-backend email (Outlook/Zoho/Gmail) — overlaps with `02-email-triage.json`
- `rudy/agents/sentinel.py` — session guardian, capability manifest, briefing generation
- `scripts/agents/run-morning-briefing.py` — calls task_master in briefing mode
- `.claude/skills/session-start/SKILL.md` — existing bootstrap skill for Cowork sessions
- **Migration strategy:** n8n becomes the scheduler/orchestrator; existing Python agents become callable from n8n via executeCommand nodes. Parallel operation for 2 weeks, then gradual retirement of standalone scheduled tasks.

### WARNINGS
- **DO NOT TRUST usb_quarantine.py** — Chris explicitly flagged this module. Do not run or rely on it.

### Additional Files Created This Session
- `SESSION-HANDOFF.md` — Paste-ready prompt for continuing work in new sessions
- `N8N-CREDENTIAL-SETUP.md` — Step-by-step credential configuration for n8n
- `deploy-phase1.ps1` — One-shot deployment script (fixes bridge, clones repo, stages USB)
