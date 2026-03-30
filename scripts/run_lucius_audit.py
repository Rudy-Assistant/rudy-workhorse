"""Run a full Lucius Fox audit. Portable — uses rudy.paths for all paths."""
import sys
from pathlib import Path

# Add repo root to sys.path dynamically
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from rudy.agents.lucius_fox import LuciusFox

lucius = LuciusFox()
lucius.execute(mode="full_audit")
print("Lucius audit complete:", lucius.status.get("summary", ""))
