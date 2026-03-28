"""
Pytest configuration — ensures test environment directories exist.
"""

import os
from pathlib import Path


def pytest_configure(config):
    """Create required directories before any imports happen."""
    desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
    (desktop / "rudy-logs").mkdir(parents=True, exist_ok=True)
    (desktop / "rudy-data").mkdir(parents=True, exist_ok=True)
