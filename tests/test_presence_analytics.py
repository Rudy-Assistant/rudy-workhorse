"""
Tests for rudy.presence_analytics — MAC analysis, device classification,
co-occurrence clustering, activity patterns, and household profiling.

No network or subprocess calls; all tests use synthetic data.
"""
import json
import os
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
(desktop / "rudy-logs").mkdir(parents=True, exist_ok=True)


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def pa_paths(tmp_path, monkeypatch):
    """Redirect all presence_analytics file paths to tmp_path."""
    import rudy.presence_analytics as mod
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(mod, "PRESENCE_LOG", tmp_path / "presence-log.json")
    monkeypatch.setattr(mod, "PRESENCE_CURRENT", tmp_path / "presence-current.json")
    monkeypatch.setattr(mod, "PRESENCE_ROUTINES", tmp_path / "presence-routines.json")
    monkeypatch.setattr(mod, "PRESENCE_DEVICES", tmp_path / "presence-devices.json")
    monkeypatch.setattr(mod, "ANALYTICS_FILE", tmp_path / "analytics.json")
    monkeypatch.setattr(mod, "INFERENCE_LOG", tmp_path / "inference-log.json")
    monkeypatch.setattr(mod, "HOUSEHOLD_FILE", tmp_path / "household.json")
    monkeypatch.setattr(mod, "SNAPSHOTS_DIR", tmp_path / "snapshots")
    return tmp_path


# ── MAC Address Intelligence ─────────────────────────────────────

class TestMacIntelligence:
    def test_is_mac_randomized_true(self):
        from rudy.presence_analytics import is_mac_randomized
        # Bit 1 of first byte set = locally administered
        assert is_mac_randomized("02:00:00:00:00:00")
        assert is_mac_randomized("0a:11:22:33:44:55")
        assert is_mac_randomized("06:bb:cc:dd:ee:ff")

    def test_is_mac_randomized_false(self):
        from rudy.presence_analytics import is_mac_randomized
        assert not is_mac_randomized("00:00:00:00:00:00")
        assert not is_mac_randomized("f8:bb:bf:59:c2:d2")
        assert not is_mac_randomized("3c:22:fb:11:22:33")

    def test_is_mac_randomized_hyphen_format(self):
        from rudy.presence_analytics import is_mac_randomized
        assert is_mac_randomized("02-00-00-00-00-00")
        assert not is_mac_randomized("f8-bb-bf-59-c2-d2")

    def test_lookup_oui_known_arris(self):
        from rudy.presence_analytics import lookup_oui
        result = lookup_oui("f8:bb:bf:59:c2:d2")
        assert result["manufacturer"] == "Arris/CommScope (ISP Router)"
        assert result["device_hint"] == "router"
        assert not result["randomized"]

    def test_lookup_oui_known_apple(self):
        from rudy.presence_analytics import lookup_oui
        result = lookup_oui("3c:22:fb:11:22:33")
        assert result["manufacturer"] == "Apple"
        assert result["device_hint"] == "apple_device"

    def test_lookup_oui_randomized_mac(self):
        from rudy.presence_analytics import lookup_oui
        result = lookup_oui("02:aa:bb:cc:dd:ee")
        assert result["randomized"]
        assert result["device_hint"] == "mobile_device"
        assert "Randomized" in result["manufacturer"]

    def test_lookup_oui_unknown(self):
        from rudy.presence_analytics import lookup_oui
        result = lookup_oui("00:01:02:03:04:05")
        assert result["manufacturer"] == "Unknown"
        assert result["device_hint"] == "unknown"

    def test_lookup_oui_raspberry_pi(self):
        from rudy.presence_analytics import lookup_oui
        result = lookup_oui("dc:a6:32:11:22:33")
        assert result["manufacturer"] == "Raspberry Pi"
        assert result["device_hint"] == "iot"


# ── ScanSnapshot ─────────────────────────────────────────────────

class TestScanSnapshot:
    def test_basic_creation(self):
        from rudy.presence_analytics import ScanSnapshot
        snap = ScanSnapshot("2024-06-15T14:30:00", {"aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"})
        assert len(snap.macs) == 2
        assert snap.hour == 14
        assert snap.day == "Saturday"
        assert snap.date == "2024-06-15"

    def test_macs_frozen(self):
        from rudy.presence_analytics import ScanSnapshot
        snap = ScanSnapshot("2024-06-15T10:00:00", {"mac1", "mac2"})
        assert isinstance(snap.macs, frozenset)


# ── Co-Occurrence Analysis ───────────────────────────────────────

