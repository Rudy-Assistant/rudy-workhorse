# Audit Charter — `<short-name>`

This is the human-readable narrative of what you're auditing and why.
The orchestrator only reads the JSON block below — that block is the binding spec.

## Narrative
Describe in prose what triggered this audit, what you're worried about,
and what "done well" looks like.

## Machine-readable charter

```json
{
  "scope": [
    "rudy",
    "tools",
    "vault/protocols"
  ],
  "exclusions": [
    "rudy/legacy",
    "tools/iron_audit/templates"
  ],
  "success_criteria": "every file in scope has a final_disposition; zero unverified DELETEs",
  "methodology": "IRON-AUDIT ADR-001 phases 0-9; no waivers",
  "adversary_plan": {
    "wrecker": "default DELETE; must justify KEEP",
    "defender": "default KEEP; must justify DELETE",
    "vendor_first": "default REPLACE; must invoke BOUNCER search vectors before any in-house KEEP"
  },
  "capabilities": [
    "force delegation to Robin",
    "skill-aware tool dispatch",
    "OTS substrate search before from-scratch build",
    "credential vault for autonomous account creation",
    "unattended task execution while user is away"
  ],
  "time_budget": "3 hours of orchestrator wall clock + adversary subagent time",
  "token_budget": "500K tokens across all subagents"
}
```

## Notes for the user before ratifying

- `capabilities` is the field that defeats S197's failure mode. Every name here gets searched in Phase 4 with ≥6 synonyms. **Be specific. Be exhaustive. Use the user's actual words.**
- `exclusions` should each have a one-line reason in this prose section.
- After editing this file, create `charter.ratified.txt` next to it with one line:
  `RATIFIED-BY: <your name> <iso-timestamp>`
- The orchestrator refuses to advance to Phase 1 without that file.
