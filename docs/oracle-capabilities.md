# Oracle Capabilities — Alfred's Extended Reach

**Imported from:** alfred-skills/CLAUDE.md (Lucius Salvage Audit, Session 10)  
**Purpose:** Canonical reference for all tools available on Oracle (the Workhorse PC).

Oracle is Alfred's physical presence. Alfred should think of Oracle's tools as his own — the dispatch channel is just a delivery mechanism. Alfred writes the script, Oracle runs it.

## Tool Inventory

| Category | Tools | Capability |
|----------|-------|-----------|
| Human Simulation | HBS v1.0 (Gaussian timing, Bezier mouse, keystroke dynamics) | Interact with any web UI indistinguishably from a human |
| Browser Automation | Playwright (CDP 9222), pyautogui | Navigate, fill forms, submit, handle auth flows |
| Screen Intelligence | mss + EasyOCR, screenshot_reader.py, screen_capture.py | See and read any screen content |
| Local LLM | Ollama (llama3.2:3b), 4-tier failover | Local reasoning without cloud dependency |
| OSINT / Security | Sherlock, theHarvester, SpiderFoot, Nmap, Scapy, HIBP | Protective intelligence, breach monitoring, network scanning |
| Vision & Voice | InsightFace, EasyOCR, PyTorch (CPU), Coqui TTS | Face recognition, OCR, text-to-speech |
| Data & Dev | DuckDB, Pandas, GitHub CLI, ruff, LangGraph | Analytics, code ops, agent orchestration |
| Comms (Planned) | Twilio + Tailscale Funnel + Flask | SMS gateway for family |

When Robin is invoked, Robin has access to all of the above plus local AI reasoning. Robin's Human Behavior Simulation means Robin can do anything Bruce could do sitting at the keyboard — with the same authority.