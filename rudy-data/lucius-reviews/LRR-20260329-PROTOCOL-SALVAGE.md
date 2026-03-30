# Lucius Review Report: Protocol Salvage
**ID:** LRR-20260329-PROTOCOL-SALVAGE  
**Date:** 2026-03-29  
**Commit:** bb47187  
**Branch:** alfred/robin-logging-nightwatch  
**Reviewer:** Lucius Fox (architectural gate)  

## Scope
Salvage fixes for two legacy protocol files:
- `rudy/robin_alfred_protocol.py` (298 → 348 lines)
- `rudy/batcave_memory.py` (252 → 259 lines)

## Verdict: APPROVED

All three conditions from the prior audit
(Alfred-Protocol-Salvage-Audit.md) are addressed:

### Condition 1: Fix hardcoded paths ✅
**Before:** Both files used `Path(USERPROFILE) / "Desktop" / "rudy-data"`  
**After:** `REPO_ROOT = Path(__file__).resolve().parent.parent` then
`RUDY_DATA = REPO_ROOT / "rudy-data"`  
**Verification:** Import test confirmed REPO_ROOT resolves to
`C:\Users\ccimi\Desktop\rudy-workhorse`

### Condition 2: Add input validation ✅
**robin_alfred_protocol.py:**
- `_sanitize_str()` strips unsafe chars (regex allowlist), max_length cap
- `_validate_payload()` enforces dict type and MAX_PAYLOAD_SIZE (50KB)
- Both `send_to_alfred()` and `respond_to_robin()` call validators
- Test: `_sanitize_str('hello<script>world')` → `'helloscriptworld'`

**batcave_memory.py:**
- `add_learning()` validates title (≤500 chars), detail (≤5000 chars),
  tags (≤20 items), all with type checks and ValueError on violation

### Condition 3: Add message TTL ✅
- `MAX_MESSAGE_AGE_HOURS = 72` (3 days)
- Both `RobinMailbox.check_inbox()` and `AlfredMailbox.check_inbox()`
  compute message age from ISO timestamp and skip expired messages
- Graceful fallback: malformed timestamps pass through (no crash)

## Quality Checks
| Check | Result |
|-------|--------|
| py_compile both files | PASS |
| Import test | PASS |
| No hardcoded Desktop paths | PASS |
| Sanitizer strips unsafe chars | PASS |
| Payload validation rejects oversized | PASS |
| Bracket/brace balance | PASS |
| Consistent with F1 fix pattern | PASS |

## Risk Assessment
- **Low risk:** Path change is identical pattern to proven F1 fix
- **Low risk:** Validation is additive — no existing behavior removed
- **Medium risk:** TTL silently drops old messages — acceptable since
  stale messages should not be acted upon

## Tech Debt Logged
- No unit tests for either module (same as robin_taskqueue.py)
- `_sanitize_str` regex should eventually be shared across modules
  (currently duplicated from robin_taskqueue.py)
- Message archival on TTL expiry not implemented (messages just skipped)
