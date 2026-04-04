# Rudy Workhorse

**The always-on automation hub for the Cimino family.**

Rudy is a multi-agent system running on Oracle (HP ENVY Laptop 16-h1xxx, Windows 11) that provides personal assistance, system management, security monitoring, and AI-powered automation. The system operates continuously, with Robin (local AI agent) running 24/7 and Alfred/Lucius (cloud agents) providing mentorship and governance via Claude/Cowork sessions.

## Architecture

```
Batman (Human) --> Alfred (Claude Opus, cloud sessions)
                     |
                     +--> Robin (Ollama qwen2.5:7b, local, always-on)
                     |      +-- Sentinel (observer, every 15 min)
                     |      +-- Nightwatch (autonomous overnight ops)
                     |      +-- MCP client (Windows-MCP, Snapshot, Type, Click)
                     |
                     +--> Lucius Fox (Claude, governance/audit sessions)
                     |
                     +--> Oracle (Windows 11 PC, scheduled tasks, services)
```

### Core Design Principles (from MISSION.md)

1. **Robin works without Alfred.** Robin runs on Ollama (free, local).
   Alfred makes Robin better, but Robin is useful on his own.
2. **Alfred's purpose is self-obsolescence.** Every session should ask:
   "What can Robin now do that he couldn't before?"
3. **Route through Robin first.** Every task routed through Robin is
   training data for his growth.

### Agents ("The Bat Family")

| Agent | Role | Runtime | Schedule |
|-------|------|---------|----------|
| **Robin** | Local AI agent: autonomous ops, MCP interaction, nightwatch | Ollama qwen2.5:7b | 10s poll cycle, always-on |
| **Alfred** | Cloud mentor: architecture, code, orchestration | Claude Opus (Cowork) | On-demand sessions |
| **Lucius Fox** | Governance: audits, scoring, dependency review | Claude (Cowork) | Weekly + on-demand |
| **Sentinel** | Environmental awareness, change detection, briefings | Python scheduled task | Every 15 min |
| **SystemMaster** | Hardware/software health monitoring | Python scheduled task | Every 5 min |
| **SecurityAgent** | Defensive intelligence, threat detection | Python scheduled task | Every 30 min |
| **TaskMaster** | Task coordination, morning briefings | Python scheduled task | Daily 7:30 AM |
| **ResearchIntel** | RSS digests, web monitoring, intelligence | Python scheduled task | Daily 6 AM |
| **OperationsMonitor** | Maintenance, cleanup, log rotation | Python scheduled task | Weekly Sun 4 AM |

### Key Modules

| Module | Purpose |
|--------|---------|
| `rudy/robin_main.py` | Robin core: orchestrator loop, MCP client, autonomy engine |
| `rudy/robin_autonomy.py` | Three-mode autonomy: directive, collaborative, initiative |
| `rudy/robin_liveness.py` | Nervous system health checks, process restart |
| `rudy/robin_sentinel.py` | Passive observer for Robin's nightwatch cycles |
| `rudy/bridge_runner.py` | Robin-to-Cowork bridge: session launching, inbox polling |
| `rudy/agents/sentinel.py` | Sentinel agent: env monitoring, governance, boot phases |
| `rudy/agents/lucius_fox.py` | Lucius Fox: audit engine, gate checks, scoring |
| `rudy/oracle_shell.py` | Unified execution layer for Oracle commands |
| `rudy/batcave_memory.py` | Shared institutional knowledge across sessions |
| `rudy/process_hygiene.py` | Orphaned process detection and cleanup |

### Communication

- **Alfred <-> Robin**: Filesystem mailbox protocol (JSON files in `robin-inbox/` and `alfred-inbox/`)
- **Directives**: `rudy-data/coordination/active-directive.json` (Batman/Alfred orders for Robin)
- **Session Loop**: Robin orchestrates Alfred/Lucius session cycles via `session-loop-config.json`
- **Memory**: `batcave-memory/learnings.json` + auto-generated `BATCAVE.md`
- **Logs**: `rudy-logs/` (agent status JSON, text logs, crash dumps)

### Governance (ADR-004, ADR-016)

All code changes go through feature branches and PRs with 5 CI checks:
lint (ruff), bandit (security), batcave-paths (no hardcoded paths),
pip-audit (dependency vulnerabilities), and smoke-test (import validation).

Lucius Fox provides three gates: `session_start_gate()` (boot),
`pre_commit_check()` (before push), and `post_session_gate()` (before handoff).

## Setup

### Prerequisites
- Python 3.12 (`C:\Python312\python.exe`)
- Git + GitHub CLI (`gh` authenticated as Rudy-Assistant)
- Ollama v0.18.3+ with `qwen2.5:7b` and `deepseek-r1:8b` models
- Node.js v24+ (for MCP servers)

### Boot Sequence
`batcave-startup.ps1` runs on Windows login and starts all services.
Robin starts via `scripts/robin-startup.bat` (in Windows Startup folder).
See `SOLE-SURVIVOR-PROTOCOL.md` for disaster recovery.

### Running Robin
```powershell
cd C:\Users\ccimi\rudy-workhorse
C:\Python312\python.exe -m rudy.robin_main
```

Robin automatically enters full orchestrator mode (nightwatch + inbox
polling + autonomy engine). The `--nightwatch` flag is deprecated as
of S97/PR #194.

## Documentation

| File | Purpose | Owner |
|------|---------|-------|
| `CLAUDE.md` | Institutional memory: people, machine, agents, HARD RULES | All agents |
| `docs/MISSION.md` | Architectural rationale and Robin Intelligence Doctrine | Batman/Alfred |
| `docs/ROBIN-CAPABILITY-MANIFEST.md` | Robin's current capabilities and MCP tools | Alfred |
| `SOLE-SURVIVOR-PROTOCOL.md` | Disaster recovery runbook | Lucius Fox |
| `vault/Protocols/` | Operational protocols (boot, roadmap, process map) | Alfred/Lucius |
| `vault/Architecture/` | Architecture Decision Records (ADRs) | Lucius Fox |
| `vault/Handoffs/` | Session handoff files for continuity | Alfred/Lucius |
| `vault/Roadmap/` | Strategic roadmap and review history | Batman/Lucius |
| `vault/Dashboards/` | Interactive HTML dashboards (Robin growth, etc.) | Alfred |

## Project Stats (as of S98)

- **Sessions**: 98 Alfred + 53 Lucius
- **PRs Merged**: 83+
- **Agents**: 9 (Robin, Alfred, Lucius, Sentinel, SystemMaster, SecurityAgent, TaskMaster, ResearchIntel, OperationsMonitor)
- **Scheduled Tasks**: 24
- **HARD RULES**: 15+ (accumulated over 98 sessions of institutional learning)

---
*Maintained by Alfred/Lucius. Last updated: S98 (2026-04-04).*
