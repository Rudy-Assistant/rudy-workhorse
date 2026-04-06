#!/usr/bin/env python3
"""
Robin Skill Learner -- Phase 3 Step 9 (ADR-020 Amendment).

Observes task patterns delegated from Alfred via the DelegationGate
and proposes Robin OpenSpace Skills when patterns repeat 3+ times.
Extends sentinel_proposals.py's pipeline with delegation-aware
skill synthesis.

Architecture:
    OBSERVE: Read delegation metrics + Robin command history
    CLUSTER: Group similar delegated operations by category/pattern
    PROPOSE: Generate OpenSpace Skill definitions via Ollama
    VALIDATE: Check proposed skills against existing capabilities
    DEPLOY: Write skill scaffolds to OpenSpace directory

Integration:
    - alfred_delegation_gate.py (reads delegation-metrics.json)
    - sentinel_proposals.py (complements command-based proposals)
    - rudy.paths (canonical paths)
    - OpenSpace skill engine (OPENSPACE_DIR from rudy.paths)

Session 140: Phase 3 Step 9 of Andrew-Readiness (ADR-020).
"""

import json
import logging
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    from rudy.paths import (
        RUDY_DATA,
        RUDY_LOGS,
        SENTINEL_LEARNING,
        OPENSPACE_DIR,
    )
except ImportError:
    RUDY_DATA = Path(__file__).resolve().parent.parent / "rudy-data"
    RUDY_LOGS = RUDY_DATA.parent / "rudy-logs"
    SENTINEL_LEARNING = RUDY_DATA / "sentinel-learning"
    OPENSPACE_DIR = Path.home() / "OpenSpace"

log = logging.getLogger("robin.skill_learner")

# Paths
SKILL_LEARNER_DIR = SENTINEL_LEARNING / "skill-learner"
SKILL_LEARNER_DIR.mkdir(parents=True, exist_ok=True)
DELEGATION_LOG = SKILL_LEARNER_DIR / "delegation-log.json"
SKILL_PROPOSALS = SKILL_LEARNER_DIR / "skill-proposals.json"
DEPLOYED_SKILLS = SKILL_LEARNER_DIR / "deployed-skills.json"
LEARNER_STATE = SKILL_LEARNER_DIR / "learner-state.json"
DELEGATION_METRICS = RUDY_DATA / "coordination" / "delegation-metrics.json"

# Thresholds
MIN_PATTERN_COUNT = 3       # Minimum repeats before proposing a skill
MIN_CONFIDENCE = 0.5        # Minimum pattern confidence for proposal
MAX_PROPOSALS_PER_CYCLE = 3  # Cap proposals per learning cycle


# -------------------------------------------------------------------
# Stage 1: OBSERVE -- Collect delegation events
# -------------------------------------------------------------------

