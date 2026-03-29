# SOLE SURVIVOR RECOVERY PROTOCOL
# Batcave Operations Continuity Plan
# Last updated: 2026-03-29 Session 5

## Purpose
If Oracle (the host machine) is the only surviving system -- Alfred (cloud) is
unreachable, Batman is unavailable, and no external services are responding --
Robin must maintain ALL Bat Family operations alone.

## Trigger Conditions
- Alfred API unreachable for >2 consecutive nightwatch cycles (10+ minutes)
- No new messages in robin-inbox/ for >30 minutes during active directive
- System reboot detected (batcave-startup.log shows fresh boot)
- Network connectivity lost (Ollama still works locally)

## Immediate Actions (First 60 seconds)

### 1. Verify Core Services
Check that these are running. Start any that are missing:
- Ollama (localhost:11434) -- Robin's brain
- Nightwatch loop -- Robin's heartbeat  
- File system access -- rudy-data/, rudy-workhorse/, rudy-logs/

### 2. Read Last Known State
- Read: batcave-memory/BATCAVE.md (institutional knowledge)
- Read: batcave-memory/session-logs/ (most recent session summary)
- Read: coordination/active-directive.json (any pending orders)
- Read: robin-inbox/*.json (any unprocessed Alfred messages)
- Read: rudy-logs/batcave-startup.log (boot status)

### 3. Log Recovery Entry
Write to rudy-logs/robin-ops-YYYYMMDD.json:
{
  "task": "sole-survivor-activation",
  "timestamp": "<now>",
  "reason": "<trigger condition>",
  "last_alfred_contact": "<timestamp>",
  "active_directive": "<directive or null>",
  "success": true
}

## Ongoing Operations (Sole Survivor Mode)

### Continue All Logs
- robin-ops log: every action, every cycle
- robin-sentinel observations: environment health
- batcave-startup.log: if services restart

### Monitor for Recovery
Every nightwatch cycle, check:
- Can we reach Alfred? (alfred-inbox/ for new messages)
- Is Batman present? (HID idle detection)
- Is network restored? (test external connectivity)

### Execute Standing Directives
If active-directive.json has an unexpired directive, continue working on it.
Robin may not complete it as well as Alfred would, but partial progress is
better than idle waiting.

### Self-Maintenance
- If disk space <10%, clean old logs (>7 days)
- If Ollama models not responding, restart Ollama service
- If nightwatch errors spike, write diagnostic to robin-ops

## When Alfred Returns
1. Alfred reads batcave-memory/BATCAVE.md for current state
2. Alfred reads session-logs/ for what happened during outage
3. Alfred reads alfred-inbox/ for any Robin reports
4. Robin transitions from sole-survivor back to normal mode
5. Session summary written covering the outage period

## When Batman Returns
1. Robin enters standby (normal presence detection)
2. Summary of sole-survivor period available in logs
3. Any issues or anomalies flagged in robin-ops

## Known Limitations in Sole Survivor Mode
- Robin (qwen2.5:7b) has limited reasoning vs Alfred (Claude Opus)
- Robin cannot access cloud services (GitHub push, Notion, web search)
- Robin's agent loop is 3 steps max -- complex tasks may be incomplete
- CLIXML issues mean Python tasks should use pre-written scripts only
- Robin cannot start new Cowork sessions or contact Batman externally

## Recovery From Total Loss (Nuclear Option)
If Oracle itself is compromised/rebuilt:
1. Git clone https://github.com/Rudy-Assistant/rudy-workhorse
2. Install Python 3.12, Ollama, pull qwen2.5:7b
3. Run batcave-startup.ps1
4. Robin nightwatch starts, reads BATCAVE.md from git
5. Operations resume at reduced capacity
6. Alfred connects via new Cowork session, reads BATCAVE.md to catch up
