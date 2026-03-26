"""
Wellness Monitor — Family safety through network presence intelligence.

Tier 1 (Current — Software Only):
  - Device inactivity detection (phone goes dark unexpectedly)
  - Routine deviation alerts (grandparent's phone not active during normal hours)
  - Extended absence warnings (known device missing for longer than usual)
  - Nighttime activity monitoring (unusual activity at odd hours)

Tier 2 (With ESP32-S3 CSI — Future):
  - Room-level presence detection
  - Breathing/vital sign monitoring
  - Fall detection via WiFi signal analysis

Tier 3 (With mmWave Sensor — Future):
  - High-accuracy fall detection (Aqara FP2)
  - Multi-person tracking
  - Zone-based monitoring

All tiers feed into the same alert pipeline → email/notification to Chris.
"""
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from collections import defaultdict

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS_DIR = DESKTOP / "rudy-logs"

# Files
WELLNESS_CONFIG = LOGS_DIR / "wellness-config.json"
WELLNESS_STATE = LOGS_DIR / "wellness-state.json"
WELLNESS_ALERTS = LOGS_DIR / "wellness-alerts.json"
PRESENCE_CURRENT = LOGS_DIR / "presence-current.json"
PRESENCE_DEVICES = LOGS_DIR / "presence-devices.json"
PRESENCE_LOG = LOGS_DIR / "presence-log.json"
PRESENCE_ROUTINES = LOGS_DIR / "presence-routines.json"


