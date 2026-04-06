# ADR-020 Phase 3 Amendment: Robin Self-Sufficiency

**Status:** Proposed
**Date:** 2026-04-06
**Session:** 138 (Batman directive)
**Deciders:** Batman (Chris Cimino)
**Amends:** ADR-020 Phase 3 ("Andrew Is Safe")

## Context

Batman directive (S138): Phase 3 should NOT focus on coding
specific caregiver use-cases. The "Andrew" persona is a design
constraint representing ANY Batman -- it measures Robin's
robustness, versatility, and reliability as a general-purpose
Batman proxy. It does NOT assume a particular use-case
(caregiving, disability, etc.).

Caregiver-class features (distress detection, caregiver alerts,
disability-specific input) are STRUCK from the Andrew-readiness
scoring and roadmap. They may be added later as optional
extensions but are not part of the core readiness metric.

This aligns with MISSION.md Core Tenets:
- "Alfred's purpose is self-obsolescence."
- "Route through Robin first. Every task is training data."
- "The system converges when Robin can handle everything."

## Scoring Revision

D10 ("Safety and Error Recovery") is reframed. The old
framing included caregiver alerts and distress detection.
The revised framing measures Robin's general error recovery,
graceful degradation, and operational resilience -- applicable
to any Batman, not a specific care scenario.

D2 ("Alternative Input Channels") drops switch access,
sip-and-puff, and eye-tracking from scoring criteria.
These are optional accessibility extensions, not core
readiness. D2 now measures: diversity of command channels
(voice, email, chat, web, HA) and their reliability.

## Original Phase 3 (STRUCK)

Steps 8-10 were:
8. Caregiver Alert System -- STRUCK
9. Graceful Degradation Announcements -- RETAINED (reframed
   as Robin operational transparency, not disability-specific)
10. Onboarding Wizard -- RETAINED (general usability)

## Revised Phase 3: "Robin Self-Sufficiency" (Target: 90%)

### Principle

Force Alfred to structurally offload to Robin everything
Robin can do locally. Alfred maximizes token efficiency by
reserving processing for intelligence-class work that ONLY
Alfred can perform (complex reasoning, cloud API orchestration,
strategic planning, code architecture).

Robin handles: file ops, git operations, system diagnostics,
compilation, linting, process management, local AI inference,
MCP tool execution, Windows automation, routine workflows.

Over time, Robin learns efficient processes through OpenSpace
Skills evolution, chaining common workstreams, and self-
improving through practice -- becoming a more capable Batman
proxy with every session.

### Step 8: Alfred Delegation Enforcer

Build a structural gate that intercepts Alfred's tool calls
and routes local-capable operations to Robin automatically.

**What to build:**
- `rudy/alfred_delegation_gate.py` -- Classifier that
  inspects intended operations and routes to Robin when:
  (a) the operation is local I/O (file read/write/edit),
  (b) the operation is a shell command (git, npm, python),
  (c) the operation is system diagnostics,
  (d) the operation is routine/repetitive (lint, compile).
- Integration with robin_alfred_protocol.py for IPC.
- Metrics: track delegated vs. retained operations per
  session. Target: >60% delegation rate.

**Impact:** D4 -> 8, D5 -> 5. Reduces Alfred token burn
by 40-60% on typical sessions.

### Step 9: Robin Task Learning (OpenSpace Evolution)

Robin learns from delegated tasks and builds reusable
workflows -- OpenSpace Skills that chain common operations.

**What to build:**
- `rudy/robin_skill_learner.py` -- Observes task patterns
  delegated from Alfred. When a pattern repeats 3+ times,
  proposes a Robin OpenSpace Skill (stored workflow).
- Skill format: JSON workflow definition with steps,
  conditions, and verification checks.
- Sentinel integration: Sentinel's proposal pipeline
  (S136) feeds observed patterns to the skill learner.
- Feedback loop: Alfred reviews proposed skills during
  boot (skill gate integration). Approved skills become
  part of Robin's permanent capability.

**Impact:** D5 -> 7. Robin's autonomous capability grows
with every session. The system self-improves.

### Step 10: Robin Workstream Chaining

Robin chains learned skills into multi-step workstreams
that execute common session workflows end-to-end.

**What to build:**
- `rudy/robin_workstream.py` -- Orchestrator that
  sequences Robin Skills into workflows. Examples:
  (a) "PR workflow": branch -> edit -> lint -> compile ->
      commit -> push -> create PR -> monitor CI.
  (b) "Health check workflow": verify PIDs -> check
      Ollama -> check Sentinel -> check disk -> report.
  (c) "Session prep workflow": sync main -> read handoff ->
      check PRs -> run skill gate -> report to Alfred.
- LangGraph integration (robin_agent_langgraph.py already
  has stateful workflow support).
- Workstream templates stored in rudy-data/robin-skills/.

**Impact:** D4 -> 9. Robin can execute entire workstreams
autonomously, reducing Alfred's per-session overhead to
strategic decisions only.

## Revised Scoring Target

| Phase | Steps | Score Before | Score After |
|-------|-------|-------------|-------------|
| Phase 1 | 1-4 | 39.7% | ~60% |
| Phase 2 | 5-7 | ~60% | ~75% |
| Phase 3 (revised) | 8-10 | ~75% | ~90% |

The revised Phase 3 achieves 90% through Robin's general-
purpose autonomy, benefiting ANY Batman -- not through
features tied to a specific user profile.

## Dependencies

| Dependency | Status | Notes |
|-----------|--------|-------|
| robin_alfred_protocol.py | EXISTS | IPC layer, 330L |
| robin_agent_langgraph.py | EXISTS | Stateful workflows, 864L |
| sentinel_proposals.py | EXISTS (S136) | Observation pipeline |
| robin_autonomy.py | EXISTS | Decision engine, 583L |
| OpenSpace Skills (R-006) | LEGACY | Revived for this phase |

No new external dependencies required. Phase 3 revised
builds entirely on existing Robin infrastructure.

## Consequences

**What becomes easier:**
- Alfred sessions are cheaper (fewer tokens on routine work).
- Robin grows more capable with every session.
- The system self-improves without manual intervention.
- Any Batman benefits from Robin's accumulated skills.

**What becomes harder:**
- Delegation gate must be precise (don't delegate what
  Robin can't yet handle -- causes failures).
- Skill quality must be validated (bad learned skills
  propagate errors).
- Robin error handling must be robust for unsupervised
  execution.

**What we revisit:**
- R-006 (OpenSpace Skills) revived from LEGACY status.
- ADR-020 scoring dimensions D2 and D10 reframed.
- Delegation metrics inform future phase planning.

---

*Proposed by Alfred (S138) per Batman directive.*
*Pending Batman approval.*
