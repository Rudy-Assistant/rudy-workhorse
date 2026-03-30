"""Invoker for Sentinel agent — called by Task Scheduler every 15 min."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from rudy.agents.sentinel import Sentinel
Sentinel().execute()
