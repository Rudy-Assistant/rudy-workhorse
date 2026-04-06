"""
Morning Robin Routine -- Proactive daily briefing for Andrew.

Session 135: Phase 2 Step 5 of Andrew-Readiness (ADR-020).

Speaks a personalized morning briefing to Andrew via TTS:
  - Greeting with time and day
  - Weather summary (via wttr.in, no API key needed)
  - Robin system health status
  - Upcoming reminders (from local schedule file)
  - Positive closing

Architecture:
    MorningRoutine gathers data from multiple sources,
    composes a natural-language script, and speaks it
    through the voice daemon's TTS engine. Designed to
    run at a configurable time via Robin's scheduler or
    as a standalone invocation.

Dependencies:
    - rudy.paths (canonical paths)
    - rudy.voice_health (service health checks)
    - urllib (weather, no external packages)
    - pyttsx3 (TTS, already installed)
"""

import json
import logging
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

try:
    from rudy.paths import RUDY_DATA, RUDY_LOGS
except ImportError:
    RUDY_DATA = Path(__file__).resolve().parent.parent / "rudy-data"
    RUDY_LOGS = RUDY_DATA / "logs"

try:
    from rudy.voice_health import ServiceHealthChecker
    _HAS_HEALTH = True
except ImportError:
    _HAS_HEALTH = False

log = logging.getLogger("morning_routine")


# -------------------------------------------------------------------
# Weather Fetcher (wttr.in -- free, no API key)
# -------------------------------------------------------------------