class WellnessMonitor:
    """
    Monitors family safety through device presence patterns.
    Designed to catch anomalies that could indicate falls, medical events,
    or other situations where someone needs help.
    """

    def __init__(self):
        self.config = self._load_json(WELLNESS_CONFIG, self._default_config())
        self.state = self._load_json(WELLNESS_STATE, {})
        self.alerts = self._load_json(WELLNESS_ALERTS, [])
        self.devices = self._load_json(PRESENCE_DEVICES, {})
        self.current = self._load_json(PRESENCE_CURRENT, {})
        self.routines = self._load_json(PRESENCE_ROUTINES, {})
        self.events = self._load_json(PRESENCE_LOG, [])

    def _load_json(self, path, default):
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except:
                pass
        return default

    def _save_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def _default_config(self):
        return {
            "check_interval_minutes": 30,
            "inactivity_threshold_minutes": 120,  # Alert if device silent for 2+ hours during active period
            "nighttime_start": 23,  # 11 PM
            "nighttime_end": 6,  # 6 AM
            "nighttime_alert_threshold_minutes": 60,  # Shorter threshold at night
            "monitored_persons": {},
            "alert_email": "ccimino2@gmail.com",
            "enabled": True,
        }

    def add_monitored_person(self, name: str, device_macs: list,
                              relationship: str = "family",
                              alert_on_inactivity: bool = True,
                              alert_on_nighttime_activity: bool = False,
                              fall_risk: bool = False,
                              custom_threshold_minutes: int = None):
        """
        Register a person to monitor for wellness.

        Args:
            name: Person's name
            device_macs: List of MAC addresses (phone, watch, etc.)
            relationship: family, grandparent, child, etc.
            alert_on_inactivity: Alert if their devices go silent
            alert_on_nighttime_activity: Alert on unusual nighttime activity
            fall_risk: Enable fall-risk specific monitoring (shorter thresholds)
            custom_threshold_minutes: Override default inactivity threshold
        """
        self.config["monitored_persons"][name] = {
            "device_macs": [m.lower() for m in device_macs],
            "relationship": relationship,
            "alert_on_inactivity": alert_on_inactivity,
            "alert_on_nighttime_activity": alert_on_nighttime_activity,
            "fall_risk": fall_risk,
            "custom_threshold_minutes": custom_threshold_minutes or (
                60 if fall_risk else self.config["inactivity_threshold_minutes"]
            ),
            "registered": datetime.now().isoformat(),
        }
        self._save_json(WELLNESS_CONFIG, self.config)
        print(f"Monitoring {name} ({relationship}) — {len(device_macs)} devices")

    def check(self) -> dict:
        """
        Run a wellness check cycle. Call this every 15-30 minutes.
        Returns a dict of findings.
        """
        now = datetime.now()
        findings = {
            "timestamp": now.isoformat(),
            "persons_checked": 0,
            "alerts_generated": [],
            "status": {},
        }

        if not self.config.get("enabled"):
            return findings

        is_nighttime = self._is_nighttime(now)

        for person_name, person_config in self.config.get("monitored_persons", {}).items():
            findings["persons_checked"] += 1
            person_status = self._check_person(person_name, person_config, now, is_nighttime)
            findings["status"][person_name] = person_status

            if person_status.get("alerts"):
                findings["alerts_generated"].extend(person_status["alerts"])

        # Save state
        self.state["last_check"] = now.isoformat()
        self.state["last_findings"] = findings
        self._save_json(WELLNESS_STATE, self.state)

        # Save alerts
        self.alerts = self.alerts[-200:]  # Keep last 200
        self._save_json(WELLNESS_ALERTS, self.alerts)

        return findings

    def _check_person(self, name: str, config: dict, now: datetime,
                       is_nighttime: bool) -> dict:
        """Check wellness status of a single person."""
        status = {
            "name": name,
            "devices_present": 0,
            "devices_absent": 0,
            "last_seen": None,
            "alerts": [],
            "wellness": "ok",
        }

        macs = config.get("device_macs", [])
        if not macs:
            return status

        # Check which of this person's devices are currently visible
        for mac in macs:
            if mac in self.current:
                status["devices_present"] += 1
                last_seen = self.current[mac].get("last_seen")
                if last_seen and (not status["last_seen"] or last_seen > status["last_seen"]):
                    status["last_seen"] = last_seen
            else:
                status["devices_absent"] += 1

        # Determine if person is "home" (any device present)
        person_home = status["devices_present"] > 0

        # Get person's state history
        person_state = self.state.get(f"person_{name}", {
            "last_seen_home": None,
            "last_seen_away": None,
            "consecutive_absent_checks": 0,
            "last_alert_time": None,
        })

        if person_home:
            person_state["last_seen_home"] = now.isoformat()
            person_state["consecutive_absent_checks"] = 0
        else:
            person_state["consecutive_absent_checks"] = \
                person_state.get("consecutive_absent_checks", 0) + 1

        # === INACTIVITY DETECTION ===
        if config.get("alert_on_inactivity") and not person_home:
            last_home = person_state.get("last_seen_home")
            if last_home:
                try:
                    last_home_dt = datetime.fromisoformat(last_home)
                    minutes_absent = (now - last_home_dt).total_seconds() / 60
                    threshold = config.get("custom_threshold_minutes",
                                          self.config["inactivity_threshold_minutes"])

                    # Use shorter threshold at night for fall-risk persons
                    if is_nighttime and config.get("fall_risk"):
                        threshold = min(threshold,
                                       self.config.get("nighttime_alert_threshold_minutes", 60))

                    if minutes_absent > threshold:
                        # Don't alert more than once per hour for same person
                        last_alert = person_state.get("last_alert_time")
                        should_alert = True
                        if last_alert:
                            try:
                                last_alert_dt = datetime.fromisoformat(last_alert)
                                if (now - last_alert_dt).total_seconds() < 3600:
                                    should_alert = False
                            except:
                                pass

                        if should_alert:
                            alert = {
                                "time": now.isoformat(),
                                "person": name,
                                "type": "inactivity",
                                "severity": "high" if config.get("fall_risk") else "medium",
                                "message": (
                                    f"{name}'s device(s) have been absent for "
                                    f"{int(minutes_absent)} minutes "
                                    f"(threshold: {int(threshold)} min)"
                                ),
                                "context": "nighttime" if is_nighttime else "daytime",
                            }
                            status["alerts"].append(alert)
                            self.alerts.append(alert)
                            person_state["last_alert_time"] = now.isoformat()
                            status["wellness"] = "concern"
                except:
                    pass

        # === NIGHTTIME ACTIVITY ===
        if config.get("alert_on_nighttime_activity") and is_nighttime and person_home:
            # Check if this person doesn't normally appear at this hour
            for mac in macs:
                routine = self.routines.get(mac, {})
                weekly = routine.get("weekly", {})
                day = now.strftime("%A")
                hour = now.hour
                if weekly.get(day):
                    typical_count = weekly[day][hour]
                    total_scans = routine.get("total_scans", 1)
                    # If this hour normally has very low activity
                    if typical_count < 2 and total_scans > 20:
                        alert = {
                            "time": now.isoformat(),
                            "person": name,
                            "type": "unusual_nighttime_activity",
                            "severity": "low",
                            "message": (
                                f"Unusual nighttime activity: {name}'s device "
                                f"active at {now.strftime('%I:%M %p')} "
                                f"(not typical for {day}s)"
                            ),
                        }
                        status["alerts"].append(alert)
                        self.alerts.append(alert)

        # === ROUTINE DEVIATION ===
        # After we have enough data (20+ scans), check if person's
        # current presence/absence matches their usual pattern
        for mac in macs:
            routine = self.routines.get(mac, {})
            if routine.get("total_scans", 0) > 20:
                weekly = routine.get("weekly", {})
                day = now.strftime("%A")
                hour = now.hour
                if weekly.get(day):
                    expected = weekly[day][hour]
                    # High expected count but device is absent
                    if expected > 5 and mac not in self.current:
                        if not any(a["type"] == "routine_deviation"
                                  for a in status["alerts"]):
                            alert = {
                                "time": now.isoformat(),
                                "person": name,
                                "type": "routine_deviation",
                                "severity": "low",
                                "message": (
                                    f"{name} is usually home at this time on "
                                    f"{day}s but their device is absent"
                                ),
                            }
                            status["alerts"].append(alert)
                            self.alerts.append(alert)

        self.state[f"person_{name}"] = person_state
        return status

    def _is_nighttime(self, dt: datetime) -> bool:
        hour = dt.hour
        start = self.config.get("nighttime_start", 23)
        end = self.config.get("nighttime_end", 6)
        if start > end:
            return hour >= start or hour < end
        return start <= hour < end

    def get_dashboard(self) -> str:
        """Generate a human-readable family safety dashboard."""
        lines = []
        lines.append("=" * 50)
        lines.append(f"  FAMILY WELLNESS DASHBOARD")
        lines.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 50)

        for name, config in self.config.get("monitored_persons", {}).items():
            macs = config.get("device_macs", [])
            present_count = sum(1 for m in macs if m in self.current)
            total = len(macs)
            home = present_count > 0

            person_state = self.state.get(f"person_{name}", {})
            last_home = person_state.get("last_seen_home", "Never")
            if last_home != "Never":
                last_home = last_home[:16]

            fall_risk = " [FALL RISK]" if config.get("fall_risk") else ""
            status_icon = "HOME" if home else "AWAY"

            lines.append(f"\n  {name} ({config.get('relationship', '?')}){fall_risk}")
            lines.append(f"    Status: {status_icon} ({present_count}/{total} devices)")
            lines.append(f"    Last home: {last_home}")

        # Recent alerts
        recent = [a for a in self.alerts[-10:] if a.get("severity") in ("high", "medium")]
        if recent:
            lines.append(f"\n  RECENT ALERTS:")
            for a in recent[-5:]:
                lines.append(f"    [{a['severity'].upper()}] {a['message']}")

        lines.append("\n" + "=" * 50)
        return "\n".join(lines)


def run_wellness_check():
    """Run a wellness check and print dashboard."""
    monitor = WellnessMonitor()
    findings = monitor.check()
    print(monitor.get_dashboard())

    if findings["alerts_generated"]:
        print(f"\n{len(findings['alerts_generated'])} alerts generated:")
        for a in findings["alerts_generated"]:
            print(f"  [{a['severity'].upper()}] {a['message']}")

    return findings


if __name__ == "__main__":
    run_wellness_check()
