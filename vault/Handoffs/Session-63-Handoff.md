# Session 63 Handoff

**Date:** 2026-04-02
**Alfred Instance:** Cowork (Claude Opus 4)
**Branch:** `af-s63-robin-cli-proposals-v2` (merged to main)
**PRs:** #129 merged (squash), #130 closed, #131 merged (squash)
**HEAD after merges:** Check `git log main -1`

## Completed

### P0: Merged PR #129 — Sentinel Learning Loop (ADR-018)
- Fixed 4 ruff lint errors (sentinel.py, sentinel_learning.py)
- Fixed batcave-paths CI (lucius-exempt on paths.py)
- All 5 CI checks green, squash-merged

### P0: Merged PR #131 — S62+S63 Combined
- S62 work: Robin CLI session init, proposal pipeline
- S63 fixes: 6 ruff lint errors across 3 files
- S63 fixes: batcave-paths CI (paths.py exemptions)
- S63 new: `rudy-data/helpers/oracle_git.py` reusable helper
- S63 new: CLAUDE.md Oracle Execution Patterns + Known MCP Bugs
- Superseded PR #130 (rebased after #129 merge conflict)

### P0: Oracle Execution Patterns in CLAUDE.md
- Shell rules (no `&&`, use Python helpers, Get-Content workaround)
- DC stdout workaround recipe (log to file + Get-Content)
- DC read_file workaround (Get-Content -Raw)
- oracle_git.py usage reference
- Known MCP Bugs table (5 bugs catalogued with workarounds)

### P0: oracle_git.py Reusable Helper
- `rudy-data/helpers/oracle_git.py` — OracleGit class
- Methods: status, log, branch, add, commit, push, full_push, pr_view, pr_merge, ruff_check
- CLI interface for direct invocation
- Handles PATH injection, GH_GIT_EXECUTABLE, UTF-8 encoding

## Not Started

### P1: Test Proposal Pipeline End-to-End
- Deferred. Pipeline code merged but not tested with actual proposal flow.

### P1: Voice Gateway Prototype
- Deferred from S62. Scope: Whisper STT → intent parser → Robin task queue.

## Known Issues

- **DC read_file metadata-only (LG-S34-003)** — still broken
- **DC start_process stdout swallowed (LG-S63-001)** — workaround documented
- **GitHub MCP create_pull_request parse error (LG-S63-002)** — PR creates despite error
- **gh CLI on Oracle can't find git** — GH_GIT_EXECUTABLE env var doesn't work for `pr create`; workaround: use GitHub MCP tool
- **git stash fails with locked Robin runtime files** — stash --include-untracked fails when bridge/sentinel hold locks on rudy-data/ files

## S64 Priorities (Suggested)

1. **P0:** Pull main on Oracle (`git checkout main && git pull`) — verify HEAD includes both merges
2. **P1:** Test proposal pipeline E2E (write → scan → approve → Robin picks up)
3. **P1:** Voice gateway prototype (Whisper STT → Robin)
4. **P1:** Clean up stale branches (100+ branches, many from S25-S52)
5. **P2:** Robin Andrew-readiness improvements (currently 3/10)

## Session Loop Config
- Status: **halted** (since S52) — do not restart without Batman approval

## Key Context for Next Alfred
- Oracle: HP ENVY, Windows 11, Python 3.12 at `C:\Python312\python.exe`
- Git at `C:\Program Files\Git\cmd\git.exe`
- gh at `C:\Program Files\GitHub CLI\gh.exe` (needs PATH injection)
- **Use `rudy-data/helpers/oracle_git.py`** for all git operations
- **Read CLAUDE.md first** — includes Oracle Execution Patterns section (S63)
- DC stdout capture unreliable — always log to file and Get-Content to read
- Currently on branch `af-s63-robin-cli-proposals-v2` locally (merged, can delete)

## Consult CLAUDE.md before any work (HARD RULE — Session 22).
