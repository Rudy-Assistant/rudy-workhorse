"""Invoker for Sentinel agent — called by Task Scheduler every 15 min."""
import sys
sys.path.insert(0, r"C:\Users\C\Desktop")
from rudy.agents.sentinel import Sentinel
Sentinel().execute()
