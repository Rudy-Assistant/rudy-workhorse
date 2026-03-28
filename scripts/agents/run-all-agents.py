#!/usr/bin/env python3
"""Run all agents sequentially — for manual invocation or diagnostics."""
import sys
import os
sys.path.insert(0, os.path.join(os.environ.get("USERPROFILE", os.path.expanduser("~")), "Desktop"))
from rudy.agents.runner import run_all
result = run_all()
print(f"\nAll healthy: {result['all_healthy']}")
print(f"Alerts: {result['total_alerts']}, Warnings: {result['total_warnings']}, Actions: {result['total_actions']}")
