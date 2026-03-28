import pytest
from unittest.mock import patch, MagicMock, mock_open
from pathlib import Path
from datetime import datetime, timedelta
import json

import rudy.movement_feed as mod


@pytest.fixture
def mock_logs_dir(tmp_path, monkeypatch):
    """Redirect all LOGS_DIR paths to tmp_path."""
    monkeypatch.setattr(mod, "LOGS_DIR", tmp_path)
    monkeypatch.setattr(mod, "PRESENCE_LOG", tmp_path / "presence-log.json")
    monkeypatch.setattr(mod, "PRESENCE_CURRENT", tmp_path / "presence-current.json")
    monkeypatch.setattr(mod, "PRESENCE_ROUTINES", tmp_path / "presence-routines.json")
    monkeypatch.setattr(mod, "PRESENCE_DEVICES", tmp_path / "presence-devices.json")
    monkeypatch.setattr(mod, "PRESENCE_ANALYTICS", tmp_path / "presence-analytics.json")
    monkeypatch.setattr(mod, "INTRUDER_DB", tmp_path / "intruder-database.json")
    monkeypatch.setattr(mod, "THREAT_TIMELINE", tmp_path / "threat-timeline.json")
    monkeypatch.setattr(mod, "WELLNESS_STATE", tmp_path / "wellness-state.json")
    monkeypatch.setattr(mod, "WELLNESS_ALERTS", tmp_path / "wellness-alerts.json")
    monkeypatch.setattr(mod, "HOUSEHOLD_FILE", tmp_path / "presence-household.json")
    monkeypatch.setattr(mod, "DEFENSE_ALERTS", tmp_path / "defense-alerts.json")
    monkeypatch.setattr(mod, "MOVEMENT_FEED", tmp_path / "movement-feed.json")
    monkeypatch.setattr(mod, "MOVEMENT_SUMMARY", tmp_path / "movement-summary.json")
    return tmp_path


class TestLoadJson:
    """Test _load_json utility function."""

    def test_load_json_file_exists(self, tmp_path):
        """Load JSON from existing file."""
        data = {"key": "value", "number": 42}
        f = tmp_path / "test.json"
        f.write_text(json.dumps(data))

        result = mod._load_json(f)
        assert result == data

    def test_load_json_file_not_exists_returns_default(self, tmp_path):
        """Return default dict when file doesn't exist."""
        f = tmp_path / "nonexistent.json"
        result = mod._load_json(f)
        assert result == {}

    def test_load_json_file_not_exists_with_custom_default(self, tmp_path):
        """Return custom default when file doesn't exist."""
        f = tmp_path / "nonexistent.json"
        result = mod._load_json(f, default=[])
        assert result == []

    def test_load_json_invalid_json_returns_default(self, tmp_path):
        """Return default dict when JSON is malformed."""
        f = tmp_path / "bad.json"
        f.write_text("{invalid json")

        result = mod._load_json(f)
        assert result == {}

    def test_load_json_invalid_json_with_custom_default(self, tmp_path):
        """Return custom default for malformed JSON."""
        f = tmp_path / "bad.json"
        f.write_text("[1, 2, 3")

        result = mod._load_json(f, default=[])
        assert result == []

    def test_load_json_empty_file_returns_default(self, tmp_path):
        """Return default for empty file."""
        f = tmp_path / "empty.json"
        f.write_text("")

        result = mod._load_json(f)
        assert result == {}


class TestSaveJson:
    """Test _save_json utility function."""

    def test_save_json_writes_file(self, tmp_path):
        """Save data to JSON file."""
        f = tmp_path / "output.json"
        data = {"key": "value", "nested": {"a": 1}}

        mod._save_json(f, data)

        assert f.exists()
        saved = json.loads(f.read_text())
        assert saved == data

    def test_save_json_with_datetime(self, tmp_path):
        """Save data containing datetime objects."""
        f = tmp_path / "output.json"
        now = datetime.now()
        data = {"timestamp": now, "other": "value"}

        mod._save_json(f, data)

        assert f.exists()
        # datetime is serialized to string
        saved = json.loads(f.read_text())
        assert "timestamp" in saved


