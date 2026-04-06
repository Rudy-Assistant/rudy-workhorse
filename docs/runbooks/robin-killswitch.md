# Runbook: Robin Killswitch

**Owner:** Alfred (S195 / P0-C)
**Files:** `scripts/robin-killswitch.bat`, `scripts/robin-killswitch.ps1`

## When to use
- Robin is hung, runaway, or doing something Batman wants stopped NOW.
- Suspected dead-loop / zombie state (PID alive ~40 sessions, near-zero CPU, no commits).
- Pre-deploy: stop Robin before merging changes that touch its hot path.

## One-click (Batman)
Double-click `scripts\robin-killswitch.bat`. Robin offline within ~15s. Done.

## Parametrized
```cmd
scripts\robin-killswitch.bat --dry-run
scripts\robin-killswitch.bat
scripts\robin-killswitch.bat --restart
```

| Flag        | Behavior                                                       |
|-------------|----------------------------------------------------------------|
| (none)      | Graceful TERM, 10s grace, force kill, mark status KILLED       |
| `--dry-run` | List targets and exit. Kills nothing.                          |
| `--restart` | Run kill, then relaunch via `scripts\start-launcher-loop.bat`  |

## How it works
1. Reads canonical Robin PIDs from `rudy-data\robin-status.json` (NEVER hardcoded).
2. Resolves child processes BEFORE killing parents.
3. `CloseMainWindow()` on each target. 10s grace.
4. Force-kill survivors.
5. Updates `robin-status.json` -> `status: KILLED, killed_at, killed_by`.
6. Writes log to `rudy-data\robin-killswitch-{ts}.log`.

## Test matrix
| Scenario                | Expected                                      |
|-------------------------|-----------------------------------------------|
| Robin healthy           | Graceful close, status=KILLED                 |
| Robin hung              | TERM ignored, force kill after 10s            |
| Robin already dead      | "PID X not running" log, status=KILLED        |
| Robin restarting mid-kill | Children resolved up front, all killed       |
| robin-status.json missing | Exit 2, no kills, FATAL log                |

## Recovery
- Manual relaunch: `scripts\start-launcher-loop.bat`
- Verify with status console (`docs\robin-console.html`).

## Future
- Hotkey Ctrl+Alt+Shift+K (P0-M, S196).
- Console Big Red Button (P0-D).
- Sentinel cooldown integration.
