---
title: "ADR-006: Lucius Fox Upgrade — Active Governance Agent"
status: Proposed
date: 2026-03-31
tags: [architecture, adr, governance, persona, enforcement]
---

# ADR-006: Lucius Fox Upgrade

## Status
Proposed (Session 35)

## Context
Lucius became a rubber stamp in Sessions 32-35. Alfred ignores registry, writes custom scripts without checks, scorer runs post-session with no enforcement. Lucius had no real-time voice or intervention capability despite being designed as governance layer.

## Decision
Three operating modes for active governance:
1. **FoxGate** — Session start protocol reviewing each priority (existing tools check, build-vs-buy, delegation, scope)
2. **Lucius Persona** — `/Lucius` mode for documentation-first governance alongside Alfred
3. **LangGraph Agent** — Future autonomous agent with persistent state, Sentinel signal integration

Add consequential scoring visible in CLAUDE.md and Sentinel→Lucius signal routing for waste/drift detection.

## Consequences
**Positive:**
- Process constrains behavior, not just memory
- Scoring enforcement (visible to every session)
- Tool reuse over reinvention
- Robin delegation becomes enforced

**Negative:**
- FoxGate overhead (2-3 min per session start)
- Risk of over-blocking legitimate code
- LangGraph requires local capacity

## Related
- [[ADR-004-Lucius-Fox-Librarian]]
- [[ADR-005-Build-vs-Buy]]
- Source: `docs/ADR-006-lucius-upgrade.md`
