---
title: "ADR-007: Obsidian Vault Integration"
status: Accepted
date: 2026-03-31
tags: [architecture, adr, vault, obsidian, knowledge-management]
---

# ADR-007: Obsidian Vault Integration

## Status
Accepted (Phase 1 implemented S38, Phase 2 in progress S39)

## Context
Institutional knowledge was scattered across CLAUDE.md, session handoffs, Notion, and code comments. No single source of truth existed for session records, findings, protocols, or architecture decisions. New sessions lost context because handoff briefs couldn't capture everything.

## Decision
Adopt an Obsidian-compatible markdown vault (`vault/`) as the canonical institutional memory. Structure: Sessions/, Architecture/, Protocols/, Findings/, Templates/, Dashboards/. HandoffWriter auto-generates session records. All decisions, findings, and protocols must be vault-first.

## Phases
1. **Phase 1 (S38):** Base dashboards, templates, session backfill (S13-S37)
2. **Phase 2 (S39):** Architecture notes (ADR-004 through ADR-010), Protocol notes, enrichment of sparse sessions

## Consequences
- Session knowledge survives context window boundaries
- Robin can read vault for institutional context
- Requires `git add -f vault/` (gitignored by default for per-Oracle customization)
- Adds maintenance burden: every session must update vault

## Related
- [[ADR-004-Lucius-Fox-Librarian]] — Lucius enforces vault discipline
- [[FoxGate]] — Step 4 requires vault session record
- Source: Session 38 P2 implementation
