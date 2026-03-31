# Sub-Agent Architecture

Six agents manage the Workhorse autonomously. All agents are in `rudy/agents/`, write status to `rudy-logs/<agent>-status.json`, and are invocable via the command runner.

## Agent Table

| Agent | Domain | Schedule | Key Responsibilities |
|-------|--------|----------|----------------------|
| **SystemMaster** | Health & Recovery | Every 5 min | Service monitoring, process restart, disk space, log rotation, network checks |
| **SecurityAgent** | Defensive Intelligence | Every 30 min | Network anomaly detection, file integrity, breach monitoring, event log analysis |
| **Sentinel** | Awareness & Growth | Every 15 min | Notices changes, spots opportunities, micro-improvements, tracks agent staleness, RustDesk session detection, incoming request monitoring, device events, service health |
| **TaskMaster** | Work Coordination | Daily 7:30 AM | Morning briefings, agent health monitoring, work queue management |
| **ResearchIntel** | Intelligence & Learning | Daily 6 AM + M/W/F 10 AM | RSS feed digests, capability inventory, 4-layer dependency health audit, tool recommendations |
| **OperationsMonitor** | Maintenance & Cleanup | Weekly Sun 4 AM | Temp cleanup, cache purge, result archiving, privacy drift detection, disk audit |
| **Lucius Fox** | Code Audits & Governance | Weekly (Sunday) + on-demand | Code audits, dependency governance, documentation ownership |

## Agent Governance Layer

The Orchestrator (`rudy/agents/orchestrator.py`) maps the full toolkit to 8 specialized domains and routes tasks with escalation policies. The WorkflowEngine (`rudy/agents/workflow_engine.py`) executes multi-step workflows with LangGraph checkpointing (falls back to sequential if LangGraph unavailable).

| Domain | Agents | Modules | Cowork Skills | Escalation |
|--------|--------|---------|---------------|-------------|
| **Infrastructure** | SystemMaster | connection_monitor, admin, vpn_manager, api_server | debug, incident-response, deploy-checklist | notify_after |
| **Security** | SecurityAgent, Sentinel | network_defense, presence, intruder_profiler, pentest, phone_check | risk-assessment, incident-response | notify_after |
| **Intelligence** | ResearchIntel | web_intelligence, knowledge_base, nlp, ocr, local_ai | documentation, tech-debt, architecture | self_resolve |
| **Legal** | (Cowork-only) | nlp, ocr, knowledge_base | 9 legal skills (contract review, NDA triage, etc.) | ask_first |
| **Operations** | OperationsMonitor | env_setup, obsolescence_monitor | runbook, process-doc, status-report | self_resolve |
| **Creative** | (Cowork-only) | voice, voice_clone, avatar | docx, pptx, xlsx, pdf + Canva | self_resolve |
| **Financial** | (via scheduled task) | financial | xlsx | notify_after |
| **Communications** | TaskMaster | email_multi, movement_feed | task-management, memory-management | self_resolve |

## Execution Framework

LangGraph (stateful workflows with SQLite checkpointing) — installed via `install-langgraph.py`. Pre-built workflows: morning_briefing, security_incident, self_improvement, maintenance.

**Framework decision**: Evaluated CrewAI (~20k stars), AutoGen (~29k), Swarms (~8k), Agency Swarm (~5k). Chose LangGraph (~9k) because: (a) already have langchain installed, (b) state persistence + human-in-the-loop fit our escalation model, (c) lightweight add-on vs. full framework replacement.

## Proactive Dependency Health (Zealous Inquisitor)

4-layer audit runs M/W/F 10 AM via ResearchIntel. Core question: "Is this dependency still the BEST solution for its function?"

| Layer | What | Method |
|-------|------|--------|
| **1: Import** | Does it load on Python 3.12? | subprocess import check |
| **2: Memory** | Known superseded packages | SUPERSEDED dict |
| **3: Live Web** | Is something better available? | PyPI API, GitHub API, web search, local AI synthesizes gathered evidence ONLY |
| **4: System** | OS/driver/tool health | Windows Update pending, driver problems, core tool versions, disk space |

**Key principle**: Local AI (Ollama) is NEVER used to judge packages from training data. It only synthesizes facts gathered from live web sources.

**Reports**: `rudy-logs/dependency-health.json`

## Lucius Review Record (LRR) Process

Before adding any new module, dependency, or architectural change:
1. Submit proposal to Lucius (mode="proposal_review")
2. Lucius searches for existing alternatives
3. Lucius issues verdict: adopt existing / adapt / build custom
4. If custom approved: implementation spec with test criteria
5. LRR stored in rudy-data/lucius-reviews/ for audit trail

## Scheduled Task Wrappers (`scripts/agents/`)

| Script | Scheduled Task | Agent | Mode |
|--------|---------------|-------|------|
| `run-system-master.py` | WorkhorseHealthCheck (5 min) | SystemMaster | full |
| `run-security-agent.py` | (every 30 min) | SecurityAgent | full |
| `run-sentinel.py` | (every 15 min) | Sentinel | full |
| `run-morning-briefing.py` | morning-briefing (7:30 AM) | TaskMaster | briefing |
| `run-research-digest.py` | daily-research-feed (6 AM) | ResearchIntel | digest |
| `run-self-improvement.py` | self-improvement (M/W/F 10 AM) | ResearchIntel | capability |
| `run-weekly-maintenance.py` | weekly-maintenance (Sun 4 AM) | OperationsMonitor | full |
| `run-all-agents.py` | (manual) | All agents | full |

## Agent Runner CLI

Entry point: `python -m rudy.agents.runner [AGENT] [--mode MODE]`

| Command | What It Does |
|---------|---------------|
| `python -m rudy.agents.runner system_master` | Full health check |
| `python -m rudy.agents.runner security_agent` | Defensive sweep |
| `python -m rudy.agents.runner sentinel` | Change detection (≤30s) |
| `python -m rudy.agents.runner task_master --mode briefing` | Morning briefing |
| `python -m rudy.agents.runner research_intel --mode digest` | Daily research digest |
| `python -m rudy.agents.runner operations_monitor` | Weekly maintenance |
| `python -m rudy.agents.runner ALL` | Run all agents sequentially |
| `python -m rudy.agents.runner health` | Read status files (no execution) |

Aliases: `system`, `security`, `ops`, `research`, `task`, `intel`

## Agent GitHub Integration

- **ObsolescenceMonitor** — `file_github_issues()` auto-files high-priority audit findings
- **Sentinel** — `_file_github_anomalies()` files actionable observations
- **All agents** — can use `rudy.integrations.github_ops.get_github()` for issue/PR operations
- **Command runner scripts** — import `rudy.env_setup.bootstrap()` to ensure tools are on PATH

## Invoking Agents from Cowork

Deploy a `.py` file to `rudy-commands/` that imports and runs the agent:
```python
import sys; sys.path.insert(0, r"C:\Users\C\Desktop")
from rudy.agents.system_master import SystemMaster
SystemMaster().execute(mode="full")
```