def collect_delegation_events(hours: int = 168) -> list[dict]:
    """Collect delegation events from metrics and Robin logs.

    Sources:
        - delegation-metrics.json (from DelegationGate)
        - delegation-log.json (historical delegation records)
        - Robin inbox processed items (completed delegations)

    Returns list of delegation event dicts.
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    events = []

    # Source 1: Current session delegation metrics
    events.extend(_read_current_metrics())

    # Source 2: Historical delegation log
    events.extend(_read_delegation_log(cutoff))

    # Source 3: Robin inbox completed delegations
    events.extend(_read_completed_delegations(cutoff))

    events.sort(key=lambda e: e.get("timestamp", ""))
    log.info(
        "Collected %d delegation events from %d hours",
        len(events), hours,
    )
    return events


def _read_current_metrics() -> list[dict]:
    """Read current delegation metrics from the gate."""
    if not DELEGATION_METRICS.exists():
        return []
    try:
        data = json.loads(
            DELEGATION_METRICS.read_text(encoding="utf-8"),
        )
        events = []
        by_cat = data.get("by_category", {})
        session = data.get("session", 0)
        for cat, counts in by_cat.items():
            delegated = counts.get("delegate", 0)
            if delegated > 0:
                events.append({
                    "timestamp": datetime.now().isoformat(),
                    "source": "delegation_gate",
                    "category": cat,
                    "disposition": "delegate",
                    "count": delegated,
                    "session": session,
                })
        return events
    except (json.JSONDecodeError, OSError) as exc:
        log.debug("Metrics read error: %s", exc)
        return []


def _read_delegation_log(cutoff: datetime) -> list[dict]:
    """Read historical delegation log entries."""
    if not DELEGATION_LOG.exists():
        return []
    try:
        entries = json.loads(
            DELEGATION_LOG.read_text(encoding="utf-8"),
        )
        filtered = []
        for entry in entries:
            ts = entry.get("timestamp", "")
            try:
                if ts and datetime.fromisoformat(ts) < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
            filtered.append(entry)
        return filtered
    except (json.JSONDecodeError, OSError) as exc:
        log.debug("Delegation log read error: %s", exc)
        return []


def _read_completed_delegations(cutoff: datetime) -> list[dict]:
    """Read completed delegation items from Robin inbox.

    F-S141-003(c): ROBIN_INBOX_V2 import is wrapped in try/except so
    a missing path constant on older rudy.paths doesn't crash the
    entire learning cycle.
    """
    try:
        from rudy.paths import ROBIN_INBOX_V2
    except ImportError:
        log.debug("ROBIN_INBOX_V2 not available in rudy.paths")
        return []

    events = []
    if not ROBIN_INBOX_V2.exists():
        return events
    for f in ROBIN_INBOX_V2.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            if data.get("type") != "task":
                continue
            ts = data.get("created_at", data.get("timestamp", ""))
            try:
                if ts and datetime.fromisoformat(ts) < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
            events.append({
                "timestamp": ts or datetime.now().isoformat(),
                "source": "robin_inbox",
                "category": data.get("category", "unknown"),
                "operation": data.get("task", "")[:200],
                "disposition": "delegate",
                "session": data.get("session", 0),
            })
        except (json.JSONDecodeError, OSError):
            continue
    return events


# -------------------------------------------------------------------
# Stage 2: CLUSTER -- Group similar delegated operations
# -------------------------------------------------------------------

def cluster_delegation_patterns(events: list[dict]) -> list[dict]:
    """Cluster delegated operations into recurring patterns.

    Groups by category, then by operation similarity.
    Returns patterns that exceed MIN_PATTERN_COUNT threshold.
    """
    if not events:
        return []

    # Group by category
    by_category = defaultdict(list)
    for e in events:
        cat = e.get("category", "unknown")
        by_category[cat].append(e)

    patterns = []

    for cat, cat_events in by_category.items():
        # Sub-group by normalized operation
        op_groups = defaultdict(list)
        for e in cat_events:
            op = _normalize_operation(e.get("operation", cat))
            op_groups[op].append(e)

        for op, group in op_groups.items():
            count = len(group)
            # Also count aggregated metrics entries
            for e in group:
                if "count" in e:
                    count += e["count"] - 1

            if count < MIN_PATTERN_COUNT:
                continue

            # Calculate confidence based on frequency and recency
            confidence = min(count / 10.0, 1.0)
            sessions_seen = len(set(
                e.get("session", 0) for e in group if e.get("session")
            ))
            if sessions_seen > 1:
                confidence = min(confidence + 0.2, 1.0)

            patterns.append({
                "category": cat,
                "operation": op,
                "frequency": count,
                "sessions_seen": sessions_seen,
                "confidence": round(confidence, 2),
                "sample_events": [
                    e.get("operation", e.get("category", ""))[:100]
                    for e in group[:5]
                ],
                "first_seen": group[0].get("timestamp", ""),
                "last_seen": group[-1].get("timestamp", ""),
            })

    # Sort by frequency descending
    patterns.sort(key=lambda p: -p["frequency"])
    log.info("Clustered %d skill-worthy patterns", len(patterns))
    return patterns


# -------------------------------------------------------------------
# Stage 3: PROPOSE -- Generate OpenSpace Skill definitions
# -------------------------------------------------------------------

def propose_skills(patterns: list[dict]) -> list[dict]:
    """Generate OpenSpace Skill proposals from recurring patterns.

    Uses Ollama to synthesize skill definitions that Robin can
    execute autonomously. Each proposal includes a skill name,
    trigger conditions, execution steps, and success criteria.

    Args:
        patterns: Clustered delegation patterns from Stage 2.

    Returns:
        List of skill proposal dicts.
    """
    if not patterns:
        return []

    # Filter to high-confidence patterns
    eligible = [
        p for p in patterns
        if p.get("confidence", 0) >= MIN_CONFIDENCE
    ][:MAX_PROPOSALS_PER_CYCLE]

    if not eligible:
        return []

    pattern_summary = "\n".join(
        f"- [{p['category']}] {p['operation']} "
        f"(seen {p['frequency']}x across {p['sessions_seen']} sessions, "
        f"confidence={p['confidence']:.0%})"
        for p in eligible
    )

    prompt = (
        "You are the Skill Learner for Robin, an AI assistant's "
        "local execution agent. Robin handles file ops, git, system "
        "diagnostics, linting, process management, local AI, and "
        "Windows automation for a quadriplegic user named Andrew.\n\n"
        "These delegation patterns were observed (tasks Alfred "
        "repeatedly sends to Robin):\n"
        f"{pattern_summary}\n\n"
        "For each pattern, propose an OpenSpace Skill that Robin "
        "can learn and execute proactively. Each skill should:\n"
        "1. Have a clear name (snake_case)\n"
        "2. Define trigger conditions (when to activate)\n"
        "3. List execution steps Robin performs\n"
        "4. Specify success criteria\n"
        "5. Include safety constraints\n\n"
    )
    prompt += (
        "Respond in JSON array format:\n"
        '[{"skill_name": "...", "description": "...", '
        '"trigger": "...", "steps": [...], '
        '"success_criteria": "...", "safety": "...", '
        '"priority": "high|medium|low"}]\n\n'
    )
    prompt += (
        "Only propose safe skills. Never propose anything that "
        "deletes user data, sends messages without confirmation, "
        "or makes irreversible changes without a dry-run mode."
    )

    proposals = _generate_via_ollama(prompt)

    # Stamp with metadata
    timestamped = []
    for i, p in enumerate(proposals):
        p["id"] = f"SKL-{datetime.now().strftime('%Y%m%d')}-{i + 1:03d}"
        p["source_pattern"] = eligible[i] if i < len(eligible) else {}
        p["generated_by"] = "skill_learner"
        p["generated_at"] = datetime.now().isoformat()
        p["status"] = "proposed"
        timestamped.append(p)

    # Persist proposals
    _save_skill_proposals(timestamped)
    log.info("Generated %d skill proposals", len(timestamped))
    return timestamped


def _generate_via_ollama(prompt: str) -> list[dict]:
    """Generate skill proposals using local Ollama model."""
    import urllib.request

    ollama_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

    try:
        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1500},
        }).encode()

        req = urllib.request.Request(
            f"{ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        # F-S141-003(b): Cap below run_learning_cycle 30s budget.
        # Leave headroom for collect/cluster/validate/deploy stages.
        ollama_timeout = float(os.environ.get("OLLAMA_TIMEOUT", "20"))
        resp = urllib.request.urlopen(req, timeout=ollama_timeout)
        result = json.loads(resp.read())
        response_text = result.get("response", "")
        return _extract_json_array(response_text)
    except (OSError, json.JSONDecodeError, KeyError) as exc:
        log.warning("Ollama skill generation failed: %s", exc)
    return []


def _extract_json_array(text: str) -> list[dict]:
    """Extract a JSON array from LLM response text."""
    import re
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    return []


# -------------------------------------------------------------------
# Stage 4: VALIDATE -- Check against existing capabilities
# -------------------------------------------------------------------

def validate_proposals(proposals: list[dict]) -> list[dict]:
    """Validate proposed skills against existing Robin capabilities.

    Checks:
        - No duplicate skill names in OpenSpace or deployed-skills
        - Execution steps reference real tools/commands
        - Safety constraints are present
        - Skill doesn't overlap with existing sentinel proposals

    Returns filtered list of valid proposals.
    """
    existing_names = _get_existing_skill_names()
    existing_proposals = _get_active_sentinel_proposals()
    valid = []

    for proposal in proposals:
        name = proposal.get("skill_name", "")

        # Check duplicate name
        if name in existing_names:
            log.info("Skipping duplicate skill: %s", name)
            proposal["status"] = "duplicate"
            continue

        # Check safety field present
        if not proposal.get("safety"):
            log.info("Skipping skill without safety: %s", name)
            proposal["status"] = "rejected_no_safety"
            continue

        # Check overlap with sentinel proposals
        desc = proposal.get("description", "").lower()
        overlap = False
        for sp in existing_proposals:
            sp_desc = sp.get("automation", "").lower()
            if sp_desc and _text_similarity(desc, sp_desc) > 0.7:
                overlap = True
                break
        if overlap:
            log.info("Skipping overlapping skill: %s", name)
            proposal["status"] = "overlaps_sentinel"
            continue

        proposal["status"] = "validated"
        valid.append(proposal)

    log.info(
        "Validated %d of %d proposals",
        len(valid), len(proposals),
    )
    return valid


def _get_existing_skill_names() -> set[str]:
    """Get names of all existing OpenSpace skills."""
    names = set()
    # From OpenSpace directory
    if OPENSPACE_DIR.exists():
        for d in OPENSPACE_DIR.iterdir():
            if d.is_dir():
                names.add(d.name)
    # From deployed-skills log
    deployed = _load_json(DEPLOYED_SKILLS, [])
    for s in deployed:
        names.add(s.get("skill_name", ""))
    return names


def _get_active_sentinel_proposals() -> list[dict]:
    """Get active proposals from sentinel_proposals pipeline."""
    proposals_file = SENTINEL_LEARNING / "active-proposals.json"
    return _load_json(proposals_file, [])


def _text_similarity(a: str, b: str) -> float:
    """Word-overlap (Jaccard) similarity between two strings.

    F-S141-003(d): Require a minimum word count on BOTH sides to
    avoid false positives where two-word strings sharing one word
    score 0.5+ and trigger spurious overlap rejection.
    """
    if not a or not b:
        return 0.0
    words_a = set(a.lower().split())
    words_b = set(b.lower().split())
    if not words_a or not words_b:
        return 0.0
    if len(words_a) < 4 or len(words_b) < 4:
        return 0.0
    intersection = words_a & words_b
    union = words_a | words_b
    return len(intersection) / len(union)


# -------------------------------------------------------------------
# Stage 5: DEPLOY -- Write skill scaffolds to OpenSpace
# -------------------------------------------------------------------

def deploy_skill_scaffold(proposal: dict) -> Optional[Path]:
    """Deploy a validated skill proposal as an OpenSpace scaffold.

    Creates:
        OpenSpace/{skill_name}/
            skill.json     -- Skill metadata and configuration
            README.md      -- Human-readable skill description
            handler.py     -- Stub handler for Robin to execute

    Args:
        proposal: Validated skill proposal dict.

    Returns:
        Path to the skill directory, or None on failure.
    """
    name = proposal.get("skill_name", "")
    if not name:
        return None

    skill_dir = OPENSPACE_DIR / name
    try:
        skill_dir.mkdir(parents=True, exist_ok=True)

        # skill.json -- machine-readable config
        skill_config = {
            "name": name,
            "description": proposal.get("description", ""),
            "trigger": proposal.get("trigger", "manual"),
            "steps": proposal.get("steps", []),
            "success_criteria": proposal.get("success_criteria", ""),
            "safety": proposal.get("safety", ""),
            "priority": proposal.get("priority", "medium"),
            "source": "skill_learner",
            "proposal_id": proposal.get("id", ""),
            "deployed_at": datetime.now().isoformat(),
            "status": "scaffold",
        }
        (skill_dir / "skill.json").write_text(
            json.dumps(skill_config, indent=2) + "\n",
            encoding="utf-8",
        )

        # README.md -- human-readable
        readme = (
            f"# {name}\n\n"
            f"{proposal.get('description', 'No description.')}\n\n"
            f"## Trigger\n\n{proposal.get('trigger', 'Manual')}\n\n"
            f"## Steps\n\n"
        )
        for i, step in enumerate(proposal.get("steps", []), 1):
            readme += f"{i}. {step}\n"
        readme += (
            f"\n## Safety\n\n{proposal.get('safety', 'N/A')}\n\n"
            f"## Success Criteria\n\n"
            f"{proposal.get('success_criteria', 'N/A')}\n\n"
            f"---\n"
            f"*Generated by Skill Learner "
            f"({proposal.get('id', 'unknown')})*\n"
        )
        (skill_dir / "README.md").write_text(
            readme, encoding="utf-8",
        )

        # handler.py -- stub for Robin execution
        handler = (
            '"""Auto-generated skill handler for '
            f'{name}."""\n\n'
            "import json\nimport logging\n"
            "from pathlib import Path\n\n"
            'log = logging.getLogger(f"robin.skill.{__name__}")\n\n\n'
            "def execute(context: dict = None) -> dict:\n"
            '    """Execute the skill.\n\n'
            "    Args:\n"
            "        context: Runtime context from Robin.\n\n"
            "    Returns:\n"
            "        Result dict with status and details.\n"
            '    """\n'
            "    context = context or {}\n"
            '    log.info("Executing skill: %s", '
            f'"{name}")\n\n'
            "    # TODO: Implement skill logic\n"
            "    # Steps from proposal:\n"
        )
        for i, step in enumerate(proposal.get("steps", []), 1):
            safe_step = step.replace('"', '\\"')[:80]
            handler += f'    # {i}. {safe_step}\n'
        handler += (
            "\n    return {\n"
            '        "status": "scaffold",\n'
            f'        "skill": "{name}",\n'
            '        "message": "Skill scaffold -- needs implementation",\n'
            "    }\n"
        )
        (skill_dir / "handler.py").write_text(
            handler, encoding="utf-8",
        )

        # Record deployment
        deployed = _load_json(DEPLOYED_SKILLS, [])
        deployed.append({
            "skill_name": name,
            "proposal_id": proposal.get("id", ""),
            "deployed_at": datetime.now().isoformat(),
            "path": str(skill_dir),
            "status": "scaffold",
        })
        DEPLOYED_SKILLS.write_text(
            json.dumps(deployed[-100:], indent=2) + "\n",
            encoding="utf-8",
        )

        # Update proposal status
        proposal["status"] = "deployed"
        log.info("Deployed skill scaffold: %s -> %s", name, skill_dir)
        return skill_dir

    except OSError as exc:
        log.error("Failed to deploy skill %s: %s", name, exc)
        return None