class WeatherFetcher:
    """Fetch weather from wttr.in in plain-text format."""

    def __init__(self, location=""):
        self.location = location
        self._url = f"https://wttr.in/{location}?format=j1"

    def fetch(self):
        """Fetch weather data. Returns dict or None on failure."""
        try:
            req = urllib.request.Request(
                self._url,
                headers={"Accept": "application/json",
                         "User-Agent": "RobinAssistant/1.0"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read())
        except Exception as e:
            log.warning("[Weather] Fetch failed: %s", e)
            return None

    def get_spoken_summary(self):
        """Get a TTS-friendly weather summary."""
        data = self.fetch()
        if not data:
            return "I couldn't check the weather right now."

        try:
            current = data["current_condition"][0]
            temp_f = current.get("temp_F", "?")
            desc = current.get("weatherDesc", [{}])[0].get("value", "")
            humidity = current.get("humidity", "?")
            feels_f = current.get("FeelsLikeF", temp_f)

            parts = [f"It's currently {temp_f} degrees"]
            if feels_f != temp_f:
                parts.append(f"feels like {feels_f}")
            if desc:
                parts.append(f"with {desc.lower()}")
            parts.append(f"and {humidity} percent humidity.")

            # Today's forecast
            forecast = data.get("weather", [{}])[0]
            max_f = forecast.get("maxtempF", "?")
            min_f = forecast.get("mintempF", "?")
            parts.append(
                f"Today's high is {max_f} and the low is {min_f}."
            )
            return " ".join(parts)
        except (KeyError, IndexError) as e:
            log.warning("[Weather] Parse error: %s", e)
            return "I got the weather data but had trouble reading it."


# -------------------------------------------------------------------
# Reminder Loader
# -------------------------------------------------------------------

class ReminderLoader:
    """Load reminders from a simple JSON schedule file.

    File format (at RUDY_DATA/morning-reminders.json):
    [
        {"text": "Take morning medication", "days": ["mon","tue","wed","thu","fri","sat","sun"]},
        {"text": "Physical therapy at 2 PM", "days": ["mon","wed","fri"]}
    ]
    """

    def __init__(self, path=None):
        self.path = path or (RUDY_DATA / "morning-reminders.json")

    def get_today(self):
        """Get reminders applicable to today."""
        if not self.path.exists():
            return []
        try:
            reminders = json.loads(self.path.read_text())
            today = datetime.now().strftime("%a").lower()
            return [
                r["text"] for r in reminders
                if today in [d.lower() for d in r.get("days", [])]
            ]
        except Exception as e:
            log.warning("[Reminders] Load error: %s", e)
            return []


# -------------------------------------------------------------------
# Morning Routine (orchestrator)
# -------------------------------------------------------------------

class MorningRoutine:
    """Orchestrates the morning briefing for Andrew.

    Usage:
        routine = MorningRoutine(tts_engine, config)
        routine.run()  # Speaks the full briefing

        # Or schedule it:
        routine.schedule(hour=8, minute=0)
    """

    def __init__(self, tts_engine=None, config=None):
        config = config or {}
        self.tts = tts_engine
        self.user_name = config.get("user_name", "Andrew")
        self.location = config.get("weather_location", "")
        self.weather = WeatherFetcher(location=self.location)
        self.reminders = ReminderLoader()
        self.health_checker = None
        if _HAS_HEALTH:
            try:
                self.health_checker = ServiceHealthChecker()
            except Exception:
                pass
        self._schedule_timer = None
        self._running = False

    def compose_briefing(self):
        """Compose the full morning briefing script.

        Returns a list of speech segments (strings) that
        will be spoken in sequence with short pauses.
        """
        now = datetime.now()
        segments = []

        # 1. Greeting
        hour = now.hour
        if hour < 12:
            greeting = "Good morning"
        elif hour < 17:
            greeting = "Good afternoon"
        else:
            greeting = "Good evening"

        day_name = now.strftime("%A")
        month_day = now.strftime("%B %d")
        segments.append(
            f"{greeting}, {self.user_name}. "
            f"It's {day_name}, {month_day}."
        )

        # 2. Weather
        weather_text = self.weather.get_spoken_summary()
        segments.append(weather_text)

        # 3. System health
        if self.health_checker:
            self.health_checker.check_all()
            summary = self.health_checker.get_spoken_summary()
            segments.append(summary)
        else:
            segments.append("I wasn't able to check my systems.")

        # 4. Reminders
        today_reminders = self.reminders.get_today()
        if today_reminders:
            if len(today_reminders) == 1:
                segments.append(
                    f"You have one reminder for today: "
                    f"{today_reminders[0]}."
                )
            else:
                reminder_list = ", ".join(today_reminders[:-1])
                reminder_list += f", and {today_reminders[-1]}"
                segments.append(
                    f"You have {len(today_reminders)} reminders "
                    f"for today: {reminder_list}."
                )
        else:
            segments.append("You have no reminders for today.")

        # 5. Closing
        segments.append(
            f"That's your briefing, {self.user_name}. "
            f"Just say 'hey Rudy' if you need anything."
        )

        log.info("[Morning] Briefing composed: %d segments", len(segments))
        return segments

    def run(self):
        """Run the morning briefing -- speak all segments."""
        segments = self.compose_briefing()
        log.info("[Morning] Speaking briefing to %s", self.user_name)

        if self.tts:
            for segment in segments:
                try:
                    self.tts.speak(segment)
                    time.sleep(0.5)  # Brief pause between segments
                except Exception as e:
                    log.error("[Morning] TTS error: %s", e)
        else:
            log.warning("[Morning] No TTS engine -- logging only")

        # Log the briefing
        self._log_briefing(segments)
        return segments

    def schedule(self, hour=8, minute=0):
        """Schedule the briefing to run daily at the given time.

        Uses a background thread that sleeps until the target
        time, runs the briefing, then reschedules for next day.
        """
        self._running = True

        def _scheduler_loop():
            while self._running:
                now = datetime.now()
                target = now.replace(
                    hour=hour, minute=minute, second=0, microsecond=0
                )
                if target <= now:
                    # Already past today's time -- schedule for tomorrow
                    target = target.replace(day=target.day + 1)
                    try:
                        # Handle month rollover
                        _ = target.timestamp()
                    except (ValueError, OSError):
                        import calendar
                        last_day = calendar.monthrange(
                            target.year, target.month
                        )[1]
                        if target.day > last_day:
                            if target.month == 12:
                                target = target.replace(
                                    year=target.year + 1,
                                    month=1, day=1
                                )
                            else:
                                target = target.replace(
                                    month=target.month + 1, day=1
                                )

                wait_secs = (target - now).total_seconds()
                log.info(
                    "[Morning] Next briefing at %s (%.0f seconds)",
                    target.strftime("%Y-%m-%d %H:%M"), wait_secs,
                )
                # Sleep in 60s chunks so we can check _running
                while wait_secs > 0 and self._running:
                    chunk = min(wait_secs, 60)
                    time.sleep(chunk)
                    wait_secs -= chunk

                if self._running:
                    try:
                        self.run()
                    except Exception as e:
                        log.error("[Morning] Briefing error: %s", e)

        thread = threading.Thread(
            target=_scheduler_loop, daemon=True,
            name="morning-routine"
        )
        thread.start()
        log.info("[Morning] Scheduled daily at %02d:%02d", hour, minute)

    def stop(self):
        """Stop the scheduled briefing."""
        self._running = False
        log.info("[Morning] Scheduler stopped.")

    def _log_briefing(self, segments):
        """Log briefing to file for audit trail."""
        log_path = RUDY_LOGS / "morning-briefings.json"
        entries = []
        if log_path.exists():
            try:
                entries = json.loads(log_path.read_text())
            except Exception:
                pass
        entries.append({
            "timestamp": datetime.now().isoformat(),
            "user": self.user_name,
            "segments": segments,
        })
        # Keep last 90 entries (~3 months)
        entries = entries[-90:]
        try:
            log_path.write_text(json.dumps(entries, indent=2))
        except Exception as e:
            log.warning("[Morning] Log write failed: %s", e)

    @property
    def status(self):
        """Current routine status."""
        return {
            "running": self._running,
            "user": self.user_name,
            "location": self.location,
            "has_tts": self.tts is not None,
            "has_health": self.health_checker is not None,
        }
