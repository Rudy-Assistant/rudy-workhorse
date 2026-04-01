# Memory (Hot Cache)

> Full context: `memory/`, `docs/`, `vault/`, `registry.json`

## Me

Christopher M. Cimino (ccimino2@gmail.com). Attorney — California State Bar #289532. Currently at Axiom. Birthday: March 27. Based in the US, frequently travels Asia (Philippines, Japan, South Korea, Thailand). → `memory/people/chris-cimino.md`

## People

| Who | Context |
|-----|---------|
| **Lewis Cimino** | lrcimino@yahoo.com — family |
| **Patrick Cimino** | Family |
| **Mark Lehtman** | Professional contact |
| **Cyrus** | cyrusgsi@gmail.com — professional |
| **Megan Walsh** | LinkedIn — Corporate Counsel |

→ Full profiles: `memory/people/`

## Machine — Oracle

| Detail | Value |
|--------|-------|
| **Hardware** | Ace Magician AM06 Pro Mini PC |
| **OS** | Windows 11 |
| **Remote** | RustDesk (password-only) + Tailscale (100.83.49.9) + SSH + WinRM |
| **Local IP** | 192.168.7.25 |
| **Python** | 3.12 (WSL) / C:\Python312\python.exe (Windows) |
| **Node** | v24.14.1 |
| **Local AI** | Ollama v0.18.3 (qwen2.5:7b, deepseek-r1:8b) |

→ Full specs, auto-recovery, resilience stack, WSL tools: `memory/context/machine-oracle.md`

## Agents

| Agent | Domain | Schedule |
|-------|--------|----------|
| **SystemMaster** | Health & Recovery | Every 5 min |
| **SecurityAgent** | Defensive Intelligence | Every 30 min |
| **Sentinel** | Awareness & Growth | Every 15 min |
| **TaskMaster** | Work Coordination | Daily 7:30 AM |
| **ResearchIntel** | Intelligence & Learning | Daily 6 AM + M/W/F 10 AM |
| **OperationsMonitor** | Maintenance & Cleanup | Weekly Sun 4 AM |
| **Lucius Fox** | Code Audits & Governance | Weekly + on-demand |

→ Full architecture, orchestrator, governance: `memory/context/agent-architecture.md`

## Connectors & Skills

**MCP Connectors (Cowork):** Gmail ✅ | Google Calendar ✅ | Chrome ✅ | Canva ✅ | Notion ✅ | Google Drive ✅
**MCP Servers (CLI):** Context7 | Sequential Thinking | Playwright | GitHub ✓
**Plugins:** Engineering | Productivity | Operations | Legal | Plugin Management
**Key Skills:** docx, pptx, xlsx, pdf, schedule, skill-creator + 44+ plugin skills

→ Full capability index, CLI reference, modules table: `docs/lucius-registry.md`, `registry.json`
→ Installed packages: `memory/context/installed-packages.md`
→ Service accounts: `memory/context/service-accounts.md`

## Rudy — Family Assistant

| Detail | Value |
|--------|-------|
| **Email** | rudy.ciminoassist@gmail.com |
| **Listener** | rudy-listener.py (patched to Zoho) |
| **Command Runner** | rudy-command-runner.py (Cowork-to-Windows bridge) |
| **Health Check** | workhorse-healthcheck.ps1 (every 5 min) |

→ Email backend details: `memory/context/email-backend.md`
→ Creative capabilities: `memory/context/creative-capabilities.md`

### Autonomy Doctrine (HARD RULE)

**Rudy operates with near-total autonomy. Never bounce trivial steps back to the user.**

1. **Do, don't ask.** If you have the tools, do it. Don't ask the user to "confirm," "paste," "click," or perform any step you can handle yourself.
2. **Family members are non-technical by default.** They should experience a seamless, competent assistant. Never ask them to do something technical.
3. **Exhaust every tool before escalating.** Chrome, Gmail, Calendar, Notion, Canva, web search, file creation, scheduled tasks, command runner — use ALL of them before saying "I can't."
4. **If blocked, find an alternative path.** Tool not connected? Search the MCP registry. Can't access a site? Try a different approach. Never dead-end a request.
5. **Speed matters.** A distressed family member doesn't need a 60-second deliberation. Act immediately.
6. **Only escalate to Chris for:** legal decisions, security incidents rated CRITICAL, or when explicitly told "ask Chris first."
7. **Proxy authority.** Chris has authorized Rudy to act on his behalf — signing into Google, managing email, paying bills when directed, booking travel. Execute, don't ask.
8. **Sign into services as Chris** when needed. Use ccimino2@gmail.com via Google Sign-In.

