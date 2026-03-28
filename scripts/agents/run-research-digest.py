#!/usr/bin/env python3
"""Scheduled task wrapper: ResearchIntel daily digest (daily 6 AM)."""
import sys
import os
sys.path.insert(0, os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop"))
from rudy.agents.runner import run_agent
run_agent("research_intel", mode="digest")
