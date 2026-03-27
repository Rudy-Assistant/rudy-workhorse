# ADR-001: Session Guardian — Local Continuity Agent

**Status:** Proposed
**Date:** 2026-03-27
**Deciders:** Chris Cimino

## Context

Three recurring failures degrade the Workhorse's effectiveness:

**1. Session amnesia.** Every new Cowork session starts cold. CLAUDE.md helps, but the session AI routinely forgets to check it, doesn't recall what skills/plugins/connectors are available, and rebuilds things from scratch.

**2. Custom-code reflex.** The session AI writes new Python scripts for problems already solved by installed packages (60+ Phase 2 packages), Cowork skills (30+ skills across 5 plugins), MCP connectors (Gmail, Calendar, Notion, Canva, Chrome), or Workhorse modules (31 rudy/ modules). This wastes time and produces inferior solutions.

**3. No continuity on disconnect.** When Cowork crashes, times out, or loses connection, all in-flight state evaporates. The local agents keep running, but they don't know what the session was working on or what still needs to happen. There's no handoff.

These aren't separate problems. They're symptoms of a missing layer: persistent local intelligence that maintains awareness of what exists, what's happening, and what the session AI should be doing.

## Decision

Build a **Session Guardian** — a lightweight local process on the Workhorse that:

1. **Maintains a capability manifest** — a machine-readable index of everything available (skills, connectors, modules, packages, agents, scheduled tasks). Updated automatically when things change. Injected into new Cowork sessions via CLAUDE.md or a briefing endpoint.

2. **Monitors session activity** — detects when a Cowork session goes inactive (no command runner activity for N minutes) and triggers a handoff protocol: saves pending state to Notion, generates a continuation prompt, and optionally activates the local agent fallback.

3. **Enforces the "check before building" rule** — provides a lookup endpoint that the session AI should query before writing custom code. "I need to do X" → "You already have rudy/Y.py, the Z skill, and the W package installed."

4. **Bridges sessions** — when a new Cowork session starts, the Guardian provides a structured briefing: what was the last session doing, what's pending, what's the current machine state, and what tools are available.

## Options Considered

### Option A: Extend Sentinel (lightweight — RECOMMENDED)

The Sentinel agent already runs every 15 minutes and owns "awareness." Extend it with:
- A capability manifest scanner (reads installed packages, skills, modules)
- A session activity monitor (checks command runner log timestamps)
- A state snapshot writer (dumps pending work to Notion on inactivity)
- A briefing generator (produces a structured context block for new sessions)

| Dimension | Assessment |
|-----------|------------|
| Complexity | **Low** — adds 3-4 methods to existing agent |
| Cost | **Zero** — uses existing scheduled task, Ollama, Notion |
| Scalability | Good — Sentinel's 30s time cap keeps it light |
| Team familiarity | **High** — same AgentBase pattern as all other agents |

**Pros:** Minimal new code. Composes with existing agent runner and scheduling. Sentinel already scans for changes and opportunities — this is a natural extension. No new processes to manage.

**Cons:** Limited to 15-minute detection granularity. Can't do real-time session monitoring.

### Option B: New standalone daemon

A new Python daemon (like the command runner) that:
- Watches command runner activity in real-time via watchfiles
- Maintains a WebSocket or HTTP endpoint for session queries
- Runs Ollama inference for capability matching

| Dimension | Assessment |
|-----------|------------|
| Complexity | **High** — new daemon, new startup entry, new monitoring |
| Cost | **Low** — but adds operational burden |
| Scalability | Excellent — real-time, event-driven |
| Team familiarity | Medium — new pattern |

**Pros:** Real-time detection. Could serve an API that Cowork queries directly. More responsive.

**Cons:** Another process to keep alive. Another thing that can crash. Adds to the "cascade failure" surface area Chris is trying to reduce. Violates "don't reinvent the wheel" — we already have a scheduled agent system.

### Option C: Cowork-side skill (no local component)

Create a custom Cowork skill that:
- Forces reading CLAUDE.md at session start
- Provides a capability lookup command
- Auto-generates continuation prompts

| Dimension | Assessment |
|-----------|------------|
| Complexity | **Low** — just a skill definition |
| Cost | **Zero** |
| Scalability | N/A |
| Team familiarity | **High** — skill-creator already exists |

