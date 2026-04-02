"""
Sentinel Learning Loop — Glue Module (ADR-018).

Composes best-in-class OSS tools into the observe→propose→execute→measure loop:
    - ActivityWatch: passive user behavior observation (local, privacy-first)
    - PM4Py: process mining / pattern discovery from event logs
    - PrefixSpan: sequential pattern mining
    - Alfred (Claude) or Robin (Ollama): proposal generation

Intelligence hierarchy (S61 doctrine):
    Alfred generates proposals when available (most intelligent actor).
    Robin generates proposals only when Alfred is offline (Sole Digital Survivor).
    Sentinel never generates proposals itself — it collects and feeds.

This module is called by Sentinel's scan cycle (sentinel.py) as a new phase.
"""

import json
import logging
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from rudy.paths import RUDY_DATA, RUDY_LOGS, ROBIN_INBOX_V2

log = logging.getLogger("sentinel.learning")

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

LEARNING_DIR = RUDY_DATA / "sentinel-learning"
LEARNING_DIR.mkdir(parents=True, exist_ok=True)

PATTERNS_FILE = LEARNING_DIR / "discovered-patterns.json"
PROPOSALS_FILE = LEARNING_DIR / "automation-proposals.json"
EFFECTIVENESS_FILE = LEARNING_DIR / "effectiveness-log.json"
AW_CACHE_FILE = LEARNING_DIR / "aw-events-cache.json"

# ActivityWatch default API
AW_API_BASE = os.environ.get("AW_API_BASE", "http://localhost:5600/api/0")

# How far back to look for patterns (hours)
OBSERVATION_WINDOW_HOURS = int(os.environ.get("SENTINEL_OBSERVATION_HOURS", "168"))  # 1 week

# Minimum pattern frequency to be considered significant
MIN_PATTERN_FREQUENCY = int(os.environ.get("SENTINEL_MIN_PATTERN_FREQ", "3"))


# ---------------------------------------------------------------------------
# Stage 1: OBSERVE — Fetch events from ActivityWatch
# ---------------------------------------------------------------------------

