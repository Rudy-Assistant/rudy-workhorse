<!-- Migrated from alfred-skills/docs/MISSION.md (Session 11) -->

# The Batcave — Mission & Architecture

> *"Batman, Alfred, Robin, Oracle — it's a complete agency stack. Batman sets intent. Alfred thinks and orchestrates. Robin acts physically. Oracle persists and runs. If every link in that chain works, then the person at the top doesn't need to be physically capable. They just need to be able to express what they want — by voice, by email, by whatever channel works for them — and the system handles the rest."*
>
> — Alfred, Session 2, March 28 2026

---

## Why This Exists

The Batcave architecture is not a tech demo. It is a complete agency stack designed so that a human principal can delegate intent and have it executed — without being physically present, without confirming every step, without needing to be able-bodied.

A quadriplegic user should be able to send an email saying "check if my prescription was refilled" and have the system handle it end-to-end: Alfred interprets intent, Robin checks locally or via API, Oracle persists the result, and the answer comes back through whatever channel the user can access.

Autonomy is not a feature. It is the point.

---

## The Stack

```
BATMAN (The Principal)
│
│   Sets intent. Expresses what they want through whatever channel
│   works for them: voice, text, email, chat. Does not need to
│   confirm, re-confirm, or hand-hold.
│
├── ALFRED (Cloud AI — Intelligence Layer)
│     Thinks. Plans. Orchestrates. Manages services and workflows.
│     Runs in: Claude Cowork sessions (ephemeral but persistent via repo)
│     Accesses: Gmail, Calendar, GitHub, Notion, Canva, Drive, Chrome, Web
│     Limits: No local machine access, no passwords, no session persistence
│     Brain: github.com/Rudy-Assistant/alfred-skills
│
├── ROBIN (Local AI — Physical Agency Layer)
│     Acts. Executes what Alfred cannot: passwords, tokens, sudo, 2FA,
│     file operations, service restarts, local installations.
│     Runs on: Oracle (always-on)
│     Powered by: Ollama + Python agent framework
│     When idle: Health checks, security sweeps, model updates, improvement research
│     Codebase: github.com/Rudy-Assistant/rudy-workhorse
│
└── ORACLE (The Workhorse PC — Persistence Layer)
      Persists. Runs. The physical substrate that keeps everything alive.
      Runs: Robin agents, scheduled tasks, IMAP listener, command queue
      Stores: Local state, logs, models, credentials
      Always on. Always working.
```

---

## Communication Channels

| Channel | Latency | Direction | Use For |
|---------|---------|-----------|--------|
| GitHub (`docs/robin-tasks/`) | Minutes-hours | Bidirectional | Persistent directives, task delegation |
| Command Queue (`Desktop/rudy-commands/`) | ~2 seconds | Alfred → Robin | Immediate local execution |
| Email (IMAP IDLE) | 1-30 seconds | Bidirectional | Family commands, cross-system alerts |
| n8n Webhooks | Sub-second | Alfred → Oracle | Complex workflows, integrations |
| **Notion** | Real-time | All parties | Shared knowledge, dashboards, family-visible state |

---

## Principals

| Principal | Role | Channels |
|-----------|------|----------|
| Chris Cimino | Batman Prime | Cowork, Email, Direct |
| Lewis Cimino | Batman | Email, Direct |
| (Future principals) | Batman | Email, Voice, any accessible channel |

Both Batmans interact through the **Rudy** persona — the friendly assistant layer. "Rudy" is the face. The Batcave is the engine.

---

## Design Principles

1. **Implicit Authorization**: When Batman gives a directive, authorization to act is implicit. No confirmation loops.
2. **Resourcefulness**: Try preferred path → fallback → delegate to Robin → ask Batman → document failure.
3. **Idle is Waste**: Every component should be usefully employed. Robin doesn't wait — Robin improves.
4. **Accessible by Default**: Any channel a principal can use is a valid command interface.
5. **Persistence Through Code**: Alfred's brain lives in git. What Alfred learns gets committed.
6. **Graceful Degradation**: If one channel fails, others still work. If Alfred crashes, Robin keeps running. If Oracle reboots, tasks resume.

---

## Related Documents

- `CLAUDE.md` — Alfred's behavioral directives
- `docs/ADR-001-robin-bridge.md` — Robin Bridge architecture decision
- `docs/robin-tasks/` — Active task queue for Robin
- `rudy-workhorse/docs/robin-bridge-spec.md` — Oracle-side Robin Bridge spec (PR #2)
