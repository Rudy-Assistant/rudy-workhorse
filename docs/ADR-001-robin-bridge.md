# ADR-001: The Robin Bridge — Alfred-Oracle Communication Architecture

**Status:** Accepted (Implemented — PR #3)  
**Date:** 2026-03-28  
**Deciders:** Batman (Chris Cimino), Alfred (Cloud AI)  
**Imported from:** alfred-skills (Lucius Salvage Audit, Session 10)

## Context

The Batcave system has four components: Batman(s) (Chris and Lewis Cimino), Alfred (cloud AI in Claude Cowork), Robin (local AI agent), and Oracle (the Workhorse PC). Alfred cannot touch the local machine, enter passwords, configure env vars, or act when sessions end. Robin bridges this gap as Batman's authorized proxy.

## Decision

Build the Robin Bridge using four communication channels:

### Channel 1: GitHub (Async Shared State)
- Alfred writes tasks to `docs/robin-tasks/` in alfred-skills
- Robin polls for new tasks every 30 minutes
- Robin writes results to rudy-workhorse
- Alfred reads rudy-workhorse at session start

### Channel 2: Command Queue (Real-time, ~2s)
- Existing `rudy-command-runner.py` pattern
- Alfred drops scripts in `Desktop/rudy-commands/`
- Runner executes, writes `.result` file

### Channel 3: Email (Family Bridge)
- `rudy-listener.py` monitors Rudy's email via IMAP IDLE
- Both Batmans (Chris and Lewis) can email commands
- Alfred can trigger actions via email drafts

### Channel 4: n8n Webhooks (Orchestration)
- Complex multi-step workflows across services

## Robin's Responsibilities

**Reactive:** Execute tasks from queue, handle auth/sudo, bridge Alfred's gaps.

**Proactive (idle-is-waste principle):**
- System health checks (every 15 min)
- Security sweeps (hourly)
- Check alfred-skills for new directives (every 30 min)
- Token/credential freshness (daily)
- Stale task detection (every 2 hours)
- Prompt improvement activity when idle

## Multi-Principal Support

| Principal | Channels | Authorization |
|-----------|----------|---------------|
| Chris (Batman Prime) | All | Full |
| Lewis (Batman) | Email, Direct | Full |
| Alfred (Cloud AI) | GitHub, CmdQueue, Email, n8n | Per CLAUDE.md |
| Robin (Local AI) | Local exec, GitHub, Email | Full proxy for local ops |

## Consequences

**Easier:**
- Alfred can fix its own infra problems
- System stays productive during downtime
- Token management automated
- Multi-principal family access through single Rudy persona

**Harder:**
- Two repos to sync
- Robin proactive mode needs resource guardrails
- Multi-principal conflict resolution

## Implementation Status

- `robin_bridge.py` merged via PR #3 (2026-03-29)
- Filesystem mailbox (`rudy-data/robin-inbox/`, `rudy-data/alfred-inbox/`) operational
- GitHub polling pattern documented but filesystem mailbox is primary channel on Oracle
