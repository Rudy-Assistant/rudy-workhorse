---
title: "FoxGate Protocol"
status: Active
date: 2026-03-31
tags: [protocol, governance, session-control, lucius]
---

# FoxGate Protocol

## Purpose
Session governance framework enforcing pre-work review gates before any priority work begins. Shifts Alfred from "builder mode" to "Lucius mode" (process oversight) to prevent tool amnesia, custom code proliferation, and Robin delegation bypass.

## Steps

1. **Session Audit** (read before anything)
   - Check Robin liveness (bridge-heartbeat.json)
   - Read CLAUDE.md HARD RULES
   - Load registry.json capability manifest
   - Load Robin skills inventory
   - Check Sentinel signals
   - Count open findings

2. **Pre-Work Review** (for EACH priority)
   - Gate 1: Search existing solutions (registry, pip, skills, MCP, Robin)
   - Gate 2: Build-vs-Buy evaluation (PyPI, GitHub, MCP registry)
   - Gate 3: Delegation check (filesystem/I/O → Robin)
   - Gate 4: Scope check (estimate time, confirm priority match)

3. **Execution Monitoring**
   - Watch for anti-patterns (custom script when tool exists, repeated failures, Robin bypass)
   - Log violations for scoring deduction

4. **Post-Session Scoring** (90-100 A, 80-89 B, 70-79 C, 60-69 D, <60 F)
   - Process compliance (30%)
   - Tool reuse (25%)
   - Robin delegation (20%)
   - Finding discipline (15%)
   - Documentation (10%)

## Key Rules

- **No priority work starts without FoxGate approval** — skipping gates "because it's faster" IS the problem
- **Alfred scope:** Reasoning, architecture, design, orchestration, review
- **Robin scope:** Everything touching local machine (filesystem, git, CI, npm, diagnostics)
- **Tool amnesia penalty:** -5 points per occurrence where registry.json wasn't checked
- **Finding zero target:** Never silently dismiss issues — banned rationalizations: "pre-existing", "structural", "out of scope"
- **Sentinel integration:** Process Lucius-relevant signals before each priority

## Related

- [[Robin-Alfred-Protocol]] — Coordination for delegation
- [[Finding-Capture]] — Mandatory finding triage
- Source: `.claude/skills/foxgate/SKILL.md`
