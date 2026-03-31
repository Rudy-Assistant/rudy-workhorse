---
name: git-operations
version: 1.0.0
description: Local git repository management operations
task_type: git
agent: robin
triggers:
  - git status
  - git pull
  - git branch
  - commit changes
  - push branch
---

# Git Operations

Execute git operations on the rudy-workhorse repository.

## Capabilities
- Status check (modified, staged, untracked files)
- Pull latest from remote
- Branch creation and switching (alfred/* namespace)
- Commit with conventional message format
- Push to remote
- PR creation via gh CLI (`C:\Program Files\GitHub CLI\gh.exe`)
- Conflict detection and reporting

## Execution Steps
1. `cd C:\Users\ccimi\rudy-workhorse`
2. Execute requested git operation
3. Validate result (exit code + output parsing)
4. Report structured result

## Branch Rules
- Feature branches: `alfred/session-{N}-{descriptor}` or `robin/{descriptor}`
- Never force-push to main
- Always pull before push
- PR required for main merges

## Output Format
```json
{
  "operation": "status|pull|commit|push|branch|pr",
  "success": true,
  "branch": "current-branch-name",
  "details": {},
  "warnings": []
}
```

## Environment
- Git: `C:\Program Files\Git\cmd\git.exe`
- gh CLI: `C:\Program Files\GitHub CLI\gh.exe`
- Repo: `C:\Users\ccimi\rudy-workhorse`
