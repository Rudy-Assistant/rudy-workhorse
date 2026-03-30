# ADR-003: Robin Handoff Protocol — Batman/Alfred Continuity of Operations

**Status:** Draft (Not yet implemented)  
**Date:** 2026-03-29  
**Decision Makers:** Batman Prime (Chris), Alfred  
**Supersedes:** Night Shift concept in ADR-002 (extends it)  
**Imported from:** alfred-skills (Lucius Salvage Audit, Session 10)

## Context

Robin was originally conceived as a background sentinel. Batman Prime has expanded Robin's mandate: Robin should be capable of taking the wheel during defined absence windows, acting as Batman's proxy with Alfred, and developing its own capabilities by learning from Alfred-Batman conversations.

## Decision

### 1. Handoff Activation (Three Modes)

**Mode A: Explicit Handoff (Primary)**  
Batman tells Alfred: "I'm stepping away for N hours" (optionally with scope constraints).  
Alfred writes a handoff signal:

```json
{
  "handoff_id": "2026-03-29T23:00:00Z",
  "mode": "explicit",
  "activated_by": "batman_prime",
  "duration_hours": 3,
  "scope": "full",
  "status": "active"
}
```

Signal location: `docs/robin-handoff/active.json` (GitHub) + mirrored to Notion.

**Mode B: Inactivity Detection (Autonomous)**  
Robin's presence detection detects no HID input for configurable threshold (default: 2 hours). Activates in conservative mode — only pre-approved maintenance tasks.

**Mode C: Time-Based (Scheduled)**  
Sentinel's existing night shift logic (after 11 PM local). Can be pre-authorized to Mode A scope via standing directives.

### 2. Robin ↔ Alfred Communication

**Alfred's Side (Cloud — Cowork Session):**  
When blocked on a permission check or user input:
- Alfred writes pending approval to `docs/robin-handoff/pending-approvals/`
- Format includes: approval_id, type, question, context, risk_level, created, expires, status
- Alfred polls for response every 60 seconds during active handoff window

**Robin's Side (Oracle — Local):**  
- Robin polls `robin-handoff/pending-approvals/` directory
- For each pending approval, Robin evaluates:
  - Is the handoff window still active?
  - Does the request fall within authorized scope?
  - Does the risk level match Robin's authorization level?
  - Does immune memory or standing directives inform the decision?
- Robin writes response with approval_id, decision, reasoning, timestamp

**Escalation Path:**  
- Risk level critical → always escalate
- Outside defined scope → escalate
- No precedent in immune memory or directives → escalate
- Escalation = write to `robin-handoff/escalations/` + desktop notification + email alert

### 3. Batman Return Detection

| Signal | Method | Action |
|--------|--------|--------|
| HID input | pynput listener on Oracle | Immediate standdown alert |
| Cowork message | Poll transcript for new Batman messages | Transfer context, stand down |
| Explicit recall | Batman says "I'm back" to Alfred | Alfred signals Robin via handoff file |
| Window expiry | Clock reaches window_end | Automatic standdown |

**Standdown sequence:**
1. Robin finishes current atomic task (never abandons mid-operation)
2. Writes handoff summary to Notion + `robin-handoff/summaries/`
3. Sets handoff status to completed
4. Returns to background sentinel mode
5. Alfred presents summary to Batman

### 4. Capability Development (Learning Mode)

- **Transcript monitoring:** Robin reads session transcripts to learn Batman's patterns
- **Pattern library:** Robin builds `rudy-data/robin-patterns.json` of decision-making tendencies
- **Confidence scoring:** Over time, high-confidence approvals get auto-approved; low-confidence ones escalate
- Always running — even when Batman is active, Robin is in passive learning mode

### 5. Authorization Levels

| Level | Trigger | Can Approve | Cannot Do |
|-------|---------|-------------|-----------|
| Sentinel | Always on | Service restarts, zombie kills, health reports | Anything requiring judgment |
| Observer | Always on | Nothing — learning only | Act on behalf of Batman |
| Conservative | Mode B/C | Maintenance, code quality, dep updates | Merges, deploys, external comms |
| Full Proxy | Mode A | Anything within stated scope | Financial, account creation, scope violations |

### 6. Audit Trail

Every Robin action during a handoff window is logged:
- `robin-handoff/summaries/{handoff_id}.md` — human-readable summary
- `robin-handoff/audit/{handoff_id}.jsonl` — machine-readable action log
- Notion session log — appended with Robin's activity section
- Immune memory — updated with any fixes or patterns learned

## Consequences

**Positive:**
- Batman sleeps; system improves
- Alfred never blocks indefinitely on permissions during handoff windows
- Robin develops genuine operational intelligence over time
- Clean audit trail for every autonomous decision

**Negative:**
- Complexity: three activation modes, approval routing, standdown logic
- Trust bootstrap: Robin starts with zero confidence scores
- GitHub polling latency: ~60 second approval turnaround
- Risk of Robin approving something Batman wouldn't — mitigated by scope constraints and escalation

## Implementation Priority

1. HID presence monitor — `robin_presence.py` (DONE — PR #4)
2. Handoff signal reader/writer — extend `robin_bridge.py`
3. Approval polling loop — new method in `robin_bridge.py`
4. Alfred handoff skill — Alfred writes handoff signals when Batman departs
5. Test: 3-hour handoff window — Batman steps away, Robin + Alfred work together
