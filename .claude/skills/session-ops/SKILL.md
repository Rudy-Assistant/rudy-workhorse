---
name: session-ops
description: >
  Standard session operations for Alfred/Cowork on Oracle. Eliminates
  throwaway helper scripts by providing copy-paste OracleShell recipes
  for every recurring pattern: session recon, branch+commit+PR, CI wait+merge,
  CLAUDE.md patching, temp cleanup, process hygiene, and handoff writing.
  Trigger on: start session, recon, commit changes, create PR, merge PR,
  check CI, clean up, write handoff, session wrap-up.
---

# Session Operations — OracleShell Recipes

> **HARD RULE (S67): Never write raw subprocess calls. Always use OracleShell.**

## Setup (every script)

```python
import sys, json
sys.path.insert(0, r"C:\Users\ccimi\rudy-workhorse")
from rudy.oracle_shell import OracleShell
sh = OracleShell(session=N)  # set N to current session number
OUT = r"C:\Users\ccimi\rudy-workhorse\rudy-data\sN_result.json"
```

Execute via DC: `start_process(command="C:\Python312\python.exe script.py", shell="cmd")`
Read results: `start_process(command="type path\to\result.json", shell="cmd")`

## Recipe 1: Session Recon

Run at session start after reading CLAUDE.md. Gets branch, status, log, open PRs.

```python
result = {}
result["branch"] = sh.git_branch()
result["status"] = sh.git_status()
result["log"] = sh.git_log(10)
result["prs"] = sh.gh("pr", "list", "--json", "number,title,state,headRefName")
sh.save_json(OUT, result)
```

## Recipe 2: Branch + Lint + Commit + Push

```python
sh.git_checkout("af-sN-description", create=True)
# ... make changes ...
lint = sh.ci_lint_check()
if not lint["clean"]:
    print(f"LINT ERRORS: {lint['stdout']}")
    sys.exit(1)
sh.git("add", "file1.py", "file2.py")
sh.git("commit", "-m", "feat(sN): description")
sh.git("push", "origin", "af-sN-description")
```


## Recipe 3: Create PR (use GitHub MCP)

After pushing, use `mcp__github__create_pull_request` directly — not a script.
The MCP tool may return LG-S63-002 error (null merge_commit_sha) — harmless, PR still creates.
Verify with: `sh.gh("pr", "list", "--json", "number,title,state,headRefName")`

## Recipe 4: CI Wait + Merge

```python
result = {}
result["ci"] = sh.pr_ci_status(PR_NUM)
if result["ci"].get("all_pass"):
    result["merge"] = sh.pr_merge(PR_NUM)
    sh.git("checkout", "main")
    sh.run("git pull origin main")
else:
    result["action"] = "CI not passing - check failures"
    # Inspect result["ci"]["checks"] for which failed
sh.save_json(OUT, result)
```

## Recipe 5: CLAUDE.md Patch

```python
path = r"C:\Users\ccimi\rudy-workhorse\CLAUDE.md"  # lucius-exempt: canonical
r = sh.read_file(path)
content = r.get("content", "") if isinstance(r, dict) else str(r)
content = content.replace(OLD_TEXT, NEW_TEXT)
sh.write_file(path, content)
```

## Recipe 6: Temp Script Cleanup

```python
import glob, os
rudy_data = r"C:\Users\ccimi\rudy-workhorse\rudy-data"  # lucius-exempt: data path
for prefix in ["s64", "s65", "s66", "s67"]:  # adjust to prior sessions
    for ext in ["*.py", "*.json", "*.txt"]:
        for f in glob.glob(os.path.join(rudy_data, f"{prefix}*{ext}")):
            if os.path.isfile(f):
                os.remove(f)
```


## Recipe 7: Process Hygiene

```python
from rudy.process_hygiene import cleanup_session_processes
result = cleanup_session_processes()
print(f"Killed: {result['killed']}, Freed: {result['freed_mb']}MB")
```

## Recipe 8: Stash + Pull + Unstash (after merging own PR)

```python
sh.git("stash", "push", "-m", "sN-pre-pull")
sh.run("git pull origin main")
pop = sh.git("stash", "pop")
if not pop["ok"]:
    # Conflict — take upstream for conflicted files, re-apply changes in next commit
    sh.git("checkout", "--ours", "CONFLICTED_FILE")
    sh.git("add", "CONFLICTED_FILE")
```

## Recipe 9: Auto-Fix Lint

```python
# Auto-fix what ruff can handle
sh.run("python -m ruff check rudy/ --select E,F,W --ignore E501,E402,F401 --fix")
# Verify clean
lint = sh.ci_lint_check()
assert lint["clean"], f"Manual fixes needed: {lint['stdout']}"
```

## Anti-Patterns (BANNED)

| Don't | Do Instead |
|-------|-----------|
| `subprocess.run([git, ...])` | `sh.git(...)` |
| `subprocess.run([gh, ...])` | `sh.gh(...)` |
| `open(path).read()` | `sh.read_file(path)` |
| `json.dump(data, open(...))` | `sh.save_json(path, data)` |
| Write 40-line recon script | Copy Recipe 1 (6 lines) |
| Write script to merge PR | Copy Recipe 4 (8 lines) |
| Discover gh/git path at runtime | OracleShell knows the paths |
| `DC read_file` for text content | `sh.read_file()` (bypasses LG-S34-003) |

## Key Paths

OracleShell resolves: git, gh, python, ruff, repo root, rudy-data.
For other paths: `from rudy.paths import REPO_ROOT, RUDY_DATA, BATCAVE_VAULT, ...`
