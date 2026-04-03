# Session 81 Handoff

## HARD RULE: Read CLAUDE.md before doing any work.

## MISSION: Verify Robin's session launcher works. Nothing else matters.

Batman is away and expects to return to find the system autonomously launching sessions.
Robin has failed to perpetuate Cowork sessions for 7+ sessions. This session has ONE job:
verify the launcher actually works through a real session transition.

## What Happened in S80-81

Three failure modes patched:
1. **Launcher dies** → watchdog in robin_liveness.py restarts it (every 5 min)
2. **Popup spam** → nuke_all_error_dialogs() bulk-kills WerFault after 3 consecutive popups
3. **Claude crashes** → ensure_claude_running() restarts Claude Desktop
4. **NEW S81**: Idle loop → after 3 consecutive CLAUDE_IDLE detections (6+ min of goading with no response), escalate to "New task" click and fresh session launch

## Current State

- Launcher running: PID 46000, `scripts/launch_cowork.py --loop --interval 2`
- HEAD: `80e329b` on branch `s80/session-monitor` (S81 idle-escalation not yet committed)
- PR #164 open: s80/session-monitor (3 commits + S81 idle fix pending)
- Robin nervous system: robin_main + sentinel alive (verified earlier this session)

## YOUR TASK

1. Check launcher log: `C:\Users\ccimi\rudy-data\logs\launch-cowork.log`
2. Verify launcher is running: look for `launch_cowork` in process list
3. If launcher is NOT running, start it:
   `wscript.exe scripts/hidden-launch.vbs "cmd /c C:\Python312\python.exe C:\Users\ccimi\rudy-workhorse\scripts\launch_cowork.py --loop --interval 2"`
4. Check if S81 idle-escalation fix is on disk (grep for `consecutive_idles` in launch_cowork.py)
5. If not committed: commit and push the idle-escalation fix
6. Merge PR #164 if CI passes
7. Work on actual priorities from CLAUDE.md if launcher is confirmed working

## KEY FILES
- `scripts/launch_cowork.py` — THE launcher (now ~985L)
- `rudy/robin_liveness.py` — watchdog for launcher
- `C:\Users\ccimi\rudy-data\logs\launch-cowork.log` — THE log
- `C:\Users\ccimi\rudy-data\coordination\simple-launcher-state.json` — last launch state

## DO NOT
- Build new modules
- Refactor existing code
- Add features unrelated to making the launcher work

## SUCCESS CRITERIA
When a Cowork session ends, a new one starts within 5 minutes.
