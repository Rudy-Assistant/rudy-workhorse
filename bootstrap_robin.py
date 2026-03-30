#!/usr/bin/env python3
"""
Robin Bootstrap Script
======================
Run this on any Windows machine to set up Robin (the local AI agent).

What it does:
1. Detects the environment (OS, Python, available tools)
2. Creates the shared directory structure (~/rudy-data, ~/rudy-logs)
3. Checks for Ollama and MCP servers
4. Generates starter configuration files
5. Validates everything works

Usage:
    python bootstrap_robin.py           # Full setup
    python bootstrap_robin.py --check   # Validate existing setup
    python bootstrap_robin.py --reset   # Reset configuration (keeps logs)

Requirements:
    - Python 3.8+
    - Ollama (with at least one model pulled)
    - Windows-MCP server (recommended)
"""

import json
import os
import platform
import shutil
import socket
import subprocess
import sys
from datetime import datetime
from pathlib import Path


# ============================================================================
# CONFIGURATION
# ============================================================================

HOME = Path.home()

DIRS = {
    "data": HOME / "Desktop" / "rudy-data",
    "logs": HOME / "Desktop" / "rudy-logs",
    "workhorse": HOME / "Desktop" / "rudy-workhorse",
}

# Ollama defaults
OLLAMA_HOST = "http://localhost:11434"
PREFERRED_MODELS = [
    "deepseek-r1:8b",      # Primary reasoning model
    "llama3.2:3b",          # Lightweight fallback
    "phi3",                 # Alternative fallback
    "mistral",              # Another fallback
]

# MCP server paths (common locations)
MCP_SEARCH_PATHS = [
    Path(os.environ.get("APPDATA", "")) / "Claude" / "claude_desktop_config.json",
    HOME / ".config" / "claude" / "claude_desktop_config.json",
]

