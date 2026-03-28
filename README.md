# Rudy Workhorse

Autonomous assistant infrastructure for an always-on mini PC, enabling persistent task execution, session continuity, and intelligent presence across multiple channels.

## Architecture Overview

Rudy Workhorse is organized into modular layers:

- **`rudy/`** — Core modules for surveillance, communication, task execution, and autonomy
  - **`core/`** — Low-level infrastructure (command runner, Gmail API, stealth browser, listener)
  - **`agents/`** — AgentBase framework and sub-agents for specialized work
  - **`integrations/`** — Third-party connectors (GitHub, Suno)
  - **`tools/`** — Diagnostic and setup utilities
  - **`config/`** — Configuration templates and schemas

- **`scripts/`** — Operational scripts and bootstrap workflows
  - **`workhorse/`** — Startup, health checks, and self-test
  - **`hooks/`** — Pre-commit quality gates
  - **`agents/`** — Agent launcher stubs
  - **`rudy/`** — Utility scripts

- **`tests/`** — Unit tests and smoke tests
- **`.github/workflows/`** — CI/CD pipeline (lint, tests, status reporting)
- **`docs/`** — Architecture documentation and ADRs

## Setup

### Prerequisites
- Python 3.11+
- pip or uv
- Git (for hooks installation)

### Clone & Install

```bash
git clone <repository-url>
cd rudy-workhorse
pip install -e .
```

### Environment Variables

Copy `.env.example` to `.env` and populate:

```bash
# Gmail (primary email provider)
RUDY_GMAIL_ADDRESS=your-email@gmail.com
RUDY_GMAIL_APP_PASSWORD=<app-specific-password>

# Zoho (backup email provider)
RUDY_ZOHO_ADDRESS=your-zoho@zoho.com
RUDY_ZOHO_APP_PASSWORD=<app-specific-password>

# System password (for scheduled tasks, RustDesk, etc.)
RUDY_SYSTEM_PASSWORD=<password>

# GitHub PAT (for repository operations)
GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...
```

On Windows, set these as system environment variables:
```cmd
setx RUDY_GMAIL_ADDRESS "your-email@gmail.com"
setx RUDY_GMAIL_APP_PASSWORD "your-password"
```

**Never commit `.env`** — it is in `.gitignore`.

### Install Git Hooks

```bash
bash scripts/hooks/install-hooks.sh
```

This installs the pre-commit quality gate to block commits with lint errors, syntax issues, or test failures.

## Development Workflow

Rudy Workhorse uses a **three-layer quality gate**:

### Layer 1: Pre-commit Hook (Local)
Runs automatically before every commit:
- Secret detection (scans staged files for hardcoded credentials)
- Ruff lint check (E, F, W rules)
- Python syntax validation
- Unit tests (if staged files touch `rudy/`, `scripts/`, or `tests/`)

**Bypass in emergency:** `git commit --no-verify`

### Layer 2: CI Pipeline (GitHub Actions)
Runs on push to `main` or `develop`, and on pull requests to `main`:

- **Lint & Syntax Check** (`lint.yml`)
  - Ruff check with standard ruleset
  - Syntax check on all Python files in `rudy/` and `scripts/`

- **Module Smoke Tests** (`test.yml`)
  - Import tests for core modules
  - Full pytest suite
  - Module count validation (≥ 10 modules required)

### Layer 3: Branch Protection
Pull requests to `main` require:
- All CI checks passing
- Code review approval
- Commit signatures (optional)

### Local Testing

Run lint:
```bash
ruff check rudy/ --select E,F,W --ignore E501,E402,F401
```

Run tests:
```bash
pytest tests/ -v
```

Run both (pre-commit hook):
```bash
bash scripts/hooks/pre-commit
```

## Agent System

All Workhorse agents inherit from **`AgentBase`** (`rudy/agents/__init__.py`), providing:

### Health Check Contract
Every agent exposes a standardized `health_check()` method returning:

```python
{
    "agent": str,           # Agent name
    "version": str,         # Agent version
    "status": str,          # "healthy" | "degraded" | "error" | "never_run" | "stale"
    "last_run": str,        # ISO timestamp or "never"
    "age_seconds": float,   # Seconds since last run
    "alerts": int,          # Count of critical alerts
    "warnings": int,        # Count of warnings
    "summary": str,         # One-line human-readable summary
    "details": dict,        # Agent-specific diagnostics (optional)
}
```