class TestMovementFeedInit:
    """Test MovementFeed initialization."""

    def test_init_loads_all_sources(self, mock_logs_dir):
        """Initialize with all JSON sources."""
        # Create all source files with minimal data
        presence_log = [{"time": "2026-03-28T10:00:00", "type": "arrival"}]
        presence_current = {"aa:bb:cc:dd:ee:01": {"last_seen": "2026-03-28T10:00:00"}}
        presence_devices = {"aa:bb:cc:dd:ee:01": {"name": "iPhone"}}
        presence_analytics = {"clusters": []}
        threat_timeline = []
        wellness_alerts = []
        household = {"context": {}}
        defense_alerts = []

        (mock_logs_dir / "presence-log.json").write_text(
            json.dumps(presence_log)
        )
        (mock_logs_dir / "presence-current.json").write_text(
            json.dumps(presence_current)
        )
        (mock_logs_dir / "presence-devices.json").write_text(
            json.dumps(presence_devices)
        )
        (mock_logs_dir / "presence-analytics.json").write_text(
            json.dumps(presence_analytics)
        )
        (mock_logs_dir / "threat-timeline.json").write_text(
            json.dumps(threat_timeline)
        )
        (mock_logs_dir / "wellness-alerts.json").write_text(
            json.dumps(wellness_alerts)
        )
        (mock_logs_dir / "presence-household.json").write_text(
            json.dumps(household)
        )
        (mock_logs_dir / "defense-alerts.json").write_text(
            json.dumps(defense_alerts)
        )

        feed = mod.MovementFeed()

        assert feed.events == presence_log
        assert feed.current == presence_current
        assert feed.devices == presence_devices
        assert feed.routines == {}
        assert feed.threat_timeline == threat_timeline
        assert feed.wellness_alerts == wellness_alerts
        assert feed.household == household

    def test_init_with_missing_files_uses_defaults(self, mock_logs_dir):
        """Initialize with missing files defaults to empty dicts/lists."""
        # Don't create any files
        feed = mod.MovementFeed()

        assert feed.events == []
        assert feed.current == {}
        assert feed.devices == {}
        assert feed.routines == {}
        assert feed.threat_timeline == []
        assert feed.wellness_alerts == []


class TestGetDeviceName:
    """Test _get_device_name method."""

    def test_get_device_name_from_known_devices(self, mock_logs_dir):
        """Return name from devices registry."""
        mac = "aa:bb:cc:dd:ee:01"
        devices = {mac: {"name": "Alice iPhone"}}

        (mock_logs_dir / "presence-devices.json").write_text(json.dumps(devices))
        feed = mod.MovementFeed()

        name = feed._get_device_name(mac)
        assert name == "Alice iPhone"

    def test_get_device_name_from_intruder_db(self, mock_logs_dir):
        """Return name from intruder devices."""
        mac = "aa:bb:cc:dd:ee:99"
        intruders = {"devices": {mac: {"label": "Unknown Device"}}}

        (mock_logs_dir / "intruder-database.json").write_text(json.dumps(intruders))
        feed = mod.MovementFeed()

        name = feed._get_device_name(mac)
        assert name == "Unknown Device"

    def test_get_device_name_fallback_to_mac_suffix(self, mock_logs_dir):
        """Return device label with MAC suffix when unknown."""
        mac = "aa:bb:cc:dd:ee:99"
        feed = mod.MovementFeed()

        name = feed._get_device_name(mac)
        # MAC suffix is last 8 characters of the full MAC
        assert name == "Device [dd:ee:99]"


