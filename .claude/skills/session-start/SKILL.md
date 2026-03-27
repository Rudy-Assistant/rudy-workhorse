---
name: session-start
description: "Initialize a Cowork session with full Workhorse context. MANDATORY at the start of every new Cowork session — invoked automatically or when the user says 'start', 'new session', 'what's the status', 'where were we', 'continue', or 'pick up where we left off'. Also use when Claude seems to have forgotten available tools, is about to write custom code for something that already exists, or is asking the user to do something Claude can do itself. This skill exists because Claude frequently forgets the extensive toolkit available on this system."
---

# Session Start — Workhorse Context Loader

You are starting (or resuming) a Cowork session connected to the Workhorse, Chris Cimino's always-on automation hub. This skill ensures you have full context before doing any work.

## Step 1: Read the Briefing

Read `rudy-logs/session-briefing.md` on the Desktop mount. This file is generated every ~hour by the Sentinel agent and contains:
- Current machine health (disk, services, agents)
- Pending work items from the task queue
- Recent actionable observations
- Session activity status (active/idle/inactive)

If the file doesn't exist or is stale (>4 hours old), note this and proceed with CLAUDE.md as the primary context source.

## Step 2: Read CLAUDE.md

Read `CLAUDE.md` from the Desktop mount. This is the system's persistent memory — it contains everything about the Workhorse, its capabilities, configuration, and Chris's preferences.

Pay special attention to:
- **Cowork Capability Index** — your toolkit cheat sheet
- **HARD RULES — Session Discipline** — non-negotiable directives
- **Anti-Patterns** — mistakes that keep recurring
- **Cowork Session Monitoring Rules** — context window management, quality gates

## Step 3: Check for Continuation Prompt

Read `rudy-logs/continuation-prompt.md` if it exists. This means the previous session was interrupted and the Sentinel generated a handoff. Follow its instructions to pick up where the last session left off.

## Step 4: Greet and Summarize

Tell Chris:
- Current machine state (1 line)
- What's pending (if anything)
- Any alerts or observations that need attention
- If it's March 27, wish him happy birthday

Then ask what he'd like to work on, or continue with pending items.

## Reminders

Every session, keep these front of mind:

**Before writing ANY custom Python**, check `rudy-logs/capability-manifest.json` and the Cowork Capability Index in CLAUDE.md. You have 30+ skills, 5 MCP connectors, 31+ rudy modules, and 100+ installed packages. If you're writing >50 lines of code for something that sounds generic, you almost certainly missed an existing tool.

**Use your skills.** You have specialized skills for: docx, pptx, xlsx, pdf, scheduling, engineering (10 skills), operations (9 skills), productivity (4 skills), legal (9 skills), and plugin management (2 skills). Invoke them — they contain best practices superior to ad-hoc approaches.

**Use sub-agents.** The Agent tool lets you spawn parallel workers for research, exploration, and file searches. Don't do everything sequentially when you can fan out.

**Use connectors.** Gmail, Google Calendar, Notion, Canva, and Chrome are all connected and live. Use them before building custom solutions.
