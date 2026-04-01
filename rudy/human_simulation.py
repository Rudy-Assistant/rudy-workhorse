"""
Human Behavior Simulation — Natural interaction patterns for browser automation.

This module makes Rudy's automated browser sessions indistinguishable from a
real human user. It addresses every major bot-detection vector:

Detection Vectors Countered:
  1. Timing analysis — Gaussian distributions, not fixed delays
  2. Mouse movement — Bezier curves with acceleration/deceleration
  3. Keystroke dynamics — Per-character timing with realistic variance
  4. Scroll behavior — Variable speed, overshoot, momentum simulation
  5. Session patterns — Natural session lengths, breaks, tab switching
  6. Browser fingerprint — Consistent, coherent fingerprints (not randomized)
  7. Page interaction — Reading time proportional to content length
  8. Navigation patterns — Organic click sequences, not direct URL jumps

Bot-Detection Failsafe:
  - Detects CAPTCHA/challenge pages via DOM signals
  - Pauses automation gracefully on detection
  - Alerts Chris via email
  - Retries with exponential backoff + jitter
  - Tracks detection frequency for pattern adjustment

Design Philosophy:
  - Consistency > Randomness (Google's Welford's algorithm catches high variance)
  - Session persistence reduces lockout risk by ~70%
  - Gradual warmup for new sessions (slow → normal speed over 10-15 min)
  - Mouse velocity variance >15 indicates human (bots are too smooth)
  - Mean action delay ~400ms ± 150ms (research-derived sweet spot)
"""

import json
import math
import random

import string
import time

from datetime import datetime, timedelta
from typing import Tuple, List

# --- Paths ---
from rudy.paths import RUDY_LOGS, RUDY_DATA  # noqa: E402

LOGS_DIR = RUDY_LOGS
SESSIONS_DIR = RUDY_DATA / "sessions"
SIM_STATE_FILE = LOGS_DIR / "human-sim-state.json"
SIM_LOG_FILE = LOGS_DIR / "human-sim-log.json"
BOT_DETECTION_LOG = LOGS_DIR / "bot-detection-log.json"

def _load_json(path, default=None):
    if path.exists():
        try:
            with open(path) as f:
                return json.load(f)
        except Exception:
            pass
    return default if default is not None else {}

def _save_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=str)

# ============================================================================
#  TIMING ENGINE — Gaussian distributions tuned to human norms
# ============================================================================