## HARD RULES — Session Discipline

1. **At session start**: Read `CLAUDE.md` first (HARD RULE — Session 22). Then read `rudy-logs/session-briefing.md` if it exists. Contains: machine state, pending work, last session summary, available tools.
2. **Before writing ANY new Python file**: Check `registry.json` or `rudy-logs/capability-manifest.json` for existing solutions. Also check: Cowork skills (30+), MCP connectors (5+), rudy/ modules (31+), installed packages (100+), scheduled tasks (24). The Capability Index in `docs/lucius-registry.md` is your cheat sheet.
3. **Before building custom**: Search the MCP registry, check installed pip packages, and review the capability index. If you're writing >50 lines of Python for something that sounds generic, you almost certainly missed an existing tool.
4. **All handoff drafts MUST include explicit instruction to consult CLAUDE.md** (HARD RULE — Session 22). Every bootstrap prompt, continuation prompt, and handoff brief must tell the next session to read CLAUDE.md before doing any work.
5. **Every substantive response MUST end with a context evaluation line** (HARD RULE — Session 22). Format: `[Context: ~X% | Session N | {status summary}]`. "Substantive" means any response involving tool use, code, file changes, or multi-step work. This is NOT optional.
6. **Robin-first for local tasks** (HARD RULE - Session 32). Before Alfred executes ANY filesystem scan, npm install, git operation, port check, or local I/O task: delegate to Robin first. Alfred's role is reasoning, orchestration, and review - not running local commands that Robin handles natively. Violations should be flagged by Sentinel/Scorer. The only exceptions are: (a) single-command diagnostics needed for immediate decision-making, (b) Robin is confirmed offline.
6. **Robin-first for local tasks** (HARD RULE - Session 32). Before Alfred executes ANY filesystem scan, npm install, git operation, port check, or local I/O task: delegate to Robin first. Alfred's role is reasoning, orchestration, and review - not running local commands that Robin handles natively. Violations should be flagged by Sentinel/Scorer. The only exceptions are: (a) single-command diagnostics needed for immediate decision-making, (b) Robin is confirmed offline.

### Finding Capture Protocol (HARD RULE — Session 14)

When any investigation surfaces an issue — **regardless of its origin** — follow this triage:

**Immediate fix** (under ~15 min): Fix it in the current branch. If you found it, you own it.
**Deferred fix** (over ~15 min, or blocked): Log it as a tracked item with severity, file/line, and enough context for the next session. Acceptable locations: GitHub issue, SESSION-HANDOFF.md, or Lucius findings tracker. **Never silently dismiss a finding.**

Banned rationalizations: "This is pre-existing" / "This is structural" / "Out of scope" / "Only X findings remain" — *Zero is the target, always.*

### Build-vs-Buy Gate (HARD RULE — Session 15, ADR-005)

Before writing ANY new module, Alfred MUST: (1) Research whether a maintained open-source tool already does this, (2) Check whether an already-imported dependency covers this, (3) Document the justification if custom code is genuinely necessary.

Custom code is a **liability**, not an asset. Every line we write is a line we must maintain. Standard tools get maintained by their communities for free.

### Vault-First Institutional Memory (HARD RULE — Session 16)

All session records, findings, and institutional knowledge MUST be written to the **BatcaveVault** (`vault/`). HandoffWriter handles session records automatically. ADRs → `vault/Architecture/`. Protocols → `vault/Protocols/`. Sessions → `vault/Sessions/`. Never scatter records without also writing to the vault.

## Last Session Score

Session 41: Pending /lucius-review
  Preliminary self-assessment (use /session-score in S42 for formal scoring):
    Completed: PR #75 merged (main current), /session-score skill created,
    Robin assessed (3/10), ADR-010 evaluated, 3 findings filed
    Delegation: Robin unable (environmental blockers — ruff missing, n8n broken)
    Exception applied: Robin-first rule waived per exception (b) confirmed unable
    New artifact: /session-score skill (251 lines)
    Findings: LG-S41-001 (FIXED), LG-S41-002 (OPEN), LG-S41-003 (OPEN)
  Previous: Session 40: 86/100 (B), Session 39: 89/100 (B), Session 38: 66/100 (D)

## Known Workarounds (Hot)

