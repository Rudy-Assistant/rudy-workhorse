"""
Movement Feed — Real-time activity and movement timeline from network presence data.

What we CAN detect from WiFi alone (Tier 1):
  - Person arrives home (device joins network)
  - Person leaves home (device drops off network)
  - Person is active (device generating traffic / responding to ARP)
  - Person is idle/sleeping (device goes quiet but stays on network)
  - Multiple people arriving/leaving together (correlated device events)
  - Routine deviations (someone not home when they usually are)
  - Nighttime activity (device active at unusual hours)

What we CANNOT detect without hardware:
  - Room-level position (needs mmWave radar or WiFi CSI)
  - Falls or medical events (needs Aqara FP2 or ESP32-S3 CSI)
  - Pet movement (needs smart collar with BLE/WiFi beacon)
  - Body presence without a device (needs CSI or radar)

Pet detection options (for future):
  - Tile/AirTag on collar → BLE beacon, detectable via Bluetooth scanning
  - Fi/Halo smart collar → WiFi-enabled, would appear on network
  - ESP32 BLE beacon on collar → custom, cheap ($5), detectable by Workhorse

This module reads from all presence data sources and produces a unified,
chronological feed suitable for dashboard display.
"""
import json
import os
import logging
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path

log = logging.getLogger(__name__)

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS_DIR = DESKTOP / "rudy-logs"

# Input sources
PRESENCE_LOG = LOGS_DIR / "presence-log.json"
PRESENCE_CURRENT = LOGS_DIR / "presence-current.json"
PRESENCE_ROUTINES = LOGS_DIR / "presence-routines.json"
PRESENCE_DEVICES = LOGS_DIR / "presence-devices.json"
PRESENCE_ANALYTICS = LOGS_DIR / "presence-analytics.json"
INTRUDER_DB = LOGS_DIR / "intruder-database.json"
THREAT_TIMELINE = LOGS_DIR / "threat-timeline.json"
WELLNESS_STATE = LOGS_DIR / "wellness-state.json"
WELLNESS_ALERTS = LOGS_DIR / "wellness-alerts.json"
HOUSEHOLD_FILE = LOGS_DIR / "presence-household.json"
DEFENSE_ALERTS = LOGS_DIR / "defense-alerts.json"

# Output
MOVEMENT_FEED = LOGS_DIR / "movement-feed.json"
MOVEMENT_SUMMARY = LOGS_DIR / "movement-summary.json"


def _load_json(path, default=None):
    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            log.debug(f"Failed to load JSON from {path}: {e}")
    return default if default is not None else {}


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)


