#!/usr/bin/env python3
"""
Batcave Shared Memory System - Compounding knowledge across sessions.

This is the Batcave's institutional memory. Both Alfred (cloud-side) and
Robin (local-side) read from and write to this system, so that learnings
from one session carry forward to the next.

Categories of Knowledge:
    technical    -- MCP quirks, encoding issues, file transfer methods
    workflow     -- What processes work, what doesnt
    coordination -- Alfred-Robin protocol learnings
    architecture -- Design decisions and their rationale
    oracle       -- Oracle system knowledge (paths, services, config)
    debugging    -- Known failure modes and their fixes

Usage:
    from rudy.batcave_memory import BatcaveMemory
    mem = BatcaveMemory()
    mem.add_learning("technical", "PowerShell UTF8 adds BOM",
                     "Use -Encoding UTF8 then strip BOM with Python",
                     source="alfred", confidence="proven")
    relevant = mem.recall("file transfer")
"""

import json
import logging
import os

from datetime import datetime
from pathlib import Path

log = logging.getLogger("batcave_memory")

HOME = Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
DESKTOP = HOME / "Desktop"
RUDY_DATA = DESKTOP / "rudy-data"
MEMORY_DIR = RUDY_DATA / "batcave-memory"
LEARNINGS_FILE = MEMORY_DIR / "learnings.json"
BATCAVE_MD = MEMORY_DIR / "BATCAVE.md"
SESSION_DIR = MEMORY_DIR / "session-logs"

for d in [MEMORY_DIR, SESSION_DIR]:
    d.mkdir(parents=True, exist_ok=True)