class TestGetClusterLabel:
    """Test _get_cluster_label method."""

    def test_get_cluster_label_from_analytics(self, mock_logs_dir):
        """Return cluster label from analytics."""
        mac = "aa:bb:cc:dd:ee:01"
        analytics = {
            "clusters": [
                {
                    "cluster_id": 0,
                    "label": "Person 1",
                    "devices": [mac],
                }
            ]
        }

        (mock_logs_dir / "presence-analytics.json").write_text(json.dumps(analytics))
        feed = mod.MovementFeed()

        label = feed._get_cluster_label(mac)
        assert label == "Person 1"

    def test_get_cluster_label_from_household_assignments(self, mock_logs_dir):
        """Return label from cluster when found."""
        mac = "aa:bb:cc:dd:ee:01"
        analytics = {
            "clusters": [{"cluster_id": 0, "label": "Person 1", "devices": [mac]}],
        }

        (mock_logs_dir / "presence-analytics.json").write_text(json.dumps(analytics))
        feed = mod.MovementFeed()

        label = feed._get_cluster_label(mac)
        # The label comes from the cluster, not household assignments
        assert label == "Person 1"

    def test_get_cluster_label_unknown_device_returns_none(self, mock_logs_dir):
        """Return None for unknown device."""
        mac = "aa:bb:cc:dd:ee:99"
        feed = mod.MovementFeed()

        label = feed._get_cluster_label(mac)
        assert label is None


class TestFormatPresenceEvent:
    """Test _format_presence_event method."""

    def test_format_presence_event_arrival_with_cluster(self, mock_logs_dir):
        """Format arrival event with cluster label."""
        feed = mod.MovementFeed()
        event = {"type": "arrival", "ip": "192.168.1.100"}

        msg = feed._format_presence_event(event, "iPhone", "Alice")

        assert "Alice arrived" in msg
        assert "iPhone" in msg
        assert "192.168.1.100" in msg

    def test_format_presence_event_departure_with_device_name(self, mock_logs_dir):
        """Format departure event with device name."""
        feed = mod.MovementFeed()
        event = {"type": "departure", "ip": "192.168.1.100", "known": True}

        msg = feed._format_presence_event(event, "iPad", None)

        assert "iPad departed" in msg
        assert "192.168.1.100" in msg

    def test_format_presence_event_unknown_device(self, mock_logs_dir):
        """Format event for unknown device."""
        feed = mod.MovementFeed()
        event = {"type": "arrival", "ip": "192.168.1.101", "known": False}

        msg = feed._format_presence_event(event, "Device [xx:xx]", None)

        assert "Unknown device at 192.168.1.101" in msg


class TestFormatThreatEvent:
    """Test _format_threat_event method."""

    def test_format_threat_event_new_intruder(self, mock_logs_dir):
        """Format new intruder event."""
        feed = mod.MovementFeed()
        event = {
            "event": "new_intruder",
            "mac": "aa:bb:cc:dd:ee:99",
            "threat_score": 75,
        }

        msg = feed._format_threat_event(event)

        assert "New unknown device profiled" in msg
        assert "ee:99" in msg
        assert "75" in msg

    def test_format_threat_event_intruder_departed(self, mock_logs_dir):
        """Format intruder departed event."""
        feed = mod.MovementFeed()
        event = {
            "event": "intruder_departed",
            "mac": "aa:bb:cc:dd:ee:99",
            "duration_min": 15,
        }

        msg = feed._format_threat_event(event)

        assert "Unknown device departed" in msg
        assert "ee:99" in msg
        assert "15" in msg