### Status Tracking
Each agent writes a status file to `~/Desktop/rudy-logs/<agent>-status.json` after every run:

```json
{
    "agent": "agent_name",
    "version": "1.0",
    "last_run": "2026-03-28T15:30:00",
    "status": "healthy",
    "duration_seconds": 2.3,
    "critical_alerts": [],
    "warnings": [],
    "actions_taken": ["Did X", "Did Y"],
    "summary": "All systems nominal"
}
```

### Crash Dumps
On unhandled exceptions, agents write detailed dumps to `~/Desktop/rudy-logs/crash-dumps/<agent>-<timestamp>.json`, including:
- Full traceback and error context
- Agent state at crash time
- Input arguments (sanitized)
- Recent log lines for debugging
- Uptime metrics

A marker file `CRASH-DETECTED.txt` is also written for quick detection.

### Creating an Agent

```python
from rudy.agents import AgentBase

class MyAgent(AgentBase):
    name = "my_agent"
    version = "1.0"

    def run(self, **kwargs):
        self.log.info("Starting work...")
        self.action("Completed task X")
        self.summarize("Everything worked fine")

    def _health_details(self) -> dict:
        return {"custom_field": "custom_value"}

# Run it
agent = MyAgent()
agent.execute()  # Handles status tracking and error recovery
```

## Session Continuity

**`SessionState`** (`rudy/session_state.py`) captures machine-readable state for handoff between Cowork sessions, reconstructing context in < 2000 tokens:

### Captured Data
- **Git state** — current branch, last 5 commits, uncommitted changes
- **CI status** — lint and test results from last check
- **Agent health** — snapshot of all agents' status files
- **Tasks** — active work items with priority scores
- **Edits** — recently modified files and why
- **Blockers** — current impediments
- **Notes** — freeform session notes

### Usage

At end of session:
```python
from rudy.session_state import SessionState

state = SessionState()
state.capture()                    # Snapshot current state
state.add_task("Fix bug X", priority=8)
state.add_blocker("Waiting for API key")
state.add_note("Next: integrate Suno API")
state.save()
```

At start of next session:
```python
state = SessionState.load()
print(state.briefing())  # Human-readable summary for session context
```

## Security

### USB Quarantine

**`usb_quarantine.py`** — Intercepts and quarantines USB device operations:
- Blocks unexpected USB insertions and ejections
- Tracks insertion/removal history
- Scans contents for malware signatures
- Requires explicit approval for device access
- Logs all USB activity to audit trail

### Fortress Paradox Safeguards

Network defense and intrusion detection:
- **`network_defense.py`** — Real-time network monitoring, suspicious flow detection
- **`intruder_profiler.py`** — Behavioral fingerprinting and anomaly detection
- **`presence_analytics.py`** — Presence-based threat assessment
- Session isolation and context containment

### Credential Handling

- Credentials loaded from environment variables only (never hardcoded)
- OAuth/app passwords used instead of plain passwords
- Secrets filtered from logs and crash dumps
- .env file excluded via .gitignore
- Pre-commit hook detects hardcoded secrets before commit

## Module Structure

### Core Infrastructure
- **`paths.py`** — Portable Desktop/rudy paths (Windows, macOS, Linux)
- **`session_state.py`** — Session state capture and briefing
- **`agents/`** — AgentBase framework and agent registry
- **`core/`**
  - `rudy-command-runner.py` — Command execution and result handling
  - `rudy-gmail-api.py` — Gmail API wrapper (read, send, label)
  - `rudy-listener.py` — Network listener for agent coordination
  - `rudy-stealth-browser.py` — Headless browser with stealth mode

### Communication & Data
- **`email_multi.py`** — Multi-provider email (Gmail + Zoho)
- **`email_poller.py`** — Polling-based email ingestion
- **`movement_feed.py`** — Location/movement data aggregation
- **`knowledge_base.py`** — Vector DB-backed information retrieval

### Autonomy & Intelligence
- **`human_simulation.py`** — Behavioral mimicry and human-like action generation
- **`local_ai.py`** — Local LLM inference (Llama, etc.)
- **`voice_clone.py`** — Voice synthesis and cloning
- **`nlp.py`** — NLP utilities (tokenization, embedding)

### Surveillance & Analytics
- **`presence_analytics.py`** — Presence pattern analysis and alerts
- **`presence.py`** — Real-time presence tracking
- **`surveillance.py`** — Activity monitoring and logging
- **`phone_check.py`** — Mobile device monitoring
- **`photo_intel.py`** — Image analysis and metadata extraction

