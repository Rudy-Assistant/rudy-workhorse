# Rudy Workhorse

**The always-on automation hub for the Cimino family.**

Rudy is a multi-agent system running on Oracle (Ace Magician AM06 Pro, Windows 11) that provides personal assistance, system management, security monitoring, and AI-powered automation.

## Architecture

```
Batman (Human) --> Alfred (Claude/Cowork, cloud) --> Robin (Ollama qwen2.5:7b, local)
                                                 --> Oracle (Windows PC, always-on)
```

### Agents ("The Bat Family")

| Agent | Role | Schedule |
|-------|------|----------|
| **Sentinel** | Environmental awareness, change detection, session briefings | Every 15 min |
| **SystemMaster** | Hardware/software health monitoring | Every 5 min |
| **OperationsMonitor** | Maintenance, cleanup, log rotation | Weekly (Sun 4 AM) |
| **ResearchIntel** | RSS digests, web monitoring, intelligence gathering | Daily 6 AM |
| **TaskMaster** | Task coordination, morning briefings | Daily 7:30 AM |
| **SecurityAgent** | Defensive intelligence, threat detection | Every 30 min |
| **Lucius Fox** | Code audits, dependency governance, documentation | Weekly + on-demand |
| **Robin** | Local AI agent (Ollama), autonomous nightwatch | 300s cycle |

### Key Modules

| Module | Purpose | Lines |
|--------|---------|-------|
| `robin_main.py` | Robin agent core: nightwatch loop, MCP client, autonomy | ~960 |
| `robin_autonomy.py` | Three-mode autonomy: directive > collaborative > initiative | ~590 |
| `batcave_memory.py` | Shared institutional knowledge across sessions | ~260 |
| `robin_sentinel.py` | Passive friction observer for Robin's nightwatch | ~250 |
| `presence_analytics.py` | Keyboard/mouse idle detection for presence awareness | ~1020 |
| `human_simulation.py` | Human-like interaction patterns for browser automation | ~1340 |
| `network_defense.py` | Network security monitoring and alerting | ~695 |

### Communication

- **Alfred <-> Robin**: Filesystem mailbox protocol (JSON files in `robin-inbox/` and `alfred-inbox/`)
- **Directives**: `coordination/active-directive.json` (Batman/Alfred orders for Robin)
- **Memory**: `batcave-memory/learnings.json` + auto-generated `BATCAVE.md`
- **Logs**: `rudy-logs/` (agent status JSON + text logs + crash dumps)

## Setup

### Prerequisites
- Python 3.12 (`C:\Python312`)
- Git (`C:\Program Files\Git`)
- Ollama with `qwen2.5:7b` model
- Node.js v24+ (for MCP servers)

### Boot Sequence
`batcave-startup.ps1` runs on Windows login and starts all services.
See `SOLE-SURVIVOR-PROTOCOL.md` for disaster recovery.

### Running Robin
```powershell
cd C:\Users\ccimi\Desktop\rudy-workhorse
C:\Python312\python.exe -m rudy.robin_main --nightwatch
```

## Documentation

| File | Purpose | Owner |
|------|---------|-------|
| `CLAUDE.md` | Institutional memory (people, machine, config) | All agents |
| `BATCAVE.md` | Auto-generated knowledge summary | BatcaveMemory |
| `SOLE-SURVIVOR-PROTOCOL.md` | Disaster recovery runbook | Lucius Fox |
| `README.md` | This file - project overview | Lucius Fox |

## Governance

New modules, dependencies, and architectural changes require a **Lucius Review Record** (LRR) before deployment. Run:
```python
from rudy.agents.lucius_fox import LuciusFox
lucius = LuciusFox()
lucius.execute(mode="proposal_review", proposal={"title": "...", "need": "...", "alternatives": [...]})
```

---
*Maintained by Lucius Fox. Last audit: 2026-03-29.*