class TestGetHouseholdSummary:
    """Test _get_household_summary method."""

    def test_get_household_summary_complete(self, mock_logs_dir):
        """Get household summary with all fields."""
        household = {
            "context": {
                "location_type": "apartment",
                "expected_residents": 2,
                "residents": [
                    {"name": "Alice", "role": "primary", "fall_risk": False},
                    {"name": "Bob", "role": "secondary", "fall_risk": True},
                ],
            }
        }

        (mock_logs_dir / "presence-household.json").write_text(json.dumps(household))
        feed = mod.MovementFeed()

        summary = feed._get_household_summary()

        assert summary["location"] == "apartment"
        assert summary["expected_residents"] == 2
        assert len(summary["residents"]) == 2
        assert summary["residents"][0]["name"] == "Alice"
        assert summary["residents"][1]["fall_risk"] is True

    def test_get_household_summary_empty_context(self, mock_logs_dir):
        """Get household summary with empty context."""
        household = {"context": {}}

        (mock_logs_dir / "presence-household.json").write_text(json.dumps(household))
        feed = mod.MovementFeed()

        summary = feed._get_household_summary()

        assert summary["location"] == "unknown"
        assert summary["expected_residents"] is None
        assert summary["residents"] == []


class TestGenerateSnapshot:
    """Test _generate_snapshot method."""

    def test_generate_snapshot_devices_online(self, mock_logs_dir):
        """Generate snapshot with devices online."""
        current = {
            "aa:bb:cc:dd:ee:01": {"last_seen": "2026-03-28T10:00:00"},
            "aa:bb:cc:dd:ee:02": {"last_seen": "2026-03-28T10:05:00"},
        }
        devices = {
            "aa:bb:cc:dd:ee:01": {"name": "iPhone"},
        }
        analytics = {"clusters": []}

        (mock_logs_dir / "presence-current.json").write_text(json.dumps(current))
        (mock_logs_dir / "presence-devices.json").write_text(json.dumps(devices))
        (mock_logs_dir / "presence-analytics.json").write_text(json.dumps(analytics))

        feed = mod.MovementFeed()
        snapshot = feed._generate_snapshot()

        assert snapshot["devices_online"] == 2
        assert snapshot["known_devices"] == 1
        assert snapshot["unknown_devices"] == 1

    @patch("rudy.movement_feed.datetime")
    def test_generate_snapshot_time_context_morning(self, mock_datetime, mock_logs_dir):
        """Generate snapshot with morning time context."""
        now = datetime(2026, 3, 28, 9, 30)
        mock_datetime.now.return_value = now

        feed = mod.MovementFeed()
        snapshot = feed._generate_snapshot()

        assert snapshot["time_context"] == "morning"

    @patch("rudy.movement_feed.datetime")
    def test_generate_snapshot_time_context_afternoon(self, mock_datetime, mock_logs_dir):
        """Generate snapshot with afternoon time context."""
        now = datetime(2026, 3, 28, 14, 30)
        mock_datetime.now.return_value = now

        feed = mod.MovementFeed()
        snapshot = feed._generate_snapshot()

        assert snapshot["time_context"] == "afternoon"

    @patch("rudy.movement_feed.datetime")
    def test_generate_snapshot_time_context_nighttime(self, mock_datetime, mock_logs_dir):
        """Generate snapshot with nighttime time context."""
        now = datetime(2026, 3, 28, 2, 30)
        mock_datetime.now.return_value = now

        feed = mod.MovementFeed()
        snapshot = feed._generate_snapshot()

        assert snapshot["time_context"] == "nighttime"

    def test_generate_snapshot_persons_home_and_away(self, mock_logs_dir):
        """Generate snapshot with persons home and away."""
        current = {"aa:bb:cc:dd:ee:01": {"last_seen": "2026-03-28T10:00:00"}}
        analytics = {
            "clusters": [
                {
                    "cluster_id": 0,
                    "label": "Alice",
                    "devices": ["aa:bb:cc:dd:ee:01", "aa:bb:cc:dd:ee:02"],
                    "avg_presence": 0.8,
                }
            ]
        }

        (mock_logs_dir / "presence-current.json").write_text(json.dumps(current))
        (mock_logs_dir / "presence-analytics.json").write_text(json.dumps(analytics))

        feed = mod.MovementFeed()
        snapshot = feed._generate_snapshot()

        persons = snapshot["persons"]
        assert len(persons) == 1
        assert persons[0]["label"] == "Alice"
        assert persons[0]["is_home"] is True
        assert persons[0]["devices_present"] == 1
        assert persons[0]["devices_total"] == 2


