"""
Home Assistant Bridge -- Andrew-Readiness Phase 2, Step 7.

Connects Robin to a Home Assistant instance via REST API,
enabling voice-controlled smart home operations for Andrew.
Control lights, locks, thermostat, TV, cameras, and more
through natural voice commands routed by the voice daemon.

Architecture:
    Voice Daemon -> IntentRouter (domain=smart_home)
    -> HomeAssistantBridge -> HA REST API -> Device action
    -> Voice confirmation back to Andrew

Configuration:
    Set HA_URL and HA_TOKEN in voice-daemon-config.json or
    ha-bridge-config.json in RUDY_DATA, or via environment
    variables HASS_URL and HASS_TOKEN.

Session 137: Phase 2 Step 7 of Andrew-Readiness (ADR-020).

Dependencies:
    - rudy.paths (canonical paths)
    - urllib.request (stdlib -- no external HTTP library needed)
    - json, logging (stdlib)
"""

import json
import logging
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
import urllib.request

try:
    from rudy.paths import RUDY_DATA
except ImportError:
    RUDY_DATA = Path(__file__).resolve().parent.parent / "rudy-data"

log = logging.getLogger("ha_bridge")

# Config file path
HA_CONFIG_PATH = RUDY_DATA / "ha-bridge-config.json"

DEFAULT_CONFIG = {
    "ha_url": "http://homeassistant.local:8123",
    "ha_token": "",
    "request_timeout": 10,
    "cache_ttl_seconds": 300,
    "friendly_name_aliases": {},
}


