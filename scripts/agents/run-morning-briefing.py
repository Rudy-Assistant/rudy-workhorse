#!/usr/bin/env python3
"""Scheduled task wrapper: TaskMaster morning briefing (daily 7:30 AM)."""
import sys, os
sys.path.insert(0, os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop"))
from rudy.agents.runner import run_agent
run_agent("task_master", mode="briefing")