class TestGenerateFeed:
    """Test generate_feed method."""

    @patch("rudy.movement_feed.datetime")
    def test_generate_feed_basic(self, mock_datetime, mock_logs_dir):
        """Generate basic feed with presence events."""
        now = datetime(2026, 3, 28, 12, 0)
        mock_datetime.now.return_value = now

        presence_log = [
            {
                "time": "2026-03-28T11:30:00",
                "type": "arrival",
                "mac": "aa:bb:cc:dd:ee:01",
                "ip": "192.168.1.100",
                "known": True,
            }
        ]
        devices = {"aa:bb:cc:dd:ee:01": {"name": "iPhone"}}
        analytics = {
            "clusters": [
                {"cluster_id": 0, "label": "Alice", "devices": ["aa:bb:cc:dd:ee:01"]}
            ]
        }

        (mock_logs_dir / "presence-log.json").write_text(json.dumps(presence_log))
        (mock_logs_dir / "presence-devices.json").write_text(json.dumps(devices))
        (mock_logs_dir / "presence-analytics.json").write_text(json.dumps(analytics))

        feed = mod.MovementFeed()
        result = feed.generate_feed(hours=24)

        assert result["period_hours"] == 24
        assert result["total_events"] >= 1
        assert len(result["feed"]) >= 1
        assert result["feed"][0]["type"] == "presence"
        assert result["feed"][0]["device"] == "iPhone"

    @patch("rudy.movement_feed.datetime")
    def test_generate_feed_filters_by_time(self, mock_datetime, mock_logs_dir):
        """Generate feed filters events by time cutoff."""
        now = datetime(2026, 3, 28, 12, 0)
        mock_datetime.now.return_value = now

        presence_log = [
            {
                "time": "2026-03-27T10:00:00",  # 26 hours ago
                "type": "arrival",
                "mac": "aa:bb:cc:dd:ee:01",
                "ip": "192.168.1.100",
                "known": True,
            },
            {
                "time": "2026-03-28T11:30:00",  # 30 minutes ago
                "type": "departure",
                "mac": "aa:bb:cc:dd:ee:01",
                "ip": "192.168.1.100",
                "known": True,
            },
        ]
        devices = {"aa:bb:cc:dd:ee:01": {"name": "iPhone"}}

        (mock_logs_dir / "presence-log.json").write_text(json.dumps(presence_log))
        (mock_logs_dir / "presence-devices.json").write_text(json.dumps(devices))
        (mock_logs_dir / "presence-analytics.json").write_text(json.dumps({"clusters": []}))

        feed = mod.MovementFeed()
        result = feed.generate_feed(hours=24)

        # Only the recent event should be included
        assert result["total_events"] == 1
        assert "departure" in result["feed"][0]["subtype"]

    @patch("rudy.movement_feed.datetime")
    def test_generate_feed_includes_threat_events(self, mock_datetime, mock_logs_dir):
        """Generate feed includes threat timeline events."""
        now = datetime(2026, 3, 28, 12, 0)
        mock_datetime.now.return_value = now

        threat_timeline = [
            {
                "time": "2026-03-28T11:00:00",
                "event": "new_intruder",
                "mac": "aa:bb:cc:dd:ee:99",
                "threat_score": 85,
            }
        ]

        (mock_logs_dir / "threat-timeline.json").write_text(json.dumps(threat_timeline))

        feed = mod.MovementFeed()
        result = feed.generate_feed(hours=24)

        assert len(result["feed"]) >= 1
        threat_item = [i for i in result["feed"] if i["type"] == "threat"]
        assert len(threat_item) > 0
        assert threat_item[0]["severity"] == "warning"

    @patch("rudy.movement_feed.datetime")
    def test_generate_feed_includes_wellness_alerts(self, mock_datetime, mock_logs_dir):
        """Generate feed includes wellness alerts."""
        now = datetime(2026, 3, 28, 12, 0)
        mock_datetime.now.return_value = now

        wellness_alerts = [
            {
                "time": "2026-03-28T11:00:00",
                "type": "inactivity",
                "person": "Alice",
                "severity": "info",
                "message": "No movement detected",
            }
        ]

        (mock_logs_dir / "wellness-alerts.json").write_text(
            json.dumps(wellness_alerts)
        )

        feed = mod.MovementFeed()
        result = feed.generate_feed(hours=24)

        wellness_items = [i for i in result["feed"] if i["type"] == "wellness"]
        assert len(wellness_items) > 0
        assert wellness_items[0]["person"] == "Alice"

    @patch("rudy.movement_feed.datetime")
    def test_generate_feed_includes_defense_alerts(self, mock_datetime, mock_logs_dir):
        """Generate feed includes high severity defense alerts."""
        now = datetime(2026, 3, 28, 12, 0)
        mock_datetime.now.return_value = now

        defense_alerts = [
            {
                "time": "2026-03-28T11:00:00",
                "severity": "alert",
                "category": "intrusion",
                "message": "Unauthorized access attempt",
            },
            {
                "time": "2026-03-28T10:00:00",
                "severity": "info",
                "category": "noise",
                "message": "High ambient noise",
            },
        ]

        (mock_logs_dir / "defense-alerts.json").write_text(
            json.dumps(defense_alerts)
        )

        feed = mod.MovementFeed()
        result = feed.generate_feed(hours=24)

        defense_items = [i for i in result["feed"] if i["type"] == "defense"]
        # Only the "alert" severity should be included, not "info"
        assert len(defense_items) == 1
        assert defense_items[0]["severity"] == "alert"

    @patch("rudy.movement_feed.datetime")
    def test_generate_feed_respects_max_events(self, mock_datetime, mock_logs_dir):
        """Generate feed respects max_events limit."""
        now = datetime(2026, 3, 28, 12, 0)
        mock_datetime.now.return_value = now

        # Create 30 events
        presence_log = [
            {
                "time": f"2026-03-28T{10 + i // 60:02d}:{i % 60:02d}:00",
                "type": "arrival" if i % 2 == 0 else "departure",
                "mac": f"aa:bb:cc:dd:ee:{i:02x}",
                "ip": f"192.168.1.{100 + i}",
                "known": True,
            }
            for i in range(30)
        ]

        (mock_logs_dir / "presence-log.json").write_text(json.dumps(presence_log))

        feed = mod.MovementFeed()
        result = feed.generate_feed(hours=24, max_events=10)

        assert len(result["feed"]) <= 10

    @patch("rudy.movement_feed.datetime")
    def test_generate_feed_sorts_by_time_descending(self, mock_datetime, mock_logs_dir):
        """Generate feed sorts events by time descending."""
        now = datetime(2026, 3, 28, 12, 0)
        mock_datetime.now.return_value = now

        presence_log = [
            {
                "time": "2026-03-28T10:00:00",
                "type": "arrival",
                "mac": "aa:bb:cc:dd:ee:01",
                "ip": "192.168.1.100",
                "known": True,
            },
            {
                "time": "2026-03-28T11:00:00",
                "type": "departure",
                "mac": "aa:bb:cc:dd:ee:01",
                "ip": "192.168.1.100",
                "known": True,
            },
        ]

        (mock_logs_dir / "presence-log.json").write_text(json.dumps(presence_log))

        feed = mod.MovementFeed()
        result = feed.generate_feed(hours=24)

        # Most recent should be first
        assert result["feed"][0]["time"] == "2026-03-28T11:00:00"
        assert result["feed"][1]["time"] == "2026-03-28T10:00:00"

    @patch("rudy.movement_feed.datetime")
    def test_generate_feed_saves_to_file(self, mock_datetime, mock_logs_dir):
        """Generate feed saves result to MOVEMENT_FEED."""
        now = datetime(2026, 3, 28, 12, 0)
        mock_datetime.now.return_value = now

        feed = mod.MovementFeed()
        feed.generate_feed(hours=24)

        # Check that file was saved
        feed_file = mock_logs_dir / "movement-feed.json"
        assert feed_file.exists()

        saved = json.loads(feed_file.read_text())
        assert saved["period_hours"] == 24
        assert "generated" in saved


