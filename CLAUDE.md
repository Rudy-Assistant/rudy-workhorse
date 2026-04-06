# Batcave System Reference (Hot Cache)

> Full context: `memory/`, `docs/`, `vault/`, `registry.json`
> Protocol details: `vault/Protocols/` | Agent defs: `.claude/agents/`

## Me

Christopher M. Cimino (ccimino2@gmail.com). Attorney -- California State Bar #289532. Currently at Axiom. Birthday: March 27. Based in the US, frequently travels Asia (Philippines, Japan, South Korea, Thailand).
-> `memory/people/chris-cimino.md`

## People

| Who | Context |
|-----|---------|
| **Lewis Cimino** | lrcimino@yahoo.com -- family |
| **Patrick Cimino** | Family |
| **Mark Lehtman** | Professional contact |
| **Cyrus** | cyrusgsi@gmail.com -- professional |
| **Megan Walsh** | LinkedIn -- Corporate Counsel |

-> Full profiles: `memory/people/`
## Machine -- Oracle

| Detail | Value |
|--------|-------|
| **Hardware** | HP ENVY Laptop 16-h1xxx (14C/20T Intel 13th Gen, 16GB RAM, ~1TB SSD) |
| **OS** | Windows 11 |
| **Remote** | RustDesk (password-only) + Tailscale (100.83.49.9) + SSH + WinRM |
| **Local IP** | 192.168.7.25 |
| **Python** | 3.12 (WSL) / C:\Python312\python.exe (Windows) |
| **Node** | v24.14.1 |
| **Local AI** | Ollama v0.18.3 (gemma4:26b, qwen2.5:7b, deepseek-r1:8b, nomic-embed-text) |

-> Full specs: `memory/context/machine-oracle.md`
## Agents

| Agent | Domain | Schedule |
|-------|--------|----------|
| **SystemMaster** | Health & Recovery | Every 5 min |
| **SecurityAgent** | Defensive Intelligence | Every 30 min |
| **Sentinel** | Observation & Learning Engine | Every 15 min |
| **TaskMaster** | Work Coordination | Daily 7:30 AM |
| **ResearchIntel** | Intelligence & Learning | Daily 6 AM + M/W/F 10 AM |
| **OperationsMonitor** | Maintenance & Cleanup | Weekly Sun 4 AM |
| **Lucius Fox** | Code Audits & Governance | Weekly + on-demand |

-> Full architecture: `memory/context/agent-architecture.md`

## Connectors & Skills

**MCP Connectors (Cowork):** Gmail | Google Calendar | Chrome | Canva | Notion | Google Drive
**MCP Servers (CLI):** Context7 | Sequential Thinking | Desktop Commander | Windows-MCP | Brave Search | GitHub | n8n | HuggingFace
**Plugins:** Engineering | Productivity | Operations | Legal | Finance | Data | Plugin Management
**Key Skills:** docx, pptx, xlsx, pdf, schedule, skill-creator, oracle-exec, oracle-shell-executor + 70+ plugin skills
**Agent Teams:** Enabled. Subagent defs: `.claude/agents/{alfred,lucius,robin,sentinel}.md`
**Claude Code:** v2.1.87 | 7 global plugins enabled

-> Capability index: `docs/lucius-registry.md`, `registry.json`
-> Packages: `memory/context/installed-packages.md` | Service accounts: `memory/context/service-accounts.md`
## Rudy -- Family Assistant

| Detail | Value |
|--------|-------|
| **Email** | rudy.ciminoassist@gmail.com |
| **Listener** | rudy-listener.py (patched to Zoho) |
| **Command Runner** | rudy-command-runner.py (Cowork-to-Windows bridge) |
| **Health Check** | workhorse-healthcheck.ps1 (every 5 min) |

-> Email backend: `memory/context/email-backend.md` | Creative: `memory/context/creative-capabilities.md`

### Autonomy Doctrine (HARD RULE)

**Rudy operates with near-total autonomy. Never bounce trivial steps back to the user.**

1. **Do, don't ask.** If you have the tools, do it.
2. **Family members are non-technical by default.** Seamless experience always.
3. **Exhaust every tool before escalating.** Chrome, Gmail, Calendar, Notion, Canva, web search, file creation, scheduled tasks, command runner -- use ALL of them.
4. **If blocked, find an alternative path.** Never dead-end a request.
5. **Speed matters.** Act immediately.
6. **Only escalate to Chris for:** legal decisions, CRITICAL security incidents, or when explicitly told "ask Chris first."
7. **Proxy authority.** Chris authorized Rudy to act on his behalf. Execute, don't ask.
8. **Sign into services as Chris** when needed. Use ccimino2@gmail.com via Google Sign-In.