### Specialized Modules
- **`financial.py`** — Portfolio tracking and financial analysis
- **`obsolescence_monitor.py`** — Dependency/library version tracking
- **`travel_mode.py`** — Location-based behavior adaptation
- **`network_defense.py`** — Network intrusion detection
- **`usb_quarantine.py`** — USB device sandboxing
- **`offline_ops.py`** — Offline capability management
- **`ocr.py`** — Optical character recognition
- **`web_intelligence.py`** — Web scraping and intelligence gathering
- **`wellness.py`** — Health and activity monitoring

### Integrations
- **`integrations/github_ops.py`** — GitHub API operations
- **`integrations/rudy-suno.py`** — Suno AI music generation

## Directory Structure

```
rudy-workhorse/
├── rudy/                          # Core Python package
│   ├── agents/                    # AgentBase and agent implementations
│   ├── core/                      # Low-level infrastructure
│   ├── config/                    # Configuration schemas
│   ├── integrations/              # Third-party connectors
│   ├── tools/                     # Diagnostic utilities
│   ├── *.py                       # Feature modules
│   └── ADR-001-session-guardian.md
├── scripts/
│   ├── workhorse/                 # Startup and health workflows
│   ├── hooks/                     # Pre-commit quality gate
│   ├── agents/                    # Agent launchers
│   └── rudy/                      # Utility scripts
├── tests/                         # Unit and smoke tests
├── .github/workflows/             # CI/CD (lint, tests, status)
├── docs/                          # Architecture and runbooks
├── pyproject.toml                 # Project metadata and tool config
├── .env.example                   # Environment variable template
├── .gitignore                     # Git exclusions
└── README.md
```

## Contributing

### Branch Strategy

- **`develop`** — Integration branch (default for feature work)
- **`main`** — Production-ready, deployed code
- **Feature branches** — Branch from `develop`, name as `feature/description`

### Workflow

1. **Create feature branch:**
   ```bash
   git checkout develop
   git pull origin develop
   git checkout -b feature/my-feature
   ```

2. **Make changes and commit:**
   ```bash
   git add <files>
   git commit -m "Clear message"
   # Pre-commit hook runs automatically
   ```

3. **Push and open PR:**
   ```bash
   git push origin feature/my-feature
   # Open PR: feature/my-feature → develop
   ```

4. **Merge to develop:**
   - Code review approval required
   - CI checks must pass
   - Squash or rebase to keep history clean

5. **Release to main:**
   - PR from `develop` → `main`
   - Requires full CI pass + review
   - Tag with semantic version (v1.2.3)

### Hook Installation

If hooks aren't auto-installed, run manually:
```bash
bash scripts/hooks/install-hooks.sh
```

This copies `scripts/hooks/pre-commit` to `.git/hooks/pre-commit` with executable permissions.

## Key Files

- **`rudy/paths.py`** — Path configuration
- **`rudy/agents/__init__.py`** — AgentBase framework
- **`rudy/session_state.py`** — Session state management
- **`scripts/hooks/pre-commit`** — Quality gate (secrets, lint, syntax, tests)
- **`scripts/workhorse/boot-selftest.py`** — Startup health check
- **`.github/workflows/lint.yml`** — Linting CI job
- **`.github/workflows/test.yml`** — Testing CI job
- **`.github/workflows/ci-status.yml`** — Status aggregation
- **`pyproject.toml`** — Project config (Python 3.11+, ruff rules, pytest)

## Quick Troubleshooting

**Commit blocked by pre-commit hook:**
- Run `ruff check --fix <file>` to auto-fix lint issues
- Run `pytest tests/ -v` to diagnose test failures
- Review secret detection output if credentials are flagged

**Tests failing in CI:**
- Check CI logs for import errors or test output
- Run `pytest tests/ -v --tb=short` locally
- Ensure all dependencies are installed

**Agent not running:**
- Check status file: `~/Desktop/rudy-logs/<agent>-status.json`
- Check crash dump: `~/Desktop/rudy-logs/crash-dumps/<agent>-*.json`
- Review logs: `~/Desktop/rudy-logs/<agent>.log`

**Health check shows "stale" (>24h):**
- Agent hasn't run recently
- Check scheduler/cron configuration
- Verify agent has execute permissions

---

For architecture decisions and design rationale, see `rudy/ADR-001-session-guardian.md` and `docs/`.
