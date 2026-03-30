"""
Canonical path resolver for the Batcave.

Every module that needs a filesystem path imports from here.
No hardcoded paths anywhere else in the codebase.

Detection strategy:
    1. REPO_ROOT: Walk up from this file (__file__) to find the repo root
       (the directory containing the 'rudy' package).
    2. DATA / LOGS / COMMANDS: Sibling directories next to the repo root,
       OR under %USERPROFILE%/Desktop if the repo is elsewhere (e.g. cloned
       to a non-standard location).  The environment variable BATCAVE_DATA
       can override this entirely.

This means:
    - Clone to ~/Desktop/rudy-workhorse  →  data lives at ~/Desktop/rudy-data
    - Clone to C:/Projects/rudy-workhorse →  data lives at C:/Projects/rudy-data
    - Set BATCAVE_DATA=D:/batcave-data    →  data lives at D:/batcave-data
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root: resolved from this file's location (rudy/paths.py → repo root)
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

# ---------------------------------------------------------------------------
# Home & Desktop (Windows-aware)
# ---------------------------------------------------------------------------

HOME = Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
DESKTOP = HOME / "Desktop"

# ---------------------------------------------------------------------------
# Data directories: sibling to repo root, overridable via env
# ---------------------------------------------------------------------------

def _data_base() -> Path:
    """Determine the base directory for Batcave runtime data.

    Priority:
        1. BATCAVE_DATA env var (explicit override)
        2. Parent of REPO_ROOT (sibling layout: rudy-workhorse, rudy-data, etc.)
    """
    env = os.environ.get("BATCAVE_DATA")
    if env:
        return Path(env)
    return REPO_ROOT.parent


_BASE = _data_base()

RUDY_DATA = _BASE / "rudy-data"
RUDY_LOGS = _BASE / "rudy-logs"
RUDY_COMMANDS = _BASE / "rudy-commands"

# Specific data paths
ROBIN_CONFIG = RUDY_DATA / "robin-config.json"
ROBIN_STATE = RUDY_DATA / "robin-state.json"
ROBIN_INBOX = RUDY_DATA / "robin-inbox"
ROBIN_SECRETS = RUDY_DATA / "robin-secrets.json"
SCREENSHOT_DIR = RUDY_LOGS / "screenshots"
LUCIUS_AUDITS = RUDY_DATA / "lucius-audits"

# Environment profile (written by environment_profiler.py)
ENVIRONMENT_PROFILE = RUDY_DATA / "environment-profile.json"

# BatcaveVault: local Obsidian memory vault (gitignored, per-Oracle)
BATCAVE_VAULT = REPO_ROOT / "vault"

# ---------------------------------------------------------------------------
# Ensure critical directories exist at import time
# ---------------------------------------------------------------------------

for _d in [RUDY_DATA, RUDY_LOGS, RUDY_COMMANDS, ROBIN_INBOX, SCREENSHOT_DIR, LUCIUS_AUDITS, BATCAVE_VAULT]:
    _d.mkdir(parents=True, exist_ok=True)
