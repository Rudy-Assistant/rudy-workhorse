# Lucius Artifact Registry v2

> Maintained by Lucius Fox — last updated Session 22 (2026-03-30)
> Codebase: 78+ files, 34,317+ lines | Repo: Rudy-Assistant/rudy-workhorse

---

## Lucius Ecosystem

| Component | File | Lines | Status | Last Touched |
|-----------|------|-------|--------|-------------|
| **Lucius Fox Agent** | `rudy/agents/lucius_fox.py` | 1,141 | ACTIVE — 4 mandates, 9 modes | Session 16 (ADR-005 Mandate 4) |
| **Lucius Gate** | `rudy/agents/lucius_gate.py` | 1,024 | ACTIVE — Phase 1C complete, circuit breakers | Session 21 (PR #40) |
| **MCP Tier Config** | `rudy/agents/lucius_mcp_tiers.yml` | 48 | ACTIVE — per-MCP timeouts calibrated from Oracle baselines | Session 21 |
| **Network Security** | ~~`rudy/agents/lucius_network_security.py`~~ | 531 | REMOVED — Session 23 (robin_taskqueue updated to use lucius_fox hygiene_check) | Pre-Session 11 |
| **Audit Runner** | `scripts/run_lucius_audit.py` | 13 | ACTIVE — thin wrapper | Session 15 |
| **Schedule Script** | `scripts/schedule_lucius_task.ps1` | 32 | UNVERIFIED — needs confirmation it runs | Session 15 |
| **PR Review CI** | `scripts/ci/lucius_pr_review.py` | 305 | ACTIVE — GitHub Actions gate (lucius-review.yml) | Session 15 |
| **Gate Tests** | `tests/test_lucius_gate.py` | — | ACTIVE — unit tests | Session 21 |
| **Gate Chaos Tests** | `tests/test_lucius_gate_chaos.py` | — | ACTIVE — chaos/resilience testing | Session 21 |
| **Gate Integration Tests** | `tests/test_lucius_gate_integration.py` | — | ACTIVE — MCP connectivity integration | Session 21 |
| **Sanitize Tests** | `tests/test_sanitize.py` | — | ACTIVE | — |

## ADR-004 Toolkit Compliance

| Toolkit | ADR-004 Spec | Status | Session |
|---------|-------------|--------|---------|
| `lucius:audit` | Full repo audit with findings and severity | ✅ PASS — 8 sub-checks | Session 16 |
| `lucius:review` | Go/no-go verdict before PR merge | ⚠️ DEGRADED — code exists, not actively enforced | Session 15 |
| `lucius:locate` | Canonical location of any artifact | ⚠️ DEGRADED — depends on registry currency | Session 11 |
| `lucius:plan` | Impact analysis before multi-file changes | ❌ NOT IMPLEMENTED | — |
| `lucius:reconcile` | Merge/import/supersede verdicts | ❌ NOT IMPLEMENTED | — |
| `lucius:skills-check` | List relevant skills for current task, runs at session start | 🔨 IN PROGRESS — Session 22 | Session 22 |

**Compliance: 2/6 PASS, 2/6 DEGRADED, 1/6 IN PROGRESS, 1/6 FAIL**

## Core Package (rudy/)

- `rudy/__init__.py` (2L) — Package init
- `rudy/__version__.py` — v0.1.0 "Genesis"
- `rudy/admin.py` (82L) — Admin elevation helper (silent UAC bypass)
- `rudy/api_server.py` (275L) — FastAPI webhook receiver and REST API
- `rudy/avatar.py` (562L) — Digital avatar: face swap, talking-head video
- `rudy/batcave_memory.py` (259L) — Shared memory system across sessions
- `rudy/email_multi.py` (390L) — Multi-provider email with failover
- `rudy/email_poller.py` (439L) — Multi-backend email polling daemon
- `rudy/environment_profiler.py` (465L) — Environment profiler
- `rudy/financial.py` (338L) — Market data, portfolio tracking, alerts
- `rudy/find_my.py` (723L) — iCloud Find My location monitoring
- `rudy/human_simulation.py` (1332L) — Natural browser behavior simulation
- `rudy/intruder_profiler.py` (489L) — Counter-espionage device intel
- `rudy/knowledge_base.py` (370L) — Semantic search engine (ChromaDB)
- `rudy/local_ai.py` (661L) — Offline LLM intelligence (Ollama/llama-cpp)
- `rudy/movement_feed.py` (413L) — Real-time activity timeline
- `rudy/network_defense.py` (694L) — 7-check defensive suite
- `rudy/nlp.py` (274L) — Sentiment, entity extraction, summarization
- `rudy/obsolescence_monitor.py` (530L) — Capability audit and freshness
- `rudy/ocr.py` (287L) — Image OCR + PDF extraction
- `rudy/offline_ops.py` (427L) — Autonomous offline operations
- `rudy/paths.py` (134L) — Canonical path resolver
- `rudy/pentest.py` — Penetration testing orchestration
- `rudy/phone_check.py` (1609L) — Mobile device security scanning
- `rudy/photo_intel.py` (770L) — EXIF metadata analysis, GPS, timeline
- `rudy/presence.py` (391L) — WiFi/ARP device scanning
- `rudy/presence_analytics.py` (1009L) — Device classification, co-occurrence
- `rudy/prompt_registry.py` (219L) — Prompt governance
- `rudy/robin_agent.py` (688L) — Robin Agent v1 (DeepSeek)
- `rudy/robin_agent_langgraph.py` (864L) — Robin Agent v2 (LangGraph)
- `rudy/robin_agent_loader.py` (34L) — Feature-flag switch v1/v2
- `rudy/robin_alfred_protocol.py` (330L) — Robin↔Alfred IPC
- `rudy/robin_autonomy.py` (583L) — Robin self-directed intelligence
- `rudy/robin_chat_gui.py` (655L) — Robin web chat interface
- `rudy/robin_cowork_launcher.py` (20L) — DISCARDED (Session 16, per Lucius audit)
- `rudy/robin_human_adapter.py` (155L) — Human simulation adapter for Windows-MCP
- `rudy/robin_liveness.py` (340L) — Robin heartbeat and auto-recovery
- `rudy/robin_logger.py` (254L) — Robin→Notion logging
- `rudy/robin_main.py` (960L) — Robin unified orchestrator
- `rudy/robin_mcp_client.py` (531L) — Robin MCP client (stdio JSON-RPC)
- `rudy/robin_sentinel.py` (13L) — Compat shim → agents/sentinel.py
- `rudy/robin_taskqueue.py` (673L) — Extended absence task queue
- `rudy/sanitize.py` (60L) — Shared input sanitization
- `rudy/surveillance.py` (591L) — Video camera integration
- `rudy/travel_mode.py` (709L) — Portable network intelligence
- `rudy/usb_quarantine.py` (1050L) — USB quarantine protocol
- `rudy/voice.py` (248L) — TTS, STT, audio processing
- `rudy/voice_clone.py` (678L) — Voice cloning (Pocket TTS)
- `rudy/web_intelligence.py` (393L) — Web scraping, article extraction
- `rudy/wellness.py` (359L) — Family safety monitoring

## Sub-Agents (rudy/agents/)

| Agent | File | Lines | Schedule | Domain |
|-------|------|-------|----------|--------|
| **Lucius Fox** | `lucius_fox.py` | 1,141 | Weekly + on-demand | Code quality, audits, governance |
| **Lucius Gate** | `lucius_gate.py` | 1,024 | Session start | MCP connectivity, circuit breakers |
| **SystemMaster** | `system_master.py` | 266 | Every 5 min | Health & recovery |
| **SecurityAgent** | `security_agent.py` | 549 | Every 30 min | Defensive intelligence |
| **Sentinel** | `sentinel.py` | 1,109 | Every 15 min | Change detection, awareness |
| **TaskMaster** | `task_master.py` | 145 | Daily 7:30 AM | Work coordination, briefings |
| **ResearchIntel** | `research_intel.py` | 897 | Daily 6 AM + M/W/F 10 AM | Intelligence, learning |
| **OperationsMonitor** | `operations_monitor.py` | 186 | Weekly Sun 4 AM | Maintenance, cleanup |
| **Robin Sentinel** | `robin_sentinel.py` | 829 | Robin night shift | Robin health + night shift |
| **Robin Bridge** | `robin_bridge.py` | 460 | On-demand | Alfred→Robin task queue |
| **Robin Presence** | `robin_presence.py` | 607 | On-demand | Batman activity detection |
| **Agent Runner** | `runner.py` | 186 | — | Unified agent dispatcher |
| **Agent Base** | `__init__.py` | 199 | — | Common infra (logging, status) |
| **Lucius Network Security** | `lucius_network_security.py` | 531 | DEPRECATED | Pending migration |

## Workflows (rudy/workflows/)

- `rudy/workflows/__init__.py` (7L)
- `rudy/workflows/handoff.py` (597L) — HandoffWriter + HandoffScanner (Alfred↔Robin continuity)
- `rudy/workflows/pr_review.py` (195L) — Lucius-gated PR review workflow
- `rudy/workflows/session_gate.py` (207L) — Session start gate integration

## Tools (rudy/tools/)

- `rudy/tools/browser_integration.py` (115L) — LangGraph browser tools
- `rudy/tools/browser_tool.py` (355L) — Playwright-direct web capability
- `rudy/tools/notion_client.py` (292L) — Notion read/write client
- `rudy/tools/ocr_fallback.py` — CLI EasyOCR fallback
- `rudy/tools/screenshot_reader.py` — Playwright screenshot + OCR
- `rudy/tools/screen_capture.py` — Desktop screen capture + OCR
- Various setup scripts

## Integrations (rudy/integrations/)

- `rudy/integrations/github_ops.py` (287L) — GitHub operations (issues, PRs, commits)
- `rudy/integrations/git_auto.py` — Automated git ops (background commit+push)
- `rudy/integrations/rudy-suno.py` (339L) — Suno AI music generation
- `rudy/integrations/rudy-suno-generate.py` (47L) — Quick Suno generator

## Scripts

### Agent Wrappers (scripts/agents/)
- `run-all-agents.py`, `run-morning-briefing.py`, `run-research-digest.py`
- `run-security-agent.py`, `run-self-improvement.py`, `run-sentinel.py`
- `run-system-master.py`, `run-weekly-maintenance.py`

### Workhorse Management (scripts/workhorse/)
- `workhorse-maintenance.py`, `workhorse-research-feed.py`
- `workhorse-subscribe.py`, `workhorse-watchdog.py`
- `run-presence-scan.py`, `run-security-agent.py`, `run-sentinel.py`
- `update-hosts-blocklist.py`, `validate-research-feed.py`

### CI (scripts/ci/)
- `lucius_pr_review.py` (305L) — Lucius PR review for GitHub Actions

### Lucius Scripts
- `scripts/run_lucius_audit.py` (13L) — Audit runner
- `scripts/schedule_lucius_task.ps1` (32L) — Task scheduler setup

## CI Workflows (.github/workflows/)

- `lint.yml` — Ruff linting
- `lucius-review.yml` — Lucius PR review gate
- `release.yml` — Release automation
- `test.yml` — Test suite

## Key Documents

- `CLAUDE.md` ✅ — Master memory/config (HARD RULE: read first every session)
- `README.md` ✅
- `SOLE-SURVIVOR-PROTOCOL.md` ✅
- `docs/SESSION-HANDOFF.md` ✅ — Session continuity protocol
- `docs/ADR-001-robin-bridge.md` ✅
- `docs/ADR-002-robin-sentinel.md` ✅
- `docs/ADR-003-robin-handoff-protocol.md` ✅
- `docs/ADR-004-lucius-fox-librarian.md` ✅ — Lucius mandate spec (12,896B)
- `docs/ADR-005-build-vs-buy-gate.md` ✅ — Mandate 4 (The Economist)
- `docs/ALFRED-DIRECTIVES.md` ✅
- `docs/BATCAVE-CLAUDE.md` ✅
- `docs/MISSION.md` ✅
- `docs/SECURITY-LOCKOUT-AUDIT.md` ✅
- Phase 1 docs: `docs/phase1/`

## Branch Governance

**Trunk:** `main` (HEAD as of Session 22)

**Remote branches needing cleanup:**
| Branch | Status | Action |
|--------|--------|--------|
| `origin/alfred/lucius-gate-core` | Merged (PR #39) | DELETE |
| `origin/alfred/lucius-gate-integration` | Merged (PR #40) | DELETE |
| `origin/alfred/session21-claudemd-update` | Merged (PR #41) | DELETE |
| `origin/alfred/robin-logging-nightwatch` | Likely merged | VERIFY and DELETE |

**Local branches:** Only `main` (clean state as of Session 22 clone)

## Connector Status

| Connector | Status | Notes |
|-----------|--------|-------|
| **GitHub** | ✅ ACTIVE | PAT expires 2026-06-26, Contents=Read+Write |
| **Gmail** | ✅ ACTIVE | ccimino2@gmail.com, full access |
| **Google Calendar** | ✅ ACTIVE | Connected |
| **Notion** | ✅ ACTIVE | Rudy Command Center workspace |
| **Google Drive** | ✅ ACTIVE | Connected 2026-03-27 |
| **Chrome Extension** | ✅ ACTIVE | Connected |
| **Canva** | ✅ ACTIVE | Connected |

## Open Actions

| ID | Description | Status | Session |
|----|------------|--------|---------|
| LA-001 | GitHub PAT renewal | ✅ DONE — renewed, expires 2026-06-26 | 11→22 |
| LA-002 | Merge robin-logging-nightwatch to main | ✅ DONE — merged | 11→22 |
| LA-003 | Implement lucius:skills-check | 🔨 IN PROGRESS | 22 |
| LA-004 | Implement lucius:plan | ✅ DONE | Session 23 |
| LA-005 | Implement lucius:reconcile | OPEN | — |
| LA-006 | Wire Sentinel→Lucius integration | ✅ DONE | Session 23 |
| LA-007 | Activate lucius-review.yml as required check | OPEN (needs admin PAT) | GitHub issue filed, Session 23 |
| LA-008 | Remove lucius_network_security.py (deprecated) | ✅ DONE | Session 23 |
| LA-009 | Clean up stale remote branches | 🔨 IN PROGRESS | 22 |

## Known Duplication (tracked)

- `sentinel.py` / `robin_sentinel.py` / `agents/sentinel.py` — compatibility shim (Session 8)
- `presence.py` / `agents/robin_presence.py` — compatibility shim
- `__init__.py` across packages — standard Python packaging (not true duplication)
- `robin_cowork_launcher.py` — DISCARDED, should be removed

## Quality Gate Status

| Check | Status | Last Verified |
|-------|--------|---------------|
| Hardcoded paths | ✅ Zero findings | Session 16 |
| Import hygiene | ✅ Zero findings | Session 16 |
| Ruff lint | ✅ Clean | Session 16 |
| Documentation | ✅ All required docs present | Session 22 |
| CI: lint + smoke-test | ✅ Passing | Session 21 |
| CI: Lucius PR review | ✅ Active (not required check yet) | Session 15 |
| Gate: MCP connectivity | ✅ Phase 1C complete, 55 tests | Session 21 |

---

*"I keep the inventory. You keep the promises." — Lucius Fox*

*Registry v2 — Session 22 (2026-03-30)*
