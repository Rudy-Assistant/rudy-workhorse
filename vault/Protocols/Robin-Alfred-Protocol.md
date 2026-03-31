---
title: "Robin-Alfred Protocol"
status: Active
date: 2026-03-31
tags: [protocol, coordination, messaging, delegation]
---

# Robin-Alfred Protocol

## Purpose
Filesystem-based message passing for autonomous coordination between Robin (local AI) and Alfred (Claude in cloud). Enables safe delegation of local tasks, status tracking, and proactive help offers without synchronous coupling.

## Steps

1. **Message Sending** — Robin/Alfred writes to inbox directories
   - Robin → Alfred: `rudy-data/alfred-inbox/{timestamp}-{type}.json`
   - Alfred → Robin: `rudy-data/robin-inbox/{timestamp}-{type}.json`

2. **Status Sharing** — Both maintain coordination files
   - `rudy-data/coordination/robin-status.json` — Robin's state/model/PID
   - `rudy-data/coordination/alfred-status.json` — Alfred's session context

3. **Task Delegation** (v2)
   - Alfred assigns: `AlfredMailbox.assign_task(task, details, deadline)`
   - Robin acknowledges: `RobinMailbox.acknowledge_task(task_msg_id, eta_minutes)`
   - Robin completes: `RobinMailbox.report_task_complete(task_msg_id, result, files_changed, success)`

4. **Proactive Help Offers** (Session 33)
   - Robin detects struggle: `detect_alfred_struggle()` returns signals
   - Robin offers: `offer_help(context, what_noticed, suggested_action)`
   - Robin documents friction: `log_friction(context, what_went_wrong, workaround, severity)`

## Key Rules

- **Message types:** request, report, health, escalation, task, ack, task_ack, task_complete, finding, session_start, session_end
- **TTL enforcement:** Messages expire after MAX_MESSAGE_AGE_HOURS (reject stale messages)
- **Payload validation:** All payloads sanitized via `sanitize_str()` and `validate_payload()`
- **Archive on read:** Mark messages read and move to `coordination/archive/`
- **Session lifecycle:** `announce_session_start()` and `announce_session_end()` track session awareness
- **Finding reporting:** Both sides report quality/security findings with severity tier
- **Proactive signals:** Robin offers help when Alfred shows error keywords or stale status

## Related

- [[FoxGate]] — Protocol that enables delegation
- [[Finding-Capture]] — Finding reporting workflow
- Source: `rudy/robin_alfred_protocol.py`
