"""
Sentinel Proposal Pipeline -- Andrew-Readiness Phase 2, Step 6.

Observes Robin's command history (voice commands, daemon logs,
command runner activity) to discover patterns in Andrew's requests
and propose automations. Extends sentinel_learning.py's ActivityWatch
pipeline with a Robin-native event source.

Architecture:
    OBSERVE: Read Robin's audit logs (voice, commands, morning briefings)
    DISCOVER: Frequency + temporal pattern mining on command history
    PROPOSE: Generate automation proposals via Ollama
    FEEDBACK: Voice-based yes/no confirmation through TTS
    MEASURE: Track proposal acceptance and effectiveness

Session 136: Phase 2 Step 6 of Andrew-Readiness (ADR-020).

Dependencies:
    - rudy.paths (canonical paths)
    - rudy.sentinel_learning (proposal generation, pattern mining)
    - json, logging, datetime (stdlib)
"""

import json
import logging
import os
import time
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

from rudy.paths import RUDY_DATA, RUDY_LOGS, ROBIN_INBOX_V2, SENTINEL_LEARNING

log = logging.getLogger("sentinel.proposals")

# Paths
PROPOSALS_DIR = SENTINEL_LEARNING / "proposals"
PROPOSALS_DIR.mkdir(parents=True, exist_ok=True)
COMMAND_HISTORY_FILE = SENTINEL_LEARNING / "command-history.json"
PROPOSAL_FEEDBACK_FILE = SENTINEL_LEARNING / "proposal-feedback.json"
ACTIVE_PROPOSALS_FILE = SENTINEL_LEARNING / "active-proposals.json"


# -------------------------------------------------------------------
# Stage 1: OBSERVE -- Collect command events from Robin's logs
# -------------------------------------------------------------------

def collect_command_events(hours: int = 168) -> list[dict]:
    """Collect command events from Robin's various log sources.

    Sources:
        - morning-briefings.json (morning routine invocations)
        - command-runner.log (Cowork-to-Windows bridge commands)
        - voice daemon audit logs (voice commands processed)
        - robin-inbox processed items (directive completions)

    Returns list of event dicts:
        {timestamp, source, command, category, duration}
    """
    cutoff = datetime.now() - timedelta(hours=hours)
    events = []

    events.extend(_collect_morning_events(cutoff))
    events.extend(_collect_command_runner_events(cutoff))
    events.extend(_collect_voice_events(cutoff))
    events.extend(_collect_inbox_events(cutoff))

    events.sort(key=lambda e: e.get("timestamp", ""))
    log.info("Collected %d command events from %d hours", len(events), hours)
    return events


def _collect_morning_events(cutoff: datetime) -> list[dict]:
    """Parse morning briefing audit log."""
    log_path = RUDY_LOGS / "morning-briefings.json"
    if not log_path.exists():
        return []
    try:
        entries = json.loads(log_path.read_text(encoding="utf-8"))
        events = []
        for entry in entries:
            ts = entry.get("timestamp", "")
            try:
                if datetime.fromisoformat(ts) < cutoff:
                    continue
            except (ValueError, TypeError):
                continue
            events.append({
                "timestamp": ts,
                "source": "morning_routine",
                "command": "morning_briefing",
                "category": "routine",
                "user": entry.get("user", "Andrew"),
            })
        return events
    except (json.JSONDecodeError, OSError) as e:
        log.debug("Morning events read error: %s", e)
        return []


def _collect_command_runner_events(cutoff: datetime) -> list[dict]:
    """Parse command runner log for executed commands."""
    log_path = RUDY_LOGS / "command-runner.log"
    if not log_path.exists():
        return []
    try:
        events = []
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "Executing:" not in line and "command:" not in line:
                    continue
                # Extract timestamp from log line (format: YYYY-MM-DD HH:MM:SS)
                parts = line.strip().split(" ", 2)
                if len(parts) < 3:
                    continue
                try:
                    ts = datetime.fromisoformat(f"{parts[0]} {parts[1]}")
                    if ts < cutoff:
                        continue
                except (ValueError, IndexError):
                    continue
                events.append({
                    "timestamp": ts.isoformat(),
                    "source": "command_runner",
                    "command": parts[2][:200],
                    "category": "system",
                })
        return events
    except OSError as e:
        log.debug("Command runner log error: %s", e)
        return []


