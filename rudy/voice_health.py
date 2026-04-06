"""
Voice Health Monitor -- Service availability and check-ins for Andrew.

Session 134: Phase 1 refinements (Steps 2-3 polish).
Companion module to voice_daemon.py. Provides:
  - Service health checks (Ollama, mic, TTS, email)
  - Graceful degradation announcements via TTS
  - Periodic check-in scheduler for Andrew's safety

Architecture:
    VoiceHealthMonitor orchestrates checks at startup and
    periodically, announcing results through the daemon's
    TTS engine. Designed for non-technical users -- all
    status is communicated in plain spoken English.
"""

import json
import logging
import threading
import time
import urllib.request
from pathlib import Path

try:
    from rudy.paths import RUDY_DATA, RUDY_LOGS
except ImportError:
    RUDY_DATA = Path(__file__).resolve().parent.parent / "rudy-data"
    RUDY_LOGS = RUDY_DATA / "logs"

log = logging.getLogger("voice_health")


# -------------------------------------------------------------------
# Service Health Checker
# -------------------------------------------------------------------

class ServiceHealthChecker:
    """Check availability of services the voice daemon depends on.

    Checks: Ollama, microphone, TTS engine, email backend.
    Returns plain-English status suitable for speaking to Andrew.
    """

    def __init__(self, ollama_host="http://localhost:11434"):
        self.ollama_host = ollama_host
        self._last_results = {}

    def check_all(self):
        """Run all health checks. Returns dict of service -> status."""
        results = {
            "ollama": self._check_ollama(),
            "microphone": self._check_microphone(),
            "tts": self._check_tts(),
            "email": self._check_email(),
        }
        self._last_results = results
        log.info("[Health] Check results: %s", results)
        return results

    def _check_ollama(self):
        """Check if Ollama is responding."""
        try:
            req = urllib.request.Request(
                f"{self.ollama_host}/api/tags",
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            models = [m["name"] for m in data.get("models", [])]
            return {"status": "up", "models": models}
        except Exception as e:
            return {"status": "down", "error": str(e)}

    def _check_microphone(self):
        """Check if a microphone is available."""
        try:
            import sounddevice as sd
            devices = sd.query_devices()
            input_devices = [
                d for d in devices
                if d.get("max_input_channels", 0) > 0
            ]
            if input_devices:
                default = sd.query_devices(kind="input")
                return {
                    "status": "up",
                    "device": default.get("name", "unknown"),
                    "count": len(input_devices),
                }
            return {"status": "down", "error": "No input devices found"}
        except Exception as e:
            return {"status": "down", "error": str(e)}

    def _check_tts(self):
        """Check if TTS engine initializes."""
        try:
            import pyttsx3
            engine = pyttsx3.init()
            voices = engine.getProperty("voices")
            engine.stop()
            return {"status": "up", "voices": len(voices)}
        except Exception as e:
            return {"status": "down", "error": str(e)}

    def _check_email(self):
        """Check email backend availability (non-blocking probe)."""
        state_file = RUDY_LOGS / "email-poller-state.json"
        if state_file.exists():
            try:
                state = json.loads(state_file.read_text())
                health = state.get("backend_health", {})
                last_poll = state.get("last_poll")
                if last_poll:
                    return {"status": "partial", "last_poll": last_poll,
                            "backends": health}
            except Exception:
                pass
        return {"status": "down", "error": "Email poller not running"}

    def get_spoken_summary(self):
        """Generate a plain-English summary of service health."""
        results = self._last_results or self.check_all()
        up_services = []
        down_services = []

        if results["ollama"]["status"] == "up":
            up_services.append("brain")
        else:
            down_services.append("brain")

        if results["microphone"]["status"] == "up":
            up_services.append("hearing")
        else:
            down_services.append("hearing")

        if results["tts"]["status"] == "up":
            up_services.append("voice")
        else:
            down_services.append("voice")

        if results["email"]["status"] in ("up", "partial"):
            up_services.append("email")
        else:
            down_services.append("email")

        parts = []
        if up_services:
            parts.append(f"My {', '.join(up_services)} "
                         f"{'is' if len(up_services) == 1 else 'are'}"
                         f" working.")
        if down_services:
            parts.append(f"My {', '.join(down_services)} "
                         f"{'is' if len(down_services) == 1 else 'are'}"
                         f" not available right now.")

        if not down_services:
            parts.append("All systems are go.")
        elif len(down_services) >= 3:
            parts.append("I'm running in limited mode.")

        return " ".join(parts)


# -------------------------------------------------------------------
# Check-In Scheduler
# -------------------------------------------------------------------

class CheckInScheduler:
    """Periodic check-ins with Andrew for safety monitoring.

    Speaks a check-in prompt at configurable intervals.
    If Andrew doesn't respond after multiple attempts,
    escalates to caregiver alert (Phase 3 feature --
    currently logs the event for future integration).
    """

    def __init__(self, tts_engine, interval_hours=4,
                 user_name="Andrew", max_missed=3):
        self.tts = tts_engine
        self.interval_hours = interval_hours
        self.user_name = user_name
        self.max_missed = max_missed
        self._timer = None
        self._missed_count = 0
        self._running = False
        self._last_checkin = None
        self._last_response = None

    def start(self):
        """Start the periodic check-in timer."""
        self._running = True
        self._schedule_next()
        log.info("[CheckIn] Started: every %d hours for %s",
                 self.interval_hours, self.user_name)

    def stop(self):
        """Stop the check-in timer."""
        self._running = False
        if self._timer:
            self._timer.cancel()
            self._timer = None
        log.info("[CheckIn] Stopped.")

    def _schedule_next(self):
        """Schedule the next check-in."""
        if not self._running:
            return
        interval_secs = self.interval_hours * 3600
        self._timer = threading.Timer(interval_secs, self._do_checkin)
        self._timer.daemon = True
        self._timer.start()

    def _do_checkin(self):
        """Perform a check-in with Andrew."""
        self._last_checkin = time.strftime("%Y-%m-%dT%H:%M:%S")
        self._missed_count += 1

        log.info("[CheckIn] Check-in #%d for %s",
                 self._missed_count, self.user_name)

        if self._missed_count <= self.max_missed:
            self.tts.speak_async(
                f"Hey {self.user_name}, just checking in. "
                f"Everything okay? Say 'hey Rudy' if you need anything."
            )
        else:
            # Escalation point -- future caregiver alert (Phase 3)
            log.warning(
                "[CheckIn] %d missed check-ins for %s. "
                "Caregiver alert would fire here (Phase 3).",
                self._missed_count, self.user_name,
            )
            self.tts.speak_async(
                f"{self.user_name}, I haven't heard from you "
                f"in a while. I'm here if you need me."
            )
            self._log_missed_checkin()

        self._schedule_next()

    def acknowledge(self):
        """Called when Andrew responds to a check-in."""
        self._missed_count = 0
        self._last_response = time.strftime("%Y-%m-%dT%H:%M:%S")
        log.info("[CheckIn] Acknowledged by %s", self.user_name)

    def _log_missed_checkin(self):
        """Log missed check-ins for future caregiver integration."""
        log_path = RUDY_LOGS / "missed-checkins.json"
        entries = []
        if log_path.exists():
            try:
                entries = json.loads(log_path.read_text())
            except Exception:
                pass
        entries.append({
            "timestamp": self._last_checkin,
            "missed_count": self._missed_count,
            "user": self.user_name,
        })
        # Keep last 100 entries
        entries = entries[-100:]
        log_path.write_text(json.dumps(entries, indent=2))

    @property
    def status(self):
        """Current check-in status dict."""
        return {
            "running": self._running,
            "interval_hours": self.interval_hours,
            "missed_count": self._missed_count,
            "last_checkin": self._last_checkin,
            "last_response": self._last_response,
        }


# -------------------------------------------------------------------
# Voice Health Monitor (orchestrator)
# -------------------------------------------------------------------

class VoiceHealthMonitor:
    """Orchestrates health checks and check-ins for the voice daemon.

    Usage:
        monitor = VoiceHealthMonitor(tts_engine, config)
        monitor.startup_announcement()  # Speaks what's working
        monitor.start_checkins()        # Starts periodic check-ins
        monitor.periodic_health_check() # Re-checks services
    """

    def __init__(self, tts_engine, config=None):
        config = config or {}
        self.tts = tts_engine
        self.checker = ServiceHealthChecker(
            ollama_host=config.get("ollama_host",
                                   "http://localhost:11434"),
        )
        self.scheduler = CheckInScheduler(
            tts_engine=tts_engine,
            interval_hours=config.get("check_in_interval_hours", 4),
            user_name=config.get("user_name", "Andrew"),
        )
        self._periodic_timer = None
        self._health_interval = 1800  # Re-check every 30 min

    def startup_announcement(self):
        """Run health checks and announce results via TTS.

        Called once at daemon startup. Tells Andrew what's
        working and what's not in plain spoken English.
        """
        results = self.checker.check_all()
        summary = self.checker.get_spoken_summary()
        log.info("[Monitor] Startup health: %s", summary)
        self.tts.speak(summary)
        return results

    def start_checkins(self):
        """Start periodic check-in scheduler."""
        self.scheduler.start()

    def stop_checkins(self):
        """Stop periodic check-in scheduler."""
        self.scheduler.stop()

    def periodic_health_check(self):
        """Re-check services and announce any changes.

        Only speaks if something changed since last check.
        Runs on a background timer.
        """
        old = dict(self.checker._last_results)
        new = self.checker.check_all()

        # Detect changes
        recovered = []
        degraded = []
        for svc in ("ollama", "microphone", "tts", "email"):
            old_status = old.get(svc, {}).get("status", "unknown")
            new_status = new.get(svc, {}).get("status", "unknown")
            if old_status != "up" and new_status == "up":
                recovered.append(svc)
            elif old_status == "up" and new_status != "up":
                degraded.append(svc)

        if recovered:
            names = ", ".join(recovered)
            self.tts.speak_async(f"Good news. My {names} "
                                 f"{'is' if len(recovered) == 1 else 'are'}"
                                 f" back online.")
            log.info("[Monitor] Recovered: %s", recovered)

        if degraded:
            names = ", ".join(degraded)
            self.tts.speak_async(f"Heads up. My {names} "
                                 f"{'has' if len(degraded) == 1 else 'have'}"
                                 f" gone offline. I'll keep trying.")
            log.info("[Monitor] Degraded: %s", degraded)

    def start_periodic_monitoring(self):
        """Start background health monitoring loop."""
        def _loop():
            while True:
                time.sleep(self._health_interval)

                try:
                    self.periodic_health_check()
                except Exception as e:
                    log.error("[Monitor] Periodic check error: %s", e)

        self._periodic_timer = threading.Thread(
            target=_loop, daemon=True, name="health-monitor"
        )
        self._periodic_timer.start()
        log.info("[Monitor] Periodic monitoring started "
                 "(every %ds)", self._health_interval)

    def on_voice_activity(self):
        """Called when any voice activity is detected.

        Resets check-in missed count (Andrew is active).
        """
        self.scheduler.acknowledge()

    @property
    def status(self):
        """Full health monitor status dict."""
        return {
            "services": self.checker._last_results,
            "checkin": self.scheduler.status,
            "spoken_summary": self.checker.get_spoken_summary(),
        }
