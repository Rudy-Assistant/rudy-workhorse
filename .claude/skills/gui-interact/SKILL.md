---
name: gui-interact
version: 1.0.0
description: Human-convincing GUI interaction via Windows-MCP + human_simulation
task_type: browse
agent: robin
capabilities:
  - human_simulation.HumanSimulator
  - robin_human_adapter.RobinHumanInterface
  - Windows-MCP (Click, Move, Type, Scroll, Snapshot)
triggers:
  - click button
  - fill form
  - interact with app
  - gui automation
  - open application
---

# GUI Interact

Interact with any Windows GUI application using human-convincing behavior.

## Core Engines
- **TimingEngine**: Gaussian delays, session warmup, reading pauses
- **MouseEngine**: Bezier curve paths, ease-in-out, velocity variance
- **KeyboardEngine**: WPM simulation (65 WPM default), typo injection + correction
- **SessionManager**: Warm/cold tracking, break scheduling
- **BotDetectionFailsafe**: Page source scanning, backoff, detection alerts
- **FingerprintManager**: Browser fingerprint rotation, stealth launch args

## Execution Pattern
```python
from rudy.human_simulation import create_simulator
sim = create_simulator("task-name")

# Navigate with human timing
sim.navigate(page, url="https://example.com")

# Click with Bezier mouse path
sim.click(page, selector="#button")

# Type with realistic keystroke timing and occasional typos
sim.type_text(page, selector="#input", text="Hello world")

# Read with natural pause
sim.read_page(page, content=page_text)

# Scroll naturally
sim.scroll_page(page, pixels=500, direction="down")
```

## Windows-MCP Alternative (no browser page object)
```python
from rudy.robin_human_adapter import create_human_interface
iface = create_human_interface(sw=1920, sh=1080)

calls = iface.human_click(500, 300)   # Bezier path + click
calls = iface.human_type("text here") # Keystroke sequence with typos
calls = iface.human_scroll(500)       # Natural scroll
calls = iface.human_navigate("url")   # Open URL
```

## Anti-Detection
- BotDetectionFailsafe scans for CAPTCHA, honeypots, bot-trap elements
- Automatic backoff on detection (exponential: 30s, 60s, 120s, 300s)
- FingerprintManager rotates user-agent, viewport, WebGL hash, timezone
- SessionManager enforces breaks after sustained activity

## Security Rules
- Never submit credentials — escalate to Batman
- Never bypass CAPTCHA — pause and alert
- Respect rate limits and robots.txt
- Log all GUI interactions to session journal