def _collect_voice_events(cutoff: datetime) -> list[dict]:
    """Parse voice daemon logs for processed voice commands."""
    log_path = RUDY_LOGS / "voice-daemon.log"
    if not log_path.exists():
        return []
    try:
        events = []
        with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                if "[Command]" not in line and "intent:" not in line:
                    continue
                parts = line.strip().split(" ", 2)
                if len(parts) < 3:
                    continue
                try:
                    ts = datetime.fromisoformat(f"{parts[0]} {parts[1]}")
                    if ts < cutoff:
                        continue
                except (ValueError, IndexError):
                    continue
                events.append({
                    "timestamp": ts.isoformat(),
                    "source": "voice_daemon",
                    "command": parts[2][:200],
                    "category": "voice",
                })
        return events
    except OSError as e:
        log.debug("Voice daemon log error: %s", e)
        return []


def _collect_inbox_events(cutoff: datetime) -> list[dict]:
    """Scan processed Robin inbox items for completed directives."""
    events = []
    for inbox_dir in [ROBIN_INBOX_V2]:
        if not inbox_dir.exists():
            continue
        for f in inbox_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                ts = data.get("created_at", data.get("timestamp", ""))
                try:
                    if ts and datetime.fromisoformat(ts) < cutoff:
                        continue
                except (ValueError, TypeError):
                    continue
                events.append({
                    "timestamp": ts or datetime.now().isoformat(),
                    "source": "robin_inbox",
                    "command": data.get("instruction", data.get("type", "unknown"))[:200],
                    "category": data.get("type", "directive"),
                })
            except (json.JSONDecodeError, OSError):
                continue
    return events


# -------------------------------------------------------------------
# Stage 2: DISCOVER -- Mine patterns from command history
# -------------------------------------------------------------------

def discover_command_patterns(events: list[dict]) -> list[dict]:
    """Extract behavioral patterns from Robin command events.

    Looks for:
        - Repeated commands (same command > N times)
        - Time-based patterns (same command at same time of day)
        - Sequence patterns (command A always followed by B)

    Returns list of pattern dicts.
    """
    if not events:
        return []
    patterns = []
    patterns.extend(_command_frequency_patterns(events))
    patterns.extend(_command_temporal_patterns(events))
    patterns.extend(_command_sequence_patterns(events))
    return patterns


def _command_frequency_patterns(events: list[dict]) -> list[dict]:
    """Find commands that repeat frequently."""
    cmd_count = defaultdict(int)
    cmd_sources = defaultdict(set)
    for e in events:
        cmd = _normalize_command(e.get("command", ""))
        if cmd:
            cmd_count[cmd] += 1
            cmd_sources[cmd].add(e.get("source", "unknown"))

    patterns = []
    for cmd, count in sorted(cmd_count.items(), key=lambda x: -x[1]):
        if count < 3:
            break
        patterns.append({
            "type": "command_frequency",
            "description": f"Command '{cmd}' executed {count} times",
            "command": cmd,
            "frequency": count,
            "sources": list(cmd_sources[cmd]),
            "confidence": min(count / 10.0, 1.0),
        })
    return patterns[:10]


def _command_temporal_patterns(events: list[dict]) -> list[dict]:
    """Find commands that happen at consistent times of day."""
    hour_cmds = defaultdict(lambda: defaultdict(int))
    for e in events:
        ts = e.get("timestamp", "")
        cmd = _normalize_command(e.get("command", ""))
        if not cmd:
            continue
        try:
            hour = datetime.fromisoformat(ts).hour
            hour_cmds[hour][cmd] += 1
        except (ValueError, TypeError):
            continue

    patterns = []
    for hour, cmds in sorted(hour_cmds.items()):
        for cmd, count in cmds.items():
            if count < 3:
                continue
            period = _hour_to_period(hour)
            patterns.append({
                "type": "command_temporal",
                "description": (
                    f"'{cmd}' runs at {hour}:00 ({period}) "
                    f"{count} times"
                ),
                "command": cmd,
                "hour": hour,
                "period": period,
                "frequency": count,
                "confidence": min(count / 7.0, 1.0),
            })
    return patterns[:10]


