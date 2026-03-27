#!/usr/bin/env python3
"""Scheduled task wrapper: SystemMaster health check (every 5 min via WorkhorseHealthCheck)."""
import sys, os
sys.path.insert(0, os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop"))
from rudy.agents.runner import run_agent
run_agent("system_master", mode="full")