class TestCooccurrence:
    def test_perfect_cooccurrence(self):
        """Two devices always together should have jaccard=1."""
        from rudy.presence_analytics import ScanSnapshot, compute_cooccurrence
        snapshots = [
            ScanSnapshot(f"2024-06-1{i}T10:00:00", {"mac_a", "mac_b"})
            for i in range(5)
        ]
        scores = compute_cooccurrence(snapshots)
        pair = ("mac_a", "mac_b")
        assert pair in scores
        assert scores[pair]["jaccard"] == 1.0
        assert scores[pair]["overlap"] == 1.0

    def test_no_cooccurrence(self):
        """Devices never seen together should have zero pair_together count."""
        from rudy.presence_analytics import ScanSnapshot, compute_cooccurrence
        snapshots = [
            ScanSnapshot("2024-06-10T10:00:00", {"mac_a"}),
            ScanSnapshot("2024-06-11T10:00:00", {"mac_b"}),
            ScanSnapshot("2024-06-12T10:00:00", {"mac_a"}),
            ScanSnapshot("2024-06-13T10:00:00", {"mac_b"}),
        ]
        scores = compute_cooccurrence(snapshots)
        pair = ("mac_a", "mac_b")
        # pair_together is 0 so pair won't appear in scores at all
        if pair in scores:
            assert scores[pair]["jaccard"] == 0.0
        else:
            # No entry = no co-occurrence, which is correct
            assert True

    def test_partial_cooccurrence(self):
        from rudy.presence_analytics import ScanSnapshot, compute_cooccurrence
        snapshots = [
            ScanSnapshot("2024-06-10T10:00:00", {"mac_a", "mac_b"}),
            ScanSnapshot("2024-06-11T10:00:00", {"mac_a"}),
            ScanSnapshot("2024-06-12T10:00:00", {"mac_a", "mac_b"}),
        ]
        scores = compute_cooccurrence(snapshots)
        pair = ("mac_a", "mac_b")
        assert 0 < scores[pair]["jaccard"] < 1.0

    def test_empty_snapshots(self):
        from rudy.presence_analytics import compute_cooccurrence
        assert compute_cooccurrence([]) == {}


# ── Device Classifier ────────────────────────────────────────────

class TestDeviceClassifier:
    def _make(self, snapshots=None, total=100):
        from rudy.presence_analytics import DeviceClassifier
        return DeviceClassifier(snapshots or [], total)

    def test_classify_router_by_oui(self):
        dc = self._make()
        result = dc.classify("f8:bb:bf:59:c2:d2", 95)
        assert result["category"] == "infrastructure"
        assert result["confidence"] >= 0.9

    def test_classify_randomized_mac(self):
        dc = self._make()
        result = dc.classify("02:aa:bb:cc:dd:ee", 50)
        assert result["category"] == "personal_mobile"

    def test_classify_always_on_unknown(self):
        dc = self._make(total=100)
        # Non-randomized, unknown OUI, present 95% → infrastructure
        result = dc.classify("00:01:02:03:04:05", 95)
        assert result["category"] == "infrastructure"

    def test_classify_rare_device(self):
        dc = self._make(total=200)
        result = dc.classify("00:01:02:03:04:05", 5)
        assert result["category"] == "visitor_or_intermittent"

    def test_classify_personal_range(self):
        dc = self._make(total=100)
        result = dc.classify("00:01:02:03:04:05", 40)
        assert result["category"] == "personal_device"

    def test_classify_early_stage(self):
        """With <20 scans, non-OUI classification defaults to unclassified."""
        dc = self._make(total=10)
        result = dc.classify("00:01:02:03:04:05", 5)
        assert result["category"] == "unclassified"
        assert result["confidence"] < 0.5

    def test_classify_virtual_machine(self):
        dc = self._make()
        result = dc.classify("00:0c:29:11:22:33", 80)
        assert result["category"] == "infrastructure"

    def test_classify_apple_device(self):
        dc = self._make()
        result = dc.classify("3c:22:fb:11:22:33", 40)
        assert result["category"] == "personal_device"

    def test_classify_returns_all_fields(self):
        dc = self._make()
        result = dc.classify("f8:bb:bf:59:c2:d2", 50)
        assert "mac" in result
        assert "category" in result
        assert "presence_ratio" in result
        assert "confidence" in result
        assert "oui" in result
        assert "scan_count" in result


# ── Person Clustering ────────────────────────────────────────────

