# Session Protocols (HARD RULES)

> Extracted from CLAUDE.md during R-001 refactor (S99).
> CLAUDE.md retains compact pointers. This file has the full text.

## Away Mode Protocol (HARD RULE -- Session 43)

When Batman says "stepping away for N minutes" or "going to bed" or similar:

**Timed mode** (e.g. "stepping away for 20 minutes"):
```python
from rudy.robin_autonomy import DirectiveTracker
DirectiveTracker.create_directive("Work plan summary here", hours=20/60)
```

**Indefinite mode** (e.g. "going to bed", "handle things"):
```python
DirectiveTracker.create_directive("Work plan summary here", hours=None)
```

Robin's sentinel picks this up automatically:
- Polls every 60s when a directive is active (vs 300s normally)
- AutonomyEngine.decide() routes to directive mode (MODE 1)
- Robin executes tasks, uses Ollama for reasoning, creates PRs
- Checkpoints logged to `rudy-data/coordination/active-directive.json`

**Inactivity auto-activation**: Robin activates after 15 min of no Batman activity
(configurable via `ROBIN_INACTIVITY_MINUTES` env var). No directive needed.

**To cancel**: Set directive status to "cancelled" in the directive file,
or Batman returning naturally supersedes (Robin yields to Alfred).

---

## Process Hygiene Protocol (HARD RULE -- Session 64)

**Every Alfred/Robin session MUST clean up spawned processes before ending.**

DC `start_process` spawns child processes (python, cmd, powershell, conhost)
that persist after completion. Without cleanup, autonomous loops accumulate
hundreds of orphans consuming GB of RAM.

**At session end (before handoff):**
```python
from rudy.process_hygiene import cleanup_session_processes
result = cleanup_session_processes()  # kills idle python/cmd/powershell
# Log: result["killed"], result["freed_mb"]
```

**In autonomous/away mode:** Robin's sentinel MUST call `cleanup_session_processes()`
every 30 minutes when a directive is active.

**Audit command:** `python -m rudy.process_hygiene --audit`
**Preview command:** `python -m rudy.process_hygiene --dry-run`

Protected: Ollama, Node (n8n/MCP), RustDesk, Tailscale, SSH. See `rudy/process_hygiene.py`.

---

## Deletion Gate (HARD RULE -- Session 70, ADR-005 Mandate 5)

**No file shall be deleted from the repository without passing the Lucius Deletion Gate.**

```python
from rudy.agents.lucius_deletion_gate import assess_deletion
result = assess_deletion("path/to/file.py")
# result["verdict"] must be "SAFE_TO_DELETE" to proceed
```

Or via CLI: `python -m rudy.agents.lucius_deletion_gate file1.py file2.py --strict`

**Gate checks:** (1) Import analysis, (2) Config references (CLAUDE.md, registry.json, workflows),
(3) HARD RULE proximity, (4) Robin nervous system -- absolute block on robin_main, robin_liveness,
robin_autonomy, robin_cowork_launcher, etc., (5) Recency.

**Verdicts:** SAFE_TO_DELETE (proceed), REVIEW_REQUIRED (human confirms), BLOCKED (cannot delete).

**Origin:** S70 near-deleted robin_cowork_launcher.py (502 lines of active code) based on stale
registry. The gate also caught a live import dependency on scripts/rudy/rudy-suno.py.

---

## Module Extraction Log (ADR-005 Phase 2, Sessions 70-74)

**Phase 2a (S70):** phone_forensics.py (382L), mvt_integration.py (78L) from phone_check.py
**Phase 2b (S71-74):** lucius_fox.py 1684 -> 578 lines (65.7% reduction). Extracted:
lucius_plan_impact, lucius_diff_review, lucius_skills_check, lucius_reinvention_check,
lucius_hardcoded_paths, lucius_import_hygiene, lucius_audit_report, lucius_proposal_review,
lucius_dependency_audit, lucius_audit_inventory, lucius_audit_governance, lucius_session_checkpoint.

Backward-compat imports preserved. **Remaining targets:** sentinel.py (~1500L), email consolidation.

---

## Lucius Gate -- Session Governance (ADR-004 v2.1, reformed by ADR-016)

**Core module:** `rudy/agents/lucius_gate.py`
**Three gates:** `session_start_gate()` (boot), `pre_commit_check()` (before push),
`post_session_gate()` (before handoff)
**MCP tiers:** `rudy/agents/lucius_mcp_tiers.yml` (CRITICAL/IMPORTANT/OPTIONAL)

Full gate docs: `docs/ADR-004-lucius-fox-librarian.md`

### Lucius Process Reform (ADR-016, effective S52)

**Principle: Fix first. Document second. Score automatically.**

**Time allocation:** 65% implementation, 20% diagnosis, 15% records.

**Fix-or-Justify Gate:** A finding filed without a fix attempt MUST include a
"Why Not Fixed" section. Invalid: "Deferred", "Out of scope". Valid: needs permissions,
context >70%, needs Batman decision.

**Compact records:** Session records max 30 lines. Handoffs max 40 lines.

**Outcome-weighted scoring:** Fixes merged=35%, Deliverable verification=20%,
Finding resolution=25%, Robin throughput=10%, Records quality=10% (penalty only).

**Self-evolution:** Every 5th session includes process retrospective.