**Pros:** Simplest. No local code. Works within existing Cowork framework.

**Cons:** Doesn't solve the continuity problem (skill dies with the session). Doesn't solve inactivity detection. Can't remind a session AI that forgot to invoke the skill. Only addresses the capability-awareness problem.

## Trade-off Analysis

**Option A (Sentinel extension) + Option C (Cowork skill)** together cover all three problems:

- **Sentinel extension** handles: inactivity detection, state snapshots, capability manifest generation, session bridging
- **Cowork skill** handles: forcing capability awareness at session start, providing in-session "what tool should I use?" lookup

Neither alone is sufficient. The skill can't detect inactivity. The Sentinel can't force the session AI to check capabilities. Together they create a closed loop.

Option B (standalone daemon) is better technically but violates the engineering principle of minimizing moving parts. We already lost remote access once to a cascade of processes crashing — adding another daemon increases that risk.

## Consequences

**What becomes easier:**
- New sessions start with full context (machine state, pending work, available tools)
- The "should I build custom or use existing?" question gets answered before code is written
- Session crashes produce a clean handoff instead of total state loss
- The Workhorse can continue meaningful work during Cowork outages

**What becomes harder:**
- Nothing significant. Both additions are small.

**What we'll need to revisit:**
- The 15-minute Sentinel cycle may need to decrease to 5 minutes for faster inactivity detection
- The capability manifest format will evolve as tools are added
- The Cowork skill may need iteration to find the right balance of helpfulness vs. overhead

## Implementation Plan

### Phase 1: Capability Manifest (Sprint 3 — next session)

1. **Sentinel: `_scan_capabilities()` method** — scans `pip list`, `rudy/` modules, Cowork skills (from CLAUDE.md), installed MCP connectors, scheduled tasks. Writes `rudy-logs/capability-manifest.json`.

2. **Sentinel: `_generate_session_briefing()` method** — reads all agent statuses, the capability manifest, pending tasks from Notion, and recent observations. Writes `rudy-logs/session-briefing.md` — a ready-to-inject context block.

3. **CLAUDE.md directive** — add a hard rule: "At session start, read `rudy-logs/session-briefing.md` if it exists. Before writing ANY new Python file, check `rudy-logs/capability-manifest.json` for existing solutions."

### Phase 2: Inactivity Detection + Handoff (Sprint 3)

4. **Sentinel: `_check_session_activity()` method** — reads command runner log. If no activity for 30+ minutes, triggers handoff: writes pending state to Notion, generates continuation prompt at `rudy-logs/continuation-prompt.md`.

5. **Sentinel: `_activate_fallback()` method** — if inactivity exceeds 2 hours, switches to local-AI-powered autonomous mode (via `offline_ops.py` + Ollama). Runs queued tasks, monitors health, generates reports.

### Phase 3: Cowork Skill (Sprint 3)

6. **`/session-start` skill** — invoked at the beginning of every Cowork session. Reads the briefing, surfaces pending work, reminds of available tools. Uses skill-creator to build.

7. **`/check-before-build` skill** — the session AI invokes this before writing custom code. Searches the capability manifest and returns matches. "I need OCR" → "You have: rudy/ocr.py, rudy/tools/ocr_fallback.py, easyocr (pip), pdfplumber (pip), the pdf skill."

### Phase 4: Feedback Loop (Sprint 4)

8. **Sentinel: track "custom code written" events** — when a new .py file appears in rudy-commands/ or rudy/, check if it duplicates something in the manifest. Log the miss. Over time, this reveals which capabilities are most forgotten.

## Action Items

1. [ ] Extend Sentinel with capability scanner + session briefing generator
2. [ ] Add CLAUDE.md hard rule for briefing + manifest checks
3. [ ] Extend Sentinel with inactivity detection + handoff protocol
4. [ ] Connect handoff to Notion (state dump) and offline_ops (fallback)
5. [ ] Create `/session-start` Cowork skill via skill-creator
6. [ ] Create `/check-before-build` Cowork skill
7. [ ] Test full cycle: session start → work → disconnect → handoff → new session → resume
