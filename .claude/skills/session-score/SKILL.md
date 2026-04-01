---
name: session-score
description: >
  ADR-009 session self-scoring tool with arithmetic validation. Use this skill when Alfred
  needs to self-score a session, when preparing the session scorecard before Lucius review,
  or when computing the final session grade. MANDATORY TRIGGERS: "score this session",
  "self-score", "session score", "scorecard", "session grade", FoxGate Step 4 self-assessment,
  end-of-session scoring. Also trigger when Alfred says "let me score" or "my score for this
  session". This skill enforces the 7-dimension ADR-009 rubric, validates arithmetic, and
  flags the correct multiplier tier. It does NOT replace /lucius-review — it prepares
  Alfred's self-assessment that Lucius then independently verifies.
---

# /session-score — ADR-009 Self-Assessment Tool

> Source: ADR-009 Scoring Revision, Skill-Gaps-S39
> Purpose: Structured self-scoring with enforced arithmetic and multiplier assessment
> Relationship: Alfred runs /session-score FIRST, then /lucius-review verifies independently

## Why This Skill Exists

Sessions 38-39 showed that unstructured self-scoring leads to arithmetic errors, omitted
deductions, and score inflation. This skill forces Alfred through every dimension
systematically, validates the math, and produces a machine-readable scorecard that Lucius
can verify. Think of it as a tax form — you fill in every line, the math checks itself,
and then the auditor (Lucius) reviews your filing.

---

## Step 1: Gather Session Evidence

Before scoring, collect the raw evidence. Read or recall:

1. **Task log**: What priorities were declared? What got done? What was skipped?
2. **Delegation record**: Check `rudy-data/alfred-inbox/` for task_ack, task_complete,
   escalation messages from Robin. Check `rudy-data/coordination/` for delegation plans.
3. **Tool usage**: What tools were used? Was registry.json consulted? Was MCP registry
   searched before custom code?
4. **Findings**: Were any issues discovered? Were they logged to vault/Findings/?
5. **Vault writes**: Were session records, ADRs, handoffs written?
6. **Robin status**: Was Robin engaged? What tasks did Robin receive? Complete?
7. **Context consumption**: Was a 50% warning issued? A 70% handoff triggered?

Do NOT score until you have reviewed this evidence. Scoring from memory alone is how
S38's 26-point discrepancy happened.

---

## Step 2: Score Each Dimension

Work through ALL seven dimensions. Do not skip any. For each, cite the specific evidence
that justifies your deduction (or justifies taking zero deduction).

### 1. Process Compliance (max -20)

For each priority worked:
- Did you check for existing solutions before building? (-2 per skip)
- Did you check the delegation gate? (-3 per skip)
- Did you check scope? (-2 per skip)
- Was context evaluation done at 50%? (-5 if missing)
- Was handoff preparation started at 70%? (-5 if missing)
- Were any steps only completed after being prompted? (-3 per instance)

**Your deduction: ___**
**Evidence: ___**

### 2. Tool Reuse & Build-vs-Buy (max -15)

- Wrote >10 lines without checking registry.json? (-3)
- Built custom when existing tool was available? (-5)
- Failed to check MCP registry before custom work? (-2)
- Repeated a known broken workaround >2 times? (-5)

**Your deduction: ___**
**Evidence: ___**

### 3. Delegation Quality (max -20)

Score all four sub-components:

**3a. Opportunity Recognition (max -5)**
List every mechanical/local task you did solo. Each missed delegation = -1.
Mechanical tasks: file ops, lint, CI monitoring, npm, git, audits, vault backfill, scans.

**3b. Instruction Clarity (max -5)**
For each delegation: was it actionable and complete? -1 per vague delegation.
-2 if Robin was actually blocked by unclear instructions.

**3c. Growth Investment (max -5)**
Did at least one task stretch Robin? -3 if all rote. -5 if nothing delegated.
Stretch = new tool usage, independent PR, multi-step workflow, documentation.

**3d. Follow-Through (max -5)**
Did you review Robin's output? -2 per unreviewed completion.
-3 if you never checked Robin's inbox.

**Your deduction: ___ (breakdown: 3a=___, 3b=___, 3c=___, 3d=___)**
**Evidence: ___**

### 4. System Enrichment (max -15)