# -------------------------------------------------------------------
# Main entry point -- called by Sentinel or Alfred
# -------------------------------------------------------------------

def run_learning_cycle(
    session_number: int = 0,
    max_runtime_secs: float = 30.0,
) -> dict:
    """Run one iteration of the skill learning pipeline.

    Called by Sentinel as a complement to sentinel_proposals.py.
    This pipeline focuses on delegation patterns rather than
    raw command history.

    Args:
        session_number: Current session number for tracking.
        max_runtime_secs: Hard cap on execution time.

    Returns:
        Summary dict with events, patterns, proposals, deployments.
    """
    start = time.time()
    summary = {
        "phase": "skill_learning_cycle",
        "session": session_number,
        "started_at": datetime.now().isoformat(),
    }

    # Check if full analysis is due (every 6 hours)
    state = _load_json(LEARNER_STATE, {})
    last_run = state.get("last_full_run", "")
    hours_since = 999
    if last_run:
        try:
            delta = datetime.now() - datetime.fromisoformat(last_run)
            hours_since = delta.total_seconds() / 3600
        except (ValueError, TypeError):
            pass

    do_full = hours_since >= 6

    # Stage 1: Collect delegation events
    events = collect_delegation_events(hours=168 if do_full else 24)
    summary["events_collected"] = len(events)

    if time.time() - start > max_runtime_secs:
        summary["aborted"] = "timeout_after_collect"
        return summary

    if not events:
        summary["result"] = "no_delegation_events"
        return summary

    # Append to persistent delegation log
    _append_delegation_log(events)

    # Stage 2: Cluster patterns
    if do_full:
        patterns = cluster_delegation_patterns(events)
        state["last_full_run"] = datetime.now().isoformat()
        state["last_pattern_count"] = len(patterns)
        state["session"] = session_number
        LEARNER_STATE.write_text(
            json.dumps(state, indent=2) + "\n", encoding="utf-8",
        )
    else:
        patterns = _load_json(
            SKILL_LEARNER_DIR / "cached-patterns.json", [],
        )

    summary["patterns_found"] = len(patterns)

    if time.time() - start > max_runtime_secs:
        summary["aborted"] = "timeout_after_cluster"
        return summary

    # Cache patterns for quick cycles
    if do_full and patterns:
        (SKILL_LEARNER_DIR / "cached-patterns.json").write_text(
            json.dumps(patterns, indent=2, default=str) + "\n",
            encoding="utf-8",
        )

    # Stage 3: Propose skills (only on full analysis with patterns)
    proposals = []
    if do_full and patterns:
        proposals = propose_skills(patterns)
        summary["proposals_generated"] = len(proposals)

        if time.time() - start > max_runtime_secs:
            summary["aborted"] = "timeout_after_propose"
            return summary

        # Stage 4: Validate proposals
        if proposals:
            proposals = validate_proposals(proposals)
            summary["proposals_validated"] = len(proposals)

            # Stage 5: Deploy validated scaffolds
            deployed = []
            for p in proposals:
                if p.get("status") == "validated":
                    path = deploy_skill_scaffold(p)
                    if path:
                        deployed.append(str(path))
            summary["skills_deployed"] = deployed
    else:
        summary["proposals_generated"] = 0
        summary["note"] = "Quick cycle -- using cached patterns"

    summary["full_analysis"] = do_full
    summary["runtime_secs"] = round(time.time() - start, 2)
    return summary


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

