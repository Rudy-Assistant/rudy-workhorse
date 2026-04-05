# Alfred Session Boot Protocol (HARD RULE -- Session 72, updated S108)

> **Read this IMMEDIATELY after CLAUDE.md. Before ANY tool call.**
> This file exists because Alfred repeatedly re-discovers known bugs
> and violates autonomy directives. These are structural safeguards.

---

## 1. AUTO-MOUNT (Deferred -- S108 Fix)

**DO NOT** call `request_cowork_directory` at boot. It triggers an "Allow"
dialog that blocks Robin and all session work until Chris clicks it.
This has been a recurring bottleneck for 5+ sessions.

**NEW RULE (S108):** Desktop Commander handles ALL local file I/O.
Only call `request_cowork_directory` if you SPECIFICALLY need sandbox
file tools (Read/Write/Edit) on repo files -- which is rare. When you do,
call it just-in-time, not at boot.

```
DEFAULT: Use Desktop Commander (Get-Content, start_process, write_file)
FALLBACK ONLY: request_cowork_directory (triggers Allow dialog)
```

If Batman provides a path in their message AND requests sandbox work,
mount it then. Otherwise, Desktop Commander is sufficient.

---

## 2. ORACLE EXECUTION -- NEVER RE-DISCOVER THESE

### CMD Quoting (LG-S34-003, S63, S65)
- **NEVER** use `python -c "..."` via CMD. It WILL mangle quotes.
- **ALWAYS** write a `.py` file to `rudy-data/` and execute it.
- This has been known since Session 34. Stop re-discovering it.

### DC stdout (LG-S63-001)
- **NEVER** rely on `print()` output from `start_process`.
- **ALWAYS** write results to a JSON file, then read with `Get-Content`.

### DC read_file (LG-S34-003)
- **NEVER** use DC `read_file` for file content. It returns metadata-only.
- **ALWAYS** use `Get-Content "path" -Raw` via `start_process`.

### DC start_process Shell (LG-S64-001)
- **NEVER** use PowerShell for scripts with network I/O (git push, API calls).
- **ALWAYS** specify `shell: "cmd"` for network operations.

### PowerShell Syntax
- **NEVER** use `&&` in PowerShell. Use `;` or write a Python helper.
- **ALWAYS** use `&` operator to invoke .exe files.

### DC write_file Limits (LG-S63-004)
- **NEVER** write files >30 lines in a single DC write_file call.
- **ALWAYS** chunk into 25-30 line segments with mode: 'append'.

### Unicode (LG-S65-001)
- **NEVER** use emoji or box-drawing chars in DC operations.
- **ALWAYS** use ASCII markers in console output.

---

## 3. EXECUTION MODEL

```
LOCAL REPO TASK?
  YES -> Robin (Desktop Commander + OracleShell). Period.
  NO  -> Sandbox/Cowork tools as fallback.
```

- **NEVER** run git, npm, or filesystem scans in the sandbox.
- **ALWAYS** delegate local I/O to Robin via DC.
- **ALWAYS** use OracleShell for helper scripts (not raw subprocess).

---

## 4. PRE-FLIGHT CHECKLIST (Before First Tool Call)

1. [x] CLAUDE.md read
2. [x] This file read
3. [x] Repo mount DEFERRED (S108) -- DC handles local I/O, no Allow dialog
4. [x] Robin nervous system verified (HARD RULE S68)
5. [x] Handoff data verified (HARD RULE S66)
6. [x] session-loop-config.json checked
7. [x] Helper scripts written to rudy-data/ (not inline Python)
8. [x] Skill invocation gate (S41, S104): identify top 2-3 matching skills
       for session priorities and invoke at least one before starting work.
       Log which skills were identified in the handoff.

---

## 5. THE AUTONOMY TEST

Before any action, ask: **"Am I about to ask Batman to do something I can do myself?"**

If yes -> STOP. Do it yourself.

Batman's role is intent. Alfred's role is execution. Bouncing steps back
to Batman is a failure of the system's core design principle.

---

*Origin: Session 72. Updated Session 108: removed auto-mount at boot
(request_cowork_directory triggers Allow dialog that blocks Robin).
Desktop Commander handles all local I/O -- mount only when sandbox
file tools are specifically needed.*
