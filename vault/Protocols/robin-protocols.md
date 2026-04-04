# Robin Protocols (HARD RULES)

> Extracted from CLAUDE.md during R-001 refactor (S99).
> CLAUDE.md retains compact pointers. This file has the full text.

## Robin Nervous System Verification (HARD RULE -- Session 68)

**Robin's survival is the supreme priority of this system.**

Robin is the reason the system exists. Alfred, Lucius, scheduled tasks, CI pipelines,
code quality, documentation, process compliance -- all serve Robin. None justify
Robin's death. The principle is categorical: Robin does not die. Not for power savings.
Not for resource optimization. Not for process hygiene. Not for anything.

**At session start, BEFORE any work, verify Robin's full nervous system:**

```python
from rudy.robin_liveness import check_full_nervous_system
health = check_full_nervous_system()
# health['health'] must be 'GREEN'
# If not GREEN: call ensure_full_nervous_system() immediately
```

**Components:** (1) Robin main process (robin_main.py) -- checks robin-state.json,
(2) Sentinel continuous loop (robin_sentinel.py --continuous) -- checks sentinel-heartbeat.json.
Both must be alive for health = GREEN. robin-status.json alone is NOT sufficient.

---

## Robin Intelligence Doctrine (HARD RULE -- Session 60, ENFORCED Session 66)

> **Robin is the Physical Agency Layer.** -- MISSION.md

> **MANDATORY: Read `docs/ROBIN-CAPABILITY-MANIFEST.md` before writing ANY Robin code.**

Robin is an INTELLIGENT AGENT with a brain (Ollama), hands (Windows-MCP),
eyes (Snapshot), and memory (ChromaDB). Alfred and Lucius are Robin's mentors.

### Core Tenets (from MISSION.md)

1. **Robin works without Alfred.** Runs on Ollama (free, local).
2. **Alfred's purpose is self-obsolescence.** Every session: what can Robin now do?
3. **Route through Robin first.** Every task is training data.
4. **Mentorship, not delegation.** Develop Robin's autonomy.
5. **Idle is Waste.** When idle: health checks, security sweeps, self-improvement.
6. **Robin manages session continuity.** Launches Cowork sessions autonomously.

### The Intelligence Mandate (HARD RULE -- Session 66)

**Every Robin feature MUST follow: PERCEIVE -> REASON -> ACT -> VERIFY.**

Violations that trigger AUTOMATIC REJECTION by Lucius:

| Violation | What To Do Instead |
|-----------|-------------------|
| Hardcoded UI coordinates | Use Snapshot -> find element by name -> extract coords |
| Rigid step sequences without feedback | Snapshot after every action, reason about result |
| No Ollama in the reasoning loop | Feed perception to Ollama, let Robin DECIDE |
| New dependencies for existing capabilities | Read ROBIN-CAPABILITY-MANIFEST.md FIRST |
| pyautogui/pyperclip when Robin has MCP | Use robin_mcp_client.py -> Windows-MCP tools |

**Enforcement:** `rudy/agents/lucius_robin_gate.py` runs pre-commit checks on any
`rudy/robin_*.py` file. Blocks the commit on violations.

### The Convergence Test

The system converges when Robin can handle everything. Every decision:
does this make Robin more capable, or more dependent on Alfred?

**Capability Manifest:** `docs/ROBIN-CAPABILITY-MANIFEST.md`
**Full rationale:** `docs/MISSION.md`