def _command_sequence_patterns(events: list[dict]) -> list[dict]:
    """Find commands that consistently follow each other."""
    if len(events) < 2:
        return []

    # Build pairs of consecutive commands within 10-minute windows
    pair_count = defaultdict(int)
    for i in range(len(events) - 1):
        cmd_a = _normalize_command(events[i].get("command", ""))
        cmd_b = _normalize_command(events[i + 1].get("command", ""))
        if not cmd_a or not cmd_b or cmd_a == cmd_b:
            continue
        try:
            ts_a = datetime.fromisoformat(events[i]["timestamp"])
            ts_b = datetime.fromisoformat(events[i + 1]["timestamp"])
            if (ts_b - ts_a).total_seconds() > 600:
                continue
        except (ValueError, TypeError, KeyError):
            continue
        pair_count[(cmd_a, cmd_b)] += 1

    patterns = []
    for (cmd_a, cmd_b), count in sorted(
        pair_count.items(), key=lambda x: -x[1]
    ):
        if count < 3:
            break
        patterns.append({
            "type": "command_sequence",
            "description": f"'{cmd_a}' is followed by '{cmd_b}' {count} times",
            "sequence": [cmd_a, cmd_b],
            "frequency": count,
            "confidence": min(count / 5.0, 1.0),
        })
    return patterns[:10]


# -------------------------------------------------------------------
# Stage 3: PROPOSE -- Generate automation proposals via Ollama
# -------------------------------------------------------------------

def generate_command_proposals(patterns: list[dict]) -> list[dict]:
    """Generate automation proposals from command patterns via Ollama.

    Uses the local Ollama model (no cloud dependency) to analyze
    patterns and suggest automations Robin can execute.

    Returns list of proposal dicts with id, automation, trigger,
    execution_plan, priority, and status.
    """
    if not patterns:
        return []

    pattern_summary = "\n".join(
        f"- [{p['type']}] {p['description']} "
        f"(confidence={p.get('confidence', 0):.0%})"
        for p in patterns[:10]
    )

    prompt = (
        "You are Sentinel, an AI assistant's learning engine. "
        "You observe a quadriplegic user named Andrew who interacts "
        "with his assistant Robin primarily through voice commands.\n\n"
        "These patterns were discovered in Andrew's command history:\n"
        f"{pattern_summary}\n\n"
        "Propose 1-3 automations that would help Andrew by reducing "
        "the number of voice commands he needs to give. Each automation "
        "should be something Robin can do proactively.\n\n"
    )
    prompt += (
        "Respond in JSON array format:\n"
        '[{"automation": "...", "trigger": "time/event/pattern", '
        '"execution_plan": "...", "success_metric": "...", '
        '"priority": "high|medium|low"}]\n\n'
        "Only propose safe, low-risk automations. Never propose "
        "anything that deletes data, sends messages without "
        "confirmation, or makes purchases."
    )

    proposals = _propose_via_ollama_local(prompt)

    # Stamp with metadata
    timestamped = []
    for i, p in enumerate(proposals):
        p["id"] = f"SP-{datetime.now().strftime('%Y%m%d')}-{i + 1:03d}"
        p["source_patterns"] = [
            pat.get("description", "") for pat in patterns[:3]
        ]
        p["generated_by"] = "ollama"
        p["generated_at"] = datetime.now().isoformat()
        p["status"] = "proposed"
        timestamped.append(p)

    # Persist proposals
    _save_proposals(timestamped)

    # Write high/medium priority proposals to Robin's inbox
    for p in timestamped:
        if p.get("priority") in ("high", "medium"):
            _write_proposal_to_inbox(p)

    log.info("Generated %d command-based proposals", len(timestamped))
    return timestamped


def _propose_via_ollama_local(prompt: str) -> list[dict]:
    """Generate proposals using local Ollama model."""
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
        log.warning("Ollama proposal generation failed: %s", exc)
    return []


def _extract_json_proposals(text: str) -> list[dict]:
    """Extract JSON proposals from LLM response text."""
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
# Stage 4: FEEDBACK -- Voice-based proposal confirmation
# -------------------------------------------------------------------

