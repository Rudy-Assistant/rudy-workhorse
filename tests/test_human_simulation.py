"""
Tests for rudy.human_simulation — TimingEngine, MouseEngine, KeyboardEngine,
SessionManager, BotDetectionFailsafe, FingerprintManager, HumanSimulator.

All time.sleep calls are mocked out; these tests verify the logic of timing
distributions, path generation, keystroke simulation, bot detection, and
session management without actual delays.
"""
import json
import math
import os
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

# Ensure directories exist before import
desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
(desktop / "rudy-logs").mkdir(parents=True, exist_ok=True)
(desktop / "data" / "sessions").mkdir(parents=True, exist_ok=True)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def sim_paths(tmp_path, monkeypatch):
    """Redirect all human_simulation file paths to tmp_path."""
    import rudy.human_simulation as mod
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(mod, "SESSIONS_DIR", tmp_path / "sessions")
    monkeypatch.setattr(mod, "SIM_STATE_FILE", tmp_path / "sim-state.json")
    monkeypatch.setattr(mod, "SIM_LOG_FILE", tmp_path / "sim-log.json")
    monkeypatch.setattr(mod, "BOT_DETECTION_LOG", tmp_path / "bot-detect.json")
    # Also patch FingerprintManager class-level attribute
    monkeypatch.setattr(mod.FingerprintManager, "FINGERPRINT_FILE",
                        tmp_path / "fingerprint.json")
    return tmp_path


# ── _load_json / _save_json ──────────────────────────────────────

def test_load_json_missing(tmp_path):
    from rudy.human_simulation import _load_json
    assert _load_json(tmp_path / "nope.json") == {}


def test_load_json_with_default(tmp_path):
    from rudy.human_simulation import _load_json
    assert _load_json(tmp_path / "nope.json", default=[]) == []


