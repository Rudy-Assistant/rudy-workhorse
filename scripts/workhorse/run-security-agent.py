"""Invoker for SecurityAgent — called by Task Scheduler every 30 min."""
import sys
sys.path.insert(0, r"C:\Users\C\Desktop")
from rudy.agents.security_agent import SecurityAgent
SecurityAgent().execute(mode="full")
