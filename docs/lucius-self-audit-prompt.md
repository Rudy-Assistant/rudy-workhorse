# Lucius Self-Audit Prompt

> **Purpose**: Lucius audits his own governance infrastructure for gaps, dead code, missing enforcement, and improvement opportunities. This is the meta-audit — Lucius turning his own tools on himself.
>
> **When to run**: Monthly, or after any session that modifies Lucius modules.
>
> **How to run**: Feed this entire prompt to Alfred at session start. Alfred executes each phase, files findings via `lucius_findings.add_finding()`, and produces a remediation plan.

---

## HARD RULE: Read `CLAUDE.md` first. Then read this document.

---

## Phase 1: Structural Integrity Audit

Verify that every Lucius module compiles, imports correctly, and hasn't rotted.

**Steps:**
1. Run `py_compile` on every file in `rudy/agents/lucius_*.py`
2. For each module, attempt a bare import: `from rudy.agents.lucius_gate import session_start_gate` (and equivalent for each module)
3. Verify import isolation (C3 constraint): scan each Lucius module for top-level non-stdlib imports. Any non-stdlib import outside a function body is a **CRITICAL** finding — it means a missing dependency bricks the entire governance layer.
4. Check that `lucius_mcp_tiers.yml` parses cleanly via `yaml.safe_load()`.

**File findings for**: import failures, C3 violations, YAML parse errors.

---

## Phase 2: Rubric-to-Code Alignment

The scorer's RUBRIC dict defines what *should* be scored. The `_score_*` functions define what *actually* gets scored. These must match.

**Steps:**
1. Read `RUBRIC` from `lucius_scorer.py`. For every dimension, list each criterion and its point allocation.
2. Read the corresponding `_score_*` function. Verify that **every criterion defined in RUBRIC is actually evaluated** in the function body. Look for:
   - Criteria defined in RUBRIC but never referenced in the scorer (dead rubric entries — this was LG-S33-001)
   - Point values in scorer code that don't match the RUBRIC allocation (this was LG-S33-002)
   - Evidence fields used by scorer that aren't in `empty_evidence()` (missing evidence template)
   - Evidence fields in `empty_evidence()` that no scorer ever reads (dead evidence)
3. Sum all max_points across dimensions. Must equal exactly 100.
4. Run the scorer with `empty_evidence()` (all defaults) — verify it produces a valid score without errors.
5. Run the scorer with a "perfect" evidence dict (all True, all counts > 0) — verify it produces 100/100.

**File findings for**: rubric/code misalignment, orphaned criteria, point total != 100, scorer crashes on edge cases.

---

## Phase 3: Gate Coverage Audit

The three gates (session_start, pre_commit, post_session) are the enforcement mechanism. Verify they actually enforce what they claim.