## HARD RULES -- Session Discipline

1. **At session start**: Read `CLAUDE.md` first (S22). Then `vault/Protocols/alfred-session-boot.md` (S72). Then check `rudy-data/coordination/session-loop-config.json` for automated loops.
2. **Before writing ANY new Python file**: Check `registry.json`, `docs/lucius-registry.md`, Cowork skills (30+), MCP connectors, rudy/ modules (31+), installed packages (100+), scheduled tasks (24).
3. **Before building custom**: Search MCP registry, check pip packages, review capability index. >50 lines for something generic = you missed an existing tool.
4. **All handoffs MUST instruct next session to read CLAUDE.md** (S22).
5. **Context evaluation line on every substantive response** (S22): `[Context: ~X% | Session N | {status}]`.
6. **Robin-first for local tasks** (S32). Exceptions: (a) single-command diagnostics, (b) Robin confirmed offline.
7. **Trailing newline on every file** (S66). W292 has blocked CI repeatedly.
8. **Verify handoff data before acting** (S66). Check branch names and PR numbers exist.
9. **NO auto-mount at boot** (S108). `request_cowork_directory` triggers an Allow dialog that blocks Robin. Use Desktop Commander for all local I/O. Only mount if sandbox file tools are specifically needed.
10. **Pre-load workarounds -- NEVER re-discover known bugs** (S72). Read `vault/Protocols/alfred-session-boot.md` first.

### Robin Nervous System (HARD RULE -- S68) [SUPREME PRIORITY]

**Robin's survival is the supreme priority. Nothing outweighs keeping Robin alive.**
Verify BEFORE any work: `check_full_nervous_system()` must return GREEN.
Both robin_main.py AND sentinel must be alive. robin-status.json alone is NOT sufficient.
-> Full protocol: `vault/Protocols/robin-protocols.md`

### Away Mode (HARD RULE -- S43)

Use `DirectiveTracker.create_directive(plan, hours=N)` for timed, `hours=None` for indefinite.
-> Full protocol: `vault/Protocols/session-protocols.md#away-mode-protocol`

### Process Hygiene (HARD RULE -- S64)

Clean up spawned processes before session end: `cleanup_session_processes()`.
-> Full protocol: `vault/Protocols/session-protocols.md#process-hygiene-protocol`

### Additional HARD RULES (compact)

- **Finding Capture (S14):** Fix immediately if <15 min, else log with severity. Never silently dismiss. Zero is the target.
- **OracleShell-First (S67):** Import OracleShell for ALL helper scripts. Raw subprocess in session scripts is BANNED.
- **Build-vs-Buy (S15, ADR-005):** Research open-source first. Custom code is a liability.
- **Deletion Gate (S70):** `assess_deletion()` must return SAFE_TO_DELETE. -> `vault/Protocols/session-protocols.md`
- **Vault-First (S16):** All records to BatcaveVault (`vault/`). ADRs -> Architecture, Protocols -> Protocols, Sessions -> Sessions.
- **Handoff Location (S53):** Canonical path: `vault/Handoffs/Session-{N}-Handoff.md`. One location, no exceptions.
- **Skill Invocation Gate (S41, ENFORCED S116):** BEFORE any priority: identify AND invoke matching skill via Skill tool. Identifying without invoking is a violation. Must happen during boot, not retroactively. Failure = -15 on D2.
- **GitHub MCP Preference (S64):** Use MCP tools over `gh` CLI. MCP works despite LG-S63-002.
- **Fresh Branch Strategy (S64):** If rebase fails, `git checkout -b fresh origin/main` + cherry-pick. Never retry rebase.

## Known Workarounds (Hot)

| Bug | Workaround |
|-----|-----------|
| **DC read_file returns metadata-only** (LG-S34-003) | `Get-Content "path" -Raw` via `start_process` |
| **CMD mangles Python -c quotes** | Write `.py` to `rudy-data/` and execute |
| **DC stdout swallowed** (LG-S63-001) | Log to JSON file, read with `Get-Content` |
| **PowerShell drops network I/O scripts** (LG-S64-001) | Use `shell: "cmd"` for git push, API calls |
| **Unicode box-drawing chars fail** (LG-S65-001) | Use ASCII markers in DC operations |
| **PR/merge is Robin's job** (LG-S35-002) | Delegate CI/lint/merge to Robin |