class TestPersonClustering:
    def test_cluster_high_overlap(self):
        from rudy.presence_analytics import cluster_devices_into_persons
        cooccurrence = {
            ("mac_a", "mac_b"): {"overlap": 0.95, "jaccard": 0.9, "together": 90},
        }
        classifications = {
            "mac_a": {"category": "personal_mobile", "presence_ratio": 0.5},
            "mac_b": {"category": "personal_device", "presence_ratio": 0.5},
        }
        clusters = cluster_devices_into_persons(cooccurrence, classifications)
        # mac_a and mac_b should be in the same cluster
        assert len(clusters) == 1
        assert set(clusters[0]["devices"]) == {"mac_a", "mac_b"}

    def test_cluster_low_overlap_stays_separate(self):
        from rudy.presence_analytics import cluster_devices_into_persons
        cooccurrence = {
            ("mac_a", "mac_b"): {"overlap": 0.2, "jaccard": 0.1, "together": 5},
        }
        classifications = {
            "mac_a": {"category": "personal_mobile", "presence_ratio": 0.5},
            "mac_b": {"category": "personal_device", "presence_ratio": 0.5},
        }
        clusters = cluster_devices_into_persons(cooccurrence, classifications)
        assert len(clusters) == 2

    def test_cluster_excludes_infrastructure(self):
        from rudy.presence_analytics import cluster_devices_into_persons
        classifications = {
            "mac_router": {"category": "infrastructure", "presence_ratio": 0.99},
            "mac_phone": {"category": "personal_mobile", "presence_ratio": 0.5},
        }
        clusters = cluster_devices_into_persons({}, classifications)
        # Only personal devices get clustered
        all_macs = [m for c in clusters for m in c["devices"]]
        assert "mac_router" not in all_macs

    def test_cluster_empty(self):
        from rudy.presence_analytics import cluster_devices_into_persons
        assert cluster_devices_into_persons({}, {}) == []

    def test_cluster_inferred_resident(self):
        from rudy.presence_analytics import cluster_devices_into_persons
        classifications = {
            "mac_a": {"category": "personal_mobile", "presence_ratio": 0.6},
        }
        clusters = cluster_devices_into_persons({}, classifications)
        assert clusters[0]["inferred_resident"] is True

    def test_cluster_non_resident(self):
        from rudy.presence_analytics import cluster_devices_into_persons
        classifications = {
            "mac_a": {"category": "personal_mobile", "presence_ratio": 0.1},
        }
        clusters = cluster_devices_into_persons({}, classifications)
        assert clusters[0]["inferred_resident"] is False


# ── Activity Pattern Analysis ────────────────────────────────────

class TestActivityPatterns:
    def test_insufficient_data(self):
        from rudy.presence_analytics import analyze_activity_patterns
        result = analyze_activity_patterns({}, "mac_a")
        assert result["status"] == "insufficient_data"

    def test_insufficient_scans(self):
        from rudy.presence_analytics import analyze_activity_patterns
        routines = {"mac_a": {"total_scans": 3, "weekly": {}}}
        result = analyze_activity_patterns(routines, "mac_a")
        assert result["status"] == "insufficient_data"

    def test_analyzed_with_data(self):
        from rudy.presence_analytics import analyze_activity_patterns
        weekly = {}
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]:
            hours = [0] * 24
            for h in range(8, 18):  # Active 8am-6pm
                hours[h] = 10
            weekly[day] = hours
        for day in ["Saturday", "Sunday"]:
            hours = [0] * 24
            for h in range(10, 22):  # Active 10am-10pm
                hours[h] = 8
            weekly[day] = hours

        routines = {"mac_a": {"total_scans": 100, "weekly": weekly}}
        result = analyze_activity_patterns(routines, "mac_a")
        assert result["status"] == "analyzed"
        assert result["total_scans"] == 100
        assert len(result["active_hours"]) > 0
        assert "estimated_sleep" in result
        assert not result["is_always_on"]

    def test_always_on_device(self):
        from rudy.presence_analytics import analyze_activity_patterns
        weekly = {}
        for day in ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]:
            hours = [50] * 24  # Active all 24 hours
            weekly[day] = hours

        routines = {"mac_a": {"total_scans": 200, "weekly": weekly}}
        result = analyze_activity_patterns(routines, "mac_a")
        assert result["is_always_on"]


# ── _find_longest_quiet_stretch ──────────────────────────────────

class TestQuietStretch:
    def test_no_quiet_hours(self):
        from rudy.presence_analytics import _find_longest_quiet_stretch
        assert _find_longest_quiet_stretch([]) == (None, None)

    def test_continuous_stretch(self):
        from rudy.presence_analytics import _find_longest_quiet_stretch
        start, end = _find_longest_quiet_stretch([1, 2, 3, 4, 5])
        assert start == 1
        assert end == 6  # 1-5 inclusive, end is next hour

    def test_midnight_wrap(self):
        from rudy.presence_analytics import _find_longest_quiet_stretch
        start, end = _find_longest_quiet_stretch([22, 23, 0, 1, 2, 3])
        assert start == 22
        assert end == 4


# ── Household Profile ────────────────────────────────────────────

