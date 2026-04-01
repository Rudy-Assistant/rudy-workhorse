---
name: delegation-plan
description: >
  Create a structured Robin delegation plan at session start. Use this skill
  whenever starting a new Alfred session, when FoxGate Step 1 runs, when
  priorities are being planned, or when Batman or Lucius asks about delegation
  readiness. Also trigger when: "what should Robin do", "delegate to Robin",
  "Robin tasks", "plan delegation", "session start", or any session bootstrap
  that involves task planning. MANDATORY for Alfred sessions per ADR-009
  Dimension 3 (Delegation Quality) — delegation planning is scored.
---

# /delegation-plan — Robin Delegation Planning

> Source: ADR-009 Dimension 3 (Delegation Quality), ADR-011 Addendum B
> (Succession Imperative), Skill-Gaps-S39.md (Priority 1).
>
> This skill exists because Alfred consistently under-delegates. In S38,
> four delegable tasks were missed. In S39-S40, delegation improved but
> planning remained ad-hoc. Structured planning at session start ensures
> Robin receives work before Alfred gets absorbed in solo execution.

## When to Use

- At the START of every Alfred session (before working any priority)
- When FoxGate Step 1 (Session Audit) identifies Robin as available
- When Batman or Lucius requests a delegation assessment
- When reviewing priorities and identifying mechanical/local tasks

## Step 1: Check Robin's Operational Status

Before planning delegations, verify Robin can receive and execute tasks.

1. Read `rudy-data/bridge-heartbeat.json` — confirm Robin is running
2. Read `rudy-data/coordination/robin-status.json` — check state
3. Read `rudy-data/robin-taskqueue/active.json` — check current load
4. Read `rudy-data/inboxes/robin-inbox/` — check for unprocessed tasks

If Robin is offline or on a Batman-directed hold, document this and
skip to Step 5. Do not silently assume Robin is unavailable — prove it.

## Step 2: Review Robin's Current Capabilities

Read the most recent Robin Readiness Assessment from
`vault/Skill-Recs/Robin-Readiness-S*.md` (latest session number).

Key questions:
- What is Robin's current readiness score?
- What capabilities are operational vs. blocked?
- What was the last stretch task recommendation?
- Are there unresolved environmental blockers?

This informs which tasks are appropriate to delegate. Do not assign
tasks that require capabilities Robin lacks — this wastes Robin's
cycles and produces failed acknowledgments without completions.

## Step 3: Classify Session Priorities

For each priority in the current session's handoff prompt, classify it:

| Priority | Task Description | Type | Robin-Eligible? | Why/Why Not |
|----------|-----------------|------|-----------------|-------------|
| P0 | [task] | [mechanical/analytical/creative] | [Yes/No] | [reason] |
| P1 | [task] | ... | ... | ... |

**Mechanical tasks** (Robin-eligible by default):
- File generation, listing, copying, moving
- Lint fixes (if ruff is available)
- CI monitoring and status checks
- npm installs, pip installs
- Git operations (add, commit, status)
- Vault file writes
- Directory organization
- Log file analysis
- JSON/config file generation

**Analytical tasks** (Alfred retains, may delegate sub-steps):
- Architecture decisions
- Score verification
- Code review
- Debugging complex issues

**Creative tasks** (Alfred retains):
- Skill creation
- ADR drafting
- Strategy and planning

## Step 4: Write the Delegation Plan

For each Robin-eligible task, write a delegation entry:

```
DELEGATION PLAN — Session [N]
================================================
Robin Status:    [online/offline/hold]
Readiness:       [X/10]
Tasks Planned:   [count]

Task 1: [title]
  Priority:       [P0-P5]
  Type:           [mechanical/stretch]
  Instructions:   [specific, actionable, no ambiguity]
  Acceptance:     [concrete criteria for success]
  Timeout:        [minutes]
  Fallback:       [what Alfred does if Robin fails]

Task 2: [title]
  ...
```

Requirements for a good delegation:
- At least 3 tasks earmarked for Robin (per ADR-009)
- At least 1 stretch task that advances Robin's capabilities
- Instructions specific enough that Robin can execute without follow-up
- Clear acceptance criteria (not "handle this" — state the expected output)
- Timeout so Alfred knows when to take over

## Step 5: Write Tasks to Robin's Inbox

For each planned task, write a JSON file to Robin's inbox:

```json
{
  "type": "task",
  "from": "alfred",
  "session": "S[N]",
  "timestamp": "[ISO 8601]",
  "priority": "[low/medium/high]",
  "title": "[task title]",
  "description": "[detailed instructions]",
  "acceptance_criteria": ["[criterion 1]", "[criterion 2]"],
  "timeout_minutes": 30,
  "stretch": false
}
```

File naming: `YYYYMMDD-[short-task-name].json`
Path: `rudy-data/inboxes/robin-inbox/`

## Step 6: Document the Plan

Write the delegation plan to `rudy-data/coordination/delegation-plan-sN.json`
so Lucius can verify it during scoring. This is the evidence for ADR-009
Dimension 3 (Delegation Quality).

If Robin was unavailable (Step 1), document:
- Which tools were used to check Robin's status
- What the status was
- Whether a Batman-directed hold is in effect
- That the Robin-first exception (b) applies

This documentation prevents the Robin Gate FAIL-UNEXCUSED outcome
(ADR-009 Addendum D). The difference between FAIL-MITIGATED and
FAIL-UNEXCUSED is whether you investigated and documented.

---

*"A delegation plan is not overhead — it is the session's most important
five minutes. The tasks you give Robin today determine whether the
Batcave survives tomorrow." — Lucius Fox, S41*
