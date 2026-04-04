# Batcave Roadmap Review Protocol (R-003)

**Owner:** Lucius Fox (steward) | Batman (approver)
**Effective:** S98 | **Origin:** R-003 (Batcave-Roadmap-S44.md)
**Review Cadence:** Every Lucius session + every 5 Alfred sessions

---

## Purpose

Formalize the roadmap lifecycle so Robin can eventually orchestrate
long-duration Night Shifts from a Batman-vetted task queue rather
than extemporaneous plans. This protocol governs how items enter,
move through, and exit the roadmap.

---

## Item Lifecycle

```
Proposed -> Batman-Approved -> In Progress -> Done
                |                   |
                v                   v
            Rejected           Blocked (with reason)
```

### States

| State | Who Sets It | Meaning |
|-------|------------|---------|
| **Proposed** | Any agent or Batman | Idea captured, not yet vetted |
| **Batman-Approved** | Batman only | Cleared for execution |
| **In Progress** | Alfred/Robin | Actively being worked |
| **Done** | Alfred (verified by Lucius) | Delivered and merged |
| **Rejected** | Batman | Evaluated and declined |
| **Blocked** | Any agent | Cannot proceed; reason documented |

---

## Review Triggers

1. **Every Lucius session**: Lucius reviews the roadmap as part of
   session governance. Check for new proposals, update statuses,
   flag stale items (no progress in 10+ sessions).
2. **Every 5th Alfred session** (S100, S105...): Alfred checks
   execution progress against the roadmap during retrospective.
3. **On Batman request**: Ad-hoc review when Batman adds new ideas
   or reprioritizes.
4. **Robin Night Shift start**: Robin reads the roadmap to select
   pre-approved work packages (R-004 dependency).

---

## Review Checklist

When reviewing the roadmap, the reviewer MUST:

1. Check each item's current status against reality (is "In Progress"
   actually being worked? Is "Proposed" still relevant?)
2. Flag items with no progress in 10+ sessions as STALE
3. Verify Done items have merged PRs or deliverables
4. Identify new proposals from session findings or Batman directives
5. Propose sequencing for Batman-Approved items based on:
   - Dependencies (what unblocks other items?)
   - Effort (quick wins first when equal priority)
   - Robin readiness (does this advance Robin's independence?)
6. Update the roadmap file with status changes and notes
7. Write review summary to vault/Roadmap/Roadmap-Review-S{N}.md

---

## Adding New Items

Any agent can propose a roadmap item by:

1. Writing an entry in `vault/Roadmap/Batcave-Roadmap-S44.md` (or
   the current active roadmap file) with Status: Proposed
2. Including: title, origin (who/when), description, suggested skills
3. Items do NOT move to In Progress without Batman approval
4. Exception: items tagged "OPEN -- immediate" by Batman may be
   executed without a separate approval step

---

## Key Files

| File | Purpose |
|------|---------|
| `vault/Roadmap/Batcave-Roadmap-S44.md` | Active roadmap (master list) |
| `vault/Roadmap/Roadmap-Review-S{N}.md` | Per-session review summaries |
| `vault/Roadmap/Proposals/TEMPLATE.md` | Template for new proposals |
| `vault/Roadmap/OpenSpace-Evolution-S53.md` | OpenSpace-specific priorities |

## Integration with Robin Night Shifts (R-004)

When R-004 is implemented, Robin will:

1. Read the roadmap at Night Shift start
2. Filter for items with Status: Batman-Approved
3. Select items matching Robin's current capability level
4. Execute with pre-defined acceptance criteria
5. Report results to alfred-inbox and update roadmap status

Until R-004 is active, roadmap execution remains Alfred-led with
Lucius review.

---

*Protocol formalized by Alfred S98. Implements R-003 from Batcave
Roadmap. Prior art: Lucius S45 Roadmap Review (ad-hoc prototype).*
