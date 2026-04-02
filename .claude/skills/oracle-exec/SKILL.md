---
name: oracle-exec
description: "Execute Python code and read files on Oracle (the local Windows machine) via Desktop Commander. MUST USE THIS SKILL whenever you need to: (1) run Python on Oracle, (2) read files that Cowork mount can't access (I/O errors, locked files, rudy-data/coordination/), or (3) interact with Oracle's filesystem when Cowork tools fail. Covers three known bugs: CMD mangles python -c quotes (LG-S34-003), DC read_file returns metadata-only, and Cowork mount I/O errors on Oracle-local files. The pattern: write a .py file via write_file, execute via start_process, then delete. Never use python -c on Oracle. Trigger on: run Python on Oracle, I/O error on mount, read_file returns metadata, Desktop Commander Python, validate on Oracle, test on Oracle, EIO error."
---

# Oracle Execution & File Access

## Why This Skill Exists

Three recurring bugs waste 2-5 tool calls per session when forgotten:

1. **CMD mangles Python `-c` quotes** (LG-S34-003) — inline Python always fails on Oracle. Write a .py file instead.
2. **Cowork mount I/O errors** — files in `rudy-data/coordination/`, locked files, and Robin runtime state often can't be read via Cowork's Read tool. Use Desktop Commander instead.
3. **DC `read_file` returns metadata-only** — Desktop Commander's own read_file sometimes returns only file metadata. The fix: write a Python script that reads and prints the file contents, then execute it.

## The Pattern

### Step 1: Write the script

Use `mcp__Desktop_Commander__write_file` to write a `.py` file to `C:\Users\ccimi\rudy-workhorse\rudy-data\` with a descriptive name prefixed by the session number (e.g., `s60_validate.py`).

The script must include `sys.path.insert(0, r'C:\Users\ccimi\rudy-workhorse')` at the top if importing from the `rudy` package.

```python
"""S{N} — {brief description}"""
import sys
sys.path.insert(0, r'C:\Users\ccimi\rudy-workhorse')
# ... your code ...
```

### Step 2: Execute via Desktop Commander

```
mcp__Desktop_Commander__start_process
  command: cd /d C:\Users\ccimi\rudy-workhorse & C:\Python312\python.exe rudy-data\s{N}_{name}.py
  shell: cmd
  timeout_ms: 15000
```

Key details:
- **Always use `shell: cmd`** — PowerShell has additional quoting issues and sometimes can't find `git`.
- **Always use `cd /d`** — the `/d` flag changes drive letter too.
- **Use semicolons (`;`) in PowerShell, ampersand (`&`) in CMD** to chain commands.
- **Python path:** `C:\Python312\python.exe` (Windows native, not WSL).
- **Timeout:** 15000ms for quick scripts, up to 60000ms for longer operations.

### Step 3: Clean up (when done with the session)

Delete temp scripts at end of session. If files are locked by an active process (like Robin's bridge), note in the handoff — don't fight it.

```
mcp__Desktop_Commander__start_process
  command: cd /d C:\Users\ccimi\rudy-workhorse & del rudy-data\s{N}_*.py
  shell: cmd
  timeout_ms: 10000
```

## Pattern B: Read Oracle Files When Cowork Mount Fails

When Cowork's `Read` tool returns an I/O error (EIO) for files under `rudy-data/`, `rudy-logs/`, or any Oracle-local path, use Desktop Commander instead:

```
mcp__Desktop_Commander__start_process
  command: type C:\Users\ccimi\rudy-workhorse\rudy-data\coordination\session-loop-config.json
  shell: cmd
  timeout_ms: 10000
```

For binary files or when `type` isn't sufficient, write a Python script that reads and prints the file (Pattern A above).

Common files that need this pattern: `session-loop-config.json`, `robin-status.json`, `active-directive.json`, any file written by Robin's bridge process.

## Pattern C: DC read_file Returns Metadata-Only

If `mcp__Desktop_Commander__read_file` returns only file metadata instead of content, fall back to Pattern A — write a Python script that opens and prints the file. This is a known Desktop Commander bug (LG-S34-003). Do NOT call `read_file` repeatedly hoping it works.

## What NOT To Do

- **Never use `python -c "..."` on Oracle.** CMD will mangle the quotes. Every time. No exceptions.
- **Never use PowerShell for git commands.** Git isn't in PowerShell's PATH on Oracle. Use `shell: cmd`.
- **Never use `&&` in PowerShell.** Use `;` instead. Or better: use CMD.
- **Never leave temp scripts without session prefix.** Always use `s{N}_` prefix so cleanup is targeted.

## Quick Reference

| Need | Command |
|------|---------|
| Python path | `C:\Python312\python.exe` |
| Repo path | `C:\Users\ccimi\rudy-workhorse` |
| Temp script dir | `rudy-data\` |
| Shell for Python | `cmd` |
| Shell for git | `cmd` |
| Chain commands (CMD) | `&` |
| Chain commands (PS) | `;` |

## Rudy Package API

Before writing scripts that import from `rudy`, check `references/rudy-api.md` in this skill directory for the actual method names. Common mistake: `PersonaRegistry` uses `list_all()` not `get_all_personas()`.
