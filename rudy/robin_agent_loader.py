#!/usr/bin/env python3
"""
Robin Agent Loader — feature-flag switch between v1 (manual loop) and v2 (LangGraph).

Usage in robin_main.py:
    from rudy.robin_agent_loader import RobinAgent

Set ROBIN_USE_LANGGRAPH=1 env var or edit USE_LANGGRAPH below to switch.
"""

import os
import logging

logger = logging.getLogger("robin.agent.loader")

# Feature flag: set to True to use LangGraph agent, False for original
USE_LANGGRAPH = os.environ.get("ROBIN_USE_LANGGRAPH", "1") == "1"

if USE_LANGGRAPH:
    try:
        from rudy.robin_agent_langgraph import RobinAgentV2 as RobinAgent
        from rudy.robin_agent_langgraph import AgentResult, AgentStep
        logger.info("Robin Agent: LangGraph v2 loaded")
    except ImportError as e:
        logger.warning(f"LangGraph import failed ({e}), falling back to v1")
        from rudy.robin_agent import RobinAgent
        from rudy.robin_agent import AgentResult, AgentStep
else:
    from rudy.robin_agent import RobinAgent
    from rudy.robin_agent import AgentResult, AgentStep
    logger.info("Robin Agent: v1 (manual loop) loaded")

__all__ = ["RobinAgent", "AgentResult", "AgentStep"]
