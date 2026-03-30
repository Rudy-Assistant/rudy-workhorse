"""
WiFi Presence Monitor — tracks devices on the local network.

Scans the ARP table and local subnet to detect:
  - Known devices (family phones, laptops, etc.)
  - Unknown devices (potential concerns)
  - Arrival and departure events
  - Routine patterns over time

Data is stored in:
  - rudy-logs/presence-devices.json — known device registry
  - rudy-logs/presence-log.json — arrival/departure event history
  - rudy-logs/presence-current.json — who's here right now
  - rudy-logs/presence-routines.json — learned patterns (day-of-week averages)
"""
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path

DESKTOP = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
LOGS_DIR = DESKTOP / "rudy-logs"
LOGS_DIR.mkdir(exist_ok=True)

# Config — auto-detect subnet from active network
def _detect_subnet():
    """Detect current subnet dynamically (supports travel mode)."""
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        s.close()
        parts = local_ip.split(".")
        return ".".join(parts[:3])
    except Exception:
        return "192.168.7"  # Fallback to home subnet

def _detect_gateway():
    """Detect default gateway."""
    try:
        result = __import__("subprocess").run(
            "ipconfig", shell=True, capture_output=True, text=True, timeout=10
        )
        import re
        for line in result.stdout.splitlines():
            if "Default Gateway" in line:
                match = re.search(r"(\d+\.\d+\.\d+\.\d+)", line)
                if match:
                    return match.group(1)
    except Exception:
        pass
    return "192.168.7.1"

LOCAL_SUBNET = _detect_subnet()
GATEWAY = _detect_gateway()
SCAN_RANGE = range(1, 255)  # .1 through .254

# Files
DEVICES_FILE = LOGS_DIR / "presence-devices.json"
LOG_FILE = LOGS_DIR / "presence-log.json"
CURRENT_FILE = LOGS_DIR / "presence-current.json"
ROUTINES_FILE = LOGS_DIR / "presence-routines.json"