class BatcaveMemory:
    """
    Shared memory system for the Batcave.
    Thread-safe for single-writer scenarios (Robin or Alfred).
    """

    CATEGORIES = [
        "technical", "workflow", "coordination",
        "architecture", "oracle", "debugging",
    ]

    CONFIDENCE_LEVELS = [
        "hypothesis",   # Untested idea
        "observed",     # Seen once
        "confirmed",    # Seen multiple times
        "proven",       # Verified and relied upon
        "deprecated",   # Was true, no longer applies
    ]

    def __init__(self):
        self.learnings = self._load_learnings()

    def _load_learnings(self):
        if LEARNINGS_FILE.exists():
            try:
                with open(LEARNINGS_FILE) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save_learnings(self):
        with open(LEARNINGS_FILE, "w") as f:
            json.dump(self.learnings, f, indent=2)

    def add_learning(self, category, title, detail,
                     source="unknown", confidence="observed",
                     tags=None, session=None):
        """Add a new learning to the shared memory."""
        if category not in self.CATEGORIES:
            log.warning("Unknown category: %s", category)

        # Check for duplicates (same title, same category)
        for existing in self.learnings:
            if (existing.get("title", "").lower() == title.lower()
                    and existing.get("category") == category):
                existing["detail"] = detail
                existing["confidence"] = confidence
                existing["updated_at"] = datetime.now().isoformat()
                existing["updated_by"] = source
                existing.setdefault("seen_count", 1)
                existing["seen_count"] += 1
                self._save_learnings()
                log.info("[Memory] Updated: [%s] %s (seen %dx)",
                         category, title, existing["seen_count"])
                return existing

        entry = {
            "id": len(self.learnings) + 1,
            "category": category,
            "title": title,
            "detail": detail,
            "source": source,
            "confidence": confidence,
            "tags": tags or [],
            "session": session,
            "created_at": datetime.now().isoformat(),
            "seen_count": 1,
        }
        self.learnings.append(entry)
        self._save_learnings()
        log.info("[Memory] New: [%s] %s", category, title)
        return entry

    def recall(self, query, category=None, limit=10):
        """Search learnings by keyword or category."""
        query_lower = query.lower()
        results = []
        for entry in self.learnings:
            if category and entry.get("category") != category:
                continue
            score = 0
            if query_lower in entry.get("title", "").lower():
                score += 10
            if query_lower in entry.get("detail", "").lower():
                score += 5
            for tag in entry.get("tags", []):
                if query_lower in tag.lower():
                    score += 7
            conf_boost = {
                "proven": 3, "confirmed": 2,
                "observed": 1, "hypothesis": 0,
                "deprecated": -5,
            }
            score += conf_boost.get(
                entry.get("confidence", ""), 0)
            if score > 0:
                results.append((score, entry))
        results.sort(key=lambda x: -x[0])
        return [e for _, e in results[:limit]]

    def get_by_category(self, category):
        """Get all learnings in a category."""
        return [e for e in self.learnings
                if e.get("category") == category
                and e.get("confidence") != "deprecated"]

    def promote_confidence(self, learning_id, new_confidence):
        """Upgrade confidence level of a learning."""
        for entry in self.learnings:
            if entry.get("id") == learning_id:
                old = entry.get("confidence")
                entry["confidence"] = new_confidence
                entry["updated_at"] = datetime.now().isoformat()
                self._save_learnings()
                log.info("[Memory] Promoted #%d: %s -> %s",
                         learning_id, old, new_confidence)
                return entry
        return None

    def write_session_summary(self, session_num, summary):
        """Write a session summary to the session-logs directory."""
        path = SESSION_DIR / ("session-%03d.json" % session_num)
        summary["session"] = session_num
        summary["timestamp"] = datetime.now().isoformat()
        with open(path, "w") as f:
            json.dump(summary, f, indent=2)
        log.info("[Memory] Session %d summary written", session_num)
        return path

    def generate_batcave_md(self):
        """Regenerate human-readable BATCAVE.md from learnings."""
        lines = [
            "# BATCAVE.md - Shared Intelligence Memory",
            "",
            "This file is auto-generated from the learnings database.",
            "Both Alfred and Robin read this at session start.",
            "Last updated: %s" % datetime.now().isoformat(),
            "",
        ]
        for cat in self.CATEGORIES:
            entries = self.get_by_category(cat)
            if not entries:
                continue
            lines.append("## %s" % cat.replace("_", " ").title())
            lines.append("")
            conf_order = {
                "proven": 0, "confirmed": 1,
                "observed": 2, "hypothesis": 3,
            }
            entries.sort(key=lambda e: (
                conf_order.get(e.get("confidence", ""), 9),
                -e.get("seen_count", 1),
            ))
            for e in entries:
                conf = e.get("confidence", "?")
                lines.append(
                    "- **[%s]** %s" % (conf.upper(), e["title"]))
                lines.append("  %s" % e["detail"])
                if e.get("tags"):
                    lines.append(
                        "  _Tags: %s_" % ", ".join(e["tags"]))
                lines.append("")
            lines.append("")
        sessions = sorted(SESSION_DIR.glob("session-*.json"))
        if sessions:
            lines.append("## Session History")
            lines.append("")
            for sp in sessions[-10:]:
                try:
                    with open(sp) as f:
                        s = json.load(f)
                    lines.append(
                        "### Session %d (%s)" % (
                            s.get("session", "?"),
                            s.get("timestamp", "?")[:10]))
                    for obj in s.get("completed", []):
                        lines.append("- %s" % obj)
                    lines.append("")
                except Exception:
                    continue
        content = "\n".join(lines)
        BATCAVE_MD.write_text(content)
        log.info("[Memory] BATCAVE.md regenerated (%d lines)",
                 len(lines))
        return content

    def stats(self):
        """Return memory statistics."""
        by_cat = {}
        by_conf = {}
        by_source = {}
        for e in self.learnings:
            cat = e.get("category", "unknown")
            by_cat[cat] = by_cat.get(cat, 0) + 1
            conf = e.get("confidence", "unknown")
            by_conf[conf] = by_conf.get(conf, 0) + 1
            src = e.get("source", "unknown")
            by_source[src] = by_source.get(src, 0) + 1
        return {
            "total": len(self.learnings),
            "by_category": by_cat,
            "by_confidence": by_conf,
            "by_source": by_source,
            "sessions": len(list(
                SESSION_DIR.glob("session-*.json"))),
        }
