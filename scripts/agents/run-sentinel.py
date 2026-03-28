#!/usr/bin/env python3
"""Scheduled task wrapper: Sentinel awareness check (every 15 min, max 30s)."""
import sys
import os
sys.path.insert(0, os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop"))
from rudy.agents.runner import run_agent
run_agent("sentinel", mode="full")
