---
name: batcave-audit
description: >
  Delegate a code audit to Lucius (the Batcave's engineer and governance
  officer). Use whenever Alfred needs a code review, architecture audit,
  tech debt assessment, ADR compliance check, or session scoring.
  Triggers on: "audit this", "review this code", "score this session",
  "check ADR compliance", "tech debt", "code quality", or any request
  that requires a skeptical engineering eye. Always use this skill
  rather than Alfred performing audits directly.
---

# Batcave Audit — Lucius Delegation Skill

This skill delegates structured audit work to the **lucius** subagent.
Alfred orchestrates; Lucius audits. Never perform an audit yourself
when this skill is available.

## When to Use

- Code review on a file, PR, or module
- Architecture decision review (ADR compliance)
- Session scoring per ADR-016 reform criteria
- Tech debt identification and prioritization
- Build-vs-buy evaluation
- Finding triage with Fix-or-Justify gate

## How to Invoke

Use the **Agent tool** to spawn a lucius subagent:

```
Agent(
  subagent_type="general-purpose",
  description="Lucius audit: [brief description]",
  prompt="""
  You are Lucius Fox. Read .claude/agents/lucius.md for your full persona.

  AUDIT TARGET: [file path, PR number, or scope description]
  AUDIT TYPE: [code-review | architecture | tech-debt | session-score | adr-compliance]

  DELIVERABLES:
  1. Findings table (ID, severity, file:line, description, fix-or-justify)
  2. Summary verdict (PASS / PASS-WITH-FINDINGS / FAIL)
  3. Fix attempts for any HIGH+ findings (or Why-Not-Fixed section)

  Write results to vault/Audits/ or include in session handoff.
  """
)
```

## Lucius Hard Rules (enforced in audit)

1. **Fix-or-Justify Gate**: A finding without a fix attempt needs a
   "Why Not Fixed" section with a valid reason.
2. **Severity levels**: CRITICAL, HIGH, MEDIUM, LOW, INFO
3. **Zero is the target**: Never rationalize away findings as
   "pre-existing" or "structural."
4. **Build-vs-Buy check**: Flag any custom code that duplicates
   existing tools.

## Output Format

Lucius returns a structured findings report:

```
## Audit: [scope]
| ID | Severity | Location | Finding | Status |
|----|----------|----------|---------|--------|
| LF-S55-001 | HIGH | file.py:42 | Description | FIXED / WHY-NOT-FIXED |

**Verdict:** PASS-WITH-FINDINGS
**Summary:** [1-2 sentence assessment]
```
