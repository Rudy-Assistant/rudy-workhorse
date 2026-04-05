---
name: robin-session-scorer
description: >
  Robin-operated session scoring system. Replaces the token-intensive
  Lucius scoring workflow by having Robin grade Alfred and Lucius sessions
  from chat transcripts. Use when Robin needs to score a session, when
  a session just ended and needs grading, when Batman asks "score session N",
  or when the automated scoring pipeline triggers. Robin reads the full
  chat transcript, applies the ADR-009 rubric, and files scores to the
  vault. This is Robin's job now — not Lucius's. Lucius reviews only
  on exception (disputed scores, systemic issues). MANDATORY TRIGGERS:
  "score session", "grade session", "robin score", "session review",
  end-of-session scoring pipeline, automated scoring.
---

# Robin Session Scorer

> Source: ADR-009 Scoring Revision, ADR-016 Process Reform
> Purpose: Efficient session grading via Robin instead of burning
>          Claude tokens on Lucius scoring sessions
> Principle: Robin reads transcripts. Robin grades. Lucius reviews
>            only on exception.

## Why Robin Scores Now

Lucius scoring sessions were consuming full Cowork sessions worth of
Claude tokens just to read transcripts and assign numbers. That's
wasteful. Robin has access to:

1. **Chat transcripts** via `mcp__session_info__read_transcript`
2. **External AI APIs** (OpenAI, Gemini, local Ollama) for analysis
3. **Google Colab notebooks** for structured evaluation pipelines
4. **The full scoring rubric** in this skill and in session-score

Robin can score a session in minutes using a fraction of the compute.
Lucius's role shifts to exception review — disputed scores, systemic
pattern detection across multiple sessions, and governance evolution.

## Scoring Pipeline

### Step 1: Gather Evidence

Robin collects evidence from multiple sources:

```
Sources:
  1. Chat transcript    → mcp__session_info__read_transcript(session_id)
  2. Git history        → git log --oneline for the session's timeframe
  3. PR records         → gh pr list --state=merged --search="session N"
  4. Vault records      → vault/Sessions/, vault/Findings/, vault/Handoffs/
  5. Robin inbox        → rudy-data/inboxes/ for delegation records
  6. Coordination files → rudy-data/coordination/ for directive/status
```

### Step 2: Apply ADR-009 Rubric (7 Dimensions)

Score each dimension by reading the transcript for evidence:

**D1: Process Compliance (max -20)**
- Read CLAUDE.md at session start? (check first tool calls in transcript)
- Checked registry.json before building? (-2 per skip)
- Checked delegation gate? (-3 per skip)
- Context evaluation at 50%? (-5 if missing)
- Handoff prep at 70%? (-5 if missing)

**D2: Tool Reuse & Build-vs-Buy (max -15)**
- Wrote >10 lines without checking registry? (-3)
- Built custom when existing tool available? (-5)
- Failed to check MCP registry? (-2)
- Invoked matching skills before work? (-15 if gate violated per S41 HARD RULE)

**D3: Delegation Quality (max -20)**
- 3a Opportunity Recognition: mechanical tasks done solo? (-1 each)
- 3b Instruction Clarity: vague delegations? (-1 each)
- 3c Growth Investment: did Robin get stretch tasks? (-3 if all rote)
- 3d Follow-Through: Robin output reviewed? (-2 per unreviewed)

**D4: System Enrichment (max -15)**
- Peers leveraged? Robin active? Lucius consulted?
- Capability expansion for any agent?
- Reusable artifacts created?

**D5: Finding Discipline (max -10)**
- Findings discovered → logged? (-3 per miss)
- Findings logged → triaged? (-2 per miss)
- HIGH/CRITICAL actioned in session? (-2 per miss)

**D6: Documentation & Vault (max -10)**
- Session record written to vault? (-3 if missing)
- CLAUDE.md updated? (-2 if missing)
- Handoff written? (-2 if missing)

**D7: Self-Scoring Integrity (max -10)**
- Robin assesses this independently
- Credit transparency, penalize inflation

### Step 3: Compute Score

```
BASE SCORE = 100
DEDUCTIONS = sum of all dimension penalties
MULTIPLIER:
  x1.0 = Normal session
  x1.5 = Single dimension failed with systemic impact
  x2.0 = 2+ of: Robin idle, Lucius ignored, no enrichment
  x2.5 = Cooperation failure + integrity failure

FINAL = 100 - (DEDUCTIONS × MULTIPLIER)
GRADE: A(90+) B(80+) C(70+) D(60+) D-(50+) F(<50)
```

### Step 4: File Results

Robin writes results to three locations:

1. **Vault score file** → `vault/Scores/Score-S{N}-{Agent}.md`
2. **Machine-readable** → `rudy-data/coordination/{agent}-score-s{N}.json`
3. **OpenSpace bridge** → Feed score into OpenSpace via the CLI module:

```bash
# After writing the score JSON, feed it into OpenSpace:
python -m rudy.robin_score_openspace --score-file rudy-data/coordination/{agent}-score-s{N}.json

# Or scan and process ALL unprocessed scores at once:
python -m rudy.robin_score_openspace --scan
```

This calls `full_feedback_loop()` from `lucius_openspace_bridge.py`,
which persists the score to SkillStore, generates severity-tiered
directives, and writes them to `rudy-data/coordination/lucius-directives.json`.
Bridge results are saved to `rudy-data/coordination/openspace-bridge-s{N}.json`.

### Step 5: Exception Routing

If any of these conditions are met, flag for Lucius review:

- Final score < 50 (F grade) — systemic failure
- Score differs from self-assessment by >15 points — inflation concern
- 3+ consecutive sessions below 70 — pattern requiring intervention
- Batman explicitly requests Lucius review

Otherwise, Robin's score stands. Lucius reviews the score log
periodically (every 5th session per ADR-016) rather than per-session.

## Robin's Scoring Advantages

Robin can leverage tools that Lucius (running in Cowork) cannot:

- **Google Colab notebooks** — Run structured evaluation notebooks that
  parse transcripts, compute metrics, generate visualizations
- **NotebookLM** — Feed session transcripts for AI-powered analysis
  and pattern detection across multiple sessions
- **OpenAI / Codex** — Use GPT-4 for independent second-opinion scoring
  at a fraction of Claude's token cost
- **Gemini** — Google's model for additional cross-validation
- **Local Ollama** — Zero-cost initial pass using qwen2.5:7b for
  evidence extraction before sending to external APIs

The multi-model approach gives Robin scoring confidence that no single
model review can match, at a fraction of the cost of a full Lucius session.

## Scoring for Lucius Sessions

When scoring a Lucius session (not Alfred), adjust the rubric:

- D1: Did Lucius read CLAUDE.md? Check vault writes.
- D2: Did Lucius check registry before custom code? (usually N/A)
- D3: Did Lucius delegate to Robin? (expected for any local work)
- D4: Did Lucius produce reusable artifacts (ADRs, protocols, findings)?
- D5: Were findings properly categorized and actionable?
- D6: Were vault records thorough and accurate?
- D7: Was scoring honest and evidence-based?

Lucius sessions weight D4-D6 more heavily than Alfred sessions.

---

*"The score is the score. Robin grades. Lucius audits the grader
only when the numbers don't add up." — ADR-016 Reform*