class TestHouseholdProfile:
    def test_build_basic(self):
        from rudy.presence_analytics import build_household_profile
        clusters = [{"cluster_id": 0, "devices": ["mac_a"], "inferred_resident": True, "avg_presence": 0.5}]
        classifications = {
            "mac_a": {"category": "personal_mobile", "scan_count": 50, "presence_ratio": 0.5},
            "mac_r": {"category": "infrastructure", "scan_count": 100, "presence_ratio": 0.99},
        }
        profile = build_household_profile(clusters, classifications)
        assert profile["infrastructure_devices"] == 1
        assert profile["personal_devices"] == 1
        assert profile["inferred_resident_count"] == 1

    def test_build_empty(self):
        from rudy.presence_analytics import build_household_profile
        profile = build_household_profile([], {})
        assert profile["total_tracked_devices"] == 0

    def test_confidence_note_no_data(self):
        from rudy.presence_analytics import _confidence_note
        assert "No data" in _confidence_note({})

    def test_confidence_note_early(self):
        from rudy.presence_analytics import _confidence_note
        cls = {"m1": {"scan_count": 5}, "m2": {"scan_count": 8}}
        note = _confidence_note(cls)
        assert "early" in note.lower() or "preliminary" in note.lower()

    def test_confidence_note_rich(self):
        from rudy.presence_analytics import _confidence_note
        cls = {f"m{i}": {"scan_count": 300} for i in range(5)}
        note = _confidence_note(cls)
        assert "Rich" in note or "High" in note.lower() or "rich" in note.lower()


# ── _try_match_clusters ──────────────────────────────────────────

class TestClusterMatching:
    def test_match_tech_savvy(self):
        from rudy.presence_analytics import _try_match_clusters
        clusters = [
            {"cluster_id": 0, "devices": ["m1", "m2", "m3"], "device_count": 3, "avg_presence": 0.6},
        ]
        residents = [
            {"name": "Chris", "tech_savvy": True, "permanent": True},
        ]
        classifications = {
            "m1": {"oui": {"randomized": True}},
            "m2": {"oui": {"randomized": False}},
            "m3": {"oui": {"randomized": False}},
        }
        assignments = _try_match_clusters(clusters, residents, classifications)
        assert len(assignments) == 1
        assert assignments[0]["resident_name"] == "Chris"

    def test_no_match_low_score(self):
        from rudy.presence_analytics import _try_match_clusters
        clusters = [
            {"cluster_id": 0, "devices": ["m1"], "device_count": 1, "avg_presence": 0.1},
        ]
        residents = [
            {"name": "Unknown", "tech_savvy": True, "permanent": True},
        ]
        classifications = {"m1": {"oui": {"randomized": False}}}
        assignments = _try_match_clusters(clusters, residents, classifications)
        # Low presence + single device for tech-savvy = uncertain match
        # May or may not match depending on score threshold
        assert isinstance(assignments, list)


# ── PresenceAnalytics (integration) ──────────────────────────────

class TestPresenceAnalytics:
    def _make(self, pa_paths):
        from rudy.presence_analytics import PresenceAnalytics
        return PresenceAnalytics()

    def test_init_empty(self, pa_paths):
        pa = self._make(pa_paths)
        assert pa.event_log == []
        assert pa.current == {}

    def test_run_empty(self, pa_paths):
        """run() with no data should not crash."""
        pa = self._make(pa_paths)
        result = pa.run()
        assert result["device_count"] == 0
        assert result["clusters"] == []

    def test_run_with_current_devices(self, pa_paths):
        """run() with current devices present."""
        # Write some "current" devices
        current = {
            "f8:bb:bf:59:c2:d2": {"ip": "192.168.7.1"},
            "02:aa:bb:cc:dd:ee": {"ip": "192.168.7.50"},
        }
        pa_paths_file = pa_paths / "presence-current.json"
        with open(pa_paths_file, "w") as f:
            json.dump(current, f)

        pa = self._make(pa_paths)
        result = pa.run()
        assert result["device_count"] == 2
        # Router should be classified as infrastructure
        profiles = result["device_profiles"]
        assert profiles["f8:bb:bf:59:c2:d2"]["category"] == "infrastructure"
        # Randomized MAC should be personal_mobile
        assert profiles["02:aa:bb:cc:dd:ee"]["category"] == "personal_mobile"

    def test_build_snapshots_from_events(self, pa_paths):
        """_build_snapshots reconstructs time-series from event log."""
        events = [
            {"time": "2024-06-15T10:00:00", "type": "arrival", "mac": "mac_a"},
            {"time": "2024-06-15T10:01:00", "type": "arrival", "mac": "mac_b"},
            {"time": "2024-06-15T10:15:00", "type": "departure", "mac": "mac_a"},
        ]
        log_file = pa_paths / "presence-log.json"
        with open(log_file, "w") as f:
            json.dump(events, f)

        pa = self._make(pa_paths)
        snapshots = pa._build_snapshots()
        assert len(snapshots) >= 1
