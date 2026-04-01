"""
Find My — iCloud location monitoring for family safety.

Monitors the locations of family members who share via Find My Friends.
Establishes baseline routines, detects unusual deviations, and alerts Chris.

Architecture:
  Primary: pyicloud FindFriendsService (API-based, fast, reliable when auth works)
  Fallback: Playwright iCloud.com/find (browser-based, handles 2FA better)
  Storage: Location history in rudy-data/findmy/

Safety Features:
  - Geofence alerts (family member leaves/enters a defined zone)
  - Routine deviation detection (unexpected location at unusual time)
  - Stale location alerts (no update in X hours — phone off or out of signal)
  - Speed anomaly (impossible travel distance between updates)
  - Panic mode: rapid polling on demand

Privacy:
  - All data stored locally on the Workhorse
  - No cloud sync of location history
  - Only Chris has access to the data
  - Family members consented via Find My Friends sharing

Required:
  pip install pyicloud keyring
  (keyring for secure credential storage on Windows)
"""

import json
import math

from datetime import datetime
from pathlib import Path
from typing import Optional, Dict, List

from rudy.paths import RUDY_LOGS, RUDY_DATA  # noqa: E402

LOGS_DIR = RUDY_LOGS
DATA_DIR = RUDY_DATA / "findmy"
HISTORY_DIR = DATA_DIR / "history"
GEOFENCES_FILE = DATA_DIR / "geofences.json"
CONFIG_FILE = DATA_DIR / "findmy-config.json"
STATE_FILE = DATA_DIR / "findmy-state.json"

