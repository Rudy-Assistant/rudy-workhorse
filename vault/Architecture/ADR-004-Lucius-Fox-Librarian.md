---
title: "ADR-004: Lucius Fox — The Batcave's Librarian"
status: Proposed
date: 2026-03-29
tags: [architecture, adr, governance, librarian, quality-gate]
---

# ADR-004: Lucius Fox — The Batcave's Librarian

## Status
Proposed

## Context
The Batcave multi-system architecture (multiple repos, Obsidian vault, agents) has no single authority owning what exists, where it lives, or whether protocols are followed. Knowledge fragmentation, duplicate sentinel instances, unused skills, and divergent designs across sessions revealed the gap.

## Decision
Lucius Fox becomes the full librarian with three mandates:
1. **The Library** — maintain canonical registry of all artifacts (repos, vault, skills, connectors, ADRs)
2. **The Gate** — enforce pre-merge review for all canonical changes
3. **The Conscience** — monitor skill utilization, protocol adherence, and waste detection

Lucius is a deliberate, methodical persona that prioritizes correctness over speed.

## Consequences
**Positive:**
- New instances orient instantly via registry
- No more artifact archaeology across repos
- Skills invoked appropriately
- Multi-instance coordination built-in

**Negative:**
- Every change requires review (overhead)
- Registry maintenance per-session cost
- Single point of failure if registry breaks

## Related
- [[ADR-005-Build-vs-Buy]]
- [[ADR-006-Lucius-Upgrade]]
- Source: `docs/ADR-004-lucius-fox-librarian.md`
