---
title: "ADR-005: Build-vs-Buy Gate — Lucius Mandate 4"
status: Accepted
date: 2026-03-30
tags: [architecture, adr, governance, efficiency, tool-selection]
---

# ADR-005: Build-vs-Buy Gate

## Status
Accepted

## Context
Session 15 revealed Lucius had zero checks for the fundamental question: "Should this code exist at all?" Alfred reinvented bandit, semgrep, reviewdog checks that already exist in industry tools, writing 314 lines of custom CI code that duplicates established solutions.

## Decision
Add Mandate 4 (The Economist): Before approving any module, workflow, or CI check, verify no existing tool, library, or already-imported dependency serves the purpose. Custom code is a liability requiring community maintenance.

## Consequences
**Positive:**
- Prevents NIH syndrome
- Reduces maintenance burden
- Forces research before implementation

**Negative:**
- Overhead added to proposal review
- Standard tools may have heavier dependencies

## Related
- [[ADR-004-Lucius-Fox-Librarian]]
- [[ADR-006-Lucius-Upgrade]]
- Source: `docs/ADR-005-build-vs-buy-gate.md`