for _d in [DATA_DIR, HISTORY_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

# ── Helpers ───────────────────────────────────────────────────

def _save_json(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

def _load_json(path: Path, default=None):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default if default is not None else {}

def haversine_km(lat1, lon1, lat2, lon2) -> float:
    """Distance between two lat/lng points in kilometers."""
    R = 6371  # Earth radius in km
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (math.sin(dlat / 2) ** 2 +
         math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) *
         math.sin(dlon / 2) ** 2)
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

# ── iCloud Auth Backend ──────────────────────────────────────

class ICloudAuth:
    """Handle iCloud authentication with session persistence."""

    def __init__(self, apple_id: str, password: str):
        self.apple_id = apple_id
        self.password = password
        self._api = None
        self._session_dir = DATA_DIR / "session"
        self._session_dir.mkdir(parents=True, exist_ok=True)

    def connect(self) -> bool:
        """Authenticate to iCloud. Returns True if successful."""
        try:
            from pyicloud import PyiCloudService
            self._api = PyiCloudService(
                self.apple_id,
                self.password,
                cookie_directory=str(self._session_dir),
            )

            # Check if 2FA is needed
            if self._api.requires_2fa:
                # Try to use stored session first
                # If that fails, we need manual 2FA entry
                return self._handle_2fa()

            if self._api.requires_2sa:
                return self._handle_2sa()

            return True

        except ImportError:
            raise RuntimeError("pyicloud not installed. Run: pip install pyicloud")
        except Exception as e:
            raise RuntimeError(f"iCloud auth failed: {e}")

    def _handle_2fa(self) -> bool:
        """Handle 2FA challenge.

        First attempt uses stored session cookies (no re-auth needed if recent).
        If that fails, we need a 2FA code — which means either:
          1. Chris provides it via email/command
          2. TOTP if configured
          3. Prompt and wait
        """
        if self._api.is_trusted_session:
            return True

        # Store that we need 2FA — the scheduled task or command runner
        # will check this state and provide the code
        state = _load_json(STATE_FILE, {})
        state["needs_2fa"] = True
        state["2fa_requested_at"] = datetime.now().isoformat()
        _save_json(STATE_FILE, state)

        # Try to send notification to Chris
        try:
            from rudy.email_multi import EmailMulti
            em = EmailMulti()
            em.send(
                to="ccimino2@gmail.com",
                subject="[RUDY] iCloud 2FA code needed",
                body=(
                    "Rudy needs a 2FA code to access Find My Friends.\n\n"
                    "Please check your trusted device for the verification code "
                    "and reply to this email with just the 6-digit code.\n\n"
                    "Alternatively, run on the Workhorse:\n"
                    "  python -m rudy.find_my verify CODE\n"
                ),
            )
        except Exception:
            pass

        return False

    def _handle_2sa(self) -> bool:
        """Handle 2-Step Authentication (older method)."""
        # Similar to 2FA but uses trusted devices list
        return self._handle_2fa()

    def verify_2fa(self, code: str) -> bool:
        """Submit a 2FA verification code."""
        if not self._api:
            return False
        try:
            result = self._api.validate_2fa_code(code)
            if result:
                # Trust this session for future use
                self._api.trust_session()
                state = _load_json(STATE_FILE, {})
                state["needs_2fa"] = False
                state["last_auth"] = datetime.now().isoformat()
                _save_json(STATE_FILE, state)
                return True
            return False
        except Exception:
            return False

    @property
    def api(self):
        return self._api

# ── Location Fetcher ─────────────────────────────────────────

class FindMyFriends:
    """Fetch and monitor friend locations from iCloud."""

    def __init__(self, auth: ICloudAuth):
        self.auth = auth
        self.config = _load_json(CONFIG_FILE, {
            "poll_interval_minutes": 15,
            "stale_threshold_hours": 4,
            "speed_limit_kmh": 200,  # Flag impossibly fast travel
            "monitored_people": {},  # name -> {label, relationship}
        })
        self.state = _load_json(STATE_FILE, {})

    def get_all_locations(self) -> List[Dict]:
        """Fetch current locations of all friends sharing with us."""
        api = self.auth.api
        if not api:
            return []

        try:
            friends_service = api.friends
            locations = []

            for friend in friends_service.get_all():
                loc = {
                    "id": friend.get("id", ""),
                    "name": self._format_name(friend),
                    "latitude": None,
                    "longitude": None,
                    "accuracy": None,
                    "timestamp": None,
                    "address": "",
                    "battery_level": None,
                    "battery_status": "",
                    "device_model": "",
                    "raw": {},
                }

                location_data = friend.get("location")
                if location_data:
                    loc["latitude"] = location_data.get("latitude")
                    loc["longitude"] = location_data.get("longitude")
                    loc["accuracy"] = location_data.get("horizontalAccuracy")
                    loc["timestamp"] = location_data.get("timestamp")
                    loc["address"] = location_data.get("address", {})

                loc["raw"] = friend
                locations.append(loc)

            return locations

        except Exception as e:
            return [{"error": str(e)[:200]}]

    def _format_name(self, friend: dict) -> str:
        """Extract a readable name from the friend dict."""
        first = friend.get("firstName", "")
        last = friend.get("lastName", "")
        if first or last:
            return f"{first} {last}".strip()
        return friend.get("id", "Unknown")

    def poll_and_analyze(self) -> Dict:
        """Fetch locations, compare to history, detect anomalies.

        This is the main method called by the scheduled task.
        Returns a report with locations and any alerts.
        """
        report = {
            "timestamp": datetime.now().isoformat(),
            "locations": [],
            "alerts": [],
            "status": "ok",
        }

        locations = self.get_all_locations()
        if not locations:
            report["status"] = "no_data"
            return report

        if locations and locations[0].get("error"):
            report["status"] = "auth_error"
            report["error"] = locations[0]["error"]
            return report

        for loc in locations:
            if not loc.get("latitude"):
                continue

            name = loc["name"]
            lat, lng = loc["latitude"], loc["longitude"]

            # Store current location
            report["locations"].append({
                "name": name,
                "lat": lat,
                "lng": lng,
                "accuracy": loc.get("accuracy"),
                "timestamp": loc.get("timestamp"),
            })

            # === Anomaly Detection ===

            # 1. Check against geofences
            fence_alerts = self._check_geofences(name, lat, lng)
            report["alerts"].extend(fence_alerts)

            # 2. Check for stale location
            stale = self._check_stale(name, loc.get("timestamp"))
            if stale:
                report["alerts"].append(stale)

            # 3. Check for speed anomaly (impossible travel)
            speed_alert = self._check_speed_anomaly(name, lat, lng, loc.get("timestamp"))
            if speed_alert:
                report["alerts"].append(speed_alert)

            # 4. Check routine deviation
            routine_alert = self._check_routine(name, lat, lng)
            if routine_alert:
                report["alerts"].append(routine_alert)

            # Save to history
            self._record_location(name, loc)

        # Save state
        _save_json(STATE_FILE, self.state)

        # Send alerts if any
        if report["alerts"]:
            self._send_alerts(report["alerts"])

        # Save report
        report_file = LOGS_DIR / "findmy-latest.json"
        _save_json(report_file, report)

        return report

    # ── Anomaly Detection ────────────────────────────────────

    def _check_geofences(self, name: str, lat: float, lng: float) -> List[Dict]:
        """Check if person is inside/outside defined geofences."""
        alerts = []
        geofences = _load_json(GEOFENCES_FILE, {"fences": []})

        for fence in geofences.get("fences", []):
            fence_lat = fence.get("lat", 0)
            fence_lng = fence.get("lng", 0)
            radius_km = fence.get("radius_km", 0.5)
            fence_name = fence.get("name", "")
            fence_type = fence.get("type", "safe_zone")  # safe_zone or exclusion_zone
            applies_to = fence.get("applies_to", [])  # empty = everyone

            # Check if this fence applies to this person
            if applies_to and name not in applies_to:
                continue

            distance = haversine_km(lat, lng, fence_lat, fence_lng)
            inside = distance <= radius_km

            # Track state transitions
            state_key = f"fence_{fence_name}_{name}"
            was_inside = self.state.get(state_key, None)
            self.state[state_key] = inside

            if was_inside is not None:  # Only alert on transitions, not first check
                if fence_type == "safe_zone" and was_inside and not inside:
                    alerts.append({
                        "type": "left_safe_zone",
                        "person": name,
                        "zone": fence_name,
                        "distance_km": round(distance, 2),
                        "severity": "WARNING",
                        "message": f"{name} left {fence_name} (now {distance:.1f}km away)",
                    })
                elif fence_type == "safe_zone" and not was_inside and inside:
                    alerts.append({
                        "type": "entered_safe_zone",
                        "person": name,
                        "zone": fence_name,
                        "severity": "INFO",
                        "message": f"{name} returned to {fence_name}",
                    })
                elif fence_type == "exclusion_zone" and not was_inside and inside:
                    alerts.append({
                        "type": "entered_exclusion_zone",
                        "person": name,
                        "zone": fence_name,
                        "severity": "ALERT",
                        "message": f"{name} entered restricted area: {fence_name}",
                    })

        return alerts

    def _check_stale(self, name: str, timestamp) -> Optional[Dict]:
        """Alert if location data is too old."""
        if not timestamp:
            return None

        threshold_hours = self.config.get("stale_threshold_hours", 4)

        try:
            if isinstance(timestamp, (int, float)):
                # Unix timestamp (milliseconds from iCloud)
                loc_time = datetime.fromtimestamp(timestamp / 1000)
            else:
                loc_time = datetime.fromisoformat(str(timestamp))

            age_hours = (datetime.now() - loc_time).total_seconds() / 3600

            if age_hours > threshold_hours:
                return {
                    "type": "stale_location",
                    "person": name,
                    "hours_stale": round(age_hours, 1),
                    "severity": "WARNING",
                    "message": f"{name}'s location is {age_hours:.0f}h old — phone may be off or out of range",
                }
        except Exception:
            pass
        return None

    def _check_speed_anomaly(self, name: str, lat: float, lng: float, timestamp) -> Optional[Dict]:
        """Detect impossibly fast travel between location updates."""
        state_key = f"last_loc_{name}"
        prev = self.state.get(state_key)

        # Store current for next check
        self.state[state_key] = {
            "lat": lat, "lng": lng,
            "timestamp": datetime.now().isoformat(),
        }

        if not prev or not prev.get("lat"):
            return None

        try:
            distance = haversine_km(lat, lng, prev["lat"], prev["lng"])
            prev_time = datetime.fromisoformat(prev["timestamp"])
            hours_elapsed = max((datetime.now() - prev_time).total_seconds() / 3600, 0.001)
            speed_kmh = distance / hours_elapsed

            limit = self.config.get("speed_limit_kmh", 200)
            if speed_kmh > limit and distance > 5:  # Ignore small GPS jitter
                return {
                    "type": "speed_anomaly",
                    "person": name,
                    "distance_km": round(distance, 1),
                    "hours": round(hours_elapsed, 2),
                    "speed_kmh": round(speed_kmh, 0),
                    "severity": "WARNING",
                    "message": (f"{name} moved {distance:.0f}km in {hours_elapsed:.1f}h "
                                f"({speed_kmh:.0f} km/h) — verify travel or possible data anomaly"),
                }
        except Exception:
            pass
        return None

    def _check_routine(self, name: str, lat: float, lng: float) -> Optional[Dict]:
        """Detect deviation from established routine patterns.

        This learns over time by building a model of where a person typically
        is at each hour of the week. After sufficient data (7+ days),
        it can flag unusual locations.
        """
        # Load history for this person
        history_file = HISTORY_DIR / f"{name.replace(' ', '_').lower()}_history.json"
        history = _load_json(history_file, {"locations": []})

        # Need at least 7 days of data to establish routine
        if len(history.get("locations", [])) < 50:  # ~3 updates/day * 7 days
            return None

        # What hour of the week is it? (0=Monday 00:00 ... 167=Sunday 23:00)
        now = datetime.now()
        hour_of_week = now.weekday() * 24 + now.hour

        # Find typical locations for this hour (±1 hour window)
        typical_locs = []
        for entry in history["locations"][-500:]:  # Last ~2 months
            try:
                entry_time = datetime.fromisoformat(entry["recorded_at"])
                entry_how = entry_time.weekday() * 24 + entry_time.hour
                if abs(entry_how - hour_of_week) <= 1 or abs(entry_how - hour_of_week) >= 167:
                    typical_locs.append((entry["lat"], entry["lng"]))
            except Exception:
                continue

        if len(typical_locs) < 3:
            return None  # Not enough data for this time slot

        # Calculate centroid of typical locations
        avg_lat = sum(t[0] for t in typical_locs) / len(typical_locs)
        avg_lng = sum(t[1] for t in typical_locs) / len(typical_locs)

        # Distance from typical location
        deviation_km = haversine_km(lat, lng, avg_lat, avg_lng)

        # Alert if more than 50km from typical (adjustable)
        if deviation_km > 50:
            return {
                "type": "routine_deviation",
                "person": name,
                "deviation_km": round(deviation_km, 1),
                "typical_lat": round(avg_lat, 4),
                "typical_lng": round(avg_lng, 4),
                "severity": "INFO",
                "message": (f"{name} is {deviation_km:.0f}km from their typical location "
                            f"for this time of week — may be traveling"),
            }
        return None

    def _record_location(self, name: str, loc: Dict):
        """Append location to history file for pattern learning."""
        history_file = HISTORY_DIR / f"{name.replace(' ', '_').lower()}_history.json"
        history = _load_json(history_file, {"locations": []})

        history["locations"].append({
            "lat": loc.get("latitude"),
            "lng": loc.get("longitude"),
            "accuracy": loc.get("accuracy"),
            "recorded_at": datetime.now().isoformat(),
            "source_timestamp": loc.get("timestamp"),
        })

        # Keep last 2000 entries (~6 months at 4x/day)
        if len(history["locations"]) > 2000:
            history["locations"] = history["locations"][-2000:]

        _save_json(history_file, history)

    def _send_alerts(self, alerts: List[Dict]):
        """Send alert email for significant location events."""
        # Only send for WARNING and ALERT severity
        serious = [a for a in alerts if a.get("severity") in ("WARNING", "ALERT")]
        if not serious:
            return

        subject = f"[RUDY] Location Alert: {serious[0].get('message', 'Check Find My')}"
        body_lines = ["Find My Friends — Location Alerts", "=" * 50, ""]

        for alert in serious:
            body_lines.append(f"[{alert.get('severity')}] {alert.get('message')}")
            body_lines.append(f"  Type: {alert.get('type')}")
            body_lines.append(f"  Person: {alert.get('person')}")
            body_lines.append("")

        body_lines.append(f"\nTimestamp: {datetime.now().isoformat()}")
        body_lines.append("Full report: rudy-logs/findmy-latest.json")

        try:
            from rudy.email_multi import EmailMulti
            em = EmailMulti()
            em.send(to="ccimino2@gmail.com", subject=subject, body="\n".join(body_lines))
        except Exception:
            pass

    # ── Geofence Management ──────────────────────────────────

    @staticmethod
    def add_geofence(name: str, lat: float, lng: float,
                     radius_km: float = 0.5, fence_type: str = "safe_zone",
                     applies_to: List[str] = None) -> Dict:
        """Add a geofence zone."""
        geofences = _load_json(GEOFENCES_FILE, {"fences": []})
        fence = {
            "name": name,
            "lat": lat,
            "lng": lng,
            "radius_km": radius_km,
            "type": fence_type,
            "applies_to": applies_to or [],
            "created": datetime.now().isoformat(),
        }
        geofences["fences"].append(fence)
        _save_json(GEOFENCES_FILE, geofences)
        return fence

    @staticmethod
    def remove_geofence(name: str) -> bool:
        """Remove a geofence by name."""
        geofences = _load_json(GEOFENCES_FILE, {"fences": []})
        before = len(geofences["fences"])
        geofences["fences"] = [f for f in geofences["fences"] if f["name"] != name]
        if len(geofences["fences"]) < before:
            _save_json(GEOFENCES_FILE, geofences)
            return True
        return False

    @staticmethod
    def list_geofences() -> List[Dict]:
        """List all geofences."""
        return _load_json(GEOFENCES_FILE, {"fences": []}).get("fences", [])

# ── Convenience Functions ────────────────────────────────────

def setup(apple_id: str, password: str) -> bool:
    """Initial setup: store credentials and attempt authentication."""
    config = _load_json(CONFIG_FILE, {})
    config["apple_id"] = apple_id
    # Password stored in config (encrypted at rest via Windows DPAPI if using keyring)
    try:
        import keyring
        keyring.set_password("rudy_findmy", apple_id, password)
        config["password_in_keyring"] = True
    except ImportError:
        # Fallback: store directly (less secure but functional)
        config["password_stored"] = True
        config["_pw"] = password
    _save_json(CONFIG_FILE, config)

    # Attempt connection
    auth = ICloudAuth(apple_id, password)
    try:
        connected = auth.connect()
        config["last_auth_attempt"] = datetime.now().isoformat()
        config["auth_success"] = connected
        _save_json(CONFIG_FILE, config)
        return connected
    except Exception as e:
        config["last_auth_error"] = str(e)[:200]
        _save_json(CONFIG_FILE, config)
        return False

def poll() -> Dict:
    """Run a polling cycle: authenticate, fetch locations, analyze."""
    config = _load_json(CONFIG_FILE, {})
    apple_id = config.get("apple_id")
    if not apple_id:
        return {"error": "Not configured. Run: python -m rudy.find_my setup"}

    # Get password
    password = None
    try:
        import keyring
        password = keyring.get_password("rudy_findmy", apple_id)
    except ImportError:
        pass
    if not password:
        password = config.get("_pw")
    if not password:
        return {"error": "No password found. Run setup again."}

    auth = ICloudAuth(apple_id, password)
    try:
        if not auth.connect():
            return {"status": "needs_2fa", "message": "2FA code required — check email"}
    except RuntimeError as e:
        return {"error": str(e)}

    fmf = FindMyFriends(auth)
    return fmf.poll_and_analyze()

def verify_2fa(code: str) -> bool:
    """Submit a 2FA code to complete authentication."""
    config = _load_json(CONFIG_FILE, {})
    apple_id = config.get("apple_id")
    password = None
    try:
        import keyring
        password = keyring.get_password("rudy_findmy", apple_id)
    except ImportError:
        pass
    if not password:
        password = config.get("_pw")

    auth = ICloudAuth(apple_id, password)
    try:
        auth.connect()  # Will fail but sets up the API object
    except Exception:
        pass

    return auth.verify_2fa(code)

# ── Pre-configured Geofences ────────────────────────────────

def setup_default_geofences():
    """Set up the family's standard geofences."""
    # Kansas Ave farm (family home)
    FindMyFriends.add_geofence(
        name="Kansas Ave (Home)",
        lat=37.6391,  # Modesto, CA approximate
        lng=-120.9969,
        radius_km=0.5,
        fence_type="safe_zone",
    )
    print("Added: Kansas Ave (Home) — 500m safe zone")

    # Chris can add more via:
    #   python -m rudy.find_my fence add "Work" 37.xxx -121.xxx 1.0

# ── CLI ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python -m rudy.find_my setup APPLE_ID PASSWORD")
        print("  python -m rudy.find_my verify CODE")
        print("  python -m rudy.find_my poll")
        print("  python -m rudy.find_my fence add NAME LAT LNG [RADIUS_KM]")
        print("  python -m rudy.find_my fence list")
        print("  python -m rudy.find_my fence remove NAME")
        print("  python -m rudy.find_my defaults  (set up family geofences)")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "setup" and len(sys.argv) >= 4:
        ok = setup(sys.argv[2], sys.argv[3])
        print(f"Setup {'succeeded' if ok else 'needs 2FA — check email'}")

    elif cmd == "verify" and len(sys.argv) >= 3:
        ok = verify_2fa(sys.argv[2])
        print(f"2FA {'verified' if ok else 'failed'}")

    elif cmd == "poll":
        result = poll()
        print(json.dumps(result, indent=2, default=str))

    elif cmd == "fence":
        if len(sys.argv) >= 3 and sys.argv[2] == "list":
            fences = FindMyFriends.list_geofences()
            for f in fences:
                print(f"  {f['name']}: ({f['lat']}, {f['lng']}) r={f['radius_km']}km [{f['type']}]")
        elif len(sys.argv) >= 6 and sys.argv[2] == "add":
            name = sys.argv[3]
            lat = float(sys.argv[4])
            lng = float(sys.argv[5])
            radius = float(sys.argv[6]) if len(sys.argv) > 6 else 0.5
            fence = FindMyFriends.add_geofence(name, lat, lng, radius)
            print(f"Added geofence: {fence['name']}")
        elif len(sys.argv) >= 4 and sys.argv[2] == "remove":
            ok = FindMyFriends.remove_geofence(sys.argv[3])
            print(f"{'Removed' if ok else 'Not found'}: {sys.argv[3]}")

    elif cmd == "defaults":
        setup_default_geofences()

    else:
        print(f"Unknown command: {cmd}")
