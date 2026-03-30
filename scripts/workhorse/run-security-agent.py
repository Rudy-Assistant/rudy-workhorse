"""Invoker for SecurityAgent — called by Task Scheduler every 30 min."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from rudy.agents.security_agent import SecurityAgent
SecurityAgent().execute(mode="full")
