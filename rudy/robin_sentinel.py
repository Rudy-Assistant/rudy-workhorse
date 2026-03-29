#!/usr/bin/env python3
"""
Robin Sentinel Observer - Passive environmental awareness on EVERY cycle.

Batmans Directive: Robin should ALWAYS be observing friction points,
even in STANDBY/SHADOW mode. This is about maintaining situational
awareness and feeding observations into the initiative priority system.

NOT busywork. NOT action-taking. Pure disciplined observation.
"""

import json
import logging
import os
import shutil
import subprocess
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger("robin_sentinel")

HOME = Path(os.environ.get("USERPROFILE", os.path.expanduser("~")))
DESKTOP = HOME / "Desktop"
RUDY_DATA = DESKTOP / "rudy-data"
RUDY_LOGS = DESKTOP / "rudy-logs"
COORD_DIR = RUDY_DATA / "coordination"
ALFRED_INBOX = RUDY_DATA / "alfred-inbox"
ROBIN_INBOX = RUDY_DATA / "robin-inbox"
AUTONOMY_LOG = RUDY_LOGS / "robin-autonomy.log"
OBSERVATION_LOG = RUDY_DATA / "robin-observations.json"


class SentinelObserver:
    """
    Passive observer that runs on EVERY nightwatch cycle.
    Records friction points, coordination gaps, and code
    quality signals without taking action. Feeds into
    InitiativeEngine priorities.
    """

    MAX_OBSERVATIONS = 500

    def __init__(self):
        self.observations = self._load()

    def _load(self):
        if OBSERVATION_LOG.exists():
            try:
                with open(OBSERVATION_LOG) as f:
                    return json.load(f)
            except (json.JSONDecodeError, OSError):
                pass
        return []

    def _save(self):
        with open(OBSERVATION_LOG, "w") as f:
            json.dump(
                self.observations[-self.MAX_OBSERVATIONS:],
                f, indent=2,
            )

    def _record(self, category, signal, details=""):
        entry = {
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "signal": signal,
            "details": details,
        }
        self.observations.append(entry)
        log.debug("[Sentinel] %s: %s", category, signal)

    def observe(self):
        """Run all passive checks. Returns summary dict."""
        findings = {
            "environment": self._observe_environment(),
            "coordination": self._observe_coordination(),
            "code_quality": self._observe_code_quality(),
        }
        self._save()
        total = sum(len(v) for v in findings.values())
        if total > 0:
            log.info(
                "[Sentinel] %d friction points: "
                "env=%d coord=%d code=%d",
                total,
                len(findings["environment"]),
                len(findings["coordination"]),
                len(findings["code_quality"]),
            )
        return findings

    def _observe_environment(self):
        """Check for environment friction: disk, stale procs, permissions."""
        signals = []
        try:
            usage = shutil.disk_usage(str(HOME))
            free_gb = usage.free / (1024 ** 3)
            pct = (usage.used / usage.total) * 100
            if free_gb < 10:
                s = "Low disk: %.1fGB free (%.0f%% used)" % (free_gb, pct)
                self._record("environment", s)
                signals.append(s)
            elif free_gb < 20:
                s = "Disk watch: %.1fGB free (%.0f%% used)" % (free_gb, pct)
                self._record("environment", s)
                signals.append(s)
        except Exception:
            pass
        try:
            r = subprocess.run(
                ["tasklist", "/FI",
                 "IMAGENAME eq python.exe", "/FO", "CSV"],
                capture_output=True, text=True, timeout=10,
            )
            n = r.stdout.count("python.exe")
            if n > 8:
                s = "Process buildup: %d python procs" % n
                self._record("environment", s)
                signals.append(s)
        except Exception:
            pass
        try:
            req = urllib.request.Request(
                "http://localhost:11434/api/tags")
            with urllib.request.urlopen(req, timeout=5):
                pass
        except Exception as e:
            s = "Ollama down: %s" % type(e).__name__
            self._record("environment", s)
            signals.append(s)
        if not RUDY_LOGS.exists():
            s = "Missing rudy-logs directory"
            self._record("environment", s)
            signals.append(s)
        return signals

    # ------ coordination ------
    def _observe_coordination(self):
        signals = []
        try:
            stale = 0
            for fp in ROBIN_INBOX.glob("*.json"):
                try:
                    with open(fp) as fh:
                        msg = json.load(fh)
                    ts = msg.get("timestamp", "")
                    if ts:
                        age = (datetime.now()
                               - datetime.fromisoformat(ts)
                               ).total_seconds() / 3600
                        if age > 2:
                            stale += 1
                except Exception:
                    continue
            if stale > 0:
                s = "Stale inbox: %d msg(s) >2h old" % stale
                self._record("coordination", s)
                signals.append(s)
        except Exception:
            pass
        try:
            n = len(list(ALFRED_INBOX.glob("*.json")))
            if n > 3:
                s = "Outbox buildup: %d awaiting Alfred" % n
                self._record("coordination", s)
                signals.append(s)
        except Exception:
            pass
        try:
            af = COORD_DIR / "alfred-status.json"
            if af.exists():
                with open(af) as f:
                    st = json.load(f)
                u = st.get("updated_at", "")
                if u:
                    age = (datetime.now()
                           - datetime.fromisoformat(u)
                           ).total_seconds() / 3600
                    if age > 12:
                        s = "Alfred silent: %.0fh" % age
                        self._record("coordination", s)
                        signals.append(s)
        except Exception:
            pass
        return signals

    # ------ code quality ------
    def _observe_code_quality(self):
        signals = []
        try:
            al = RUDY_LOGS / "robin-agent.log"
            if al.exists():
                txt = al.read_text(errors="ignore")
                tail = txt.splitlines()[-100:]
                errs = sum(
                    1 for l in tail
                    if "ERROR" in l or "Traceback" in l
                )
                if errs > 3:
                    s = "Error spike: %d in last 100 lines" % errs
                    self._record("code_quality", s)
                    signals.append(s)
        except Exception:
            pass
        try:
            if AUTONOMY_LOG.exists():
                txt = AUTONOMY_LOG.read_text(errors="ignore")
                tail = txt.splitlines()[-50:]
                dep = sum(
                    1 for l in tail
                    if "deprecat" in l.lower()
                )
                if dep > 0:
                    s = "Deprecation warnings: %d" % dep
                    self._record("code_quality", s)
                    signals.append(s)
        except Exception:
            pass
        return signals

    # ------ priority boost ------
    def get_priority_boost(self, area):
        """
        Priority boost for initiative areas based on
        recent observations. More signals = higher boost.
        """
        cutoff = (
            datetime.now() - timedelta(hours=4)
        ).isoformat()
        recent = [
            o for o in self.observations
            if o.get("timestamp", "") > cutoff
        ]
        cat_map = {
            "reliability": "code_quality",
            "environment_health": "environment",
            "alfred_coordination": "coordination",
            "codebase_quality": "code_quality",
        }
        target = cat_map.get(area)
        if not target:
            return 0
        hits = [
            o for o in recent
            if o.get("category") == target
        ]
        return min(len(hits), 5)
