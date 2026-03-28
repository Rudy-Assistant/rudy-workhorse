#!/usr/bin/env python3
"""Scheduled task wrapper: SecurityAgent defensive sweep (every 30 min)."""
import sys
import os
sys.path.insert(0, os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop"))
from rudy.agents.runner import run_agent
run_agent("security_agent", mode="full")
