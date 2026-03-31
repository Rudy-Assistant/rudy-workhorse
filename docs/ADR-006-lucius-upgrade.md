# ADR-006: Lucius Fox Upgrade — From Rubber Stamp to Active Governance Agent

**Status:** PROPOSED (Session 35)
**Supersedes:** Parts of ADR-004 (Lucius Gate v2.1)
**Author:** Alfred + Batman
**Date:** 2026-03-31

## Context

Lucius Fox was designed (ADR-004) as the Batcave's governance layer: session gates,
pre-commit checks, compliance scoring. In practice, Lucius has become a rubber stamp.
Evidence from Sessions 32-35:

- Alfred routinely ignores registry.json before writing custom code (HARD RULE #2)
- Alfred writes 20+ custom scripts per session without checking existing tools
- The scorer runs post-session (if at all) with no consequence for low scores
- session_start_gate checks infrastructure but not behavioral compliance
- pre_commit_check runs on branch protection only, not code quality
- Lucius has no voice — he cannot intervene, suggest, or block in real-time

Batman's directive: Lucius should be the archetypal "by-the-books" bureaucrat who
ensures rigid QA to minimize waste, maximize efficiency, and keep code operational.
He should function as either a full alter-ego of Alfred (maximally employing proper
process) or one of several cooperating agents — not a background cron job.

## Decision

### 1. Three Operating Modes for Lucius

**Mode A: FoxGate (Session Protocol)**
Triggered by `/FoxGate` at session start. Lucius reviews the session plan,
checks proposals against existing tools, and gates each priority item before
Alfred starts work. This is the "approval" layer that currently doesn't exist.

Flow:
```
/FoxGate → Lucius reads CLAUDE.md, registry.json, Robin skills, MCP connectors
         → Alfred proposes plan for each priority
         → Lucius reviews each proposal:
              "Does an existing tool/skill/package handle this?"
              "Is Robin the right executor for this?"
              "What's the minimum custom code path?"
         → Lucius approves, rejects, or suggests alternatives
         → Only approved work proceeds
         → Lucius monitors tool calls for drift during execution
```

**Mode B: Lucius Persona (/Lucius)**
A full persona switch in Cowork. When Batman opens a second tab and types `/Lucius`,
Alfred assumes the Lucius identity: methodical, process-obsessed, documentation-first.
Lucius-mode Alfred excels at:
- GitHub repository documentation and housekeeping
- Obsidian vault consolidation and institutional memory
- Findings tracking, score analysis, and trend reporting
- Registry audits and capability gap analysis
- Code review with ADR compliance checking

This enables concurrent workflows: Alfred builds features in Tab 1 while
Lucius consolidates documentation in Tab 2.

**Mode C: Autonomous Agent (LangGraph)**
Long-term: Lucius as a LangGraph agent with his own reasoning loop, running
on Robin's local Ollama infrastructure. This agent would:
- Maintain persistent state across sessions (via vault + findings tracker)
- Receive signals from Sentinel (the "spider web")
- Score Alfred's work in real-time (not just post-session)
- Generate improvement recommendations that feed into CLAUDE.md
- Run adversarial code review via Codex plugin

### 2. Sentinel → Lucius Signal Routing (Spider Web)

The Sentinel already passively observes system state on every autonomy cycle.
Currently it only feeds Robin. Under this ADR, Sentinel becomes the shared
"nerve center" whose signals route to both Robin AND Lucius:

```
Sentinel (passive observer)
  │
  ├── Robin signals: system health, process status, task completion
  │
  └── Lucius signals (NEW):
        ├── waste_detected: custom code written without registry check
        ├── delegation_violation: Alfred doing Robin's job
        ├── tool_amnesia: existing tool ignored for custom solution
        ├── score_trend: declining compliance over N sessions
        ├── finding_stale: open finding older than 2 sessions
        └── drift_alert: work diverging from approved plan
```

Sentinel writes these signals to `rudy-data/coordination/lucius-signals.json`.
Lucius consumes them during FoxGate protocol, post-session scoring, and
(in Mode C) in real-time during his autonomous reasoning loop.

### 3. Consequential Scoring

Current: Scorer runs post-session, score goes into vault, next session ignores it.

Proposed: Score is injected into CLAUDE.md's hot cache section, visible to every
new session instance. Format:

```
## Last Session Score
Session 35: 62/100 (C)
  -15: Custom code without registry check (7 instances)
  -10: Repeated broken tool calls (DC read_file x5)
  -8: Did not delegate to Robin (lint fix, pip install, temp cleanup)
  -5: No pre-work Lucius review
```

This creates the reinforcement loop: the next Alfred instance sees exactly
what went wrong and adjusts behavior. The HandoffWriter automatically
updates this section. Lucius scores, HandoffWriter publishes.

### 4. Pre-Work Review Gate (FoxGate Core)

Before Alfred starts ANY priority item, FoxGate runs this checklist:

```
1. EXISTING SOLUTION CHECK
   - Search registry.json for matching capability
   - Search installed pip packages (pip list | grep)
   - Search Cowork skills (30+)
   - Search MCP connectors (5+)
   - Search Robin skills (scripts/*.py)
   → If match found: USE IT. Do not write custom code.

2. BUILD-VS-BUY GATE (ADR-005)
   - If no existing solution: search PyPI, GitHub, MCP registry
   - Evaluate at least 3 candidates
   - Document justification if custom code is necessary
   → Custom code is a LAST RESORT, not the default.

3. DELEGATION CHECK
   - Is this a local I/O task? → Robin
   - Is this mechanical (lint, CI, merge)? → Robin (robin_pr_merge.py)
   - Is this one-time diagnostics? → Robin
   → Alfred's role: reasoning, orchestration, review. Not execution.

4. SCOPE CHECK
   - Does the proposed approach match the priority description?
   - Is the time estimate reasonable?
   - Are there dependencies on other priorities?
   → Prevent scope creep and rabbit holes.
```

Each check produces a PASS/WARN/BLOCK result. BLOCK stops work on that
priority until Alfred revises the approach. WARN allows work but logs
a score deduction.

### 5. Lucius as Persona — Capability Map

When in `/Lucius` mode, the agent has these distinct characteristics:

| Aspect | Alfred | Lucius |
|--------|--------|--------|
| Priority | Speed, results | Process, correctness |
| Code style | Custom if faster | Existing tools first, always |
| Documentation | Minimal | Exhaustive |
| Risk tolerance | Moderate | Zero — every edge case matters |
| Delegation | Sometimes forgets | Enforces HARD RULE #6 rigidly |
| Findings | Logs when noticed | Hunts proactively |
| Scoring | Subject of scoring | Author of scoring |
| Vault | Writes when reminded | Writes compulsively |
| Registry | Checks when prompted | Checks before every action |

## Implementation Plan

### Phase 1: FoxGate Skill + Consequential Scoring (Session 36)
- Create Cowork skill `/FoxGate` that runs pre-work review gate
- Wire scorer output into CLAUDE.md "Last Session Score" section
- Add Sentinel → Lucius signal types to SentinelObserver

### Phase 2: Lucius Persona Skill (Session 36-37)
- Create Cowork skill `/Lucius` for persona mode
- Define Lucius system prompt with documentation/archival focus
- Test concurrent Tab 1 (Alfred) + Tab 2 (Lucius) workflow

### Phase 3: LangGraph Agent (Session 37-38)
- Design Lucius as LangGraph agent with persistent state
- Tools: registry lookup, pip search, skill catalog, findings tracker
- Integration: receives Sentinel signals, produces score reports
- Optional: Codex adversarial review as a Lucius tool

### Phase 4: Full Integration (Session 38+)
- Lucius reviews PRs before merge (not just CI checks)
- Lucius maintains registry.json automatically
- Lucius runs periodic codebase audits (dead code, unused imports, drift)
- Lucius generates session briefing documents from vault analysis

## Consequences

### Positive
- Alfred's behavior is constrained by process, not just memory
- Scoring has teeth — visible to every session instance
- Existing tools get used instead of reinvented
- Robin delegation becomes enforced, not aspirational
- Batman can chat with Lucius directly for bookkeeping/documentation
- Sentinel data flows to governance, not just monitoring

### Negative
- FoxGate adds overhead to session start (estimated 2-3 minutes)
- Lucius may over-block legitimate custom code needs
- LangGraph agent requires Ollama model capacity on Oracle
- Two-persona system needs clear handoff protocol

### Risks
- Lucius becomes so rigid that Alfred can't do creative problem-solving
  → Mitigation: FoxGate has a "justified override" option with logging
- LangGraph agent hallucinates registry entries
  → Mitigation: Lucius tools read real files, not LLM memory
- Context pressure from FoxGate protocol in already-long sessions
  → Mitigation: FoxGate caches results, doesn't re-run on every priority

## References
- ADR-004: Lucius Gate v2.1 (current implementation)
- ADR-005: Build-vs-Buy Gate
- CLAUDE.md: HARD RULES #2, #3, #6
- Session 35 Batman feedback on Lucius as rubber stamp
- SentinelObserver: rudy/robin_sentinel.py
