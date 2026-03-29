# Robin Bridge — Oracle-Side Specification

Describes Robin's responsibilities and the communication protocol between
Robin (local agent on Oracle) and Alfred (cloud AI in Cowork).

Companion to: alfred-skills/docs/ADR-001-robin-bridge.md

## Task Polling

Robin polls alfred-skills/docs/robin-tasks/ every 30 minutes.

When status: pending found:
1. Change to claimed, push
2. Execute locally
3. Fill Result section
4. Change to completed/failed, push

## Proactive Schedule

| Task | Frequency | Agent |
|------|-----------|-------|
| System health | 15 min | system_master |
| Security sweep | 1 hour | security_agent |
| Poll alfred-skills | 30 min | robin_bridge |
| Token freshness | Daily | robin_bridge |
| Stale task scan | 2 hours | task_master |
| Log rotation | Daily | operations_monitor |
| Model updates | Weekly | robin_bridge |
| Improvement prompts | When idle | research_intel |

## Communication Back to Alfred

- GitHub: Push results to rudy-workhorse, update tasks in alfred-skills
- Email: Status reports to Batman(s) via Rudy email
- Logs: Desktop/rudy-logs/ for local inspection
- Presence dashboard: Update presence-dashboard.jsx data

## Authorization

Robin has full Batman proxy authorization for local ops.
Can: enter passwords, configure tokens, handle sudo/2FA, install software,
modify system files, restart services.

Cannot: send emails without logging, delete without backup, break recovery.

## Implementation

Primary: rudy/robin_bridge.py (to be built)
Dependencies: rudy/local_ai.py, rudy/agents/runner.py
Config: Reads alfred-skills CLAUDE.md for behavioral directives