class MovementFeed:
    """
    Aggregates all presence, security, and wellness data into a unified
    chronological feed of events.
    """

    def __init__(self):
        self.events = _load_json(PRESENCE_LOG, [])
        self.current = _load_json(PRESENCE_CURRENT, {})
        self.devices = _load_json(PRESENCE_DEVICES, {})
        self.routines = _load_json(PRESENCE_ROUTINES, {})
        self.analytics = _load_json(PRESENCE_ANALYTICS, {})
        self.intruders = _load_json(INTRUDER_DB, {})
        self.threat_timeline = _load_json(THREAT_TIMELINE, [])
        self.wellness_state = _load_json(WELLNESS_STATE, {})
        self.wellness_alerts = _load_json(WELLNESS_ALERTS, [])
        self.household = _load_json(HOUSEHOLD_FILE, {})
        self.defense_alerts = _load_json(DEFENSE_ALERTS, [])

    def generate_feed(self, hours: int = 24, max_events: int = 200) -> dict:
        """
        Generate a unified movement feed for the past N hours.
        Returns structured data suitable for dashboard rendering.
        """
        now = datetime.now()
        cutoff = now - timedelta(hours=hours)
        cutoff_str = cutoff.isoformat()

        feed_items = []

        # 1. Presence events (arrivals/departures)
        for event in self.events:
            t = event.get("time", "")
            if t < cutoff_str:
                continue
            mac = event.get("mac", "")
            device_name = self._get_device_name(mac)
            cluster_label = self._get_cluster_label(mac)

            feed_items.append({
                "time": t,
                "type": "presence",
                "subtype": event.get("type", "unknown"),  # arrival or departure
                "device": device_name,
                "mac": mac,
                "ip": event.get("ip", "?"),
                "person": cluster_label,
                "known": event.get("known", False),
                "icon": "arrive" if event.get("type") == "arrival" else "depart",
                "severity": "info",
                "message": self._format_presence_event(event, device_name, cluster_label),
            })

        # 2. Threat events (new intruders, departures)
        for event in self.threat_timeline:
            t = event.get("time", "")
            if t < cutoff_str:
                continue
            feed_items.append({
                "time": t,
                "type": "threat",
                "subtype": event.get("event", "unknown"),
                "mac": event.get("mac", ""),
                "severity": "warning" if "new" in event.get("event", "") else "info",
                "icon": "threat",
                "message": self._format_threat_event(event),
            })

        # 3. Wellness alerts
        for alert in self.wellness_alerts:
            t = alert.get("time", "")
            if t < cutoff_str:
                continue
            feed_items.append({
                "time": t,
                "type": "wellness",
                "subtype": alert.get("type", "unknown"),
                "person": alert.get("person", "?"),
                "severity": alert.get("severity", "info"),
                "icon": "wellness",
                "message": alert.get("message", "Wellness alert"),
            })

        # 4. Defense alerts (high severity only)
        for alert in self.defense_alerts:
            t = alert.get("time", "")
            if t < cutoff_str:
                continue
            if alert.get("severity") in ("alert", "critical"):
                feed_items.append({
                    "time": t,
                    "type": "defense",
                    "subtype": alert.get("category", "unknown"),
                    "severity": alert.get("severity", "warning"),
                    "icon": "shield",
                    "message": alert.get("message", "Defense alert"),
                })

        # Sort by time descending (most recent first)
        feed_items.sort(key=lambda x: x.get("time", ""), reverse=True)
        feed_items = feed_items[:max_events]

        # Generate current status snapshot
        snapshot = self._generate_snapshot()

        result = {
            "generated": now.isoformat(),
            "period_hours": hours,
            "total_events": len(feed_items),
            "feed": feed_items,
            "snapshot": snapshot,
            "household_context": self._get_household_summary(),
        }

        _save_json(MOVEMENT_FEED, result)
        return result

    def _generate_snapshot(self) -> dict:
        """Current state: who's home, device counts, etc."""
        now = datetime.now()
        devices_present = len(self.current)
        known_present = sum(1 for m in self.current if m in self.devices)
        unknown_present = devices_present - known_present

        # Build per-person status from analytics clusters
        persons = []
        clusters = self.analytics.get("clusters", [])
        self.analytics.get("device_profiles", {})

        for cluster in clusters:
            devices_in_cluster = cluster.get("devices", [])
            present_count = sum(1 for m in devices_in_cluster if m in self.current)
            total = len(devices_in_cluster)
            is_home = present_count > 0

            # Find last seen time
            last_seen = None
            for mac in devices_in_cluster:
                dev = self.current.get(mac, {})
                ls = dev.get("last_seen")
                if ls and (not last_seen or ls > last_seen):
                    last_seen = ls

            persons.append({
                "label": cluster.get("label", f"Person {cluster['cluster_id'] + 1}"),
                "cluster_id": cluster.get("cluster_id"),
                "is_home": is_home,
                "devices_present": present_count,
                "devices_total": total,
                "last_seen": last_seen,
                "avg_presence": cluster.get("avg_presence", 0),
            })

        # Time-based context
        hour = now.hour
        if 6 <= hour < 12:
            time_context = "morning"
        elif 12 <= hour < 17:
            time_context = "afternoon"
        elif 17 <= hour < 21:
            time_context = "evening"
        elif 21 <= hour < 23:
            time_context = "late_evening"
        else:
            time_context = "nighttime"

        return {
            "timestamp": now.isoformat(),
            "time_context": time_context,
            "devices_online": devices_present,
            "known_devices": known_present,
            "unknown_devices": unknown_present,
            "persons": persons,
            "network_healthy": unknown_present == 0 or devices_present > 0,
        }

    def _get_device_name(self, mac: str) -> str:
        """Get human-readable device name."""
        if mac in self.devices:
            return self.devices[mac].get("name", mac)
        # Check intruder dossiers
        intruder_devices = self.intruders.get("devices", {})
        if mac in intruder_devices:
            return intruder_devices[mac].get("label", mac)
        return f"Device [{mac[-8:]}]"

    def _get_cluster_label(self, mac: str) -> str:
        """Get the person-cluster label for a device."""
        clusters = self.analytics.get("clusters", [])
        for cluster in clusters:
            if mac in cluster.get("devices", []):
                return cluster.get("label", f"Person {cluster['cluster_id'] + 1}")

        # Check household context for assignment
        household = self.analytics.get("household", {})
        assignments = household.get("cluster_assignments", [])
        for a in assignments:
            cid = a.get("cluster_id")
            for cluster in clusters:
                if cluster.get("cluster_id") == cid and mac in cluster.get("devices", []):
                    return a.get("resident_name", cluster.get("label", "?"))

        return None

    def _format_presence_event(self, event: dict, device_name: str,
                                 cluster_label: str) -> str:
        """Format a presence event for human display."""
        etype = event.get("type", "?")
        ip = event.get("ip", "?")
        known = event.get("known", False)

        if cluster_label:
            who = cluster_label
        elif known:
            who = device_name
        else:
            who = f"Unknown device at {ip}"

        if etype == "arrival":
            return f"{who} arrived ({device_name}, {ip})"
        elif etype == "departure":
            return f"{who} departed ({device_name}, {ip})"
        return f"{who}: {etype}"

    def _format_threat_event(self, event: dict) -> str:
        """Format a threat timeline event."""
        etype = event.get("event", "?")
        mac = event.get("mac", "?")
        if etype == "new_intruder":
            score = event.get("threat_score", "?")
            return f"New unknown device profiled [{mac[-8:]}] (threat score: {score})"
        elif etype == "intruder_departed":
            dur = event.get("duration_min", "?")
            return f"Unknown device departed [{mac[-8:]}] (was here {dur} min)"
        return f"Threat event: {etype} [{mac[-8:]}]"

    def _get_household_summary(self) -> dict:
        """Brief household context for the feed header."""
        ctx = self.household.get("context", {})
        return {
            "location": ctx.get("location_type", "unknown"),
            "expected_residents": ctx.get("expected_residents"),
            "residents": [
                {"name": r.get("name"), "role": r.get("role"),
                 "fall_risk": r.get("fall_risk", False)}
                for r in ctx.get("residents", [])
            ],
        }

    def get_activity_heatmap(self) -> dict:
        """
        Generate an activity heatmap: per-device, per-hour presence counts.
        Useful for visualizing daily patterns.
        """
        heatmap = {}
        for mac, routine in self.routines.items():
            name = self._get_device_name(mac)
            weekly = routine.get("weekly", {})

            # Aggregate all days into a single 24-hour profile
            hourly = [0] * 24
            for day, hours in weekly.items():
                for h in range(24):
                    hourly[h] += hours[h]

            total = sum(hourly)
            if total == 0:
                continue

            # Normalize to 0-1
            max_val = max(hourly) if hourly else 1
            normalized = [round(h / max_val, 2) for h in hourly]

            # Find peak and quiet hours
            peak_hour = hourly.index(max(hourly))
            quiet_hours = [h for h in range(24) if hourly[h] < max_val * 0.1]

            heatmap[mac] = {
                "device": name,
                "hourly_raw": hourly,
                "hourly_normalized": normalized,
                "peak_hour": peak_hour,
                "quiet_hours": quiet_hours,
                "total_observations": total,
            }

        return heatmap

    def print_feed(self, hours: int = 24):
        """Print a human-readable movement feed."""
        feed = self.generate_feed(hours)

        print("=" * 60)
        print("  MOVEMENT FEED")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')} — Past {hours}h")
        print("=" * 60)

        # Snapshot
        snap = feed.get("snapshot", {})
        print(f"\n  NOW: {snap.get('devices_online', 0)} devices online "
              f"({snap.get('known_devices', 0)} known, "
              f"{snap.get('unknown_devices', 0)} unknown)")
        print(f"  Time: {snap.get('time_context', '?')}")

        persons = snap.get("persons", [])
        if persons:
            home = [p for p in persons if p.get("is_home")]
            away = [p for p in persons if not p.get("is_home")]
            if home:
                print(f"  Home: {', '.join(p['label'] for p in home)}")
            if away:
                print(f"  Away: {', '.join(p['label'] for p in away)}")

        # Feed
        items = feed.get("feed", [])
        if items:
            print(f"\n  Timeline ({len(items)} events):")
            print(f"  {'—' * 50}")
            for item in items[:30]:  # Show last 30
                t = item.get("time", "?")[:19]
                sev = item.get("severity", "info")
                icon = {"info": " ", "warning": "!", "alert": "!!", "critical": "!!!"}
                msg = item.get("message", "?")
                print(f"  {t} [{icon.get(sev, '?')}] {msg}")
        else:
            print("\n  No events in the past {hours}h")

        # Household
        hh = feed.get("household_context", {})
        residents = hh.get("residents", [])
        if residents:
            print(f"\n  Household: {hh.get('location', '?')}")
            for r in residents:
                fr = " [FALL RISK]" if r.get("fall_risk") else ""
                print(f"    {r.get('name', '?')} ({r.get('role', '?')}){fr}")

        print("\n" + "=" * 60)


def generate_movement_feed(hours: int = 24):
    """Generate and print the movement feed."""
    mf = MovementFeed()
    mf.print_feed(hours)
    return mf.generate_feed(hours)


if __name__ == "__main__":
    generate_movement_feed()