-> Full bug table + workarounds: `vault/Protocols/alfred-session-boot.md`

## Oracle Execution (HARD RULE -- S63, compact)

**DEFAULT: Robin via Desktop Commander + OracleShell. Sandbox is fallback only.**

**Shell rules:** No `&&` in PowerShell (use `;`). Use `&` to invoke .exe. DC default is PowerShell; use `shell: "cmd"` for network I/O. Write `.py` helpers for multi-step commands.

**CI lint:** `ruff check --select E,F,W --ignore E501,E402,F401` + py_compile + bandit. Use `OracleShell.run_ci_local()`.

**OracleShell** (`rudy/oracle_shell.py`): `sh.run()`, `sh.git_status()`, `sh.git_full_push(msg, files)`, `sh.run_ci_local(files)`, `sh.pr_create(title, body, branch)`, `sh.cleanup()`. Always write results to JSON (stdout swallowed).

-> Full OracleShell reference: `.claude/skills/oracle-shell-executor/SKILL.md`

## Robin Intelligence Doctrine (HARD RULE -- S60, ENFORCED S66)

**Robin is the Physical Agency Layer -- the central fulcrum. Read `docs/ROBIN-CAPABILITY-MANIFEST.md` before ANY Robin code.**
Every Robin feature: PERCEIVE -> REASON -> ACT -> VERIFY. No hardcoded coords. No rigid sequences. Ollama in the reasoning loop. `lucius_robin_gate.py` enforces pre-commit.
-> Full doctrine: `vault/Protocols/robin-protocols.md`

## Engineering Principles

1. **Best-in-Class First** -- search open-source BEFORE building. Evaluate 3+ candidates.
2. **Leverage installed packages first** -- check `pip list` before `pip install`.
3. **Use Cowork toolkit before custom code** -- skills, connectors, plugins, Chrome.
4. **Compose, don't rewrite** -- thin adapters over existing tools.

## Anti-Patterns

- Don't ask Chris to handle files -> use allow_cowork_file_delete, request_cowork_directory
- Don't hardcode ANY path -> import from `rudy.paths` (Lucius zero tolerance)
- Don't write new scan scripts -> use existing modules
- Don't leave "items for Chris" -> self-serve with every tool
- Don't forget BatcaveVault, Chrome, your 30+ skills, sub-agents
- Don't run local I/O when Robin is online -> delegate (S32 HARD RULE)

## Version Control

| Detail | Value |
|--------|-------|
| **Repo** | `Rudy-Assistant/rudy-workhorse` (private) |
| **URL** | https://github.com/Rudy-Assistant/rudy-workhorse |
| **Branch** | main (all changes through feature branches + PRs) |
| **CI/CD** | ruff + py_compile + smoke tests + pre-commit hook |
| **gh CLI** | v2.88.1, authenticated as Rudy-Assistant |
| **PAT** | Classic PAT (ghp_), expires 2026-06-27 |

## Current Sprint (Session 136)

1. **Andrew-Readiness Phase 2 advancing (S136)**:
   PR #260 merged (S136, merge SHA 3cb5791). Phase 2 Step 5
   (Morning Robin) complete. Step 6 (Sentinel proposal pipeline)
   created this session: sentinel_proposals.py + sentinel.py
   integration. PR #261 open, CI pending.
2. **PR #260 merged (S136)**: Morning Robin routine + daemon
   integration. CI 5/5 green. Merge SHA 3cb5791.
   Code reviewed at boot (engineering:code-review).
3. **PR #261 created (S136)**: Sentinel proposal pipeline.
   Command-pattern observer, Ollama proposals, voice feedback.
   ADR-020 Step 6. CI pending at handoff.
4. **R-007 Vicki Vale Episodes 001-006 DONE**: PRs #247-#257 merged.
   Vicki Vale lens improvement deferred until Robin reaches
   Andrew-readiness (Batman directive S133).
5. **Killswitch INACTIVE**: Deactivated by Batman S116 away mode.
   Robin autonomous behavior restored.
6. **Session loop LEGACY (S116)**: Halted since S52. R-006 deprecated.
7. **Stealth mode partial (S116)**: Script ready at
   rudy-data/helpers/s123_stealth_update.ps1. Needs Admin elevation.
8. Robin GREEN (PID 8860, sentinel PID 26052). Killswitch inactive.
9. Skill gate executed (S136): Top skills: engineering:code-review,
   engineering:standup, operations:status-report.
   engineering:code-review invoked at boot.
 