**Steps:**
1. **session_start_gate()**:
   - Does it check all MCPs defined in `DEFAULT_MCP_TIERS` or the YAML config?
   - Does it load and report open findings?
   - Does it run skills recommendations when `task_description` is provided?
   - Is there a code path where a CRITICAL MCP failure still returns `passed=True`? (That's a bug.)
   - Time the gate: run it 3x, average the duration. If >30s, file a performance finding.

2. **pre_commit_check()**:
   - It currently only checks protected branches. Is this sufficient? Compare against ADR-004's spec for what pre-commit should verify. Missing checks are findings.
   - ADR-004 Section 2 says pre_commit should verify: branch protection, CI status, commit message format, and that no hardcoded paths are introduced. How many of these are actually implemented?

3. **post_session_gate()**:
   - Does it actually invoke the scorer when evidence is provided?
   - Does it gracefully handle missing scorer (ImportError)?
   - Does it check vault accessibility?
   - Is `context_window_pct` truly enforced or just checked for presence?

**File findings for**: gates that don't enforce their documented scope, missing checks per ADR-004, performance issues.

---

## Phase 4: Findings Tracker Health

The findings system is Lucius's memory. If it's broken, findings get lost.

**Steps:**
1. Load `lucius-findings.json` — does it parse? Is the schema valid?
2. Count open findings by severity. Are there any CRITICAL findings that have been open > 3 sessions? These should have been escalated automatically.
3. Run `escalate_stale_findings(current_session=33)` — does it work? Does it correctly identify findings that need escalation?
4. Test deduplication: call `add_finding()` twice with identical parameters. Verify it returns the same finding (no duplicate).
5. Check for orphaned findings: findings with `status != "resolved"` but whose file no longer exists in the repo. These are stale and should be auto-resolved.
6. Verify the `fingerprint` function produces stable hashes (same input = same output across runs).

**File findings for**: corrupt store, missed escalations, broken dedup, orphaned findings.

---

## Phase 5: Waste Detection Calibration

The waste scanner finds stale artifacts and orphaned modules. Verify its accuracy.

**Steps:**
1. Run `full_waste_scan(session=33)` — record counts.
2. **Stale artifact false positives**: Are any of the "stale" files actually still in active use? Cross-reference against recent imports and git log. Files that are imported but old aren't truly stale — they're stable.
3. **Orphaned module false negatives**: Are there modules that *should* be flagged as orphans but aren't? Check for modules that are only imported by tests, or only by other orphans (transitive orphans).
4. **Missing scan coverage**: The waste scanner only looks at `rudy/` and `scripts/`. Should it also scan `n8n/`, `workhorse/`, `user-apps/`? If yes, file an enhancement finding.
5. Check that filed waste findings don't flood the tracker (cap should be 10 per category per scan).

**File findings for**: false positives, false negatives, missing coverage areas.

---

## Phase 6: Robin Delegation Enforcement

Session 32 added Hard Rule #6 (Robin-first for local I/O). Session 33 added scoring. Verify the enforcement is real.

**Steps:**
1. Check that `lucius_scorer.py` actually scores `robin_delegation` (Session 33 fix — verify it stuck).
2. Check that `empty_evidence()` includes `robin_delegations_count`, `alfred_local_io_count`, `robin_online`.
3. Simulate scoring scenarios:
   - Robin online, 5 delegations, 0 Alfred I/O → should be 5/5 pts
   - Robin online, 0 delegations, 5 Alfred I/O → should be 0/5 pts with penalty note
   - Robin offline, any Alfred I/O → should be 5/5 pts (no penalty)
   - Robin online, 3 delegations, 2 Alfred I/O → should be partial credit
4. Check if anything *enforces* delegation at runtime (not just scores it after the fact). If not, file an enhancement: Lucius should warn Alfred in real-time when Alfred runs local I/O while Robin is online.

**File findings for**: scoring regressions, missing runtime enforcement, edge case failures.

---

## Phase 7: Skill Enforcement Audit

ADR-004 Mandate 3 says Lucius should flag missed skill opportunities. Verify this works.

**Steps:**
1. Does `session_start_gate()` actually call `_skills_check()` when `task_description` is provided? Trace the code path.
2. Does `LuciusFox._skills_check()` exist and return meaningful recommendations?
3. Does the scorer's `skills_invoked_ratio` criterion actually know which skills were invoked? Or is it relying on Alfred self-reporting (which is unreliable)?
4. List all 44+ Cowork skills available. How many has Alfred actually invoked across the last 5 sessions? If <20%, that's a systemic underutilization finding.
5. Is there any mechanism to detect that Alfred should have used a skill but didn't? (e.g., Alfred writes a docx by hand instead of using the docx skill). If not, file an enhancement.

**File findings for**: broken skill recommendations, skill underutilization, missing detection of skill-appropriate tasks.

---

## Phase 8: Protocol Compliance Meta-Check

Lucius enforces protocols. But does Lucius follow his own protocols?

**Steps:**
1. Does Lucius's own code follow the Build-vs-Buy gate (ADR-005)? Check if any Lucius module reimplements something that exists in a standard library or installed package.
2. Does Lucius use `rudy.paths` exclusively (zero hardcoded paths)?
3. Are all Lucius modules registered in `registry.json`?
4. Do Lucius review records (`rudy-data/lucius-reviews/`) follow a consistent schema?
5. Is Lucius's ADR (004) still accurate given the current implementation? List any drift between spec and code.
6. Does Lucius have tests? Check `tests/test_lucius_gate*.py` — what's the coverage? Are the Session 33 changes (robin_delegation scoring) tested?

**File findings for**: Lucius's own protocol violations, ADR drift, missing test coverage.

---

## Phase 9: Friction Log Review

Session 33 introduced `friction-log.json`. Audit it for actionable patterns.

**Steps:**
1. Read `rudy-data/coordination/friction-log.json`.
2. Categorize entries by source (alfred vs robin) and severity.
3. Identify the top 3 friction themes. For each, propose a concrete fix.
4. Check if any friction points map to existing findings (dedup opportunity).
5. If the friction log doesn't exist yet (new feature), file an INFO finding noting it needs to accumulate data.

**File findings for**: recurring friction patterns, unaddressed high-severity friction.

---

## Deliverables

After completing all 9 phases, produce:

1. **Findings summary**: Total findings filed, by severity, by phase.
2. **Top 5 remediation priorities**: Ordered by impact (CRITICAL first, then effort-weighted).
3. **Lucius health score**: Percentage of checks that passed without findings.
4. **Next audit date**: Recommend when to re-run based on findings severity.

Format: Write results to `vault/Sessions/Lucius-Self-Audit-S{N}.md` and file a summary in the session handoff.

---

*"The most dangerous failure mode isn't a gate that blocks incorrectly — it's a gate that passes when it shouldn't."*
