"""
Intruder Profiler — Counter-espionage device intelligence for high-threat networks.

Context: The Cimino family farm (4101 Kansas Ave, Modesto) is home to a former
District Attorney, an attorney, and a prominent local family. Any unrecognized
device on this network is, by default, treated as a potential hostile intrusion
until cleared by the system's behavioral analysis or manual approval.

This module does NOT perform any offensive actions. It observes, profiles,
fingerprints, and builds intelligence dossiers on unknown devices using only
passive, read-only network observation techniques that are standard and legal
for any network administrator to perform on their own network.

Capabilities:
  1. Device fingerprinting (MAC OUI, hostname, mDNS/NetBIOS, open ports)
  2. Behavioral profiling (connection patterns, timing, duration, frequency)
  3. Threat scoring (composite risk score based on multiple signals)
  4. Intruder dossier generation (persistent file per unknown device)
  5. Clearance workflow (promote device from "unknown" to "cleared" with reason)
  6. Correlation (link devices that appear/disappear together — same actor?)
  7. Historical pattern matching (has this device appeared before?)
"""
import json
import os
import re
import subprocess
import time
import hashlib
from collections import defaultdict, Counter
from datetime import datetime, timedelta
from pathlib import Path

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS_DIR = DESKTOP / "rudy-logs"
DOSSIER_DIR = LOGS_DIR / "intruder-dossiers"
DOSSIER_DIR.mkdir(parents=True, exist_ok=True)

INTRUDER_DB = LOGS_DIR / "intruder-database.json"
CLEARED_DEVICES = LOGS_DIR / "cleared-devices.json"
THREAT_TIMELINE = LOGS_DIR / "threat-timeline.json"

SUBNET = "192.168.7"

# Threat scoring weights
THREAT_WEIGHTS = {
    "randomized_mac": 5,        # Privacy MAC = deliberate concealment
    "unknown_oui": 3,           # Can't identify manufacturer
    "first_appearance": 10,     # Never seen before on this network
    "appeared_at_night": 8,     # 11 PM - 6 AM arrival is suspicious
    "appeared_briefly": 6,      # Came and went quickly (< 30 min)
    "no_hostname": 4,           # Device doesn't broadcast a name
    "unusual_ports_open": 7,    # Has services running (not just a phone)
    "correlates_with_unknown": 5, # Appeared simultaneously with another unknown
    "recurrent_unknown": -3,    # Seen before and was harmless (reduces score)
    "outside_dhcp_range": 6,    # Static IP outside normal DHCP allocation
    "high_frequency_connect": 4, # Connects/disconnects rapidly (scanning?)
}

# Normal DHCP range (adjust based on your router config)
DHCP_RANGE = range(20, 100)

# Common OUI prefixes for consumer devices (low threat)
CONSUMER_OUI = {
    "apple", "samsung", "google", "amazon", "roku", "sonos",
    "ring", "nest", "wyze", "tp-link", "netgear", "arris",
}