def fetch_aw_events(hours: int = OBSERVATION_WINDOW_HOURS) -> list[dict]:
    """Fetch window/app events from ActivityWatch's local API.

    Returns a list of event dicts: {timestamp, duration, app, title}.
    Gracefully returns [] if AW is not running.
    """
    try:
        import urllib.request
        import urllib.error

        # Get available buckets
        resp = urllib.request.urlopen(f"{AW_API_BASE}/buckets", timeout=5)
        buckets = json.loads(resp.read())

        # Find the window watcher bucket (aw-watcher-window_<hostname>)
        window_buckets = [b for b in buckets if "aw-watcher-window" in b]
        if not window_buckets:
            log.warning("No ActivityWatch window watcher bucket found")
            return []

        bucket_id = window_buckets[0]

        # Fetch events within the observation window
        end = datetime.utcnow()
        start = end - timedelta(hours=hours)
        params = f"start={start.isoformat()}Z&end={end.isoformat()}Z&limit=-1"
        url = f"{AW_API_BASE}/buckets/{bucket_id}/events?{params}"
        resp = urllib.request.urlopen(url, timeout=30)
        raw_events = json.loads(resp.read())

        events = []
        for e in raw_events:
            events.append({
                "timestamp": e.get("timestamp", ""),
                "duration": e.get("duration", 0),
                "app": e.get("data", {}).get("app", "unknown"),
                "title": e.get("data", {}).get("title", ""),
            })

        # Cache for offline analysis
        AW_CACHE_FILE.write_text(
            json.dumps(events[:5000], indent=2, default=str),
            encoding="utf-8",
        )
        log.info(f"Fetched {len(events)} events from ActivityWatch ({hours}h window)")
        return events

    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        log.info(f"ActivityWatch not available: {exc}")
        # Fall back to cached events if available
        if AW_CACHE_FILE.exists():
            try:
                return json.loads(AW_CACHE_FILE.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                pass
        return []


# ---------------------------------------------------------------------------
# Stage 2: DISCOVER — Mine patterns from event logs
# ---------------------------------------------------------------------------

def discover_patterns(events: list[dict]) -> list[dict]:
    """Extract behavioral patterns from ActivityWatch events.

    Uses PM4Py for process mining and PrefixSpan for sequential patterns.
    Falls back to simple frequency analysis if dependencies aren't installed.

    Returns list of pattern dicts:
        {type, description, frequency, confidence, events_sample}
    """
    if not events:
        return []

    patterns = []

    # --- Frequency analysis (always available, no dependencies) ---
    patterns.extend(_frequency_patterns(events))

    # --- Time-of-day patterns ---
    patterns.extend(_temporal_patterns(events))

    # --- Sequential patterns (PrefixSpan if available) ---
    try:
        from prefixspan import PrefixSpan

        # Build sequences: group events by hour-blocks, extract app sequences
        sequences = _build_sequences(events, block_minutes=30)
        if sequences:
            ps = PrefixSpan(sequences)
            ps.minlen = 2
            ps.maxlen = 5
            frequent = ps.frequent(MIN_PATTERN_FREQUENCY)
            for freq, seq in frequent[:20]:  # Top 20 sequences
                patterns.append({
                    "type": "sequential",
                    "description": f"User frequently does: {' → '.join(seq)}",
                    "sequence": seq,
                    "frequency": freq,
                    "confidence": min(freq / max(len(sequences), 1), 1.0),
                })
    except ImportError:
        log.debug("PrefixSpan not installed — skipping sequential pattern mining")

    # --- Process mining (PM4Py if available) ---
    try:
        import pm4py

        # Convert to PM4Py event log format
        pm4py_log = _to_pm4py_log(events)
        if pm4py_log is not None and len(pm4py_log) > 10:
            # Discover directly-follows graph
            dfg, start_activities, end_activities = pm4py.discover_dfg(pm4py_log)
            # Extract top edges (most common transitions)
            top_transitions = sorted(dfg.items(), key=lambda x: -x[1])[:10]
            for (src, dst), count in top_transitions:
                if count >= MIN_PATTERN_FREQUENCY:
                    patterns.append({
                        "type": "process_transition",
                        "description": f"After '{src}', user often switches to '{dst}' ({count} times)",
                        "from_app": src,
                        "to_app": dst,
                        "frequency": count,
                        "confidence": min(count / max(len(events), 1), 1.0),
                    })
    except ImportError:
        log.debug("PM4Py not installed — skipping process mining")
    except Exception as exc:
        log.warning(f"PM4Py analysis failed: {exc}")

    # Filter to significant patterns only
    patterns = [p for p in patterns if p.get("frequency", 0) >= MIN_PATTERN_FREQUENCY]

    # Save patterns
    PATTERNS_FILE.write_text(
        json.dumps(patterns, indent=2, default=str),
        encoding="utf-8",
    )
    log.info(f"Discovered {len(patterns)} behavioral patterns")
    return patterns


def _frequency_patterns(events: list[dict]) -> list[dict]:
    """Simple frequency analysis: what apps does the user spend most time in?"""
    app_time: dict[str, float] = {}
    app_count: dict[str, int] = {}
    for e in events:
        app = e.get("app", "unknown")
        dur = e.get("duration", 0)
        app_time[app] = app_time.get(app, 0) + dur
        app_count[app] = app_count.get(app, 0) + 1

    patterns = []
    for app, total_secs in sorted(app_time.items(), key=lambda x: -x[1])[:10]:
        hours = total_secs / 3600
        count = app_count.get(app, 0)
        if count >= MIN_PATTERN_FREQUENCY:
            patterns.append({
                "type": "frequency",
                "description": f"User spends {hours:.1f}h in {app} ({count} sessions)",
                "app": app,
                "total_hours": round(hours, 2),
                "session_count": count,
                "frequency": count,
                "confidence": 0.9,
            })
    return patterns


def _temporal_patterns(events: list[dict]) -> list[dict]:
    """Time-of-day analysis: when does the user use specific apps?"""
    from collections import defaultdict

    hour_apps: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for e in events:
        ts = e.get("timestamp", "")
        app = e.get("app", "unknown")
        try:
            hour = datetime.fromisoformat(ts.replace("Z", "+00:00")).hour
            hour_apps[hour][app] += 1
        except (ValueError, AttributeError):
            continue

    patterns = []
    for hour, apps in sorted(hour_apps.items()):
        top_app = max(apps, key=apps.get) if apps else None
        count = apps.get(top_app, 0) if top_app else 0
        if count >= MIN_PATTERN_FREQUENCY:
            period = "morning" if 5 <= hour < 12 else "afternoon" if 12 <= hour < 17 else "evening" if 17 <= hour < 21 else "night"
            patterns.append({
                "type": "temporal",
                "description": f"At {hour}:00 ({period}), user typically uses {top_app} ({count} times)",
                "hour": hour,
                "app": top_app,
                "frequency": count,
                "confidence": min(count / max(sum(apps.values()), 1), 1.0),
            })
    return patterns


def _build_sequences(events: list[dict], block_minutes: int = 30) -> list[list[str]]:
    """Group events into time-block sequences of app names."""
    if not events:
        return []

    sequences = []
    current_seq: list[str] = []
    last_ts = None

    for e in sorted(events, key=lambda x: x.get("timestamp", "")):
        ts_str = e.get("timestamp", "")
        app = e.get("app", "unknown")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except (ValueError, AttributeError):
            continue

        if last_ts and (ts - last_ts).total_seconds() > block_minutes * 60:
            if len(current_seq) >= 2:
                sequences.append(current_seq)
            current_seq = []

        # Deduplicate consecutive same-app entries
        if not current_seq or current_seq[-1] != app:
            current_seq.append(app)
        last_ts = ts

    if len(current_seq) >= 2:
        sequences.append(current_seq)

    return sequences


def _to_pm4py_log(events: list[dict]):
    """Convert AW events to a PM4Py-compatible DataFrame."""
    try:
        import pandas as pd

        rows = []
        for i, e in enumerate(events):
            rows.append({
                "case:concept:name": f"session_{i // 50}",  # Group by ~50 events
                "concept:name": e.get("app", "unknown"),
                "time:timestamp": e.get("timestamp", ""),
            })
        if not rows:
            return None
        df = pd.DataFrame(rows)
        df["time:timestamp"] = pd.to_datetime(df["time:timestamp"], utc=True, errors="coerce")
        df = df.dropna(subset=["time:timestamp"])
        return df if len(df) > 0 else None
    except ImportError:
        log.debug("pandas not installed — skipping PM4Py log conversion")
        return None


# ---------------------------------------------------------------------------
# Stage 3: PROPOSE — Generate automation proposals via Alfred or Robin
# ---------------------------------------------------------------------------

def generate_proposals(
    patterns: list[dict],
    use_alfred: bool = True,
) -> list[dict]:
    """Generate automation proposals from discovered patterns.

    Intelligence hierarchy:
        1. Alfred (Claude) — if use_alfred=True and a Cowork session is active
        2. Robin (Ollama) — local fallback, always available

    Returns list of proposal dicts:
        {id, pattern, automation, priority, status}
    """
    if not patterns:
        return []

    # Format patterns for the LLM
    pattern_summary = "\n".join(
        f"- [{p['type']}] {p['description']} (freq={p.get('frequency', '?')}, conf={p.get('confidence', '?'):.1%})"
        for p in patterns[:15]  # Top 15 patterns
    )

    prompt = f"""You are Sentinel, the Batcave's learning engine. You've observed these behavioral patterns
from the user's computer activity over the past week:

{pattern_summary}

The Batcave System has these execution capabilities:
- Robin can manage files, run scripts, send emails, check schedules, automate web tasks
- n8n workflows can be created for recurring automation
- Scheduled tasks can run PowerShell/Python at specific times
- Chrome automation can interact with web services

Based on these patterns, propose 1-3 specific, actionable automations that would save the user
time or reduce friction. For each proposal, specify:
1. What it automates (be specific)
2. How Robin would execute it (which tools/skills)
3. When it should trigger (time-based, event-based, or pattern-based)
4. How to measure if it helped (what metric changes)

Respond in JSON format:
[{{"automation": "...", "execution_plan": "...", "trigger": "...", "success_metric": "...", "priority": "high|medium|low"}}]

Only propose automations that are clearly beneficial and low-risk. Never propose anything
that could delete data, send messages without confirmation, or make purchases."""

    proposals = []

    # Try Alfred first (most intelligent actor)
    if use_alfred:
        proposals = _propose_via_alfred(prompt)

    # Fall back to Robin (Ollama) if Alfred unavailable
    if not proposals:
        proposals = _propose_via_ollama(prompt)

    # Stamp proposals with metadata
    timestamped = []
    for i, p in enumerate(proposals):
        p["id"] = f"SP-{datetime.now().strftime('%Y%m%d')}-{i+1:03d}"
        p["source_patterns"] = [pat.get("description", "") for pat in patterns[:3]]
        p["generated_by"] = "alfred" if use_alfred and proposals else "robin"
        p["generated_at"] = datetime.now().isoformat()
        p["status"] = "proposed"
        timestamped.append(p)

    # Save proposals
    existing = _load_json(PROPOSALS_FILE, [])
    existing.extend(timestamped)
    # Keep last 100 proposals
    PROPOSALS_FILE.write_text(
        json.dumps(existing[-100:], indent=2, default=str),
        encoding="utf-8",
    )

    # Write actionable proposals to Robin's inbox
    for p in timestamped:
        if p.get("priority") in ("high", "medium"):
            _write_to_robin_inbox(p)

    log.info(f"Generated {len(timestamped)} automation proposals")
    return timestamped


def _propose_via_alfred(prompt: str) -> list[dict]:
    """Generate proposals using Alfred (Claude) if available.

    Checks if a Cowork session or Claude CLI is accessible.
    Returns [] if Alfred is not available.
    """
    # In a Cowork session, Alfred IS the current context — proposals
    # are generated inline. This function is for Robin-driven Sentinel
    # cycles where we check if Alfred is reachable via CLI.
    try:
        import subprocess
        result = subprocess.run(
            ["claude", "-p", prompt, "--output-format", "json"],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0 and result.stdout.strip():
            # Parse Claude's response for JSON
            return _extract_json_proposals(result.stdout)
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        log.debug(f"Alfred not available via CLI: {exc}")
    return []


def _propose_via_ollama(prompt: str) -> list[dict]:
    """Generate proposals using Robin (Ollama) as fallback."""
    try:
        import urllib.request

        ollama_url = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        model = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")

        payload = json.dumps({
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.3, "num_predict": 1024},
        }).encode()

        req = urllib.request.Request(
            f"{ollama_url}/api/generate",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read())
        response_text = result.get("response", "")
        return _extract_json_proposals(response_text)

    except (OSError, json.JSONDecodeError, KeyError) as exc:
        log.warning(f"Ollama proposal generation failed: {exc}")
    return []


def _extract_json_proposals(text: str) -> list[dict]:
    """Extract JSON proposals from LLM response text."""
    # Try direct parse first
    try:
        parsed = json.loads(text)
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "result" in parsed:
            return json.loads(parsed["result"]) if isinstance(parsed["result"], str) else parsed["result"]
    except (json.JSONDecodeError, TypeError):
        pass

    # Try to find JSON array in the text
    import re
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass

    return []


# ---------------------------------------------------------------------------
# Stage 4: EXECUTE — Route proposals to Robin's inbox
# ---------------------------------------------------------------------------

def _write_to_robin_inbox(proposal: dict) -> None:
    """Write an automation proposal to Robin's inbox for execution."""
    ROBIN_INBOX_V2.mkdir(parents=True, exist_ok=True)
    filename = f"sentinel-proposal-{proposal.get('id', 'unknown')}.json"
    filepath = ROBIN_INBOX_V2 / filename
    message = {
        "type": "automation-proposal",
        "from": "sentinel",
        "priority": proposal.get("priority", "medium"),
        "proposal": proposal,
        "instruction": (
            f"Sentinel has proposed an automation: {proposal.get('automation', 'N/A')}. "
            f"Execution plan: {proposal.get('execution_plan', 'N/A')}. "
            f"Trigger: {proposal.get('trigger', 'N/A')}. "
            "Please evaluate feasibility and implement if appropriate."
        ),
        "created_at": datetime.now().isoformat(),
    }
    filepath.write_text(json.dumps(message, indent=2), encoding="utf-8")
    log.info(f"Wrote proposal {proposal.get('id')} to Robin's inbox")


# ---------------------------------------------------------------------------
# Stage 5: MEASURE — Track automation effectiveness
# ---------------------------------------------------------------------------

def measure_effectiveness(proposal_id: str, events_after: list[dict]) -> dict:
    """Measure whether a deployed automation reduced manual user effort.

    Compares user behavior after automation deployment against the
    baseline pattern that triggered the proposal.

    Returns effectiveness dict:
        {proposal_id, manual_frequency_before, manual_frequency_after, reduction_pct, verdict}
    """
    proposals = _load_json(PROPOSALS_FILE, [])
    proposal = next((p for p in proposals if p.get("id") == proposal_id), None)
    if not proposal:
        return {"proposal_id": proposal_id, "verdict": "not_found"}

    # Simple heuristic: check if the pattern's app/activity frequency decreased
    source_patterns = proposal.get("source_patterns", [])
    # This is a placeholder — real measurement would compare specific
    # activity frequencies before vs after deployment
    result = {
        "proposal_id": proposal_id,
        "measured_at": datetime.now().isoformat(),
        "events_analyzed": len(events_after),
        "verdict": "pending_data",  # Needs baseline comparison
        "note": "Measurement requires before/after event comparison — collecting baseline",
    }

    # Append to effectiveness log
    log_entries = _load_json(EFFECTIVENESS_FILE, [])
    log_entries.append(result)
    EFFECTIVENESS_FILE.write_text(
        json.dumps(log_entries[-50:], indent=2, default=str),
        encoding="utf-8",
    )
    return result


# ---------------------------------------------------------------------------
# Main entry point — called by Sentinel's scan cycle
# ---------------------------------------------------------------------------

def run_learning_cycle(
    max_runtime_secs: float = 25.0,
    use_alfred: bool = True,
) -> dict:
    """Run one iteration of the learning loop.

    Called by Sentinel._scan_behavioral_patterns() during its 15-min cycle.
    Designed to be fast — heavy analysis (PM4Py) only runs every 6 hours.

    Args:
        max_runtime_secs: Hard cap on execution time
        use_alfred: Whether to try Alfred for proposals (True in Cowork sessions)

    Returns:
        Summary dict with counts and timing
    """
    start = time.time()
    summary = {"phase": "learning_cycle", "started_at": datetime.now().isoformat()}

    # Check if heavy analysis is due (every 6 hours)
    state = _load_json(LEARNING_DIR / "cycle-state.json", {})
    last_full = state.get("last_full_analysis", "")
    hours_since_full = 999
    if last_full:
        try:
            delta = datetime.now() - datetime.fromisoformat(last_full)
            hours_since_full = delta.total_seconds() / 3600
        except (ValueError, TypeError):
            pass

    do_full = hours_since_full >= 6

    # Stage 1: Observe (always — quick AW API call)
    events = fetch_aw_events(hours=OBSERVATION_WINDOW_HOURS if do_full else 24)
    summary["events_fetched"] = len(events)

    if time.time() - start > max_runtime_secs:
        summary["aborted"] = "timeout_after_observe"
        return summary

    if not events:
        summary["result"] = "no_events_available"
        return summary

    # Stage 2: Discover patterns (full analysis every 6h, quick check otherwise)
    if do_full:
        patterns = discover_patterns(events)
        state["last_full_analysis"] = datetime.now().isoformat()
        (LEARNING_DIR / "cycle-state.json").write_text(
            json.dumps(state, indent=2), encoding="utf-8",
        )
    else:
        # Use cached patterns from last full analysis
        patterns = _load_json(PATTERNS_FILE, [])

    summary["patterns_discovered"] = len(patterns)

    if time.time() - start > max_runtime_secs:
        summary["aborted"] = "timeout_after_discover"
        return summary

    # Stage 3: Propose automations (only on full analysis cycles)
    if do_full and patterns:
        proposals = generate_proposals(patterns, use_alfred=use_alfred)
        summary["proposals_generated"] = len(proposals)
    else:
        summary["proposals_generated"] = 0
        summary["note"] = "Quick cycle — using cached patterns, no new proposals"

    summary["runtime_secs"] = round(time.time() - start, 2)
    summary["full_analysis"] = do_full
    return summary


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_json(path: Path, default):
    """Load JSON from file, returning default on any error."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return default
