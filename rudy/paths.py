import os
from pathlib import Path

# Resolve Desktop portably — works on Windows, macOS, and Linux
DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"

RUDY = DESKTOP / "rudy"
LOGS = DESKTOP / "rudy-logs"
COMMANDS = DESKTOP / "rudy-commands"
SESSIONS = DESKTOP / "rudy-sessions"