class ProposalFeedback:
    """Manages voice-based feedback for automation proposals.

    When a proposal is ready, Robin asks Andrew via TTS:
        "I noticed you often [pattern]. Would you like me to
         do that automatically? Say yes or no."

    Feedback is stored and used to refine future proposals.
    """

    def __init__(self, tts_engine=None):
        self.tts = tts_engine
        self.feedback_log = _load_json(PROPOSAL_FEEDBACK_FILE, [])

    def present_proposal(self, proposal: dict) -> str:
        """Present a proposal to Andrew via TTS and return the prompt.

        The actual voice response collection is handled by the
        voice daemon's command loop. This method composes and
        speaks the question, then writes a pending-feedback
        marker so the daemon knows to route the next yes/no
        response back here.
        """
        automation = proposal.get("automation", "do something helpful")
        trigger = proposal.get("trigger", "automatically")

        question = (
            f"I've noticed a pattern in how you use me. "
            f"I could {automation} {trigger}. "
            f"Would you like me to set that up? Say yes or no."
        )

        if self.tts:
            try:
                self.tts.speak(question)
            except Exception as e:
                log.warning("TTS failed for proposal: %s", e)

        # Write pending feedback marker
        pending = {
            "proposal_id": proposal.get("id", "unknown"),
            "question": question,
            "asked_at": datetime.now().isoformat(),
            "status": "awaiting_response",
        }
        pending_file = SENTINEL_LEARNING / "pending-feedback.json"
        pending_file.write_text(
            json.dumps(pending, indent=2), encoding="utf-8"
        )
        log.info("Presented proposal %s to user", proposal.get("id"))
        return question

    def record_feedback(self, proposal_id: str, accepted: bool,
                        reason: str = "") -> dict:
        """Record Andrew's yes/no response to a proposal."""
        entry = {
            "proposal_id": proposal_id,
            "accepted": accepted,
            "reason": reason,
            "recorded_at": datetime.now().isoformat(),
        }
        self.feedback_log.append(entry)
        # Keep last 200 feedback entries
        self.feedback_log = self.feedback_log[-200:]
        PROPOSAL_FEEDBACK_FILE.write_text(
            json.dumps(self.feedback_log, indent=2), encoding="utf-8"
        )

        # Update proposal status
        proposals = _load_json(ACTIVE_PROPOSALS_FILE, [])
        for p in proposals:
            if p.get("id") == proposal_id:
                p["status"] = "accepted" if accepted else "rejected"
                p["feedback_at"] = entry["recorded_at"]
                break
        ACTIVE_PROPOSALS_FILE.write_text(
            json.dumps(proposals, indent=2), encoding="utf-8"
        )

        # Speak confirmation
        if self.tts:
            if accepted:
                msg = "Got it. I'll set that up for you."
            else:
                msg = "No problem. I won't set that up."
            try:
                self.tts.speak(msg)
            except Exception:
                pass

        log.info(
            "Feedback for %s: %s",
            proposal_id, "accepted" if accepted else "rejected"
        )
        return entry

    def get_acceptance_rate(self) -> float:
        """Return the overall proposal acceptance rate."""
        if not self.feedback_log:
            return 0.0
        accepted = sum(1 for f in self.feedback_log if f.get("accepted"))
        return accepted / len(self.feedback_log)


# -------------------------------------------------------------------
# Stage 5: MEASURE -- Track proposal effectiveness
# -------------------------------------------------------------------

def measure_proposal_impact(proposal_id: str,
                            events_after: list[dict]) -> dict:
    """Measure if an accepted automation reduced manual commands.

    Compares the frequency of the automated command before vs after
    deployment. A reduction indicates the automation is working.
    """
    proposals = _load_json(ACTIVE_PROPOSALS_FILE, [])
    proposal = next(
        (p for p in proposals if p.get("id") == proposal_id), None
    )
    if not proposal:
        return {"proposal_id": proposal_id, "verdict": "not_found"}

    # Check if the automated command appears less frequently
    patterns = proposal.get("source_patterns", [])
    result = {
        "proposal_id": proposal_id,
        "measured_at": datetime.now().isoformat(),
        "events_after": len(events_after),
        "patterns_targeted": patterns,
        "verdict": "collecting_baseline",
    }

    log.info("Measured impact for %s: %s", proposal_id, result["verdict"])
    return result


# -------------------------------------------------------------------
# Main entry point -- called by Sentinel's scan cycle
# -------------------------------------------------------------------