class PresenceMonitor:
    """WiFi-based presence detection via ARP scanning."""

    def __init__(self):
        self.known_devices = self._load_json(DEVICES_FILE, {})
        self.current_presence = self._load_json(CURRENT_FILE, {})
        self.event_log = self._load_json(LOG_FILE, [])
        self.routines = self._load_json(ROUTINES_FILE, {})

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

    def scan(self) -> dict:
        """
        Full presence scan cycle:
        1. Ping sweep to populate ARP table
        2. Read ARP table
        3. Compare to previous state
        4. Record arrivals/departures
        5. Update routines
        """
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Starting presence scan...")

        # Step 1: Quick ping sweep to refresh ARP cache
        # Use a batch approach — ping multiple hosts in parallel
        self._ping_sweep()

        # Step 2: Read the ARP table
        discovered = self._read_arp_table()
        print(f"  Discovered {len(discovered)} devices on network")

        # Step 3: Compare to previous state
        events = self._detect_changes(discovered)

        # Step 4: Update current state
        now = datetime.now().isoformat()
        new_presence = {}
        for mac, info in discovered.items():
            new_presence[mac] = {
                "mac": mac,
                "ip": info["ip"],
                "name": self.known_devices.get(mac, {}).get("name", "Unknown"),
                "type": self.known_devices.get(mac, {}).get("type", "unknown"),
                "last_seen": now,
                "first_seen_today": self.current_presence.get(mac, {}).get(
                    "first_seen_today", now
                ),
            }

        self.current_presence = new_presence
        self._save_json(CURRENT_FILE, self.current_presence)

        # Step 5: Update routines
        self._update_routines(discovered)

        # Step 6: Save event log (keep last 1000 events)
        self.event_log = self.event_log[-1000:]
        self._save_json(LOG_FILE, self.event_log)

        # Build summary
        known_present = sum(1 for m in new_presence if m in self.known_devices)
        unknown_present = sum(1 for m in new_presence if m not in self.known_devices)

        result = {
            "timestamp": now,
            "devices_found": len(discovered),
            "known_present": known_present,
            "unknown_present": unknown_present,
            "events": events,
            "devices": {
                mac: {
                    "name": info.get("name", "Unknown"),
                    "ip": info.get("ip"),
                    "type": info.get("type", "unknown"),
                }
                for mac, info in new_presence.items()
            },
        }

        return result

    def _ping_sweep(self):
        """Quick parallel ping sweep to populate the ARP cache."""
        print("  Running ping sweep...")
        # Use PowerShell for parallel pinging (much faster than sequential)
        # Test-Connection is slow, use raw ping with short timeout
        # Fallback: use simple ARP + targeted pings for common ranges
        # The ARP table often has most active devices already
        try:
            # First just refresh with a broadcast ping (Windows supports this poorly,
            # so we do targeted pings to common DHCP ranges)
            for i in [1, 2] + list(range(20, 35)) + list(range(100, 115)):
                subprocess.Popen(
                    f'ping -n 1 -w 500 {LOCAL_SUBNET}.{i}',
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            # Also ping the broadcast address
            subprocess.Popen(
                f'ping -n 1 -w 500 {LOCAL_SUBNET}.255',
                shell=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(3)  # Wait for pings to complete and ARP table to populate
        except Exception:
            pass

    def _read_arp_table(self) -> dict:
        """Read the Windows ARP table and extract MAC-to-IP mappings."""
        discovered = {}
        try:
            result = subprocess.run(
                "arp -a", shell=True, capture_output=True, text=True, timeout=10
            )
            # Parse ARP output
            # Format: "  192.168.7.1          aa-bb-cc-dd-ee-ff     dynamic"
            for line in result.stdout.splitlines():
                line = line.strip()
                match = re.match(
                    r'(\d+\.\d+\.\d+\.\d+)\s+([\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2}-[\da-f]{2})\s+(\w+)',
                    line, re.IGNORECASE
                )
                if match:
                    ip = match.group(1)
                    mac = match.group(2).lower()
                    entry_type = match.group(3)

                    # Skip broadcast and multicast MACs
                    if mac.startswith("ff-ff-ff") or mac.startswith("01-00-5e"):
                        continue
                    # Only include our subnet
                    if ip.startswith(f"{LOCAL_SUBNET}."):
                        discovered[mac] = {
                            "ip": ip,
                            "type": entry_type,
                            "seen_at": datetime.now().isoformat(),
                        }
        except Exception as e:
            print(f"  ARP scan failed: {e}")

        # Also try getmac for additional info
        try:
            result = subprocess.run(
                "getmac /v /fo csv", shell=True, capture_output=True, text=True, timeout=10
            )
            # This gives us the local machine's MACs too
        except Exception:
            pass

        return discovered

    def _detect_changes(self, discovered: dict) -> list:
        """Compare current scan to previous state, detect arrivals/departures."""
        events = []
        now = datetime.now()

        prev_macs = set(self.current_presence.keys())
        curr_macs = set(discovered.keys())

        # Arrivals
        for mac in curr_macs - prev_macs:
            name = self.known_devices.get(mac, {}).get("name", "Unknown Device")
            ip = discovered[mac]["ip"]
            is_known = mac in self.known_devices

            event = {
                "time": now.isoformat(),
                "type": "arrival",
                "mac": mac,
                "ip": ip,
                "name": name,
                "known": is_known,
            }
            events.append(event)
            self.event_log.append(event)

            if is_known:
                print(f"  ARRIVED: {name} ({ip}) [{mac}]")
            else:
                print(f"  ARRIVED: UNKNOWN DEVICE ({ip}) [{mac}]")

        # Departures
        for mac in prev_macs - curr_macs:
            name = self.known_devices.get(mac, {}).get("name", "Unknown Device")
            prev_ip = self.current_presence.get(mac, {}).get("ip", "?")
            is_known = mac in self.known_devices

            event = {
                "time": now.isoformat(),
                "type": "departure",
                "mac": mac,
                "ip": prev_ip,
                "name": name,
                "known": is_known,
            }
            events.append(event)
            self.event_log.append(event)

            if is_known:
                print(f"  DEPARTED: {name} ({prev_ip})")
            else:
                print(f"  DEPARTED: Unknown device ({prev_ip}) [{mac}]")

        if not events:
            print("  No changes since last scan")

        return events

    def _update_routines(self, discovered: dict):
        """Learn routines — track when each device is typically present."""
        now = datetime.now()
        day_name = now.strftime("%A")  # Monday, Tuesday, etc.
        hour = now.hour

        for mac in discovered:
            if mac not in self.routines:
                self.routines[mac] = {
                    "name": self.known_devices.get(mac, {}).get("name", "Unknown"),
                    "weekly": {d: [0] * 24 for d in [
                        "Monday", "Tuesday", "Wednesday", "Thursday",
                        "Friday", "Saturday", "Sunday"
                    ]},
                    "total_scans": 0,
                }

            self.routines[mac]["weekly"][day_name][hour] += 1
            self.routines[mac]["total_scans"] = self.routines[mac].get("total_scans", 0) + 1

        self._save_json(ROUTINES_FILE, self.routines)

    def register_device(self, mac: str, name: str, device_type: str = "phone",
                        owner: str = "unknown"):
        """Register a known device."""
        mac = mac.lower()
        self.known_devices[mac] = {
            "name": name,
            "type": device_type,  # phone, laptop, tablet, iot, router
            "owner": owner,
            "registered": datetime.now().isoformat(),
        }
        self._save_json(DEVICES_FILE, self.known_devices)
        print(f"Registered: {name} ({mac}) — {device_type} owned by {owner}")

    def get_presence_summary(self) -> str:
        """Human-readable summary of who's home."""
        if not self.current_presence:
            return "No presence data available (run a scan first)"

        lines = [f"Presence Summary — {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
        lines.append("-" * 40)

        known = []
        unknown = []

        for mac, info in self.current_presence.items():
            if mac in self.known_devices:
                known.append(info)
            else:
                unknown.append(info)

        if known:
            lines.append(f"\nKnown devices ({len(known)}):")
            for d in known:
                lines.append(f"  {d['name']} — {d['ip']} [{d['mac']}]")

        if unknown:
            lines.append(f"\nUnknown devices ({len(unknown)}):")
            for d in unknown:
                lines.append(f"  {d['ip']} [{d['mac']}] (first seen: {d.get('first_seen_today', '?')[:16]})")

        return "\n".join(lines)

# Convenience function for command runner invocation
def run_scan(run_analytics=True):
    """Run a single presence scan, optionally followed by analytics."""
    monitor = PresenceMonitor()
    result = monitor.scan()
    print(f"\n{monitor.get_presence_summary()}")

    # Run analytics after each scan to update inferences
    if run_analytics:
        try:
            from rudy.presence_analytics import PresenceAnalytics
            analytics = PresenceAnalytics()
            analytics.run()
            print("  [Analytics] Inference cycle complete")
        except Exception as e:
            print(f"  [Analytics] Warning: {e}")

        # Run intruder profiling on unknown devices
        try:
            from rudy.intruder_profiler import IntruderProfiler
            profiler = IntruderProfiler()
            threat = profiler.process_scan(monitor.current_presence, monitor.known_devices)
            level = threat.get("threat_level", "green")
            unknowns = threat.get("unknown", 0)
            new_intruders = len(threat.get("new_intruders", []))
            if new_intruders > 0:
                print(f"  [Intruder] {new_intruders} NEW unknown device(s) profiled! Level: {level.upper()}")
            elif unknowns > 0:
                print(f"  [Intruder] {unknowns} uncleared device(s) on network. Level: {level.upper()}")
            else:
                print("  [Intruder] Network clear.")
        except Exception as e:
            print(f"  [Intruder] Warning: {e}")

    return result

if __name__ == "__main__":
    run_scan()
