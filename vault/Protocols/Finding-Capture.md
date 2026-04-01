---
title: "Finding Capture Protocol"
status: Active
date: 2026-03-31
tags: [protocol, quality-gate, findings, triage]
---

# Finding Capture Protocol

## Purpose
Mandatory triage and tracking for any investigation surfacing issues, regardless of origin. Eliminates silent dismissals and enforces zero-target discipline for finding backlog.

## Steps

1. **Immediate Triage**
   - Issue found → classify by effort
   - Under ~15 min → fix in current branch immediately
   - Over ~15 min OR blocked → log as tracked item

2. **Log Tracked Finding**
   - Severity: CRITICAL / HIGH / MEDIUM / LOW
   - Location: file/line number
   - Context: enough detail for next session to understand
   - Acceptable tracking: GitHub issue, SESSION-HANDOFF.md, or Lucius findings tracker

3. **Never Dismiss Silently**
   - If you found it, you own it
   - Document it somewhere trackable (vault preferred)

## Key Rules

- **Zero is the target, always** — no "but pre-existing" / "only N findings remain" rationalizations
- **Banned dismissals:** "This is pre-existing", "This is structural", "Out of scope", "Only X findings remain"
- **Vault-first:** All findings must be recorded in BatcaveVault (`vault/`)
- **Finding discipline:** Part of session scoring (15% weight under FoxGate)
- **Severity inheritance:** If issue blocks work, escalate to HIGH even if intrinsically MEDIUM

## Related

- [[FoxGate]] — Post-session scoring includes finding discipline (15%)
- [[Robin-Alfred-Protocol]] — Finding reporting message type
- Source: `CLAUDE.md` lines 95-102 (HARD RULE — Session 14)