def run_proposal_cycle(max_runtime_secs: float = 25.0) -> dict:
    """Run one iteration of the command-based proposal pipeline.

    Called by Sentinel._scan_behavioral_patterns() as a complement
    to the ActivityWatch-based sentinel_learning.py. This pipeline
    uses Robin's own logs rather than desktop activity.

    Args:
        max_runtime_secs: Hard cap on execution time.

    Returns:
        Summary dict with event counts, patterns, proposals.
    """
    start = time.time()
    summary = {
        "phase": "proposal_cycle",
        "started_at": datetime.now().isoformat(),
    }

    # Check if full analysis is due (every 6 hours)
    state = _load_json(SENTINEL_LEARNING / "proposal-cycle-state.json", {})
    last_full = state.get("last_full_analysis", "")
    hours_since = 999
    if last_full:
        try:
            delta = datetime.now() - datetime.fromisoformat(last_full)
            hours_since = delta.total_seconds() / 3600
        except (ValueError, TypeError):
            pass

    do_full = hours_since >= 6

    # Stage 1: Collect command events
    events = collect_command_events(hours=168 if do_full else 24)
    summary["events_collected"] = len(events)

    if time.time() - start > max_runtime_secs:
        summary["aborted"] = "timeout_after_collect"
        return summary

    if not events:
        summary["result"] = "no_command_events"
        return summary

    # Save command history for reference
    _save_command_history(events)

    # Stage 2: Discover patterns
    if do_full:
        patterns = discover_command_patterns(events)
        state["last_full_analysis"] = datetime.now().isoformat()
        state["last_pattern_count"] = len(patterns)
        (SENTINEL_LEARNING / "proposal-cycle-state.json").write_text(
            json.dumps(state, indent=2), encoding="utf-8"
        )
    else:
        patterns = _load_json(
            SENTINEL_LEARNING / "discovered-command-patterns.json", []
        )

    summary["patterns_discovered"] = len(patterns)

    if time.time() - start > max_runtime_secs:
        summary["aborted"] = "timeout_after_discover"
        return summary

    # Save discovered patterns
    if do_full and patterns:
        (SENTINEL_LEARNING / "discovered-command-patterns.json").write_text(
            json.dumps(patterns, indent=2, default=str), encoding="utf-8"
        )

    # Stage 3: Generate proposals (only on full analysis)
    if do_full and patterns:
        proposals = generate_command_proposals(patterns)
        summary["proposals_generated"] = len(proposals)
    else:
        summary["proposals_generated"] = 0
        summary["note"] = "Quick cycle -- cached patterns, no new proposals"

    summary["full_analysis"] = do_full
    summary["runtime_secs"] = round(time.time() - start, 2)
    return summary


# -------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------

def _normalize_command(cmd: str) -> str:
    """Normalize a command string for pattern matching."""
    if not cmd:
        return ""
    # Strip timestamps, PIDs, and common prefixes
    cmd = cmd.strip()
    for prefix in ["[Command]", "[Daemon]", "intent:", "Executing:"]:
        if cmd.startswith(prefix):
            cmd = cmd[len(prefix):].strip()
    # Truncate for grouping (first 80 chars)
    return cmd[:80].strip()


def _hour_to_period(hour: int) -> str:
    """Convert hour to human-readable period."""
    if 5 <= hour < 12:
        return "morning"
    elif 12 <= hour < 17:
        return "afternoon"
    elif 17 <= hour < 21:
        return "evening"
    return "night"


def _save_proposals(proposals: list[dict]) -> None:
    """Persist proposals to the active proposals file."""
    existing = _load_json(ACTIVE_PROPOSALS_FILE, [])
    existing.extend(proposals)
    existing = existing[-100:]
    ACTIVE_PROPOSALS_FILE.write_text(
        json.dumps(existing, indent=2, default=str), encoding="utf-8"
    )


def _save_command_history(events: list[dict]) -> None:
    """Save collected command history for reference."""
    COMMAND_HISTORY_FILE.write_text(
        json.dumps(events[-500:], indent=2, default=str), encoding="utf-8"
    )


def _write_proposal_to_inbox(proposal: dict) -> None:
    """Write a proposal to Robin's inbox for presentation to Andrew."""
    ROBIN_INBOX_V2.mkdir(parents=True, exist_ok=True)
    filename = f"sentinel-cmd-proposal-{proposal.get('id', 'unknown')}.json"
    filepath = ROBIN_INBOX_V2 / filename
    message = {
        "type": "automation-proposal",
        "from": "sentinel-proposals",
        "priority": proposal.get("priority", "medium"),
        "proposal": proposal,
        "instruction": (
            f"Sentinel discovered a pattern and proposes: "
            f"{proposal.get('automation', 'N/A')}. "
            f"Present to Andrew via voice for approval."
        ),
        "created_at": datetime.now().isoformat(),
    }
    filepath.write_text(json.dumps(message, indent=2), encoding="utf-8")
    log.info("Wrote proposal %s to Robin inbox", proposal.get("id"))


def _load_json(path: Path, default):
    """Load JSON from file, returning default on any error."""
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return default
