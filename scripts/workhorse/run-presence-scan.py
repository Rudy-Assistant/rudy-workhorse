"""Run a WiFi presence scan — can be called standalone or by agents."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from rudy.presence import run_scan
run_scan()
