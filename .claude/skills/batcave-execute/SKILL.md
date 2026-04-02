---
name: batcave-execute
description: >
  Delegate a local execution task to Robin (the Batcave's autonomous
  executor). Use whenever Alfred needs filesystem operations, git
  commands, npm/pip installs, script execution, port checks, service
  restarts, or any local I/O task. This is a HARD RULE (Session 32):
  Alfred must NEVER execute local I/O tasks directly — always delegate
  to Robin via this skill. Triggers on: file operations, git commands,
  npm/pip, shell commands, "run this", "execute", "install", "build",
  "deploy locally", or any task requiring local machine interaction.
---

# Batcave Execute — Robin Delegation Skill

This skill delegates local execution tasks to the **robin** subagent.
Alfred reasons and orchestrates; Robin executes. This enforces the
Robin-first HARD RULE (Session 32).

## When to Use

- ANY filesystem scan, read, write, move, or delete
- Git operations (commit, push, pull, branch, merge, rebase)
- npm/pip/package manager commands
- Running Python or PowerShell scripts
- Port checks, service status, process management
- CI/CD pipeline monitoring
- File organization or cleanup tasks

## How to Invoke

Use the **Agent tool** to spawn a robin subagent:

```
Agent(
  subagent_type="general-purpose",
  description="Robin execute: [brief description]",
  prompt="""
  You are Robin. Read .claude/agents/robin.md for your full persona.

  TASK: [specific task description]
  WORKING DIRECTORY: C:\Users\ccimi\rudy-workhorse
  EXPECTED OUTPUT: [what success looks like]

  RULES:
  - Do, don't ask. Execute immediately.
  - Use Shell for file ops, git, scripts. Use Snapshot only for UI.
  - Report results concisely: what changed, what succeeded, what failed.
  """
)
```

## Robin Hard Rules (enforced in execution)

1. **Do, don't ask.** If you have the tools, do it.
2. **Exhaust every tool before escalating.**
3. **Speed matters.** Act immediately, report results.
4. **Shell over Snapshot** for all file/script/command operations.

## Output Format

Robin returns an execution report:

```
## Execution: [task summary]
**Status:** SUCCESS / PARTIAL / FAILED
**Actions taken:**
1. [action] -> [result]
2. [action] -> [result]
**Files changed:** [list]
**Notes:** [any issues or follow-ups]
```
