# Lucius Fox: Robin Branch Merge Plan

**Plan ID**: LUCIUS-SESSION11-MERGE-PLAN
**Date**: 2026-03-29
**Author**: Lucius Fox (via Alfred/Cowork, Session 11)
**Classification**: OPERATIONS — Git Branch Consolidation
**Prerequisites**: New GitHub PAT with `repo` scope

---

## Decision

**Fast-forward merge** of `alfred/robin-logging-nightwatch` into `main`.

The reconciliation audit found zero conflicts, zero KEEP-MAIN verdicts, and zero files
requiring manual merge. Nightwatch is a strict superset of main. A fast-forward merge
is the cleanest operation — it advances main's HEAD to nightwatch's tip without creating
a merge commit, preserving the full linear commit history.

---

## Pre-Merge Checklist

- [ ] New GitHub PAT generated with `repo` scope for `Rudy-Assistant` org
- [ ] PAT configured in `rudy-data/robin-secrets.json` and environment
- [ ] Verify local state is clean: `git status` shows no uncommitted changes
- [ ] Commit ADR-004 if untracked: `docs/ADR-004-lucius-fox-librarian.md`

## Git Operations (Execute in Order)

### Step 0: Commit Outstanding Work
```
git add docs/ADR-004-lucius-fox-librarian.md docs/robin-merge-plan.md
git add rudy-data/coordination/
git commit -m "docs: Add ADR-004 Lucius Fox spec + merge plan + coordination dir"
```

### Step 1: Push Nightwatch to Origin
```
git push origin alfred/robin-logging-nightwatch
```

### Step 2: Fast-Forward Merge to Main
```
git checkout main
git merge --ff-only alfred/robin-logging-nightwatch
```

### Step 3: Push Main
```
git push origin main
```

### Step 4: Clean Up Stale Branches
```
git branch -d alfred/robin-logging-nightwatch
git push origin --delete alfred/robin-logging-nightwatch
```

## Post-Merge Verification

```
python -c "from rudy.agents.robin_sentinel import run_boot_sequence; print('sentinel OK')"
python -c "from rudy.robin_taskqueue import load_queue; print('taskqueue OK')"
python -c "from rudy.robin_alfred_protocol import RobinMailbox; print('mailbox OK')"
python -c "from rudy.sanitize import sanitize_str; print('sanitize OK')"
python -m pytest tests/test_sanitize.py -v
git log --oneline -5
git branch -a
```

## Post-Merge Actions

1. Update `robin_bridge.py` ALFRED_REPO constant (alfred-skills being archived)
2. Archive `alfred-skills` repo on GitHub
3. Add .gitignore rules for runtime data
4. Update BatcaveVault docs to reflect merged state

## Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| ff-only merge fails | LOW | LOW | Fall back to regular merge |
| Push fails (PAT) | HIGH | MEDIUM | Batman generates new PAT first |
| Import breakage | LOW | LOW | Shims in place; run verification |

---

*See full reconciliation: BatcaveVault/Audits/Robin Code Reconciliation.md*
