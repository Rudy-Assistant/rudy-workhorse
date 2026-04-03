# Session 81 Handoff

## HARD RULE: Read CLAUDE.md before doing any work.

## ROOT CAUSE FOUND AND FIXED

The launcher has NEVER worked in Cowork mode because `assess_state()` was broken:

1. **"Progress" false positive**: The Cowork sidebar has a permanent "Progress" panel.
   `assess_state()` checked for "Progress" as a working indicator → returned
   `CLAUDE_WORKING` even when the model had stopped responding. Every check,
   every session, for 7+ sessions.

2. **"New task" sidebar Link**: The sidebar always shows a "New task" Link.
   After removing "Progress", this would falsely trigger `CLAUDE_READY` between
   turns in an active conversation.

3. **Missing launch trigger states**: `COWORK_SELECT` and `PROMPT_READY` were
   not in the loop's launch-trigger set, so after clicking "New task" from
   idle escalation, those states fell through to "unhandled — wait 60s."

## Fixes Applied (commit 7f1bc67 on s80/session-monitor)

- Removed "Progress" from working indicators
- Changed "Stop" → "Stop response", "Working" → "Working on it" (more specific)
- "New task" check now requires `control_type="Button"` (sidebar Link ignored)
- Added `COWORK_SELECT` + `PROMPT_READY` to launch trigger states
- Added consecutive idle escalation: 3 goads → click "New task" → launch

## Expected Flow After Session Ends

1. ~2 min: Launcher detects CLAUDE_IDLE (no "Stop response" visible)
2. ~2 min: First goad sent (continuation prompt)
3. If model has context: responds → CLAUDE_WORKING → continues working
4. If context full: goad fails → CLAUDE_IDLE again → 2nd goad → 3rd goad → ESCALATE
5. ~6-7 min: Click "New task" → COWORK_SELECT/PROMPT_READY → launch()
6. New session starts with latest handoff from vault/Handoffs/

## Current State

- Launcher running with fix (new PID after restart at 10:53)
- HEAD: 7f1bc67 on s80/session-monitor
- PR #164 open with 6 commits total
- Robin nervous system: alive (verified earlier)

## Priorities for Next Session

1. Verify the launcher actually launched THIS session (check log)
2. If it did: merge PR #164, declare victory
3. If it didn't: check log, diagnose which step failed, fix
4. Clean rudy-data/ (100+ stale helper scripts)
5. Update CLAUDE.md with launcher fix docs
