"""
Compatibility shim - SentinelObserver has been consolidated into rudy/agents/sentinel.py.
This file exists for backward compatibility with robin_autonomy.py imports.

Consolidated: 2026-03-29T16:50:24.074430
Per Lucius Fox audit finding: triple sentinel duplication.
"""

# Re-export from canonical location
from rudy.agents.sentinel import SentinelObserver  # noqa: F401

__all__ = ["SentinelObserver"]