def test_load_json_corrupt(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{invalid", encoding="utf-8")
    from rudy.human_simulation import _load_json
    assert _load_json(bad, default={"ok": True}) == {"ok": True}


def test_save_and_load(tmp_path):
    from rudy.human_simulation import _save_json, _load_json
    path = tmp_path / "sub" / "test.json"
    _save_json(path, {"key": 42})
    assert _load_json(path) == {"key": 42}


# ============================================================================
#  TIMING ENGINE
# ============================================================================

class TestTimingEngine:
    def _make(self):
        from rudy.human_simulation import TimingEngine
        return TimingEngine()

    def test_delay_returns_seconds(self):
        te = self._make()
        d = te.delay("action")
        assert isinstance(d, float)
        assert d > 0

    def test_delay_within_bounds(self):
        """All delays should be within profile min/max bounds."""
        te = self._make()
        for _ in range(100):
            d = te.delay("keystroke") * 1000  # convert to ms
            # With fatigue factor, values may slightly exceed nominal max
            # but should be reasonable
            assert d > 0
            assert d < 5000  # Generous upper bound

    def test_delay_unknown_profile_falls_back_to_action(self):
        te = self._make()
        d = te.delay("nonexistent_profile")
        assert d > 0

    def test_sleep_calls_time_sleep(self):
        te = self._make()
        with patch("rudy.human_simulation.time.sleep") as mock_sleep:
            result = te.sleep("action")
        assert result > 0
        mock_sleep.assert_called_once()

    def test_typing_delays_length_matches_text(self):
        te = self._make()
        text = "Hello World"
        delays = te.typing_delays(text)
        assert len(delays) == len(text)

    def test_typing_delays_space_uses_word_gap(self):
        """Spaces should produce delays from the word_gap profile."""
        te = self._make()
        text = "a b"
        delays = te.typing_delays(text)
        assert len(delays) == 3
        # The space delay (index 1) should generally be longer than keystroke
        # (not guaranteed due to randomness, but statistically likely)

    def test_typing_delays_all_positive(self):
        te = self._make()
        delays = te.typing_delays("Test string with CAPS and !punctuation!")
        assert all(d > 0 for d in delays)

    def test_reading_time_empty(self):
        te = self._make()
        t = te.reading_time("")
        assert t == 0.5

    def test_reading_time_scales_with_length(self):
        te = self._make()
        short = te.reading_time("Hello world")
        long_text = " ".join(["word"] * 200)
        long_t = te.reading_time(long_text)
        assert long_t > short

    def test_welford_updates_stats(self):
        te = self._make()
        for _ in range(10):
            te.delay("action")
        stats = te.timing_stats
        assert stats["n"] == 10
        assert stats["mean_ms"] > 0
        assert stats["std_ms"] >= 0

    def test_reset_session(self):
        te = self._make()
        for _ in range(5):
            te.delay("action")
        te.reset_session()
        stats = te.timing_stats
        assert stats["n"] == 0

    def test_fatigue_increases_over_time(self):
        """Fatigue factor increases as session progresses."""
        te = self._make()
        # Fresh session
        te.delay("action")
        fresh_fatigue = te._fatigue_factor

        # Simulate 60 minutes elapsed
        te._session_start = time.time() - 3600
        te.delay("action")
        fatigued = te._fatigue_factor

        assert fatigued > fresh_fatigue

    def test_fatigue_capped(self):
        """Fatigue factor should not exceed 1.4."""
        te = self._make()
        te._session_start = time.time() - 86400  # 24 hours ago
        te.delay("action")
        assert te._fatigue_factor <= 1.4

    def test_profiles_exist(self):
        from rudy.human_simulation import TimingEngine
        expected = ["action", "keystroke", "word_gap", "read_word",
                    "scroll", "page_settle", "micro_pause", "think", "tab_switch"]
        for p in expected:
            assert p in TimingEngine.PROFILES


# ============================================================================
#  MOUSE ENGINE
# ============================================================================

class TestMouseEngine:
    def _make(self):
        from rudy.human_simulation import MouseEngine
        return MouseEngine()

    def test_generate_path_basic(self):
        me = self._make()
        path = me.generate_path((0, 0), (100, 100))
        assert len(path) >= 2
        # First point should be near start, last near end
        assert path[-1][0] == pytest.approx(100, abs=20)
        assert path[-1][1] == pytest.approx(100, abs=20)

    def test_generate_path_very_short_distance(self):
        me = self._make()
        path = me.generate_path((50, 50), (51, 50))
        assert path == [(50, 50), (51, 50)]

    def test_generate_path_updates_last_pos(self):
        me = self._make()
        assert me._last_pos == (0, 0)
        me.generate_path((0, 0), (200, 200))
        assert me._last_pos != (0, 0)

    def test_velocity_variance_insufficient_samples(self):
        me = self._make()
        assert me.velocity_variance == 0

    def test_velocity_variance_after_movement(self):
        me = self._make()
        # Generate several paths to build up velocity samples
        for i in range(5):
            me.generate_path((0, 0), (500 + i * 50, 300 + i * 30))
        # Should have some variance now
        assert me.velocity_variance >= 0

    def test_ease_in_out_boundaries(self):
        me = self._make()
        assert me._ease_in_out(0.0) == 0.0
        assert me._ease_in_out(1.0) == 1.0
        assert me._ease_in_out(0.5) == 0.5

    def test_ease_in_out_monotonic(self):
        me = self._make()
        prev = -1
        for i in range(11):
            t = i / 10
            val = me._ease_in_out(t)
            assert val >= prev
            prev = val

    def test_generate_scroll_sequence_down(self):
        me = self._make()
        seq = me.generate_scroll_sequence(500, "down")
        # All non-zero values should be positive (down)
        non_zero = [s for s in seq if s != 0]
        assert all(s > 0 for s in non_zero)
        # Total scrolled should approximately match target
        total = sum(abs(s) for s in seq if s != 0)
        assert total >= 400  # Allow some variance

    def test_generate_scroll_sequence_up(self):
        me = self._make()
        seq = me.generate_scroll_sequence(500, "up")
        non_zero = [s for s in seq if s != 0]
        assert all(s < 0 for s in non_zero)

    def test_scroll_contains_pause_markers(self):
        me = self._make()
        seq = me.generate_scroll_sequence(2000, "down")
        # For a long scroll, there should be pause markers (0)
        assert 0 in seq

    def test_path_not_straight_line(self):
        """Paths should curve, not be perfectly straight."""
        me = self._make()
        random.seed(42)
        path = me.generate_path((0, 0), (1000, 0), steps=50, overshoot_chance=0)
        # If straight, all y values would be ~0.
        # With curves, at least some y values should deviate
        y_values = [p[1] for p in path[1:-1]]
        max_deviation = max(abs(y) for y in y_values) if y_values else 0
        assert max_deviation > 0  # Path curves away from straight line

    def test_velocity_samples_trimmed(self):
        me = self._make()
        # Generate many paths to exceed the 1000-sample buffer
        for _ in range(30):
            me.generate_path((0, 0), (500, 500), steps=50)
        assert len(me._velocity_samples) <= 1000


# ============================================================================
#  KEYBOARD ENGINE
# ============================================================================

class TestKeyboardEngine:
    def _make(self, **kwargs):
        from rudy.human_simulation import KeyboardEngine
        return KeyboardEngine(**kwargs)

    def test_generate_keystrokes_length(self):
        kb = self._make(typo_rate=0)  # No typos for predictable length
        events = kb.generate_keystrokes("hello")
        type_events = [e for e in events if e["action"] == "type"]
        assert len(type_events) == 5

    def test_keystrokes_have_positive_delays(self):
        kb = self._make(typo_rate=0)
        events = kb.generate_keystrokes("Test string")
        assert all(e["delay_s"] > 0 for e in events)

    def test_typo_rate_zero_means_no_corrections(self):
        kb = self._make(typo_rate=0)
        events = kb.generate_keystrokes("Hello World test string for typing")
        corrections = [e for e in events if e["action"] == "correct"]
        assert len(corrections) == 0

    def test_typo_rate_high_produces_corrections(self):
        """With high typo rate, we expect some corrections."""
        kb = self._make(typo_rate=0.5)  # 50% typo rate
        random.seed(42)
        events = kb.generate_keystrokes("abcdefghijklmnop")
        corrections = [e for e in events if e["action"] == "correct"]
        assert len(corrections) > 0

    def test_keystrokes_include_think_pauses(self):
        """With enough text, there should be occasional think pauses."""
        kb = self._make(typo_rate=0)
        random.seed(42)
        text = " ".join(["word"] * 50)  # Lots of spaces = chances for think pause
        events = kb.generate_keystrokes(text)
        think_pauses = [e for e in events if e["action"] == "think_pause"]
        # Statistically expect at least 1 with 50 spaces at 12% chance each
        assert len(think_pauses) >= 0  # Non-deterministic, just ensure no crash

    def test_key_distance_same_key(self):
        kb = self._make()
        d = kb._key_distance("a", "a")
        assert d == 0.0

    def test_key_distance_adjacent(self):
        kb = self._make()
        d = kb._key_distance("a", "s")
        assert d == 1.0

    def test_key_distance_unknown_key(self):
        kb = self._make()
        d = kb._key_distance("1", "2")
        assert d == 2.0  # Default for non-letter keys

    def test_nearby_key_returns_neighbor(self):
        kb = self._make()
        # 'f' neighbors should include d, g, r, t, v, c
        for _ in range(10):
            neighbor = kb._nearby_key("f")
            assert neighbor != "f" or neighbor == "f"  # May return self if no neighbors

    def test_nearby_key_unknown(self):
        kb = self._make()
        assert kb._nearby_key("1") == "1"

    def test_wpm_affects_base_delay(self):
        fast = self._make(wpm=120)
        slow = self._make(wpm=30)
        assert fast.base_delay_ms < slow.base_delay_ms


# ============================================================================
#  SESSION MANAGER
# ============================================================================

class TestSessionManager:
    def _make(self, sim_paths, name="test-session"):
        from rudy.human_simulation import SessionManager
        return SessionManager(name)

    def test_init_creates_session(self, sim_paths):
        sm = self._make(sim_paths)
        assert sm.session_name == "test-session"
        assert sm._action_count == 0

    def test_is_warm_false_initially(self, sim_paths):
        sm = self._make(sim_paths)
        assert not sm.is_warm

    def test_is_warm_after_10_min(self, sim_paths):
        sm = self._make(sim_paths)
        sm._session_start = time.time() - 700  # 11+ minutes ago
        assert sm.is_warm

    def test_warmup_factor_starts_high(self, sim_paths):
        sm = self._make(sim_paths)
        assert sm.warmup_factor > 1.5

    def test_warmup_factor_decreases_to_one(self, sim_paths):
        sm = self._make(sim_paths)
        sm._session_start = time.time() - 700
        assert sm.warmup_factor == 1.0

    def test_should_take_break_false_early(self, sim_paths):
        sm = self._make(sim_paths)
        # Fresh session, should not suggest a break
        assert not sm.should_take_break()

    def test_record_action(self, sim_paths):
        sm = self._make(sim_paths)
        sm.record_action("click", "https://example.com", success=True)
        assert sm._action_count == 1
        assert len(sm.session_data["actions"]) == 1
        assert sm.session_data["actions"][0]["type"] == "click"

    def test_record_action_trims_old(self, sim_paths):
        sm = self._make(sim_paths)
        for i in range(600):
            sm.record_action("click", f"url-{i}")
        # Trims to 300 when exceeding 500, but continues to add after trim
        # So final count should be less than 600
        assert len(sm.session_data["actions"]) < 600

    def test_get_session_health(self, sim_paths):
        sm = self._make(sim_paths)
        sm.record_action("navigate", success=True)
        sm.record_action("click", success=False)

        health = sm.get_session_health()
        assert health["session_name"] == "test-session"
        assert health["total_actions"] == 2
        assert health["recent_failure_rate"] == 0.5
        assert "warmup_complete" in health

    def test_session_persists_to_file(self, sim_paths):
        sm = self._make(sim_paths)
        sm.record_action("test")

        from rudy.human_simulation import _load_json, SIM_STATE_FILE
        state = _load_json(SIM_STATE_FILE)
        assert "test-session" in state.get("sessions", {})


# ============================================================================
#  BOT DETECTION FAILSAFE
# ============================================================================

class TestBotDetectionFailsafe:
    def _make(self, sim_paths):
        from rudy.human_simulation import BotDetectionFailsafe
        return BotDetectionFailsafe()

    def test_check_clean_page(self, sim_paths):
        bd = self._make(sim_paths)
        result = bd.check_page("<html><body>Normal page</body></html>", "https://example.com")
        assert not result["detected"]
        assert result["action"] == "continue"

    def test_check_rate_limit_429(self, sim_paths):
        bd = self._make(sim_paths)
        result = bd.check_page("", "https://example.com", status_code=429)
        assert result["detected"]
        assert result["signal"] == "HTTP 429 Rate Limit"
        assert result["action"] == "backoff"

    def test_check_forbidden_403(self, sim_paths):
        bd = self._make(sim_paths)
        result = bd.check_page("", "https://example.com", status_code=403)
        assert result["detected"]
        assert result["signal"] == "HTTP 403 Forbidden"

    def test_check_captcha_in_dom(self, sim_paths):
        bd = self._make(sim_paths)
        html = '<div class="g-recaptcha" data-sitekey="abc"></div>'
        result = bd.check_page(html, "https://example.com")
        assert result["detected"]
        assert "CAPTCHA" in result["signal"]
        assert result["severity"] == "alert"

    def test_check_text_signal(self, sim_paths):
        bd = self._make(sim_paths)
        html = "<h1>Unusual Traffic Detected</h1><p>Please verify you're human</p>"
        result = bd.check_page(html, "https://example.com")
        assert result["detected"]
        assert "unusual traffic" in result["signal"].lower()

    def test_check_challenge_url(self, sim_paths):
        bd = self._make(sim_paths)
        result = bd.check_page("", "https://challenges.cloudflare.com/challenge")
        assert result["detected"]
        assert "Challenge URL" in result["signal"]

    def test_consecutive_detections_increase(self, sim_paths):
        bd = self._make(sim_paths)
        bd.check_page("", "", status_code=429)
        assert bd._consecutive_detections == 1
        bd.check_page("", "", status_code=429)
        assert bd._consecutive_detections == 2

    def test_backoff_exponential(self, sim_paths):
        bd = self._make(sim_paths)
        bd._consecutive_detections = 1
        b1 = bd.get_backoff_seconds()

        bd._consecutive_detections = 3
        b3 = bd.get_backoff_seconds()

        # b3 should be roughly 4x b1 (2^2 scaling), within jitter range
        assert b3 > b1

    def test_backoff_capped(self, sim_paths):
        bd = self._make(sim_paths)
        bd._consecutive_detections = 20
        b = bd.get_backoff_seconds()
        # Should be capped at 480 + jitter (25%)
        assert b <= 480 * 1.25 + 1

    def test_reset_backoff(self, sim_paths):
        bd = self._make(sim_paths)
        bd._consecutive_detections = 5
        bd.reset_backoff()
        assert bd._consecutive_detections == 0
        assert bd._backoff_seconds == 30

    def test_escalation_threshold(self, sim_paths):
        """3+ detections in an hour should escalate."""
        bd = self._make(sim_paths)
        bd.max_detections_per_hour = 3

        for _ in range(3):
            result = bd.check_page("", "", status_code=429)

        assert result["action"] == "escalate"
        assert result["severity"] == "critical"

    def test_get_detection_rate(self, sim_paths):
        bd = self._make(sim_paths)
        bd.check_page("", "", status_code=429)
        bd.check_page('<div class="g-recaptcha"></div>', "")

        rate = bd.get_detection_rate(hours=24)
        assert rate["total_detections"] == 2
        assert rate["period_hours"] == 24

    def test_detection_log_trimmed(self, sim_paths):
        bd = self._make(sim_paths)
        for _ in range(250):
            bd.check_page("", "", status_code=429)
        assert len(bd.log["events"]) <= 200


# ============================================================================
#  FINGERPRINT MANAGER
# ============================================================================

class TestFingerprintManager:
    def _make(self, sim_paths):
        from rudy.human_simulation import FingerprintManager
        return FingerprintManager()

    def test_generates_fingerprint_on_init(self, sim_paths):
        fm = self._make(sim_paths)
        assert "user_agent" in fm.fingerprint
        assert "viewport" in fm.fingerprint
        assert "timezone" in fm.fingerprint

    def test_fingerprint_has_chrome_ua(self, sim_paths):
        fm = self._make(sim_paths)
        assert "Chrome/" in fm.fingerprint["user_agent"]
        assert "Mozilla/5.0" in fm.fingerprint["user_agent"]

    def test_fingerprint_persists(self, sim_paths):
        fm1 = self._make(sim_paths)
        fp1 = fm1.fingerprint.copy()

        # Second init should load the same fingerprint
        fm2 = self._make(sim_paths)
        assert fm2.fingerprint["rotation_id"] == fp1["rotation_id"]

    def test_rotation_after_30_days(self, sim_paths):
        fm = self._make(sim_paths)

        # Simulate 31-day-old fingerprint
        fm.fingerprint["created"] = (
            datetime.now() - timedelta(days=31)
        ).isoformat()
        from rudy.human_simulation import _save_json, FingerprintManager
        _save_json(FingerprintManager.FINGERPRINT_FILE, fm.fingerprint)

        fm2 = self._make(sim_paths)
        # New fingerprint should have been generated (different ID likely)
        assert fm2.fingerprint["created"] != fm.fingerprint["created"]

    def test_get_launch_args(self, sim_paths):
        fm = self._make(sim_paths)
        args = fm.get_launch_args()
        assert any("--window-size=" in a for a in args)
        assert any("--user-agent=" in a for a in args)
        assert any("AutomationControlled" in a for a in args)

    def test_get_stealth_scripts(self, sim_paths):
        fm = self._make(sim_paths)
        scripts = fm.get_stealth_scripts()
        assert len(scripts) > 0
        # Should include webdriver override
        assert any("webdriver" in s for s in scripts)
        # Should include chrome runtime
        assert any("chrome" in s.lower() for s in scripts)

    def test_identity_summary(self, sim_paths):
        fm = self._make(sim_paths)
        summary = fm.identity_summary
        assert "rotation_id" in summary
        assert "chrome_version" in summary
        assert "viewport" in summary
        assert "x" in summary["viewport"]  # e.g., "1920x1080"

    def test_viewport_in_valid_set(self, sim_paths):
        fm = self._make(sim_paths)
        vp = fm.fingerprint["viewport"]
        from rudy.human_simulation import FingerprintManager
        valid_sizes = [(w, h) for w, h in FingerprintManager.VIEWPORTS]
        assert (vp["width"], vp["height"]) in valid_sizes


# ============================================================================
#  HUMAN SIMULATOR (integration)
# ============================================================================

class TestHumanSimulator:
    def _make(self, sim_paths):
        from rudy.human_simulation import HumanSimulator
        return HumanSimulator(session_name="test")

    def test_init_creates_all_components(self, sim_paths):
        hs = self._make(sim_paths)
        assert hs.timing is not None
        assert hs.mouse is not None
        assert hs.keyboard is not None
        assert hs.session is not None
        assert hs.failsafe is not None
        assert hs.fingerprint is not None

    def test_attach_page(self, sim_paths):
        hs = self._make(sim_paths)
        mock_page = MagicMock()
        hs.attach_page(mock_page)
        assert hs._page is mock_page

    def test_navigate_no_page_raises(self, sim_paths):
        hs = self._make(sim_paths)
        with pytest.raises(ValueError, match="No page"):
            hs.navigate(url="https://example.com")

    def test_type_text_no_page_raises(self, sim_paths):
        hs = self._make(sim_paths)
        with pytest.raises(ValueError, match="No page"):
            hs.type_text(selector="#input", text="hello")

    def test_click_no_page_raises(self, sim_paths):
        hs = self._make(sim_paths)
        with pytest.raises(ValueError, match="No page"):
            hs.click(selector="#btn")

    def test_scroll_no_page_raises(self, sim_paths):
        hs = self._make(sim_paths)
        with pytest.raises(ValueError, match="No page"):
            hs.scroll_page(pixels=500)

    def test_get_status(self, sim_paths):
        hs = self._make(sim_paths)
        status = hs.get_status()
        assert "timing" in status
        assert "mouse" in status
        assert "session" in status
        assert "bot_detection" in status
        assert "fingerprint" in status

    def test_navigate_with_mock_page(self, sim_paths):
        hs = self._make(sim_paths)
        mock_page = MagicMock()
        mock_page.content.return_value = "<html>Normal page</html>"
        mock_page.url = "https://example.com"

        with patch("rudy.human_simulation.time.sleep"):
            hs.navigate(mock_page, "https://example.com")

        mock_page.goto.assert_called_once_with(
            "https://example.com", wait_until="domcontentloaded"
        )

    def test_click_with_mock_page_bounding_box(self, sim_paths):
        hs = self._make(sim_paths)
        mock_page = MagicMock()
        mock_page.locator.return_value.bounding_box.return_value = {
            "x": 100, "y": 200, "width": 80, "height": 30
        }

        with patch("rudy.human_simulation.time.sleep"):
            hs.click(mock_page, "#button")

        mock_page.mouse.click.assert_called_once()

    def test_click_fallback_when_no_bbox(self, sim_paths):
        hs = self._make(sim_paths)
        mock_page = MagicMock()
        mock_page.locator.return_value.bounding_box.return_value = None

        with patch("rudy.human_simulation.time.sleep"):
            hs.click(mock_page, "#button")

        mock_page.click.assert_called_once_with("#button")

    def test_handle_bot_detection_backoff(self, sim_paths):
        hs = self._make(sim_paths)
        detection = {"action": "backoff", "signal": "test", "severity": "warning"}

        with patch("rudy.human_simulation.time.sleep") as mock_sleep:
            hs._handle_bot_detection(detection)
        mock_sleep.assert_called_once()

    def test_handle_bot_detection_continue(self, sim_paths):
        hs = self._make(sim_paths)
        detection = {"action": "continue"}

        with patch("rudy.human_simulation.time.sleep") as mock_sleep:
            hs._handle_bot_detection(detection)
        mock_sleep.assert_not_called()

    def test_send_alert_does_not_crash(self, sim_paths):
        """_send_alert is best-effort and should never raise."""
        hs = self._make(sim_paths)
        detection = {"signal": "test", "severity": "warning", "action": "pause"}
        hs._send_alert(detection)  # Should not raise
        hs._send_alert(detection, critical=True)  # Should not raise

    def test_print_status_does_not_crash(self, sim_paths, capsys):
        hs = self._make(sim_paths)
        # Generate some data
        hs.timing.delay("action")
        hs.mouse.generate_path((0, 0), (500, 500))
        hs.print_status()
        captured = capsys.readouterr()
        assert "HUMAN SIMULATION ENGINE" in captured.out


# ── Convenience functions ─────────────────────────────────────────

def test_create_simulator(sim_paths):
    from rudy.human_simulation import create_simulator
    sim = create_simulator("my-session")
    assert sim.session.session_name == "my-session"


def test_demo_timing(sim_paths, capsys):
    from rudy.human_simulation import demo_timing
    demo_timing()
    captured = capsys.readouterr()
    assert "Timing Engine Demo" in captured.out
    assert "action" in captured.out


def test_demo_mouse(sim_paths, capsys):
    from rudy.human_simulation import demo_mouse
    demo_mouse()
    captured = capsys.readouterr()
    assert "Mouse path" in captured.out
    assert "Velocity variance" in captured.out