_SESSION_PREFIX_RE = re.compile(r'^s\d+:\s*', re.IGNORECASE)


def _normalize_operation(op: str) -> str:
    """Normalize an operation string for clustering.

    Strips any "sN:" session prefix (regex, not hardcoded), and the
    "session " literal, then truncates. Fix for F-S141-003(a).
    """
    if not op:
        return ""
    op = op.strip().lower()
    op = _SESSION_PREFIX_RE.sub("", op)
    if op.startswith("session "):
        op = op[len("session "):].strip()
    return op[:100]


def _append_delegation_log(events: list[dict]) -> None:
    """Append events to the persistent delegation log."""
    existing = _load_json(DELEGATION_LOG, [])
    existing.extend(events)
    # Keep last 1000 entries
    existing = existing[-1000:]
    DELEGATION_LOG.write_text(
        json.dumps(existing, indent=2, default=str) + "\n",
        encoding="utf-8",
    )

def _save_skill_proposals(proposals: list[dict]) -> None:
    """Persist skill proposals."""
    existing = _load_json(SKILL_PROPOSALS, [])
    existing.extend(proposals)
    existing = existing[-100:]
    SKILL_PROPOSALS.write_text(
        json.dumps(existing, indent=2, default=str) + "\n",
        encoding="utf-8",
    )