class TestGetActivityHeatmap:
    """Test get_activity_heatmap method."""

    def test_get_activity_heatmap_basic(self, mock_logs_dir):
        """Generate activity heatmap from routines."""
        routines = {
            "aa:bb:cc:dd:ee:01": {
                "weekly": {
                    "monday": [1, 1, 1, 1, 1, 5, 10, 8, 3, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                    "tuesday": [1, 1, 1, 1, 1, 4, 9, 7, 2, 1, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
                }
            }
        }
        devices = {"aa:bb:cc:dd:ee:01": {"name": "iPhone"}}

        (mock_logs_dir / "presence-routines.json").write_text(json.dumps(routines))
        (mock_logs_dir / "presence-devices.json").write_text(json.dumps(devices))

        feed = mod.MovementFeed()
        heatmap = feed.get_activity_heatmap()

        assert "aa:bb:cc:dd:ee:01" in heatmap
        entry = heatmap["aa:bb:cc:dd:ee:01"]
        assert entry["device"] == "iPhone"
        assert len(entry["hourly_raw"]) == 24
        assert len(entry["hourly_normalized"]) == 24
        assert entry["peak_hour"] == 6
        assert entry["total_observations"] > 0

    def test_get_activity_heatmap_empty_routines(self, mock_logs_dir):
        """Get activity heatmap with empty routines."""
        feed = mod.MovementFeed()
        heatmap = feed.get_activity_heatmap()

        assert heatmap == {}

    def test_get_activity_heatmap_quiet_hours(self, mock_logs_dir):
        """Get activity heatmap identifies quiet hours."""
        routines = {
            "aa:bb:cc:dd:ee:01": {
                "weekly": {
                    "monday": [0] * 6 + [10] + [0] * 17,  # Only hour 6 has activity
                }
            }
        }

        (mock_logs_dir / "presence-routines.json").write_text(json.dumps(routines))

        feed = mod.MovementFeed()
        heatmap = feed.get_activity_heatmap()

        entry = heatmap["aa:bb:cc:dd:ee:01"]
        quiet_hours = entry["quiet_hours"]
        # Quiet hours are those < 10% of max (1.0 in this case)
        # All hours with 0 activity should be quiet
        assert 0 in quiet_hours
        assert 6 not in quiet_hours  # Hour 6 has max activity


class TestPrintFeed:
    """Test print_feed method."""

    @patch("rudy.movement_feed.datetime")
    def test_print_feed_basic(self, mock_datetime, mock_logs_dir, capsys):
        """Print feed to stdout."""
        now = datetime(2026, 3, 28, 12, 0)
        mock_datetime.now.return_value = now

        presence_log = [
            {
                "time": "2026-03-28T11:30:00",
                "type": "arrival",
                "mac": "aa:bb:cc:dd:ee:01",
                "ip": "192.168.1.100",
                "known": True,
            }
        ]
        devices = {"aa:bb:cc:dd:ee:01": {"name": "iPhone"}}

        (mock_logs_dir / "presence-log.json").write_text(json.dumps(presence_log))
        (mock_logs_dir / "presence-devices.json").write_text(json.dumps(devices))

        feed = mod.MovementFeed()
        feed.print_feed(hours=24)

        captured = capsys.readouterr()
        assert "MOVEMENT FEED" in captured.out
        assert "devices online" in captured.out


class TestGenerateMovementFeed:
    """Test module-level generate_movement_feed function."""

    @patch("rudy.movement_feed.datetime")
    def test_generate_movement_feed_function(self, mock_datetime, mock_logs_dir, capsys):
        """Test module-level function."""
        now = datetime(2026, 3, 28, 12, 0)
        mock_datetime.now.return_value = now

        result = mod.generate_movement_feed(hours=24)

        assert result is not None
        assert "period_hours" in result
        captured = capsys.readouterr()
        assert "MOVEMENT FEED" in captured.out


class TestEdgeCases:
    """Test edge cases and error handling."""

    @patch("rudy.movement_feed.datetime")
    def test_empty_feed_with_no_data(self, mock_datetime, mock_logs_dir):
        """Generate feed with no data sources."""
        now = datetime(2026, 3, 28, 12, 0)
        mock_datetime.now.return_value = now

        feed = mod.MovementFeed()
        result = feed.generate_feed(hours=24)

        assert result["total_events"] == 0
        assert result["feed"] == []

    def test_malformed_event_with_missing_fields(self, mock_logs_dir):
        """Handle presence events with missing fields."""
        presence_log = [
            {
                "time": "2026-03-28T11:30:00",
                # Missing type, mac, ip
            }
        ]

        (mock_logs_dir / "presence-log.json").write_text(json.dumps(presence_log))

        feed = mod.MovementFeed()
        result = feed.generate_feed(hours=24)

        # Should not crash
        assert len(result["feed"]) >= 1

    def test_device_without_cluster_assignment(self, mock_logs_dir):
        """Handle device not in any cluster."""
        presence_log = [
            {
                "time": "2026-03-28T11:30:00",
                "type": "arrival",
                "mac": "aa:bb:cc:dd:ee:99",  # Not in any cluster
                "ip": "192.168.1.100",
                "known": False,
            }
        ]
        analytics = {"clusters": []}

        (mock_logs_dir / "presence-log.json").write_text(json.dumps(presence_log))
        (mock_logs_dir / "presence-analytics.json").write_text(json.dumps(analytics))

        feed = mod.MovementFeed()
        result = feed.generate_feed(hours=24)

        assert len(result["feed"]) >= 1
        assert result["feed"][0]["person"] is None

    @patch("rudy.movement_feed.datetime")
    def test_zero_hours_feed(self, mock_datetime, mock_logs_dir):
        """Generate feed with zero hours should return no events."""
        now = datetime(2026, 3, 28, 12, 0)
        mock_datetime.now.return_value = now

        presence_log = [
            {
                "time": "2026-03-28T11:30:00",
                "type": "arrival",
                "mac": "aa:bb:cc:dd:ee:01",
                "ip": "192.168.1.100",
                "known": True,
            }
        ]

        (mock_logs_dir / "presence-log.json").write_text(json.dumps(presence_log))

        feed = mod.MovementFeed()
        result = feed.generate_feed(hours=0)

        # All events are outside 0-hour window
        assert result["total_events"] == 0

    def test_snapshot_with_multiple_clusters(self, mock_logs_dir):
        """Generate snapshot with multiple person clusters."""
        current = {
            "aa:bb:cc:dd:ee:01": {"last_seen": "2026-03-28T10:00:00"},
            "aa:bb:cc:dd:ee:02": {"last_seen": "2026-03-28T10:05:00"},
        }
        analytics = {
            "clusters": [
                {
                    "cluster_id": 0,
                    "label": "Alice",
                    "devices": ["aa:bb:cc:dd:ee:01"],
                    "avg_presence": 0.9,
                },
                {
                    "cluster_id": 1,
                    "label": "Bob",
                    "devices": ["aa:bb:cc:dd:ee:02"],
                    "avg_presence": 0.7,
                },
            ]
        }

        (mock_logs_dir / "presence-current.json").write_text(json.dumps(current))
        (mock_logs_dir / "presence-analytics.json").write_text(json.dumps(analytics))

        feed = mod.MovementFeed()
        snapshot = feed._generate_snapshot()

        persons = snapshot["persons"]
        assert len(persons) == 2
        assert persons[0]["label"] == "Alice"
        assert persons[1]["label"] == "Bob"
