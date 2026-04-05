"""Vicki Vale -- Vault data extraction for narrative generation.

Origin: R-007, ADR-017 (S127)
Usage: Import in helper scripts or invoke via CLI.

    from rudy.vicki_vale import VickiVale
    vv = VickiVale()
    data = vv.build_episode_context([125, 126, 127])
"""

import json
import os
import re
from pathlib import Path

from rudy.paths import BATCAVE_VAULT, RUDY_DATA

NARRATIVES_DIR = BATCAVE_VAULT / "Narratives"
HANDOFFS_DIR = BATCAVE_VAULT / "Handoffs"
SCORES_DIR = BATCAVE_VAULT / "Scores"
FINDINGS_DIR = BATCAVE_VAULT / "Findings"
SESSIONS_DIR = BATCAVE_VAULT / "Sessions"
ARCHITECTURE_DIR = BATCAVE_VAULT / "Architecture"
EPISODE_INDEX = NARRATIVES_DIR / "episode-index.json"

# Pre-mapped thematic arcs with session ranges
ARCS = {
    "the-awakening": {
        "title": "The Awakening",
        "sessions": list(range(39, 53)),
        "tagline": "Robin's evolution from file-counter to autonomous agent.",
    },
    "the-reform": {
        "title": "The Reform",
        "sessions": list(range(52, 67)),
        "tagline": "Lucius's transformation. Process compression. Fix-first.",
    },
    "the-nervous-system": {
        "title": "The Nervous System",
        "sessions": list(range(64, 73)),
        "tagline": "Robin's survival becomes supreme priority.",
    },
    "the-governance-wars": {
        "title": "The Governance Wars",
        "sessions": list(range(70, 81)),
        "tagline": "Deletion gates. Module extraction. Safety vs speed.",
    },
    "autonomy": {
        "title": "Autonomy",
        "sessions": list(range(100, 128)),
        "tagline": "CLAUDE.md refactor. Night shifts. Robin unchained.",
    },
}


class VickiVale:
    """Vault data extractor for narrative generation."""

    def __init__(self):
        NARRATIVES_DIR.mkdir(parents=True, exist_ok=True)
        self._index = self._load_index()

    def _load_index(self):
        if EPISODE_INDEX.exists():
            with open(EPISODE_INDEX) as f:
                return json.load(f)
        return {"next_episode": 1, "episodes": []}

    def _save_index(self):
        with open(EPISODE_INDEX, "w") as f:
            json.dump(self._index, f, indent=2)
            f.write("\n")

    def _read_file_safe(self, path):
        """Read a file, returning empty string on failure."""
        try:
            return Path(path).read_text(encoding="utf-8")
        except Exception:
            return ""

    def scan_handoffs(self, start, end):
        """Read handoffs for sessions in [start, end] inclusive."""
        results = {}
        for n in range(start, end + 1):
            path = HANDOFFS_DIR / f"Session-{n}-Handoff.md"
            content = self._read_file_safe(path)
            if content:
                results[n] = content
        return results

    def scan_scores(self, start, end):
        """Read Alfred and Lucius scores in [start, end]."""
        results = {}
        for n in range(start, end + 1):
            for agent in ("Alfred", "Lucius"):
                path = SCORES_DIR / f"Score-S{n}-{agent}.md"
                content = self._read_file_safe(path)
                if content:
                    results[f"S{n}-{agent}"] = content
        return results

    def scan_findings(self, start=None, end=None):
        """Read findings, optionally filtered by session range."""
        results = {}
        if not FINDINGS_DIR.exists():
            return results
        for f in sorted(FINDINGS_DIR.iterdir()):
            if not f.suffix == ".md":
                continue
            # Extract session number from filename like LF-S49-002-...
            match = re.search(r"S(\d+)", f.name)
            if match:
                snum = int(match.group(1))
                if start and snum < start:
                    continue
                if end and snum > end:
                    continue
            content = self._read_file_safe(f)
            if content:
                results[f.stem] = content
        return results

    def scan_sessions(self, start, end):
        """Read session records in [start, end]."""
        results = {}
        if not SESSIONS_DIR.exists():
            return results
        for f in sorted(SESSIONS_DIR.iterdir()):
            match = re.search(r"S(?:ession-)?(\d+)", f.name)
            if match:
                snum = int(match.group(1))
                if start <= snum <= end:
                    content = self._read_file_safe(f)
                    if content:
                        results[f.stem] = content
        return results

    def extract_arc_data(self, arc_name):
        """Extract all vault data for a pre-mapped thematic arc."""
        arc = ARCS.get(arc_name)
        if not arc:
            return {"error": f"Unknown arc: {arc_name}", "known": list(ARCS.keys())}
        start = min(arc["sessions"])
        end = max(arc["sessions"])
        return {
            "arc": arc,
            "handoffs": self.scan_handoffs(start, end),
            "scores": self.scan_scores(start, end),
            "findings": self.scan_findings(start, end),
            "sessions": self.scan_sessions(start, end),
        }

    def build_episode_context(self, session_nums):
        """Combine all vault sources for a list of session numbers."""
        start = min(session_nums)
        end = max(session_nums)
        return {
            "session_range": [start, end],
            "handoffs": self.scan_handoffs(start, end),
            "scores": self.scan_scores(start, end),
            "findings": self.scan_findings(start, end),
            "sessions": self.scan_sessions(start, end),
        }

    def register_episode(self, title, slug, session_range, episode_type):
        """Register a new episode in the index and return its number."""
        num = self._index["next_episode"]
        entry = {
            "episode": num,
            "title": title,
            "slug": slug,
            "session_range": session_range,
            "type": episode_type,
            "file": f"Episode-{num:03d}-{slug}.md",
        }
        self._index["episodes"].append(entry)
        self._index["next_episode"] = num + 1
        self._save_index()
        return entry

    def save_episode(self, entry, content):
        """Save episode markdown to vault/Narratives/."""
        path = NARRATIVES_DIR / entry["file"]
        path.write_text(content, encoding="utf-8")
        return str(path)

    def list_arcs(self):
        """Return available pre-mapped arcs."""
        return {k: {"title": v["title"], "tagline": v["tagline"],
                     "range": f"S{min(v['sessions'])}-S{max(v['sessions'])}"}
                for k, v in ARCS.items()}


if __name__ == "__main__":
    import sys
    vv = VickiVale()
    if len(sys.argv) > 1 and sys.argv[1] == "arcs":
        print(json.dumps(vv.list_arcs(), indent=2))
    elif len(sys.argv) > 1 and sys.argv[1] == "scan":
        start = int(sys.argv[2]) if len(sys.argv) > 2 else 125
        end = int(sys.argv[3]) if len(sys.argv) > 3 else 127
        ctx = vv.build_episode_context(list(range(start, end + 1)))
        out = RUDY_DATA / f"vicki-scan-{start}-{end}.json"
        # Save summary (not full content -- too large)
        summary = {
            "session_range": ctx["session_range"],
            "handoff_count": len(ctx["handoffs"]),
            "score_count": len(ctx["scores"]),
            "finding_count": len(ctx["findings"]),
            "session_count": len(ctx["sessions"]),
            "handoff_sessions": sorted(ctx["handoffs"].keys()),
            "score_keys": sorted(ctx["scores"].keys()),
            "finding_keys": sorted(ctx["findings"].keys()),
        }
        with open(out, "w") as f:
            json.dump(summary, f, indent=2)
            f.write("\n")
        print(f"Scan saved to {out}")
    else:
        print("Usage: python -m rudy.vicki_vale [arcs|scan START END]")