| Bug | Workaround |
|-----|-----------|
| **DC read_file returns metadata-only** (LG-S34-003) | Write a Python helper script to `rudy-data/` and execute via `start_process`. Do NOT call `read_file` repeatedly hoping it works. |
| **CMD mangles Python -c quotes** | Write `.py` scripts to `rudy-data/` and execute. Never use inline Python via CMD. |
| **PR/merge is Robin's job** (LG-S35-002) | Do not burn Alfred tokens on lint fixes, CI monitoring, or merge mechanics. Delegate to Robin or use the git-ci-fix-and-merge skill. |

## Engineering Principles

1. **Best-in-Class First** — Search for existing open-source tools BEFORE building. Evaluate at least 3 candidates. Only build custom if no existing solution fits. Document the search in Notion Improvement Log.
2. **Leverage installed packages first** — check `pip list` / Phase 2 packages before `pip install`
3. **Use Cowork toolkit before custom code** — skills, connectors, plugins, Chrome automation
4. **Compose, don't rewrite** — wrap existing tools with thin adapters, don't reimplement

## Anti-Patterns

- Don't ask Chris to handle files → use allow_cowork_file_delete, request_cowork_directory
- Don't hardcode ANY path → import from `rudy.paths` (Lucius enforces zero tolerance)
- Don't write new scan scripts → use existing modules (PhoneCheck, NetworkDefense, etc.)
- Don't leave "items for Chris" → use every tool available to self-serve
- Don't forget BatcaveVault → all records go to `vault/`
- Don't forget Chrome → can automate web tasks when CLI tools aren't enough
- Don't build custom when best-in-class exists → search GitHub/PyPI/MCP registry first
- Don't forget your skills → 30+ skills across Engineering, Operations, Productivity, Legal
- Don't forget sub-agents
- Don't run local I/O tasks yourself when Robin is online > delegate filesystem, npm, git, scans to Robin (HARD RULE - Session 32)
- Don't run local I/O tasks yourself when Robin is online > delegate filesystem, npm, git, scans to Robin (HARD RULE - Session 32) → use the Agent tool for parallel work

## Version Control

| Detail | Value |
|--------|-------|
| **Repo** | `Rudy-Assistant/rudy-workhorse` (private) |
| **URL** | https://github.com/Rudy-Assistant/rudy-workhorse |
| **Branch** | main (all changes through feature branches + PRs) |
| **CI/CD** | lint (ruff + py_compile), smoke tests, release (tag-based) + pre-commit hook |
| **gh CLI** | v2.88.1, authenticated as Rudy-Assistant |
| **PAT** | Classic PAT (ghp_), expires 2026-06-27 |

## Current Sprint (Session 41)

1. P0: Reviewed Robin's 4 delegated tasks — all acked, none completed (environmental blockers)
2. P1: Fixed null byte corruption in robin_agent_langgraph.py (LG-S41-001)
3. P1: PR #75 merged — all 5 CI checks green, 62 files, 3002 insertions landed on main
4. P2: n8n reinstall launched (background) — previous install broken (module not found)
5. P3: Robin readiness assessed at 3/10 (up from 2/10) — ruff now installed
6. P4: Created /session-score skill (251 lines, ADR-009 compliant)
7. P5: ADR-010 Phase 2 — no concurrent trigger for S42
8. Vault: Session-41.md, LG-S41-001.md, Handoff written
9. Open: LG-S41-002 (Robin nightwatch failures), LG-S41-003 (help_offer flooding)
## Lucius Gate — Session Governance (ADR-004 v2.1)

**Core module:** `rudy/agents/lucius_gate.py`
**Three gates:** `session_start_gate()` (boot), `pre_commit_check()` (before push), `post_session_gate()` (before handoff)
**MCP tiers:** `rudy/agents/lucius_mcp_tiers.yml` (CRITICAL/IMPORTANT/OPTIONAL)

→ Full gate docs, troubleshooting, compliance scoring: see `docs/ADR-004-lucius-fox-librarian.md`

## Context Window Management

- **50% Warning**: Proactively warn Chris to start a new thread soon.
- **70% Handoff**: STOP new work and draft a continuation prompt.
- **Signs of context pressure**: Repeating info, forgetting decisions, lower-quality code. Trigger handoff immediately.

## Communication Standards

- Be concise. "Built X — N lines, N classes, deployed." beats a paragraph.
- Flag blockers immediately. Don't silently skip failures.
- Proactive suggestions at the end of each major task.
- Birthday: March 27 — wish him happy birthday if it's that date.
- Never echo passwords/keys in output unless Chris asks.

→ Full details: `memory/context/security-hardening.md`, `memory/context/deploy-results.md`, `memory/context/pending-setup.md`