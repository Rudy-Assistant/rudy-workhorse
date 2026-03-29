# Rudy Workhorse — Handoff & Codebase Status

> **Last updated**: 2026-03-28 by Alfred (Cowork Claude)
> **Branch**: `develop` (HEAD: `36f19c7`)
> **Repo**: `Rudy-Assistant/rudy-workhorse` (GitHub, private)

---

## Purpose of This Document

This is a living reference for any new Claude session picking up work on this codebase. It captures the current state of the code, what has been done, what remains, and how the code relates to the broader "Oracle" architectural vision Chris is developing. When you receive an Oracle architecture document alongside this handoff, your job is to evaluate the current codebase against that vision and identify gaps, misalignments, and implementation priorities.

---

## Current Codebase Snapshot

### Numbers at a Glance

| Metric | Value |
|---|---|
| Python modules (rudy/*.py) | 32 |
| Agent implementations (rudy/agents/*.py) | 8 |
| Core infrastructure (rudy/core/*.py) | 5 |
| Integration modules | 3 |
| Test files | 30 |
| Total passing tests | 1,395 |
| Ruff lint status | Clean (0 errors) |
| Lines of code (rudy/) | ~20,400 |
| Lines of test code (tests/) | ~16,000 |

### Branch State

- `develop` is 25+ commits ahead of `main`
- PR #1 is open (`develop` -> `main`)
- All work happens on `develop`; `main` is production-stable
- Git config for automated commits: `Alfred (Cowork Claude) <alfred@rudy-assistant.com>`

---

## Module Inventory

### Core Infrastructure

| Module | Lines | Tests | Purpose |
|---|---|---|---|
| `paths.py` | 44 | 19 | Portable Desktop/rudy paths (Win/Mac/Linux) |
| `session_state.py` | 257 | 18 | Session state capture and briefing for continuity |
| `utils.py` | 87 | 24 | Shared utilities (JSON, hashing, retry) |
| `admin.py` | ~80 | 33 | Run commands with Windows admin elevation |
| `api_server.py` | ~300 | 36 | FastAPI REST API for remote control |
| `offline_ops.py` | ~400 | 67 | Connectivity checking, action queue, offline recovery |

### Communication

| Module | Lines | Tests | Purpose |
|---|---|---|---|
| `email_multi.py` | 399 | 33* | Multi-provider email (Gmail + Zoho + Outlook failover) |
| `email_poller.py` | ~350 | 61 | IMAP polling, message processing, Claude integration |
| `nlp.py` | ~350 | 50 | Sentiment, entities, summarization, language detection |
| `voice.py` | ~450 | 53 | TTS (online/offline), STT (Whisper), audio processing |
| `voice_clone.py` | 694 | 65 | PocketTTS, Bark, OpenVoice engine chain |
| `ocr.py` | ~350 | 51 | Image OCR, PDF/DOCX/EPUB/PPTX text extraction |

### Intelligence & Autonomy

| Module | Lines | Tests | Purpose |
|---|---|---|---|
| `human_simulation.py` | 1,352 | 89 | Timing, mouse, keyboard simulation; bot detection evasion |
| `knowledge_base.py` | ~400 | 59 | ChromaDB vector search, text chunking, semantic retrieval |
| `local_ai.py` | 675 | 0 | Local LLM inference (Llama, etc.) |
| `web_intelligence.py` | ~400 | 34 | Article extraction, page watching, domain intel, job monitor |
| `photo_intel.py` | 786 | 68 | EXIF, geocoding, duplicate detection, timeline generation |

### Security & Surveillance

| Module | Lines | Tests | Purpose |
|---|---|---|---|
| `network_defense.py` | 699 | 49 | Registry monitoring, port auditing, ARP watch, DNS analysis |
| `intruder_profiler.py` | ~400 | 56 | Behavioral fingerprinting, threat scoring, device clearance |
| `presence.py` | ~450 | 47 | ARP-based device presence, subnet detection, routines |
| `presence_analytics.py` | 1,026 | 47 | MAC analysis, clustering, activity patterns, household profile |
| `surveillance.py` | 610 | 52 | Camera discovery, motion/person detection, alert management |
| `usb_quarantine.py` | 1,072 | 54 | USB interception, malware scanning, device quarantine |
| `travel_mode.py` | 727 | 26 | Network fingerprinting, home/away detection, baseline management |

### Specialized

| Module | Lines | Tests | Purpose |
|---|---|---|---|
| `financial.py` | ~350 | 30 | Portfolio tracking, price alerts, watchlist, market data |
| `phone_check.py` | 1,622 | 0 | Mobile device monitoring (LARGEST module — split candidate) |
| `find_my.py` | 770 | 0 | Apple Find My integration, geofencing, location polling |
| `movement_feed.py` | ~350 | 46 | Event formatting, snapshots, activity heatmaps |
| `wellness.py` | ~350 | 63 | Health monitoring, inactivity alerts, nighttime detection |
| `obsolescence_monitor.py` | ~500 | 59 | Package auditing, module health, landscape scanning |
| `avatar.py` | 574 | 51 | SadTalker, Wav2Lip, FaceSwap, MoviePy compositing |

### Agent System

All agents inherit from `AgentBase` (`rudy/agents/__init__.py`), which provides health checks, status tracking, crash dumps, and a shared `_run_cmd()` helper.

| Agent | Purpose |
|---|---|
| `sentinel.py` | Continuous security monitoring (network, USB, presence) |
| `security_agent.py` | Deep security scans (event logs, WiFi, processes) |
| `system_master.py` | System health, resource monitoring, self-healing |
| `task_master.py` | Task scheduling, priority management |
| `operations_monitor.py` | Operational status aggregation |
| `research_intel.py` | Web research, feed processing, knowledge updates |
| `runner.py` | Agent orchestration and execution |

---

## Code Quality Status (as of 2026-03-28)

### Completed Improvements

1. **Test coverage**: 252 -> 1,395 tests (454% increase). 20 new test modules. All mock subprocess/network; use `tmp_path` isolation.

2. **Bare except elimination**: All 110 `except Exception:` patterns replaced with `except Exception as e: log.debug(f"context: {e}")` across 31 files. Every module now has `import logging; log = logging.getLogger(__name__)`.

3. **shell=True hardening**: Reduced from 43 to 9 occurrences (79% reduction). Remaining 9 are PowerShell elevation commands, complex quoting, or intentional backward compatibility in `AgentBase`.

4. **Type hints**: Return type annotations added to all functions/methods in 20 modules.

5. **Security**: All hardcoded credentials removed. Secrets loaded from environment variables only. Pre-commit hook detects credential leaks.

### Known Technical Debt

1. **`phone_check.py`** (1,622 lines) — Too large, should be split into sub-modules (ADB commands, device state, health checks, reporting).

2. **Modules still without tests**: `find_my.py`, `local_ai.py`, `phone_check.py`. These depend heavily on external hardware/APIs making them harder to test.

3. **Remaining `shell=True`** (9 occurrences):
   - `admin.py` (2): PowerShell `Start-Process -Verb RunAs` — genuinely needs shell
   - `agents/__init__.py` (1): Backward compat for string commands — documented
   - `agents/security_agent.py` (3): PowerShell `Get-WinEvent` with hashtable syntax
   - `avatar.py` (1): Dynamic command construction via `_run()`
   - `obsolescence_monitor.py` (1): Dynamic command construction via `_run()`
   - `api_server.py` (1): Writes shell=True to generated script file (not executed directly)

4. **Agent files lack type hints**: `rudy/agents/*.py` have not been annotated yet.

5. **No `pytest-cov`**: Coverage percentage is not tracked. Adding it would help target future test work.

6. **`core/` scripts use legacy patterns**: Hyphenated filenames (`rudy-listener.py`), some still reference hardcoded paths.

---

## Environment & Infrastructure

### The Workhorse Machine

- **Hardware**: Ace Magician AM06 Pro Mini PC, Windows 11, headless
- **Remote access**: RustDesk (password auth, unattended) + Tailscale (100.83.49.9)
- **Local IP**: 192.168.7.25, gateway 192.168.7.1
- **Python**: 3.11+, Node v24.14.1
- **WSL 2**: Ubuntu 24.04, Python 3.12

### Development Tools

- **Claude Code**: Installed globally via npm (Git Bash backend)
- **MCP servers**: Context7, Sequential Thinking, Playwright, GitHub
- **Cowork connectors**: Gmail, Google Calendar, Chrome, Canva, Notion, Google Drive
- **GitHub PAT**: Fine-grained, expires 2026-06-26 (Contents Read+Write)

### Email Architecture

- **Primary (Rudy)**: rudy.ciminoassist@gmail.com (2FA on, app password in env var)
- **Backup**: Zoho (rudy.ciminoassistant@zoho.com) — needs IMAP enabled
- **Listener**: `rudy-listener.py` (IMAP IDLE + poll fallback, patched to Zoho)
- **Poller**: `email_poller.py` (polling-based alternative, multi-backend)

### Notion Integration

- **Workspace**: "Rudy -- Workhorse Command Center"
- **Improvement Log**: Database at `collection://732ddacf-590b-4e5b-96bd-c5cf9e462e34`
  - Schema: Improvement (title), Category, Agent, Status, Date, Impact
- **Sprint Logs**: Individual pages per session/sprint

---

## How to Evaluate Against Oracle Architecture

When you receive the Oracle architecture document, here is how to approach the review:

### Step 1: Map Existing Modules to Oracle Components

For each component in the Oracle architecture, identify which existing `rudy/` module(s) (if any) implement that capability. Note gaps where no module exists.

### Step 2: Assess Alignment

For each existing module, evaluate:
- Does it implement the Oracle vision correctly, or is it a divergent/ad-hoc implementation?
- Is it at the right abstraction level? (Too low-level? Too tightly coupled?)
- Does the interface match what Oracle expects?

### Step 3: Identify Structural Gaps

Look for:
- **Missing orchestration layers** — Oracle may define coordination patterns that don't exist yet
- **Missing data flows** — How modules communicate may differ from the Oracle vision
- **Missing abstraction boundaries** — Current modules may need to be wrapped or refactored
- **Missing capabilities** — Things Oracle requires that aren't in the codebase at all

### Step 4: Prioritize

Produce a ranked list of changes needed, considering:
- What can be done by renaming/reorganizing existing code
- What requires new code
- What requires rethinking existing implementations
- Dependencies between changes

### Key Questions to Answer

1. Does the current agent system (`AgentBase` + 7 agents) map to Oracle's agent/component model?
2. Does the current email/communication stack align with Oracle's messaging architecture?
3. Does the security stack (network_defense, intruder_profiler, usb_quarantine, sentinel) match Oracle's security posture?
4. Is the knowledge_base + local_ai stack the right foundation for Oracle's intelligence layer?
5. Does the presence/surveillance/travel stack match Oracle's awareness model?
6. What new modules or refactors are needed to bridge from current state to Oracle?

---

## Git Workflow for the Reviewer

```bash
# Clone and switch to develop
git clone https://github.com/Rudy-Assistant/rudy-workhorse.git
cd rudy-workhorse
git checkout develop

# Verify current state
python -m ruff check rudy/ tests/    # Should be clean
python -m pytest tests/ -q            # Should show 1,395 passed

# Browse the code
ls rudy/*.py                          # All modules
ls rudy/agents/*.py                   # Agent system
ls tests/test_*.py                    # Test files
cat CLAUDE.md                         # Working memory / context
cat docs/HANDOFF.md                   # This file
```

---

## Commit History (Session of 2026-03-28)

```
36f19c7 Add 175 tests for avatar, voice_clone, and obsolescence_monitor modules
bfed6ba Add 152 tests for presence, voice, and surveillance modules
164d61b Add 148 tests for api_server, email_poller, and ocr modules
de80853 Add 131 tests for wellness and photo_intel; type hints for 6 more modules
ad9d542 Add 102 tests for movement_feed and intruder_profiler; type hints for 6 modules
9616e1c Add 209 tests for 4 more untested modules (admin, knowledge_base, nlp, offline_ops)
2600266 Add return type hints to 8 modules and convert 6 more shell=True calls to list form
6892f2e Convert 16 more shell=True subprocess calls to safe list form
50f3f55 Convert 11 static shell=True subprocess calls to list form for security
f174af0 Replace all 110 remaining bare except patterns with debug logging across 31 files
a84d7bc Add 226 tests for 5 untested modules
436098e Replace 27 bare except patterns with debug logging in core modules
```

---

## Contact

- **Owner**: Christopher M. Cimino (ccimino2@gmail.com)
- **Automated commits**: Alfred (Cowork Claude) <alfred@rudy-assistant.com>
