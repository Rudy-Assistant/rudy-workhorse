"""
DISCARDED (2026-03-29) — Per Lucius Build Process Audit.

This file attempted to launch Cowork sessions programmatically,
which is the wrong approach. Robin's autonomy is correctly
implemented via Cowork Scheduled Tasks:
  - robin-coordinator (every 3h)
  - morning-briefing (daily 7:30)
  - workhorse-watchdog (every 6h)

See: BatcaveVault/Architecture/Lucius Audit of Build Process Proposal.md

This file is kept as a tombstone to prevent re-invention.
"""

raise ImportError(
    "robin_cowork_launcher.py is discarded. "
    "Robin autonomy uses Cowork Scheduled Tasks, not programmatic launches."
)