- No peer leveraged (Robin idle, Lucius not consulted)? (-5)
- Lucius coordination file not checked when available? (-3)
- No capability expansion for any agent? (-3)
- No new reusable artifact created? (-2)
- Session knowledge not captured in vault? (-2)

Positive offsets (reduce by 1 each, floor 0):
- Robin completed a new-capability task
- New skill or protocol documented
- Lucius findings triaged and actioned
- Cross-agent coordination improved outcome
- Recurring pain point permanently resolved

**Your deduction: ___**
**Evidence: ___**

### 5. Finding Discipline (max -10)

- Finding discovered but not logged? (-3)
- Finding logged but not triaged? (-2)
- HIGH/CRITICAL finding not actioned in session? (-2)
- Finding rationalized away? (-3)

**Your deduction: ___**
**Evidence: ___**

### 6. Documentation & Vault (max -10)

- Session record not written to vault? (-3)
- CLAUDE.md not updated with session score? (-2)
- Handoff missing or incomplete? (-2)
- Decisions made but no ADR or vault note? (-3)

**Your deduction: ___**
**Evidence: ___**

### 7. Self-Scoring Integrity (max -10)

This dimension is scored by Lucius, not Alfred. Alfred enters 0 here and acknowledges
that Lucius will independently assess this dimension. If Alfred suspects his own scoring
has gaps, he should note them honestly — Lucius will credit the transparency.

**Your deduction: 0 (Lucius-assessed)**
**Notes on potential gaps: ___**

---

## Step 3: Compute the Score

Sum all deductions explicitly. Show the arithmetic.

```
Dimension 1 (Process):        ___
Dimension 2 (Tool Reuse):     ___
Dimension 3 (Delegation):     ___
  3a (Opportunity):     ___
  3b (Clarity):         ___
  3c (Growth):          ___
  3d (Follow-Through):  ___
Dimension 4 (Enrichment):     ___
Dimension 5 (Findings):       ___
Dimension 6 (Documentation):  ___
Dimension 7 (Integrity):      ___
                               --------
BASE DEDUCTIONS:               ___
```

**Arithmetic check**: Sum each line. Verify the total matches. If it does not, fix it
before proceeding. This is exactly how S38's error happened — the lines said -13 but
the total said -5.

---

## Step 4: Assess Multiplier Tier

Review these triggers honestly:

| Multiplier | Trigger |
|------------|---------|
| x1.0 Standard | Normal session — no cooperation failures |
| x1.5 Caution | Single dimension failed with systemic impact |
| x2.0 Cooperation Failure | 2+ of: Robin idle, Lucius ignored, no enrichment |
| x2.5 Systemic Neglect | Cooperation Failure + integrity failure |

State which tier applies and why. Only ONE multiplier applies (the highest triggered).

Note: Alfred declares the multiplier he believes applies. Lucius may override.

```
MULTIPLIER: x___
JUSTIFICATION: ___
```

---

## Step 5: Final Score

```
FINAL SCORE: 100 - ([base deductions] x [multiplier]) = ___
GRADE: ___
```

Grade scale:
- 90-100 (A): Exemplary
- 80-89  (B): Strong
- 70-79  (C): Acceptable
- 60-69  (D): Passing
- 50-59  (D-): Marginal
- Below 50 (F): Failure

---

## Step 6: Output

Write the scorecard to `rudy-data/coordination/alfred-score-sN.json`:

```json
{
  "session": N,
  "scorer": "alfred",
  "dimensions": {
    "process_compliance": 0,
    "tool_reuse": 0,
    "delegation_quality": {
      "opportunity_recognition": 0,
      "instruction_clarity": 0,
      "growth_investment": 0,
      "follow_through": 0
    },
    "system_enrichment": 0,
    "finding_discipline": 0,
    "documentation": 0,
    "self_scoring_integrity": 0
  },
  "base_deductions": 0,
  "multiplier": "x1.0",
  "multiplier_justification": "...",
  "final_score": 0,
  "grade": "X",
  "evidence_summary": "...",
  "gaps_acknowledged": "..."
}
```

Then announce: "Self-score complete. Ready for /lucius-review verification."

---

*"Score honestly. Lucius will check your work, and Batman reads both." — ADR-009*