def load_ha_config() -> dict:
    """Load HA bridge config from file, env vars, or defaults."""
    config = DEFAULT_CONFIG.copy()
    if HA_CONFIG_PATH.exists():
        try:
            with open(HA_CONFIG_PATH, encoding="utf-8") as f:
                config.update(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            log.warning("HA config load failed: %s", e)
    # Environment overrides (highest priority)
    if os.environ.get("HASS_URL"):
        config["ha_url"] = os.environ["HASS_URL"]
    if os.environ.get("HASS_TOKEN"):
        config["ha_token"] = os.environ["HASS_TOKEN"]
    return config


def save_ha_config(config: dict) -> None:
    """Persist HA bridge config to JSON."""
    HA_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(HA_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


# -------------------------------------------------------------------
# HA REST API Client
# -------------------------------------------------------------------

class HAClient:
    """Low-level HTTP client for Home Assistant REST API.

    Uses stdlib urllib only -- no requests/httpx dependency.
    All methods return parsed JSON or raise HAError.
    """

    def __init__(self, url: str, token: str, timeout: int = 10):
        self.url = url.rstrip("/")
        self.token = token
        self.timeout = timeout

    def _headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, path: str,
                 data: dict | None = None) -> dict | list:
        """Make an HTTP request to HA API."""
        full_url = f"{self.url}/api{path}"
        body = json.dumps(data).encode() if data else None
        req = urllib.request.Request(
            full_url, data=body, headers=self._headers(),
            method=method,
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except HTTPError as e:
            body = e.read().decode() if e.fp else ""
            raise HAError(
                f"HA API {method} {path}: HTTP {e.code}: {body[:200]}"
            ) from e
        except URLError as e:
            raise HAError(
                f"HA API connection failed: {e.reason}"
            ) from e
        except json.JSONDecodeError as e:
            raise HAError(f"HA API bad JSON: {e}") from e

    def get(self, path: str) -> dict | list:
        return self._request("GET", path)

    def post(self, path: str, data: dict | None = None) -> dict | list:
        return self._request("POST", path, data)

    def check_connection(self) -> dict:
        """Verify HA API is reachable. Returns API status."""
        return self.get("/")


class HAError(Exception):
    """Error communicating with Home Assistant."""
    pass


# -------------------------------------------------------------------
# Entity Discovery and Caching
# -------------------------------------------------------------------

class EntityCache:
    """Cache HA entity states with TTL to avoid excessive API calls."""

    def __init__(self, client: HAClient, ttl: int = 300):
        self.client = client
        self.ttl = ttl
        self._cache: list[dict] = []
        self._last_refresh: float = 0.0

    def refresh(self, force: bool = False) -> list[dict]:
        """Fetch all entity states from HA."""
        now = time.time()
        if not force and self._cache and (now - self._last_refresh) < self.ttl:
            return self._cache
        try:
            self._cache = self.client.get("/states")
            self._last_refresh = now
            log.info("Entity cache refreshed: %d entities", len(self._cache))
        except HAError as e:
            log.warning("Entity refresh failed: %s", e)
        return self._cache

    def find_entity(self, name: str,
                    domain: str | None = None) -> dict | None:
        """Find an entity by friendly name or entity_id.

        Searches friendly_name first, then entity_id. Case-insensitive.
        If domain is given, restricts to that HA domain (e.g. 'light').
        """
        entities = self.refresh()
        name_lower = name.lower().strip()
        best = None
        for entity in entities:
            eid = entity.get("entity_id", "")
            attrs = entity.get("attributes", {})
            friendly = attrs.get("friendly_name", "").lower()
            if domain and not eid.startswith(f"{domain}."):
                continue
            if name_lower == friendly or name_lower == eid:
                return entity
            if name_lower in friendly or name_lower in eid:
                best = entity
        return best

    def get_entity(self, entity_id: str) -> dict | None:
        """Get a specific entity by ID (uses cache)."""
        entities = self.refresh()
        for e in entities:
            if e.get("entity_id") == entity_id:
                return e
        return None

    def list_by_domain(self, domain: str) -> list[dict]:
        """List all entities for a given HA domain."""
        entities = self.refresh()
        return [
            e for e in entities
            if e.get("entity_id", "").startswith(f"{domain}.")
        ]

    def summarize_domains(self) -> dict[str, int]:
        """Count entities per domain for discovery."""
        entities = self.refresh()
        counts: dict[str, int] = {}
        for e in entities:
            eid = e.get("entity_id", "")
            domain = eid.split(".")[0] if "." in eid else "unknown"
            counts[domain] = counts.get(domain, 0) + 1
        return counts


# -------------------------------------------------------------------
# Smart Home Command Executor
# -------------------------------------------------------------------

DOMAIN_SERVICES = {
    "light": {
        "on": "turn_on", "off": "turn_off", "toggle": "toggle",
        "brightness": "turn_on",
    },
    "switch": {
        "on": "turn_on", "off": "turn_off", "toggle": "toggle",
    },
    "lock": {
        "lock": "lock", "unlock": "unlock",
    },
    "cover": {
        "open": "open_cover", "close": "close_cover",
        "stop": "stop_cover",
    },
    "climate": {
        "heat": "set_hvac_mode", "cool": "set_hvac_mode",
        "off": "turn_off", "on": "turn_on",
        "temperature": "set_temperature",
    },
    "media_player": {
        "on": "turn_on", "off": "turn_off",
        "play": "media_play", "pause": "media_pause",
        "stop": "media_stop", "volume": "volume_set",
        "mute": "volume_mute", "next": "media_next_track",
        "previous": "media_previous_track",
    },
    "fan": {
        "on": "turn_on", "off": "turn_off", "toggle": "toggle",
    },
    "scene": {
        "activate": "turn_on",
    },
    "script": {
        "run": "turn_on",
    },
}


# Voice-friendly action aliases (Andrew says -> HA action)
ACTION_ALIASES = {
    "turn on": "on", "switch on": "on", "enable": "on",
    "turn off": "off", "switch off": "off", "disable": "off",
    "dim": "brightness", "brighten": "brightness",
    "lock": "lock", "unlock": "unlock",
    "open": "open", "close": "close",
    "set temperature": "temperature", "set temp": "temperature",
    "warmer": "heat", "cooler": "cool",
    "play": "play", "pause": "pause", "stop": "stop",
    "mute": "mute", "unmute": "mute",
    "volume up": "volume", "volume down": "volume",
    "next": "next", "skip": "next", "previous": "previous",
    "activate": "activate", "run": "run",
}


class HomeAssistantBridge:
    """Main bridge between Robin and Home Assistant.

    Handles entity discovery, command execution, and
    voice-friendly status queries for Andrew.
    """

    def __init__(self, config: dict | None = None):
        self.config = config or load_ha_config()
        url = self.config.get("ha_url", DEFAULT_CONFIG["ha_url"])
        token = self.config.get("ha_token", "")
        timeout = self.config.get(
            "request_timeout", DEFAULT_CONFIG["request_timeout"]
        )
        self.client = HAClient(url, token, timeout)
        cache_ttl = self.config.get(
            "cache_ttl_seconds", DEFAULT_CONFIG["cache_ttl_seconds"]
        )
        self.cache = EntityCache(self.client, cache_ttl)
        self.aliases = self.config.get("friendly_name_aliases", {})
        self._connected = False

    def connect(self) -> dict:
        """Test connection to HA and return API status."""
        try:
            status = self.client.check_connection()
            self._connected = True
            log.info("Connected to HA: %s", status.get("message", "OK"))
            return {"connected": True, "status": status}
        except HAError as e:
            self._connected = False
            log.warning("HA connection failed: %s", e)
            return {"connected": False, "error": str(e)}

    @property
    def is_connected(self) -> bool:
        return self._connected

    def execute_command(self, action: str, target: str,
                        params: dict | None = None) -> dict:
        """Execute a smart home command.

        Args:
            action: What to do (e.g. "on", "off", "lock",
                    "temperature", "brightness", "play")
            target: Device name or entity_id (e.g. "bedroom light",
                    "light.bedroom", "front door lock")
            params: Optional parameters (e.g. {"brightness": 128},
                    {"temperature": 72})

        Returns:
            Result dict with success status and voice-friendly message.
        """
        # Resolve action alias
        action_key = ACTION_ALIASES.get(action.lower(), action.lower())

        # Resolve target name alias
        resolved_target = self.aliases.get(target.lower(), target)

        # Find the entity
        entity = self.cache.find_entity(resolved_target)
        if not entity:
            return {
                "success": False,
                "message": f"I couldn't find a device called {target}.",
                "error": "entity_not_found",
            }

        entity_id = entity["entity_id"]
        ha_domain = entity_id.split(".")[0]
        friendly = entity.get("attributes", {}).get(
            "friendly_name", entity_id
        )

        # Find the HA service to call
        domain_services = DOMAIN_SERVICES.get(ha_domain, {})
        service_name = domain_services.get(action_key)
        if not service_name:
            return {
                "success": False,
                "message": (
                    f"I don't know how to {action} the {friendly}."
                ),
                "error": "unsupported_action",
            }

        # Build service data
        service_data = {"entity_id": entity_id}
        if params:
            service_data.update(params)

        # Special parameter handling
        if action_key == "brightness" and "brightness" not in service_data:
            service_data["brightness"] = 128
        if action_key == "temperature" and "temperature" not in service_data:
            service_data["temperature"] = 72
        if action_key in ("heat", "cool"):
            service_data["hvac_mode"] = action_key

        # Call the HA service
        try:
            self.client.post(
                f"/services/{ha_domain}/{service_name}",
                service_data,
            )
            # Invalidate cache for this entity
            self.cache._last_refresh = 0.0
            msg = self._build_confirmation(
                action_key, friendly, ha_domain, params
            )
            log.info("HA command OK: %s/%s -> %s",
                     ha_domain, service_name, entity_id)
            return {
                "success": True,
                "message": msg,
                "entity_id": entity_id,
                "service": f"{ha_domain}.{service_name}",
            }
        except HAError as e:
            log.error("HA command failed: %s", e)
            return {
                "success": False,
                "message": f"Sorry, I couldn't control the {friendly}.",
                "error": str(e),
            }

    def _build_confirmation(self, action: str, friendly: str,
                            domain: str,
                            params: dict | None = None) -> str:
        """Build a voice-friendly confirmation message."""
        if action == "on":
            return f"The {friendly} is now on."
        elif action == "off":
            return f"The {friendly} is now off."
        elif action == "toggle":
            return f"I've toggled the {friendly}."
        elif action == "lock":
            return f"The {friendly} is now locked."
        elif action == "unlock":
            return f"The {friendly} is now unlocked."
        elif action == "brightness":
            level = params.get("brightness", 128) if params else 128
            pct = int(level / 255 * 100)
            return f"The {friendly} is set to {pct} percent."
        elif action == "temperature":
            temp = params.get("temperature", 72) if params else 72
            return f"The thermostat is set to {temp} degrees."
        elif action in ("heat", "cool"):
            return f"The thermostat is set to {action} mode."
        elif action in ("play", "pause", "stop"):
            return f"The {friendly} is now {action}ing."
        elif action == "mute":
            return f"The {friendly} is muted."
        elif action == "volume":
            return f"Volume adjusted on the {friendly}."
        elif action == "open":
            return f"The {friendly} is opening."
        elif action == "close":
            return f"The {friendly} is closing."
        return f"Done. The {friendly} has been updated."

    def get_status(self, target: str) -> dict:
        """Get the status of a device in voice-friendly format.

        Args:
            target: Device name or entity_id.

        Returns:
            Dict with success, state, and voice-friendly message.
        """
        resolved = self.aliases.get(target.lower(), target)
        entity = self.cache.find_entity(resolved)
        if not entity:
            return {
                "success": False,
                "message": f"I couldn't find a device called {target}.",
            }

        entity_id = entity["entity_id"]
        state = entity.get("state", "unknown")
        attrs = entity.get("attributes", {})
        friendly = attrs.get("friendly_name", entity_id)
        ha_domain = entity_id.split(".")[0]

        msg = self._build_status_message(
            friendly, state, ha_domain, attrs
        )
        return {
            "success": True,
            "entity_id": entity_id,
            "state": state,
            "attributes": attrs,
            "message": msg,
        }

    def _build_status_message(self, friendly: str, state: str,
                              domain: str, attrs: dict) -> str:
        """Build a voice-friendly status message."""
        if domain == "light":
            if state == "on":
                brightness = attrs.get("brightness", 0)
                pct = int(brightness / 255 * 100) if brightness else 100
                return f"The {friendly} is on at {pct} percent."
            return f"The {friendly} is off."
        elif domain == "lock":
            return f"The {friendly} is {state}."
        elif domain == "climate":
            current = attrs.get("current_temperature", "unknown")
            target = attrs.get("temperature", "not set")
            mode = attrs.get("hvac_mode", state)
            return (
                f"The thermostat is in {mode} mode. "
                f"Current temperature is {current}, "
                f"target is {target} degrees."
            )
        elif domain == "media_player":
            title = attrs.get("media_title", "")
            if title:
                return f"The {friendly} is {state}, playing {title}."
            return f"The {friendly} is {state}."
        elif domain == "cover":
            return f"The {friendly} is {state}."
        elif domain == "sensor":
            unit = attrs.get("unit_of_measurement", "")
            return f"The {friendly} reads {state} {unit}."
        elif domain == "binary_sensor":
            return f"The {friendly} is {state}."
        return f"The {friendly} is {state}."

    def get_room_summary(self, room: str) -> dict:
        """Get summary of all devices in a room.

        Searches entity friendly_names for the room keyword
        and returns a spoken summary.
        """
        entities = self.cache.refresh()
        room_lower = room.lower()
        room_entities = [
            e for e in entities
            if room_lower in e.get("attributes", {}).get(
                "friendly_name", ""
            ).lower()
        ]
        if not room_entities:
            return {
                "success": False,
                "message": f"I don't see any devices in the {room}.",
            }

        parts = []
        for e in room_entities[:10]:
            friendly = e.get("attributes", {}).get(
                "friendly_name", e["entity_id"]
            )
            state = e.get("state", "unknown")
            parts.append(f"{friendly} is {state}")

        summary = ". ".join(parts) + "."
        return {
            "success": True,
            "message": f"In the {room}: {summary}",
            "entities": len(room_entities),
        }

    def discover_devices(self) -> dict:
        """Discover all HA devices and return a spoken summary."""
        counts = self.cache.summarize_domains()
        interesting = {
            "light": "lights", "switch": "switches",
            "lock": "locks", "climate": "thermostats",
            "media_player": "media players", "cover": "covers",
            "fan": "fans", "camera": "cameras",
            "sensor": "sensors", "binary_sensor": "binary sensors",
            "scene": "scenes", "script": "scripts",
        }
        parts = []
        for domain, label in interesting.items():
            count = counts.get(domain, 0)
            if count > 0:
                parts.append(f"{count} {label}")
        if not parts:
            return {
                "success": True,
                "message": "I found no controllable devices.",
                "counts": counts,
            }
        summary = ", ".join(parts)
        return {
            "success": True,
            "message": f"I found {summary} in your home.",
            "counts": counts,
        }


# -------------------------------------------------------------------
# Voice Intent Handler -- bridges voice daemon to HA
# -------------------------------------------------------------------

def handle_smart_home_intent(intent: dict,
                             bridge: "HomeAssistantBridge | None" = None,
                             ) -> dict:
    """Handle a smart_home intent from the voice daemon.

    Called when IntentRouter classifies a voice command as
    domain=smart_home. Parses the action and entities from
    the intent and executes via HA bridge.

    Args:
        intent: Structured intent from IntentRouter with
                action, entities, and raw_text fields.
        bridge: Optional pre-initialized bridge instance.

    Returns:
        Dict with success status and voice message.
    """
    if bridge is None:
        bridge = HomeAssistantBridge()
        conn = bridge.connect()
        if not conn.get("connected"):
            return {
                "success": False,
                "message": "I can't reach the smart home system right now.",
            }

    action = intent.get("action", "").lower()
    entities = intent.get("entities", {})
    raw_text = intent.get("raw_text", "")

    # Extract target device from entities or raw text
    target = (
        entities.get("device")
        or entities.get("target")
        or entities.get("entity")
        or entities.get("room")
        or ""
    )

    # If no explicit target, try to parse from raw text
    if not target and raw_text:
        target = _extract_target_from_text(raw_text)

    # Handle status queries
    status_words = ("status", "state", "check", "is", "what",
                    "how", "temperature", "temp")
    if any(w in action for w in status_words) or not action:
        if entities.get("room"):
            return bridge.get_room_summary(entities["room"])
        if target:
            return bridge.get_status(target)
        return bridge.discover_devices()

    # Handle device control
    if not target:
        return {
            "success": False,
            "message": "Which device would you like me to control?",
        }

    # Build params from entities
    params = {}
    if entities.get("brightness") is not None:
        try:
            params["brightness"] = int(
                float(entities["brightness"]) / 100 * 255
            )
        except (ValueError, TypeError):
            pass
    if entities.get("temperature") is not None:
        try:
            params["temperature"] = float(entities["temperature"])
        except (ValueError, TypeError):
            pass
    if entities.get("volume") is not None:
        try:
            params["volume_level"] = float(entities["volume"]) / 100
        except (ValueError, TypeError):
            pass

    return bridge.execute_command(action, target, params or None)


def _extract_target_from_text(text: str) -> str:
    """Best-effort extraction of device name from raw text.

    Strips common action words to isolate the target device.
    """
    text = text.lower().strip()
    strip_phrases = [
        "turn on the", "turn off the", "switch on the",
        "switch off the", "toggle the", "dim the",
        "brighten the", "lock the", "unlock the",
        "open the", "close the", "set the", "check the",
        "what is the", "is the", "turn on", "turn off",
        "please", "can you", "could you", "hey rudy",
    ]
    for phrase in strip_phrases:
        text = text.replace(phrase, "")
    return text.strip()


# -------------------------------------------------------------------
# Morning Routine Integration
# -------------------------------------------------------------------

def get_home_summary_for_briefing(bridge: "HomeAssistantBridge | None" = None,
                                  ) -> str:
    """Get a short home status for the morning briefing.

    Called by MorningRoutine to include smart home status
    in Andrew's daily briefing. Returns a spoken sentence.
    """
    if bridge is None:
        try:
            bridge = HomeAssistantBridge()
            bridge.connect()
        except Exception:
            return ""
    if not bridge.is_connected:
        return ""

    try:
        entities = bridge.cache.refresh()
        # Summarize key info: climate, locks, lights on
        climate = [
            e for e in entities
            if e.get("entity_id", "").startswith("climate.")
        ]
        locks = [
            e for e in entities
            if e.get("entity_id", "").startswith("lock.")
        ]
        lights_on = [
            e for e in entities
            if e.get("entity_id", "").startswith("light.")
            and e.get("state") == "on"
        ]

        parts = []
        if climate:
            c = climate[0]
            temp = c.get("attributes", {}).get(
                "current_temperature", "unknown"
            )
            parts.append(f"Inside temperature is {temp} degrees")
        unlocked = [
            lk for lk in locks if lk.get("state") == "unlocked"
        ]
        if unlocked:
            names = ", ".join(
                lk.get("attributes", {}).get("friendly_name", "a lock") for lk in unlocked
            )
            parts.append(f"Warning: {names} is unlocked")
        elif locks:
            parts.append("All locks are secured")
        if lights_on:
            parts.append(f"{len(lights_on)} lights are on")

        return ". ".join(parts) + "." if parts else ""
    except Exception as e:
        log.debug("Home summary failed: %s", e)
        return ""


# -------------------------------------------------------------------
# CLI Entry Point
# -------------------------------------------------------------------

def main():
    """CLI for testing the HA bridge."""
    import argparse
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(message)s")

    p = argparse.ArgumentParser(
        description="Robin Home Assistant Bridge"
    )
    p.add_argument("--test", action="store_true",
                   help="Test HA connection")
    p.add_argument("--discover", action="store_true",
                   help="Discover devices")
    p.add_argument("--status", type=str, default=None,
                   help="Get device status")
    p.add_argument("--action", type=str, default=None,
                   help="Action to perform (on/off/lock/etc)")
    p.add_argument("--target", type=str, default=None,
                   help="Target device name")
    p.add_argument("--room", type=str, default=None,
                   help="Room summary")
    args = p.parse_args()

    bridge = HomeAssistantBridge()
    conn = bridge.connect()
    print(f"Connection: {json.dumps(conn, indent=2)}")

    if not conn.get("connected"):
        print("Failed to connect to Home Assistant.")
        return

    if args.discover:
        result = bridge.discover_devices()
        print(result["message"])
    elif args.status:
        result = bridge.get_status(args.status)
        print(result["message"])
    elif args.room:
        result = bridge.get_room_summary(args.room)
        print(result["message"])
    elif args.action and args.target:
        result = bridge.execute_command(args.action, args.target)
        print(result["message"])
    elif args.test:
        print("Connection successful.")
    else:
        result = bridge.discover_devices()
        print(result["message"])


if __name__ == "__main__":
    main()
