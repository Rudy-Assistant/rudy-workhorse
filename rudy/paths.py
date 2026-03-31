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

# Handoff directory: Alfred writes handoff briefs, Robin scans on activation
HANDOFFS_DIR = RUDY_DATA / "handoffs"

# BatcaveVault: local Obsidian memory vault (gitignored, per-Oracle)
BATCAVE_VAULT = REPO_ROOT / "vault"

# Vault Handoffs: canonical handoff location inside Obsidian (most-used folder)
VAULT_HANDOFFS = BATCAVE_VAULT / "Handoffs"

# ---------------------------------------------------------------------------
# Ensure critical directories exist at import time
# ---------------------------------------------------------------------------

for _d in [RUDY_DATA, RUDY_LOGS, RUDY_COMMANDS, ROBIN_INBOX, SCREENSHOT_DIR, LUCIUS_AUDITS, HANDOFFS_DIR, BATCAVE_VAULT, VAULT_HANDOFFS]:
    _d.mkdir(parents=True, exist_ok=True)

# Scaffold BatcaveVault Home.md if missing (per-Oracle, gitignored)
_vault_home = BATCAVE_VAULT / "Home.md"
if not _vault_home.exists():
    _vault_home.write_text(
        "# BatcaveVault\n\n"
        "Local knowledge vault for this Oracle instance.\n\n"
        "## Quick Links\n\n"
        "- [[Session Log]]\n"
        "- [[Standing Orders]]\n"
        "- [[Agent Roster]]\n",
        encoding="utf-8",
    )


# ---------------------------------------------------------------------------
# Executable finder — replaces hardcoded Python/Git paths across codebase
# ---------------------------------------------------------------------------

def find_exe(name: str, fallbacks: tuple[str, ...] = ()) -> str:
    """Find an executable on PATH or in known locations.

    Args:
        name: Executable name (e.g. "python", "git")
        fallbacks: Tuple of absolute paths to check if not on PATH

    Returns:
        Full path to the executable, or bare *name* as last resort.
    """
    import shutil
    import sys as _sys

    found = shutil.which(name)
    if found:
        return found
    for fb in fallbacks:
        if Path(fb).exists():
            return fb
    # Last resort: if we're looking for Python, use our own interpreter
    if name.lower() in ("python", "python3"):
        return _sys.executable or name
    return name


PYTHON_EXE = find_exe("python", (
    r"C:\Python312\python.exe",
    r"C:\Python311\python.exe",
    r"C:\Users\ccimi\AppData\Local\Programs\Python\Python312\python.exe",
))

GIT_EXE = find_exe("git", (
    r"C:\Program Files\Git\cmd\git.exe",
    r"C:\Program Files (x86)\Git\cmd\git.exe",
))

# Claude desktop app candidate paths (used by robin_wake_alfred.py)
CLAUDE_APP_GLOBS = [
    str(HOME / "AppData" / "Local" / "AnthropicClaude" / "app-*" / "claude.exe"),
    str(HOME / "AppData" / "Local" / "Programs" / "claude-desktop" / "claude*.exe"),
]