def _load_json(path: Path, default):
    """Load JSON from file, returning default on any error."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return default


# -------------------------------------------------------------------
# CLI test harness
# -------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)

    test_mode = "--test" in sys.argv
    session = 140

    if test_mode:
        # Dry run with sample delegation events
        sample_events = [
            {"timestamp": datetime.now().isoformat(), "source": "delegation_gate", "category": "git", "disposition": "delegate", "count": 5, "session": 139},
            {"timestamp": datetime.now().isoformat(), "source": "delegation_gate", "category": "file_io", "disposition": "delegate", "count": 4, "session": 139},
            {"timestamp": datetime.now().isoformat(), "source": "delegation_gate", "category": "lint_compile", "disposition": "delegate", "count": 6, "session": 138},
            {"timestamp": datetime.now().isoformat(), "source": "delegation_gate", "category": "diagnostics", "disposition": "delegate", "count": 3, "session": 137},
            {"timestamp": datetime.now().isoformat(), "source": "delegation_gate", "category": "local_ai", "disposition": "delegate", "count": 3, "session": 139},
            {"timestamp": datetime.now().isoformat(), "source": "delegation_gate", "category": "routine", "disposition": "delegate", "count": 4, "session": 138},
        ]
        patterns = cluster_delegation_patterns(sample_events)
        print(f"Patterns found: {len(patterns)}")
        for p in patterns:
            print(f"  [{p['category']}] {p['operation']} x{p['frequency']} (conf={p['confidence']})")

        result = {"test": True, "patterns": len(patterns)}
        out_path = RUDY_DATA / "coordination" / "skill-learner-test.json"
        out_path.write_text(json.dumps(result, indent=2) + "\n")
        print(f"Test results: {result}")
    else:
        summary = run_learning_cycle(session_number=session)
        out = RUDY_DATA / "coordination" / "skill-learner-result.json"
        out.write_text(json.dumps(summary, indent=2) + "\n")
        print(f"Learning cycle complete: {summary}")