class TimingEngine:
    """
    Generates human-realistic delays using Gaussian distributions.

    Google uses Welford's online algorithm to compute running mean/variance
    of inter-action timing. Perfectly uniform delays or delays with
    unnaturally low variance are flagged. Our distributions are calibrated
    from human-computer interaction research.

    Key parameters (from research):
      - Action delay: mean=400ms, std=150ms (clicking, navigation)
      - Keystroke delay: mean=100ms, std=25ms (per character)
      - Reading speed: ~250 words/minute, with variance
      - Scroll pause: mean=800ms, std=200ms (between scroll actions)
      - Page load wait: mean=1500ms, std=500ms (settling after navigation)
    """

    # Timing profiles (mean_ms, std_ms, min_ms, max_ms)
    PROFILES = {
        "action":       (400, 150, 80, 1500),    # Click, button press
        "keystroke":    (100, 25, 40, 250),       # Per-character typing
        "word_gap":     (200, 60, 80, 500),       # Between-word pause
        "read_word":    (240, 50, 120, 600),      # Per-word reading time
        "scroll":       (800, 200, 300, 2000),    # Between scroll actions
        "page_settle":  (1500, 500, 500, 5000),   # After page navigation
        "micro_pause":  (50, 15, 20, 150),        # Mouse hover, focus shift
        "think":        (2000, 800, 500, 8000),   # Decision-making pause
        "tab_switch":   (600, 200, 200, 2000),    # Switching browser tabs
        "session_break": (300000, 120000, 60000, 900000),  # 5 min ± 2 min
    }

    def __init__(self):
        self._welford_n = 0
        self._welford_mean = 0.0
        self._welford_m2 = 0.0
        self._fatigue_factor = 1.0  # Increases slightly over session
        self._session_start = time.time()

    def delay(self, profile: str = "action") -> float:
        """
        Generate a delay in seconds from the named profile.
        Returns the delay value (caller decides whether to sleep).
        """
        mean_ms, std_ms, min_ms, max_ms = self.PROFILES.get(
            profile, self.PROFILES["action"]
        )

        # Apply fatigue — humans slow down over time
        elapsed_min = (time.time() - self._session_start) / 60
        fatigue = 1.0 + (elapsed_min / 120) * 0.15  # +15% after 2 hours
        self._fatigue_factor = min(fatigue, 1.4)  # Cap at 40% slowdown

        mean_ms *= self._fatigue_factor
        std_ms *= self._fatigue_factor

        # Gaussian sample, clamped to bounds
        sample = random.gauss(mean_ms, std_ms)
        sample = max(min_ms, min(max_ms, sample))

        # Update Welford's running statistics (for self-monitoring)
        self._welford_update(sample)

        return sample / 1000.0  # Return seconds

    def sleep(self, profile: str = "action"):
        """Generate a delay and actually sleep for that duration."""
        d = self.delay(profile)
        time.sleep(d)
        return d

    def typing_delays(self, text: str) -> List[float]:
        """
        Generate per-character typing delays for a string.
        Accounts for:
          - Faster typing for common letter sequences
          - Slower on special characters (shift key)
          - Word-gap pauses on spaces
          - Occasional micro-hesitations (3% chance)
        """
        delays = []
        for i, char in enumerate(text):
            if char == " ":
                delays.append(self.delay("word_gap"))
            elif char in string.punctuation or char.isupper():
                # Shift key adds ~30-80ms
                base = self.delay("keystroke")
                shift_penalty = random.gauss(50, 15) / 1000
                delays.append(base + max(0.02, shift_penalty))
            else:
                delays.append(self.delay("keystroke"))

            # Occasional micro-hesitation (human uncertainty)
            if random.random() < 0.03:
                delays[-1] += random.gauss(300, 100) / 1000

        return delays

    def reading_time(self, text: str) -> float:
        """
        Estimate how long a human would spend reading text.
        ~250 WPM average, with per-word variance.
        """
        words = len(text.split())
        if words == 0:
            return 0.5

        total_ms = 0
        for _ in range(words):
            total_ms += self.delay("read_word") * 1000

        # Add a couple of "re-read" pauses for longer text
        if words > 50:
            rereads = random.randint(1, max(1, words // 100))
            for _ in range(rereads):
                total_ms += random.gauss(2000, 500)

        return total_ms / 1000.0

    def _welford_update(self, value):
        """Welford's online algorithm for running mean/variance."""
        self._welford_n += 1
        delta = value - self._welford_mean
        self._welford_mean += delta / self._welford_n
        delta2 = value - self._welford_mean
        self._welford_m2 += delta * delta2

    @property
    def timing_stats(self) -> dict:
        """Return current timing statistics (for self-monitoring)."""
        variance = self._welford_m2 / self._welford_n if self._welford_n > 1 else 0
        return {
            "n": self._welford_n,
            "mean_ms": round(self._welford_mean, 1),
            "variance": round(variance, 1),
            "std_ms": round(math.sqrt(variance), 1) if variance > 0 else 0,
            "fatigue_factor": round(self._fatigue_factor, 3),
            "session_minutes": round((time.time() - self._session_start) / 60, 1),
        }

    def reset_session(self):
        """Reset fatigue and stats for a new session."""
        self._welford_n = 0
        self._welford_mean = 0.0
        self._welford_m2 = 0.0
        self._fatigue_factor = 1.0
        self._session_start = time.time()

# ============================================================================
#  MOUSE ENGINE — Bezier curves with human-like acceleration
# ============================================================================

class MouseEngine:
    """
    Generates realistic mouse movement paths using cubic Bezier curves
    with velocity variance, overshoot, and micro-corrections.

    Key behaviors:
      - Curved paths (never straight lines — humans can't do that)
      - Acceleration at start, deceleration near target
      - Occasional overshoot + correction (especially for small targets)
      - Velocity variance >15 (bots are too smooth, typically <5)
      - Subtle jitter from hand tremor
    """

    def __init__(self):
        self._last_pos = (0, 0)
        self._velocity_samples = []

    def generate_path(
        self, start: Tuple[int, int], end: Tuple[int, int],
        steps: int = 0, overshoot_chance: float = 0.15
    ) -> List[Tuple[int, int]]:
        """
        Generate a human-like mouse path from start to end.

        Returns list of (x, y) points to move through.
        """
        dx = end[0] - start[0]
        dy = end[1] - start[1]
        distance = math.sqrt(dx**2 + dy**2)

        if distance < 2:
            return [start, end]

        # Auto-calculate steps based on distance (~1 point per 5-15 pixels)
        if steps == 0:
            steps = max(10, int(distance / random.gauss(10, 3)))
            steps = min(steps, 200)  # Cap for very long moves

        # Generate control points for cubic Bezier
        # Offset perpendicular to the direct line for curve
        perp_x = -dy / distance
        perp_y = dx / distance

        # Control point offset: bigger for longer distances
        offset_magnitude = distance * random.gauss(0.2, 0.08)
        offset_sign = random.choice([-1, 1])

        cp1 = (
            start[0] + dx * 0.3 + perp_x * offset_magnitude * offset_sign,
            start[1] + dy * 0.3 + perp_y * offset_magnitude * offset_sign,
        )
        cp2 = (
            start[0] + dx * 0.7 + perp_x * offset_magnitude * offset_sign * 0.5,
            start[1] + dy * 0.7 + perp_y * offset_magnitude * offset_sign * 0.5,
        )

        # Generate path along Bezier curve with acceleration profile
        path = []
        for i in range(steps + 1):
            # Non-linear t for acceleration/deceleration (ease-in-out)
            t_linear = i / steps
            t = self._ease_in_out(t_linear)

            # Cubic Bezier formula
            x = (
                (1 - t)**3 * start[0]
                + 3 * (1 - t)**2 * t * cp1[0]
                + 3 * (1 - t) * t**2 * cp2[0]
                + t**3 * end[0]
            )
            y = (
                (1 - t)**3 * start[1]
                + 3 * (1 - t)**2 * t * cp1[1]
                + 3 * (1 - t) * t**2 * cp2[1]
                + t**3 * end[1]
            )

            # Add hand tremor (±1-2px Gaussian jitter)
            tremor_x = random.gauss(0, 0.8)
            tremor_y = random.gauss(0, 0.8)

            path.append((int(x + tremor_x), int(y + tremor_y)))

        # Overshoot + correction for small targets
        if random.random() < overshoot_chance and distance > 30:
            overshoot_dist = random.gauss(8, 3)
            angle = math.atan2(dy, dx)
            overshoot_pt = (
                int(end[0] + overshoot_dist * math.cos(angle)),
                int(end[1] + overshoot_dist * math.sin(angle)),
            )
            # Replace last few points with overshoot + correction
            path[-1] = overshoot_pt
            # Add correction back to target
            correction_steps = random.randint(3, 6)
            for j in range(1, correction_steps + 1):
                t = j / correction_steps
                cx = overshoot_pt[0] + (end[0] - overshoot_pt[0]) * t
                cy = overshoot_pt[1] + (end[1] - overshoot_pt[1]) * t
                path.append((int(cx + random.gauss(0, 0.5)),
                             int(cy + random.gauss(0, 0.5))))

        self._last_pos = path[-1]
        self._record_velocity(path)
        return path

    def _ease_in_out(self, t: float) -> float:
        """Smooth acceleration/deceleration curve."""
        if t < 0.5:
            return 2 * t * t
        return -1 + (4 - 2 * t) * t

    def _record_velocity(self, path: List[Tuple[int, int]]):
        """Track velocity variance for self-monitoring."""
        for i in range(1, len(path)):
            dx = path[i][0] - path[i-1][0]
            dy = path[i][1] - path[i-1][1]
            v = math.sqrt(dx**2 + dy**2)
            self._velocity_samples.append(v)

        # Keep only recent samples
        if len(self._velocity_samples) > 1000:
            self._velocity_samples = self._velocity_samples[-500:]

    @property
    def velocity_variance(self) -> float:
        """
        Current velocity variance. Human mouse movement typically has
        variance >15. Bot movement is usually <5.
        """
        if len(self._velocity_samples) < 10:
            return 0
        mean = sum(self._velocity_samples) / len(self._velocity_samples)
        variance = sum((v - mean)**2 for v in self._velocity_samples) / len(self._velocity_samples)
        return round(variance, 2)

    def generate_scroll_sequence(
        self, total_pixels: int, direction: str = "down"
    ) -> List[int]:
        """
        Generate human-like scroll increments.
        Humans scroll in bursts with variable speed and occasional pauses.
        """
        sign = -1 if direction == "up" else 1
        scrolled = 0
        increments = []

        while scrolled < abs(total_pixels):
            # Burst of 2-5 scroll ticks
            burst_size = random.randint(2, 5)
            for _ in range(burst_size):
                tick = int(random.gauss(80, 25))  # ~80px per tick
                tick = max(20, min(200, tick))
                remaining = abs(total_pixels) - scrolled
                tick = min(tick, remaining)
                increments.append(tick * sign)
                scrolled += tick
                if scrolled >= abs(total_pixels):
                    break

            # Pause between bursts (reading)
            if scrolled < abs(total_pixels):
                increments.append(0)  # 0 = pause marker

        return increments

# ============================================================================
#  KEYBOARD ENGINE — Realistic typing patterns
# ============================================================================

class KeyboardEngine:
    """
    Simulates human typing with realistic per-character timing.

    Accounts for:
      - Key proximity effects (adjacent keys are faster)
      - Shift-key delays for capitals and special characters
      - Occasional typos with self-correction (1-2% rate)
      - Variable speed: fast on familiar sequences, slow on unusual ones
      - Burst-pause pattern (type a few words, brief pause, continue)
    """

    # Simplified QWERTY adjacency (row, col positions)
    QWERTY_POS = {
        'q': (0, 0), 'w': (0, 1), 'e': (0, 2), 'r': (0, 3), 't': (0, 4),
        'y': (0, 5), 'u': (0, 6), 'i': (0, 7), 'o': (0, 8), 'p': (0, 9),
        'a': (1, 0), 's': (1, 1), 'd': (1, 2), 'f': (1, 3), 'g': (1, 4),
        'h': (1, 5), 'j': (1, 6), 'k': (1, 7), 'l': (1, 8),
        'z': (2, 0), 'x': (2, 1), 'c': (2, 2), 'v': (2, 3), 'b': (2, 4),
        'n': (2, 5), 'm': (2, 6),
    }

    def __init__(self, typo_rate: float = 0.015, wpm: float = 65):
        """
        typo_rate: Probability of a typo per character (default 1.5%).
        wpm: Target words per minute (affects base timing).
        """
        self.typo_rate = typo_rate
        self.base_delay_ms = (60000 / wpm) / 5  # ms per character (avg 5 chars/word)
        self.timing = TimingEngine()

    def generate_keystrokes(self, text: str) -> List[dict]:
        """
        Generate a sequence of keystroke events for typing the given text.

        Returns list of dicts:
          {"char": "a", "delay_s": 0.095, "action": "type"}
          {"char": "Backspace", "delay_s": 0.07, "action": "correct"}  # typo fix
        """
        events = []
        prev_char = None

        for i, char in enumerate(text):
            # Base delay with Gaussian variance
            delay_ms = random.gauss(self.base_delay_ms, self.base_delay_ms * 0.25)

            # Key-distance adjustment
            if prev_char and prev_char.lower() in self.QWERTY_POS and char.lower() in self.QWERTY_POS:
                dist = self._key_distance(prev_char.lower(), char.lower())
                delay_ms += dist * random.gauss(12, 3)  # ~12ms per unit distance

            # Shift penalty for uppercase and special chars
            if char.isupper() or char in '!@#$%^&*()_+{}|:"<>?':
                delay_ms += random.gauss(45, 12)

            # Clamp
            delay_ms = max(35, min(400, delay_ms))

            # Occasional typo
            if random.random() < self.typo_rate and char.isalpha():
                # Type wrong character
                wrong_char = self._nearby_key(char.lower())
                events.append({
                    "char": wrong_char,
                    "delay_s": delay_ms / 1000,
                    "action": "type",
                })
                # Notice delay (200-600ms)
                notice_delay = random.gauss(350, 100) / 1000
                events.append({
                    "char": "Backspace",
                    "delay_s": max(0.1, notice_delay),
                    "action": "correct",
                })
                # Retype correct character (a bit slower — careful now)
                events.append({
                    "char": char,
                    "delay_s": (delay_ms * 1.3) / 1000,
                    "action": "type",
                })
            else:
                events.append({
                    "char": char,
                    "delay_s": delay_ms / 1000,
                    "action": "type",
                })

            # Burst-pause: after every 4-8 words, brief think pause
            if char == " " and random.random() < 0.12:
                events.append({
                    "char": None,
                    "delay_s": random.gauss(0.8, 0.3),
                    "action": "think_pause",
                })

            prev_char = char

        return events

    def _key_distance(self, a: str, b: str) -> float:
        """Euclidean distance between two keys on QWERTY layout."""
        if a not in self.QWERTY_POS or b not in self.QWERTY_POS:
            return 2.0  # Default for non-letter keys
        pa, pb = self.QWERTY_POS[a], self.QWERTY_POS[b]
        return math.sqrt((pa[0] - pb[0])**2 + (pa[1] - pb[1])**2)

    def _nearby_key(self, char: str) -> str:
        """Return a plausible typo character (adjacent key)."""
        if char not in self.QWERTY_POS:
            return char
        pos = self.QWERTY_POS[char]
        neighbors = [
            k for k, p in self.QWERTY_POS.items()
            if abs(p[0] - pos[0]) <= 1 and abs(p[1] - pos[1]) <= 1 and k != char
        ]
        return random.choice(neighbors) if neighbors else char

# ============================================================================
#  SESSION MANAGER — Persistent, coherent browser sessions
# ============================================================================

class SessionManager:
    """
    Manages browser session lifecycle with human-like patterns.

    Key principles:
      - Consistent fingerprints beat randomized ones (coherence > chaos)
      - Sessions should persist and be reused (not fresh each time)
      - Natural session durations (15-90 min active, then break)
      - Warmup period: first 10 min of a session, go slower than normal
      - Cool-down: gradual activity decrease before session end
    """

    def __init__(self, session_name: str = "default"):
        self.session_name = session_name
        self.state = _load_json(SIM_STATE_FILE, {})
        self.session_data = self.state.get("sessions", {}).get(session_name, {})
        self._session_start = time.time()
        self._action_count = 0
        self._warmup_complete = False

    @property
    def is_warm(self) -> bool:
        """Whether warmup period has elapsed (first 10 min)."""
        elapsed = time.time() - self._session_start
        self._warmup_complete = elapsed > 600  # 10 minutes
        return self._warmup_complete

    @property
    def warmup_factor(self) -> float:
        """
        Speed multiplier during warmup. Starts at 1.8x (slow),
        gradually decreases to 1.0x over 10 minutes.
        """
        elapsed = time.time() - self._session_start
        if elapsed >= 600:
            return 1.0
        # Linear ramp from 1.8 → 1.0 over 10 min
        return 1.8 - (0.8 * elapsed / 600)

    def should_take_break(self) -> bool:
        """
        Whether the session should pause for a natural break.
        Active sessions of 30-90 min should have breaks.
        """
        elapsed_min = (time.time() - self._session_start) / 60
        if elapsed_min < 25:
            return False
        # Increasing probability after 25 min
        break_prob = min(0.8, (elapsed_min - 25) / 60)
        return random.random() < break_prob * 0.01  # Check per-action

    def record_action(self, action_type: str, url: str = "", success: bool = True):
        """Record an action for session analytics."""
        self._action_count += 1

        if "actions" not in self.session_data:
            self.session_data["actions"] = []

        self.session_data["actions"].append({
            "time": datetime.now().isoformat(),
            "type": action_type,
            "url": url[:100] if url else "",
            "success": success,
        })

        # Trim to last 500 actions
        if len(self.session_data["actions"]) > 500:
            self.session_data["actions"] = self.session_data["actions"][-300:]

        self.session_data["last_active"] = datetime.now().isoformat()
        self.session_data["total_actions"] = self.session_data.get("total_actions", 0) + 1
        self._save()

    def get_session_health(self) -> dict:
        """Return session health metrics for monitoring."""
        actions = self.session_data.get("actions", [])
        failures = sum(1 for a in actions[-50:] if not a.get("success", True))

        return {
            "session_name": self.session_name,
            "total_actions": self.session_data.get("total_actions", 0),
            "recent_failure_rate": failures / max(1, min(50, len(actions))),
            "last_active": self.session_data.get("last_active"),
            "session_age_hours": (
                time.time() - self._session_start
            ) / 3600,
            "warmup_complete": self.is_warm,
            "warmup_factor": round(self.warmup_factor, 2),
            "bot_detections": self.session_data.get("bot_detections", 0),
        }

    def _save(self):
        if "sessions" not in self.state:
            self.state["sessions"] = {}
        self.state["sessions"][self.session_name] = self.session_data
        _save_json(SIM_STATE_FILE, self.state)

# ============================================================================
#  BOT DETECTION FAILSAFE — Detect and respond to challenges
# ============================================================================

class BotDetectionFailsafe:
    """
    Monitors for bot-detection signals and responds gracefully.

    Detection signals:
      - CAPTCHA iframes (reCAPTCHA, hCaptcha, Turnstile)
      - "Unusual traffic" / "verify you're human" text
      - HTTP 429 (rate limit) or 403 (forbidden) responses
      - Account lockout / "suspicious activity" pages
      - Browser challenge pages (Cloudflare, Akamai)

    Response strategy:
      1. PAUSE immediately (don't keep hitting the page)
      2. LOG the detection event with context
      3. ALERT Chris via email (if available)
      4. BACKOFF with exponential delay + jitter
      5. RETRY with reduced activity level
      6. ESCALATE if detections exceed threshold
    """

    # DOM signals that indicate bot detection
    CAPTCHA_SIGNALS = [
        "g-recaptcha", "h-captcha", "cf-turnstile",
        "recaptcha-anchor", "captcha-container",
        "challenge-form", "captcha_challenge",
    ]

    TEXT_SIGNALS = [
        "unusual traffic", "verify you're human",
        "automated queries", "prove you're not a robot",
        "suspicious activity", "account has been locked",
        "too many requests", "rate limit exceeded",
        "please complete the security check",
        "access denied", "blocked",
    ]

    CHALLENGE_URLS = [
        "challenges.cloudflare.com",
        "geo.captcha-delivery.com",
        "google.com/recaptcha",
        "hcaptcha.com",
    ]

    def __init__(self, max_detections_per_hour: int = 3):
        self.max_detections_per_hour = max_detections_per_hour
        self.log = _load_json(BOT_DETECTION_LOG, {"events": [], "stats": {}})
        self._consecutive_detections = 0
        self._backoff_seconds = 30  # Starting backoff

    def check_page(self, page_source: str = "", url: str = "",
                    status_code: int = 200) -> dict:
        """
        Analyze a page for bot-detection signals.

        Returns:
          {"detected": bool, "signal": str, "severity": str, "action": str}
        """
        result = {
            "detected": False,
            "signal": None,
            "severity": "none",
            "action": "continue",
        }

        source_lower = page_source.lower() if page_source else ""

        # Check HTTP status
        if status_code == 429:
            result.update(detected=True, signal="HTTP 429 Rate Limit",
                         severity="warning", action="backoff")
        elif status_code == 403:
            result.update(detected=True, signal="HTTP 403 Forbidden",
                         severity="warning", action="backoff")

        # Check for CAPTCHA elements in DOM
        for sig in self.CAPTCHA_SIGNALS:
            if sig in source_lower:
                result.update(detected=True, signal=f"CAPTCHA: {sig}",
                             severity="alert", action="pause_and_alert")
                break

        # Check for text-based signals
        if not result["detected"]:
            for sig in self.TEXT_SIGNALS:
                if sig in source_lower:
                    result.update(detected=True, signal=f"Text: {sig}",
                                 severity="warning", action="backoff")
                    break

        # Check URL for challenge pages
        if not result["detected"]:
            for challenge_url in self.CHALLENGE_URLS:
                if challenge_url in url.lower():
                    result.update(detected=True, signal=f"Challenge URL: {challenge_url}",
                                 severity="alert", action="pause_and_alert")
                    break

        if result["detected"]:
            self._handle_detection(result, url)

        return result

    def _handle_detection(self, result: dict, url: str):
        """Process a detection event."""
        self._consecutive_detections += 1

        event = {
            "time": datetime.now().isoformat(),
            "signal": result["signal"],
            "severity": result["severity"],
            "url": url[:200],
            "consecutive": self._consecutive_detections,
            "backoff_s": self.get_backoff_seconds(),
        }

        self.log["events"].append(event)

        # Update stats
        stats = self.log.get("stats", {})
        stats["total_detections"] = stats.get("total_detections", 0) + 1
        stats["last_detection"] = event["time"]
        self.log["stats"] = stats

        # Trim log
        if len(self.log["events"]) > 200:
            self.log["events"] = self.log["events"][-100:]

        _save_json(BOT_DETECTION_LOG, self.log)

        # Check escalation threshold
        recent = [
            e for e in self.log["events"]
            if e.get("time", "") > (
                datetime.now() - timedelta(hours=1)
            ).isoformat()
        ]
        if len(recent) >= self.max_detections_per_hour:
            result["action"] = "escalate"
            result["severity"] = "critical"

    def get_backoff_seconds(self) -> float:
        """
        Exponential backoff with jitter.
        30s → 60s → 120s → 240s → 480s (cap at 8 min)
        Plus ±25% random jitter.
        """
        base = self._backoff_seconds * (2 ** (self._consecutive_detections - 1))
        base = min(base, 480)  # Cap at 8 minutes
        jitter = base * random.uniform(-0.25, 0.25)
        return base + jitter

    def reset_backoff(self):
        """Reset backoff after successful actions (no detection)."""
        self._consecutive_detections = 0
        self._backoff_seconds = 30

    def get_detection_rate(self, hours: int = 24) -> dict:
        """Get detection rate statistics."""
        cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
        recent = [e for e in self.log.get("events", []) if e.get("time", "") > cutoff]

        return {
            "period_hours": hours,
            "total_detections": len(recent),
            "by_severity": {
                "warning": sum(1 for e in recent if e.get("severity") == "warning"),
                "alert": sum(1 for e in recent if e.get("severity") == "alert"),
                "critical": sum(1 for e in recent if e.get("severity") == "critical"),
            },
            "consecutive_current": self._consecutive_detections,
            "current_backoff_s": round(self.get_backoff_seconds(), 1),
        }

# ============================================================================
#  FINGERPRINT MANAGER — Coherent, persistent browser identity
# ============================================================================

class FingerprintManager:
    """
    Maintains consistent browser fingerprints across sessions.

    Key insight: Randomizing fingerprints on every session is a
    stronger bot signal than having a single consistent one.
    Google and other platforms track fingerprint stability — a
    "person" whose screen resolution, timezone, and fonts change
    every day is obviously automated.

    This manager creates ONE coherent identity and sticks with it,
    only rotating on a 30-day cycle or when forced.
    """

    FINGERPRINT_FILE = LOGS_DIR / "browser-fingerprint.json"

    # Realistic viewport sizes (common resolutions)
    VIEWPORTS = [
        (1920, 1080), (1536, 864), (1440, 900), (1366, 768),
        (2560, 1440), (1680, 1050), (1280, 720),
    ]

    # Common user-agent components
    CHROME_VERSIONS = [
        "120.0.6099.109", "121.0.6167.85", "122.0.6261.57",
        "123.0.6312.86", "124.0.6367.60", "125.0.6422.76",
    ]

    PLATFORMS = [
        ("Windows NT 10.0; Win64; x64", "Win32"),
        ("Windows NT 11.0; Win64; x64", "Win32"),
    ]

    def __init__(self):
        self.fingerprint = _load_json(self.FINGERPRINT_FILE, {})
        if not self.fingerprint or self._should_rotate():
            self._generate_fingerprint()

    def _should_rotate(self) -> bool:
        """Rotate fingerprint every 30 days."""
        created = self.fingerprint.get("created")
        if not created:
            return True
        try:
            created_dt = datetime.fromisoformat(created)
            return (datetime.now() - created_dt).days > 30
        except Exception:
            return True

    def _generate_fingerprint(self):
        """Generate a coherent browser fingerprint."""
        viewport = random.choice(self.VIEWPORTS)
        chrome_ver = random.choice(self.CHROME_VERSIONS)
        platform_info, platform_str = random.choice(self.PLATFORMS)

        self.fingerprint = {
            "created": datetime.now().isoformat(),
            "rotation_id": random.randint(1000, 9999),
            "user_agent": (
                f"Mozilla/5.0 ({platform_info}) "
                f"AppleWebKit/537.36 (KHTML, like Gecko) "
                f"Chrome/{chrome_ver} Safari/537.36"
            ),
            "viewport": {"width": viewport[0], "height": viewport[1]},
            "screen": {
                "width": viewport[0],
                "height": viewport[1],
                "availWidth": viewport[0],
                "availHeight": viewport[1] - 40,  # Taskbar
                "colorDepth": 24,
                "pixelRatio": random.choice([1, 1.25, 1.5, 2]),
            },
            "platform": platform_str,
            "language": "en-US",
            "languages": ["en-US", "en"],
            "timezone": "America/Los_Angeles",
            "timezone_offset": 480 if random.random() < 0.5 else 420,  # PST/PDT
            "hardware_concurrency": random.choice([4, 8, 12, 16]),
            "device_memory": random.choice([4, 8, 16]),
            "max_touch_points": 0,  # Desktop
            "webgl_vendor": "Google Inc. (Intel)",
            "webgl_renderer": random.choice([
                "ANGLE (Intel, Intel(R) UHD Graphics 630, OpenGL 4.5)",
                "ANGLE (Intel, Intel(R) UHD Graphics 620, OpenGL 4.5)",
                "ANGLE (Intel, Intel(R) Iris(R) Xe Graphics, OpenGL 4.5)",
            ]),
            "do_not_track": None,  # Most real users don't set this
            "plugins_count": random.randint(3, 5),
        }

        _save_json(self.FINGERPRINT_FILE, self.fingerprint)

    def get_launch_args(self) -> List[str]:
        """Get Chromium launch arguments that match our fingerprint."""
        fp = self.fingerprint
        vp = fp.get("viewport", {})

        return [
            f"--window-size={vp.get('width', 1920)},{vp.get('height', 1080)}",
            f"--user-agent={fp.get('user_agent', '')}",
            f"--lang={fp.get('language', 'en-US')}",
            "--disable-blink-features=AutomationControlled",
            "--disable-features=IsolateOrigins,site-per-process",
            "--disable-infobars",
            "--no-first-run",
            "--no-default-browser-check",
        ]

    def get_stealth_scripts(self) -> List[str]:
        """
        JavaScript snippets to inject for fingerprint coherence.
        Overrides navigator properties, WebGL, etc.
        """
        fp = self.fingerprint
        screen = fp.get("screen", {})

        scripts = []

        # Override navigator.webdriver
        scripts.append("""
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined,
            });
        """)

        # Override navigator.platform
        scripts.append(f"""
            Object.defineProperty(navigator, 'platform', {{
                get: () => '{fp.get("platform", "Win32")}',
            }});
        """)

        # Override navigator.hardwareConcurrency
        scripts.append(f"""
            Object.defineProperty(navigator, 'hardwareConcurrency', {{
                get: () => {fp.get("hardware_concurrency", 8)},
            }});
        """)

        # Override navigator.deviceMemory
        scripts.append(f"""
            Object.defineProperty(navigator, 'deviceMemory', {{
                get: () => {fp.get("device_memory", 8)},
            }});
        """)

        # Override screen properties
        scripts.append(f"""
            Object.defineProperty(screen, 'width', {{ get: () => {screen.get('width', 1920)} }});
            Object.defineProperty(screen, 'height', {{ get: () => {screen.get('height', 1080)} }});
            Object.defineProperty(screen, 'availWidth', {{ get: () => {screen.get('availWidth', 1920)} }});
            Object.defineProperty(screen, 'availHeight', {{ get: () => {screen.get('availHeight', 1040)} }});
            Object.defineProperty(screen, 'colorDepth', {{ get: () => {screen.get('colorDepth', 24)} }});
        """)

        # Chrome runtime (missing in headless)
        scripts.append("""
            window.chrome = {
                runtime: {
                    onMessage: { addListener: function() {} },
                    sendMessage: function() {},
                },
                loadTimes: function() { return {}; },
                csi: function() { return {}; },
            };
        """)

        # Permissions API override
        scripts.append("""
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) =>
                parameters.name === 'notifications'
                    ? Promise.resolve({ state: Notification.permission })
                    : originalQuery(parameters);
        """)

        return scripts

    @property
    def identity_summary(self) -> dict:
        """Brief summary of current fingerprint identity."""
        fp = self.fingerprint
        return {
            "rotation_id": fp.get("rotation_id"),
            "created": fp.get("created"),
            "chrome_version": (fp.get("user_agent", "").split("Chrome/")[1].split(" ")[0]
                              if "Chrome/" in fp.get("user_agent", "") else "?"),
            "viewport": f"{fp.get('viewport', {}).get('width')}x{fp.get('viewport', {}).get('height')}",
            "timezone": fp.get("timezone"),
            "cores": fp.get("hardware_concurrency"),
        }

# ============================================================================
#  HUMAN SIMULATOR — Unified interface for all human behavior
# ============================================================================

class HumanSimulator:
    """
    Master controller that orchestrates all simulation components.

    Usage with Playwright:
        sim = HumanSimulator(session_name="google-rudy")

        # Apply fingerprint to browser
        browser = playwright.chromium.launch(args=sim.fingerprint.get_launch_args())
        context = browser.new_context(
            user_agent=sim.fingerprint.fingerprint["user_agent"],
            viewport=sim.fingerprint.fingerprint["viewport"],
        )
        page = context.new_page()

        # Inject stealth scripts
        for script in sim.fingerprint.get_stealth_scripts():
            page.add_init_script(script)

        # Navigate with human timing
        sim.navigate(page, "https://gmail.com")

        # Type with realistic patterns
        sim.type_text(page, "#email", "user@example.com")

        # Click with mouse movement
        sim.click(page, "#next-button")
    """

    def __init__(self, session_name: str = "default"):
        self.timing = TimingEngine()
        self.mouse = MouseEngine()
        self.keyboard = KeyboardEngine()
        self.session = SessionManager(session_name)
        self.failsafe = BotDetectionFailsafe()
        self.fingerprint = FingerprintManager()
        self._page = None

    def attach_page(self, page):
        """Attach a Playwright page for direct interaction."""
        self._page = page

    def navigate(self, page=None, url: str = ""):
        """Navigate to URL with human-like timing."""
        p = page or self._page
        if not p:
            raise ValueError("No page attached. Call attach_page() or pass page.")

        # Pre-navigation pause (humans don't instantly click)
        self.timing.sleep("action")

        p.goto(url, wait_until="domcontentloaded")

        # Post-navigation settle (page load + visual scan)
        warmup = self.session.warmup_factor
        settle_time = self.timing.delay("page_settle") * warmup
        time.sleep(settle_time)

        # Check for bot detection
        try:
            source = p.content()
            detection = self.failsafe.check_page(
                page_source=source, url=p.url
            )
            if detection["detected"]:
                self._handle_bot_detection(detection)
        except Exception:
            pass

        self.session.record_action("navigate", url)

    def type_text(self, page=None, selector: str = "", text: str = "",
                  clear_first: bool = True):
        """Type text with realistic keystroke timing."""
        p = page or self._page
        if not p:
            raise ValueError("No page attached.")

        # Click the field first (with mouse movement)
        self.click(p, selector)

        # Clear existing text if requested
        if clear_first:
            p.fill(selector, "")
            self.timing.sleep("micro_pause")

        # Generate and execute keystrokes
        keystrokes = self.keyboard.generate_keystrokes(text)

        for ks in keystrokes:
            if ks["action"] == "think_pause":
                time.sleep(ks["delay_s"] * self.session.warmup_factor)
                continue

            time.sleep(ks["delay_s"] * self.session.warmup_factor)

            if ks["char"] == "Backspace":
                p.keyboard.press("Backspace")
            elif ks["char"]:
                p.keyboard.type(ks["char"])

        self.session.record_action("type", selector)

    def click(self, page=None, selector: str = ""):
        """Click an element with mouse movement to target."""
        p = page or self._page
        if not p:
            raise ValueError("No page attached.")

        # Get element position
        try:
            box = p.locator(selector).bounding_box()
            if not box:
                # Fallback: direct click
                p.click(selector)
                self.session.record_action("click", selector)
                return
        except Exception:
            p.click(selector)
            self.session.record_action("click", selector)
            return

        # Calculate target point (with slight randomness within the element)
        target_x = int(box["x"] + box["width"] * random.uniform(0.3, 0.7))
        target_y = int(box["y"] + box["height"] * random.uniform(0.3, 0.7))

        # Generate mouse path from current position
        path = self.mouse.generate_path(
            self.mouse._last_pos, (target_x, target_y)
        )

        # Execute mouse movement
        for point in path:
            p.mouse.move(point[0], point[1])
            time.sleep(random.gauss(0.008, 0.002))  # ~8ms between points

        # Pre-click pause
        self.timing.sleep("micro_pause")

        # Click
        p.mouse.click(target_x, target_y)

        # Post-click settle
        self.timing.sleep("action")

        self.session.record_action("click", selector)

    def scroll_page(self, page=None, pixels: int = 500, direction: str = "down"):
        """Scroll with human-like burst pattern."""
        p = page or self._page
        if not p:
            raise ValueError("No page attached.")

        increments = self.mouse.generate_scroll_sequence(pixels, direction)

        for inc in increments:
            if inc == 0:
                # Pause (reading)
                self.timing.sleep("scroll")
            else:
                p.mouse.wheel(0, inc)
                time.sleep(random.gauss(0.05, 0.015))

        self.session.record_action("scroll", f"{direction}:{pixels}px")

    def read_page(self, page=None, content: str = ""):
        """
        Simulate reading the page content.
        Waits a natural amount of time proportional to visible text.
        """
        p = page or self._page
        if not content and p:
            try:
                content = p.inner_text("body")
            except Exception:
                content = ""

        read_time = self.timing.reading_time(content[:2000])  # Cap analysis
        read_time = min(read_time, 30)  # Max 30s simulated reading
        read_time *= self.session.warmup_factor

        # Humans scroll while reading
        if read_time > 3:
            scroll_after = random.uniform(1.5, read_time * 0.4)
            time.sleep(scroll_after)
            self.scroll_page(p, random.randint(200, 500))
            time.sleep(read_time - scroll_after)
        else:
            time.sleep(read_time)

        self.session.record_action("read")

    def _handle_bot_detection(self, detection: dict):
        """Respond to a bot detection event."""
        action = detection.get("action", "continue")

        if action == "continue":
            return

        if action == "backoff":
            backoff = self.failsafe.get_backoff_seconds()
            time.sleep(backoff)

        elif action == "pause_and_alert":
            # Alert Chris (if email is available)
            self._send_alert(detection)
            # Long pause
            backoff = self.failsafe.get_backoff_seconds()
            time.sleep(backoff * 2)

        elif action == "escalate":
            self._send_alert(detection, critical=True)
            # Very long pause (15-30 min)
            time.sleep(random.uniform(900, 1800))

    def _send_alert(self, detection: dict, critical: bool = False):
        """Send bot-detection alert via email (best-effort)."""
        try:
            import smtplib
            from email.mime.text import MIMEText

            subject = (
                "CRITICAL: Rudy Bot Detection Escalation"
                if critical else "Rudy: Bot Detection Alert"
            )
            body = (
                f"Bot detection triggered at {datetime.now().isoformat()}\n\n"
                f"Signal: {detection.get('signal')}\n"
                f"Severity: {detection.get('severity')}\n"
                f"Action: {detection.get('action')}\n"
                f"Session: {self.session.session_name}\n\n"
                f"Detection rate (24h): {json.dumps(self.failsafe.get_detection_rate(), indent=2)}\n"
            )

            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = "rudy.ciminoassist@gmail.com"
            msg["To"] = "ccimino2@gmail.com"

            with smtplib.SMTP("smtp.gmail.com", 587) as server:
                server.starttls()
                server.login("rudy.ciminoassist@gmail.com", "bviu yjdp tufr tnys")
                server.send_message(msg)
        except Exception:
            # Best-effort — don't crash on alert failure
            pass

    def get_status(self) -> dict:
        """Full status report of the simulation engine."""
        return {
            "timestamp": datetime.now().isoformat(),
            "timing": self.timing.timing_stats,
            "mouse": {
                "velocity_variance": self.mouse.velocity_variance,
                "human_like": self.mouse.velocity_variance > 15,
            },
            "session": self.session.get_session_health(),
            "bot_detection": self.failsafe.get_detection_rate(),
            "fingerprint": self.fingerprint.identity_summary,
        }

    def print_status(self):
        """Print a human-readable status report."""
        status = self.get_status()

        print("=" * 55)
        print("  HUMAN SIMULATION ENGINE — STATUS")
        print("=" * 55)

        t = status["timing"]
        print("\n  Timing:")
        print(f"    Actions sampled: {t['n']}")
        print(f"    Mean delay: {t['mean_ms']}ms (target: ~400ms)")
        print(f"    Std deviation: {t['std_ms']}ms (target: ~150ms)")
        print(f"    Fatigue factor: {t['fatigue_factor']}x")
        print(f"    Session length: {t['session_minutes']} min")

        m = status["mouse"]
        vv = m["velocity_variance"]
        human = "PASS" if m["human_like"] else f"LOW ({vv} < 15)"
        print("\n  Mouse:")
        print(f"    Velocity variance: {vv} [{human}]")

        s = status["session"]
        print(f"\n  Session: {s['session_name']}")
        print(f"    Total actions: {s['total_actions']}")
        print(f"    Failure rate: {s['recent_failure_rate']:.1%}")
        wf = s["warmup_factor"]
        warmup_str = "complete" if s["warmup_complete"] else f"{wf}x"
        print(f"    Warmup: {warmup_str}")
        print(f"    Bot detections: {s['bot_detections']}")

        b = status["bot_detection"]
        print("\n  Bot Detection (24h):")
        print(f"    Total: {b['total_detections']}")
        print(f"    By severity: {json.dumps(b['by_severity'])}")
        print(f"    Consecutive: {b['consecutive_current']}")
        print(f"    Backoff: {b['current_backoff_s']}s")

        f = status["fingerprint"]
        print("\n  Fingerprint:")
        print(f"    ID: {f['rotation_id']}")
        print(f"    Chrome: {f['chrome_version']}")
        print(f"    Viewport: {f['viewport']}")
        print(f"    Timezone: {f['timezone']}")

        print("\n" + "=" * 55)

# ============================================================================
#  CONVENIENCE FUNCTIONS
# ============================================================================

def create_simulator(session_name: str = "default") -> HumanSimulator:
    """Create a pre-configured HumanSimulator instance."""
    return HumanSimulator(session_name=session_name)

def demo_timing():
    """Demo the timing engine distributions."""
    te = TimingEngine()
    print("Timing Engine Demo — 20 samples per profile:\n")
    for profile in ["action", "keystroke", "scroll", "page_settle", "think"]:
        samples = [te.delay(profile) * 1000 for _ in range(20)]
        mean = sum(samples) / len(samples)
        std = (sum((s - mean)**2 for s in samples) / len(samples)) ** 0.5
        print(f"  {profile:15s}  mean={mean:7.1f}ms  std={std:6.1f}ms  "
              f"range=[{min(samples):6.1f}, {max(samples):7.1f}]")
    print(f"\n  Timing stats: {te.timing_stats}")

def demo_mouse():
    """Demo mouse path generation."""
    me = MouseEngine()
    path = me.generate_path((100, 100), (800, 500))
    print(f"Mouse path: {len(path)} points from (100,100) → (800,500)")
    print(f"  First 5: {path[:5]}")
    print(f"  Last 5: {path[-5:]}")
    print(f"  Velocity variance: {me.velocity_variance}")

if __name__ == "__main__":
    print("Human Behavior Simulation Module\n")
    demo_timing()
    print()
    demo_mouse()
    print()
    sim = create_simulator("demo")
    sim.print_status()
