# ADR-005: Build-vs-Buy Gate — Lucius Mandate 4

**Status:** Accepted
**Date:** 2026-03-30
**Author:** Alfred (Session 15), mandated by Batman Prime
**Supersedes:** None (new mandate)

## Context

Session 15 revealed a systemic failure in the Batcave's quality gates. Despite Lucius Fox v2.0 enforcing hardcoded path hygiene, import discipline, lint compliance, and pre-merge review, he had **zero checks** for the most fundamental engineering question: *should this code exist at all?*

### The Failure

In Session 15 alone, Alfred wrote 314 lines of custom CI review code (`scripts/ci/lucius_pr_review.py`) that reimplements checks already available in:

| Custom Check | Lines | Industry Tool | Status |
|-------------|-------|--------------|--------|
| Hardcoded path detection | ~30 | **semgrep** (custom rules) | Reinvented |
| Security anti-patterns (eval, exec, shell, pickle) | ~25 | **bandit** (68 built-in checks, B101-B703) | Reinvented |
| Broad except detection | ~15 | **pylint** W0702/W0703, **ruff** E722 | Reinvented |
| Import hygiene | ~15 | **semgrep** (custom rules) | Partially custom |
| Diff parsing + PR comment posting | ~80 | **reviewdog** (universal adapter) | Reinvented |

This is not an isolated incident. Prior sessions built:

| Module | Lines | What It Reimplements |
|--------|-------|---------------------|
| `lucius_fox.py` security checks | ~60 | bandit |
| `lucius_fox.py` lint wrapper | ~30 | Direct ruff (already in CI) |
| `lucius_fox.py` dependency audit | ~50 | pip-audit, safety |
| `lucius_fox.py` docstring checks | ~30 | pylint C0114/C0115/C0116, ruff D100-D107 |
| `lucius_fox.py` complexity (implicit) | 0 | radon, ruff C901 (never added) |

### Root Cause

Lucius's three mandates (Library, Gate, Conscience) audit code *quality* but never audit code *necessity*. There is no check that asks:

1. Does an established, maintained tool already do this?
2. Are we importing a library elsewhere in the codebase that already solves this?
3. Is the custom implementation meaningfully better than the standard tool, or just different?

The accountant was checking that every receipt was formatted correctly, but never asking why we're manufacturing our own paper when Office Depot is next door.

## Decision

### Add Mandate 4: The Economist

Lucius Fox gains a fourth mandate:

> **Mandate 4 (The Economist):** Before any new module, workflow, CI check, or significant function is approved, verify that no existing tool, library, or already-imported dependency serves the same purpose. Custom code is a liability — every line we write is a line we must maintain, debug, and document. Standard tools get maintained by their communities for free.

### Concrete Implementation

1. **Proposal review enhancement**: `_review_proposal()` must now check:
   - Does a PyPI package exist that does this? (Check `KNOWN_REPLACEMENTS` registry)
   - Does GitHub Actions marketplace have an action for this?
   - Is an equivalent already imported elsewhere in the codebase?
   - If custom code exists, what is the justification? (Must be documented)

2. **New hygiene check**: `_check_reinvention()` scans for patterns that indicate wheel-reinvention:
   - Custom regex pattern matching that duplicates bandit/semgrep rules
   - Custom subprocess wrappers around tools that have Python APIs
   - Custom CI scripts that replicate existing GitHub Actions
   - Custom diff parsing (tool X exists)

3. **KNOWN_REPLACEMENTS registry**: A maintained lookup table in lucius_fox.py mapping common custom patterns to their standard replacements.

4. **Diff review addition**: When reviewing new code in PRs, flag functions whose docstrings or names suggest functionality covered by standard tools.

### Remediation Plan

Immediate (this PR):
- Add Mandate 4 to Lucius (the check infrastructure)
- Add `KNOWN_REPLACEMENTS` registry
- Add `_check_reinvention()` to hygiene_check mode
- Document the policy in CLAUDE.md

Near-term (next 2 sessions):
- Replace `scripts/ci/lucius_pr_review.py` security checks with bandit
- Replace custom diff commenting with reviewdog
- Add pip-audit to CI for dependency scanning
- Keep only the truly custom check: hardcoded path detection (Batcave-specific)

Longer-term:
- Slim `lucius_fox.py` by delegating to bandit, pip-audit, and ruff for their respective domains
- Lucius becomes an *orchestrator* of standard tools, not a reimplementor

### What Stays Custom (Justified)

| Component | Why Custom | Standard Alternative Considered |
|-----------|-----------|-------------------------------|
| `rudy/paths.py` | Repo-specific path constants | No equivalent (project config) |
| `robin_alfred_protocol.py` | Air-gapped filesystem IPC for Oracle | Celery/RQ require broker daemon |
| `robin_taskqueue.py` | Offline priority queue for air-gapped system | Celery/RQ require Redis/RabbitMQ |
| Hardcoded path detection | Batcave-specific `C:\Users\ccimi\Desktop` patterns | semgrep could do this with custom rules |
| `batcave_memory.py` | Confidence-tracked learning with dedup | LangGraph checkpoints lack confidence/dedup |
| `knowledge_base.py` | Already uses ChromaDB (standard tool) | N/A (good choice) |
| Lucius review record format | Custom verdict + findings JSON | No standard for agent-to-agent review records |

## Consequences

### Positive
- Prevents future NIH syndrome
- Reduces maintenance burden (fewer custom lines = fewer bugs)
- Forces research before implementation
- Lucius gains credibility as a true efficiency auditor

### Negative
- Adds overhead to proposal review (must research alternatives)
- Some standard tools have heavier dependency footprints
- Air-gapped Oracle constraint limits some replacements

### Risks
- Over-correction: rejecting all custom code even when genuinely justified
- Mitigation: KNOWN_REPLACEMENTS includes explicit "KEEP" entries with documented justification