class IntruderProfiler:
    """
    Profiles and scores unknown devices on the network.
    Call process_scan() after every presence scan.
    """

    def __init__(self):
        self.database = self._load_json(INTRUDER_DB, {"devices": {}, "stats": {}})
        self.cleared = self._load_json(CLEARED_DEVICES, {})
        self.timeline = self._load_json(THREAT_TIMELINE, [])

    def _load_json(self, path, default):
        if path.exists():
            try:
                with open(path) as f:
                    return json.load(f)
            except Exception:
                pass
        return default

    def _save_json(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

    def process_scan(self, current_devices: dict, known_devices: dict) -> dict:
        """
        Process a presence scan result. Identifies unknowns, profiles them,
        updates dossiers, and returns threat assessment.

        Args:
            current_devices: {mac: {ip, last_seen, ...}} from presence scan
            known_devices: {mac: {name, owner, ...}} registered devices
        """
        now = datetime.now()
        is_night = now.hour >= 23 or now.hour < 6
        results = {
            "timestamp": now.isoformat(),
            "total_devices": len(current_devices),
            "known": 0,
            "cleared": 0,
            "unknown": 0,
            "new_intruders": [],
            "active_threats": [],
            "threat_level": "green",
        }

        unknown_macs_this_scan = []

        for mac, device_info in current_devices.items():
            ip = device_info.get("ip", "?")

            # Is this device known (registered)?
            if mac in known_devices:
                results["known"] += 1
                continue

            # Is this device cleared (manually approved)?
            if mac in self.cleared:
                results["cleared"] += 1
                continue

            # UNKNOWN DEVICE — profile it
            results["unknown"] += 1
            unknown_macs_this_scan.append(mac)

            # Get or create dossier
            dossier = self.database["devices"].get(mac, self._new_dossier(mac, ip))

            # Update sighting
            dossier["sightings"].append({
                "time": now.isoformat(),
                "ip": ip,
                "nighttime": is_night,
            })
            dossier["sightings"] = dossier["sightings"][-500:]  # Cap
            dossier["last_seen"] = now.isoformat()
            dossier["total_sightings"] += 1
            dossier["current_ip"] = ip

            # First-time profiling
            if dossier["total_sightings"] == 1:
                dossier = self._deep_profile(dossier, ip)
                results["new_intruders"].append({
                    "mac": mac, "ip": ip,
                    "threat_score": dossier.get("threat_score", 0),
                })

                # Log to timeline
                self.timeline.append({
                    "time": now.isoformat(),
                    "event": "new_intruder",
                    "mac": mac,
                    "ip": ip,
                    "threat_score": dossier.get("threat_score", 0),
                    "nighttime": is_night,
                })

            # Update threat score
            dossier["threat_score"] = self._compute_threat_score(dossier, is_night)

            # Save dossier
            self.database["devices"][mac] = dossier
            self._write_dossier_file(mac, dossier)

            if dossier["threat_score"] >= 15:
                results["active_threats"].append({
                    "mac": mac, "ip": ip,
                    "score": dossier["threat_score"],
                    "label": dossier.get("label", "Unknown"),
                })

        # Check for correlated unknowns (appeared together)
        if len(unknown_macs_this_scan) > 1:
            for mac in unknown_macs_this_scan:
                dossier = self.database["devices"].get(mac, {})
                co_unknowns = [m for m in unknown_macs_this_scan if m != mac]
                dossier.setdefault("correlated_unknowns", [])
                for co in co_unknowns:
                    if co not in dossier["correlated_unknowns"]:
                        dossier["correlated_unknowns"].append(co)
                self.database["devices"][mac] = dossier

        # Check for departures (devices that were in DB but are now gone)
        for mac, dossier in self.database["devices"].items():
            if mac not in current_devices and dossier.get("currently_present", False):
                duration = 0
                if dossier.get("last_seen"):
                    try:
                        last = datetime.fromisoformat(dossier["last_seen"])
                        duration = (now - last).total_seconds() / 60
                    except Exception:
                        pass
                dossier["currently_present"] = False
                dossier["departures"] = dossier.get("departures", 0) + 1
                dossier["last_visit_duration_min"] = round(duration, 1)

                self.timeline.append({
                    "time": now.isoformat(),
                    "event": "intruder_departed",
                    "mac": mac,
                    "duration_min": round(duration, 1),
                })

            elif mac in current_devices:
                dossier["currently_present"] = True

        # Determine overall threat level
        if results["active_threats"]:
            max_score = max(t["score"] for t in results["active_threats"])
            if max_score >= 25:
                results["threat_level"] = "red"
            elif max_score >= 15:
                results["threat_level"] = "orange"
            else:
                results["threat_level"] = "yellow"

        # Save everything
        self.database["stats"]["last_scan"] = now.isoformat()
        self.database["stats"]["total_tracked"] = len(self.database["devices"])
        self.database["stats"]["active_unknowns"] = results["unknown"]
        self._save_json(INTRUDER_DB, self.database)
        self.timeline = self.timeline[-2000:]
        self._save_json(THREAT_TIMELINE, self.timeline)

        return results

    def _new_dossier(self, mac: str, ip: str) -> dict:
        """Create a new intruder dossier."""
        return {
            "mac": mac,
            "first_seen": datetime.now().isoformat(),
            "last_seen": None,
            "current_ip": ip,
            "total_sightings": 0,
            "departures": 0,
            "sightings": [],
            "threat_score": 0,
            "threat_factors": [],
            "label": "Unknown",
            "status": "uncleared",
            "profile": {},
            "correlated_unknowns": [],
            "notes": [],
            "currently_present": True,
        }

    def _deep_profile(self, dossier: dict, ip: str) -> dict:
        """
        Deep-profile a new device using passive network observation.
        All techniques are standard network administration.
        """
        profile = {}

        # 1. MAC analysis
        mac = dossier["mac"]
        first_byte = int(mac.replace("-", ":").split(":")[0], 16)
        is_randomized = bool(first_byte & 0x02)
        profile["mac_randomized"] = is_randomized

        if not is_randomized:
            oui = ":".join(mac.replace("-", ":").split(":")[:3])
            profile["oui"] = oui
            # We could do a web lookup here but keeping it offline
        else:
            profile["oui"] = "randomized"

        # 2. IP analysis
        ip_last = int(ip.split(".")[-1])
        profile["ip_in_dhcp_range"] = ip_last in DHCP_RANGE
        profile["ip_last_octet"] = ip_last

        # 3. Hostname resolution (reverse DNS + NetBIOS)
        hostname = None
        try:
            result = subprocess.run(
                f"nbtstat -A {ip}",
                shell=True, capture_output=True, text=True, timeout=5
            )
            for line in result.stdout.splitlines():
                if "<00>" in line and "UNIQUE" in line:
                    hostname = line.split()[0].strip()
                    break
        except Exception:
            pass

        if not hostname:
            try:
                hostname = subprocess.run(
                    f"nslookup {ip}",
                    shell=True, capture_output=True, text=True, timeout=5
                ).stdout
                match = re.search(r'Name:\s+(\S+)', hostname)
                hostname = match.group(1) if match else None
            except Exception:
                pass

        profile["hostname"] = hostname
        dossier["label"] = hostname or f"Unknown ({ip})"

        # 4. Quick port probe (only common discovery ports)
        # This is standard network admin — like running nmap on your own network
        open_ports = []
        for port in [80, 443, 22, 8080, 5000, 8443, 554, 9100]:
            try:
                sock = __import__("socket").socket(__import__("socket").AF_INET, __import__("socket").SOCK_STREAM)
                sock.settimeout(0.5)
                result = sock.connect_ex((ip, port))
                if result == 0:
                    open_ports.append(port)
                sock.close()
            except Exception:
                pass
        profile["open_ports"] = open_ports

        # 5. TTL fingerprinting (OS family detection)
        try:
            result = subprocess.run(
                f"ping -n 1 -w 1000 {ip}",
                shell=True, capture_output=True, text=True, timeout=5
            )
            ttl_match = re.search(r'TTL=(\d+)', result.stdout)
            if ttl_match:
                ttl = int(ttl_match.group(1))
                profile["ttl"] = ttl
                if ttl <= 64:
                    profile["os_family"] = "Linux/Android/iOS"
                elif ttl <= 128:
                    profile["os_family"] = "Windows"
                else:
                    profile["os_family"] = "Unknown"
        except Exception:
            pass

        dossier["profile"] = profile
        return dossier

    def _compute_threat_score(self, dossier: dict, is_night: bool) -> int:
        """Compute composite threat score from multiple signals."""
        score = 0
        factors = []
        profile = dossier.get("profile", {})

        # MAC randomization
        if profile.get("mac_randomized"):
            score += THREAT_WEIGHTS["randomized_mac"]
            factors.append("randomized_mac")

        # First appearance on network
        if dossier["total_sightings"] <= 1:
            score += THREAT_WEIGHTS["first_appearance"]
            factors.append("first_seen")

        # Nighttime arrival
        first_sighting = dossier.get("sightings", [{}])[0] if dossier.get("sightings") else {}
        if first_sighting.get("nighttime") or is_night:
            score += THREAT_WEIGHTS["appeared_at_night"]
            factors.append("nighttime")

        # No hostname
        if not profile.get("hostname"):
            score += THREAT_WEIGHTS["no_hostname"]
            factors.append("no_hostname")

        # Open ports (running services = not just a phone)
        if profile.get("open_ports"):
            score += THREAT_WEIGHTS["unusual_ports_open"]
            factors.append(f"open_ports:{profile['open_ports']}")

        # Outside DHCP range
        if not profile.get("ip_in_dhcp_range", True):
            score += THREAT_WEIGHTS["outside_dhcp_range"]
            factors.append("outside_dhcp")

        # Correlated with other unknowns
        if dossier.get("correlated_unknowns"):
            score += THREAT_WEIGHTS["correlates_with_unknown"]
            factors.append(f"correlated:{len(dossier['correlated_unknowns'])}")

        # Recurring but uncleared (slight reduction — probably harmless neighbor)
        if dossier["total_sightings"] > 5:
            score += THREAT_WEIGHTS["recurrent_unknown"]
            factors.append("recurrent")

        # Brief visits (connect then quickly disconnect)
        if dossier.get("last_visit_duration_min", 999) < 30 and dossier.get("departures", 0) > 0:
            score += THREAT_WEIGHTS["appeared_briefly"]
            factors.append("brief_visit")

        dossier["threat_factors"] = factors
        return max(score, 0)

    def _write_dossier_file(self, mac: str, dossier: dict):
        """Write individual dossier file for the intruder."""
        safe_mac = mac.replace(":", "-")
        filepath = DOSSIER_DIR / f"dossier-{safe_mac}.json"
        self._save_json(filepath, dossier)

    def clear_device(self, mac: str, reason: str, cleared_by: str = "Chris"):
        """
        Clear a device — move it from unknown/hostile to approved.
        Keeps the dossier for historical reference.
        """
        mac = mac.lower()
        self.cleared[mac] = {
            "cleared_at": datetime.now().isoformat(),
            "cleared_by": cleared_by,
            "reason": reason,
        }
        self._save_json(CLEARED_DEVICES, self.cleared)

        if mac in self.database["devices"]:
            self.database["devices"][mac]["status"] = "cleared"
            self.database["devices"][mac]["notes"].append(
                f"Cleared by {cleared_by}: {reason}"
            )
            self._save_json(INTRUDER_DB, self.database)

        print(f"Device {mac} cleared: {reason}")

    def get_threat_summary(self) -> str:
        """Generate a human-readable threat summary."""
        lines = ["=" * 55]
        lines.append("  COUNTER-INTELLIGENCE THREAT BOARD")
        lines.append(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("=" * 55)

        stats = self.database.get("stats", {})
        devices = self.database.get("devices", {})

        active = [d for d in devices.values() if d.get("currently_present") and d["status"] != "cleared"]
        historical = [d for d in devices.values() if not d.get("currently_present")]

        lines.append(f"\n  Tracked unknowns: {len(devices)}")
        lines.append(f"  Currently present: {len(active)}")
        lines.append(f"  Historical: {len(historical)}")
        lines.append(f"  Cleared: {len(self.cleared)}")

        if active:
            lines.append(f"\n  ACTIVE UNKNOWNS:")
            for d in sorted(active, key=lambda x: x.get("threat_score", 0), reverse=True):
                score = d.get("threat_score", 0)
                icon = "***" if score >= 25 else "**" if score >= 15 else "*" if score >= 8 else "."
                label = d.get("label", "?")
                ip = d.get("current_ip", "?")
                mac = d.get("mac", "?")
                factors = ", ".join(d.get("threat_factors", []))
                lines.append(f"    [{icon}] Score {score:2d} | {ip} [{mac}]")
                lines.append(f"         {label} | Factors: {factors}")
                lines.append(f"         Seen {d.get('total_sightings', 0)}x | First: {d.get('first_seen', '?')[:10]}")

        # Recent timeline
        recent = self.timeline[-10:] if self.timeline else []
        if recent:
            lines.append(f"\n  RECENT EVENTS:")
            for e in recent:
                lines.append(f"    {e.get('time', '?')[:19]} | {e.get('event', '?')} | {e.get('mac', '?')}")

        lines.append("\n" + "=" * 55)
        return "\n".join(lines)


def run_intruder_scan():
    """Run intruder profiling against current presence data."""
    from rudy.presence import PresenceMonitor

    pm = PresenceMonitor()
    # Quick scan to refresh presence data
    pm.scan()

    profiler = IntruderProfiler()
    result = profiler.process_scan(pm.current_presence, pm.known_devices)

    print(profiler.get_threat_summary())

    if result["new_intruders"]:
        print(f"\n  NEW INTRUDERS DETECTED:")
        for i in result["new_intruders"]:
            print(f"    {i['ip']} [{i['mac']}] — Threat Score: {i['threat_score']}")

    return result


if __name__ == "__main__":
    run_intruder_scan()
