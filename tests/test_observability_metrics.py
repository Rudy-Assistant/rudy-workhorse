"""
Comprehensive tests for MetricsCollector.

Tests cover:
- Counter increment operations
- Gauge set/get operations
- Histogram value observation and statistics
- Metric retrieval and querying
- Prometheus format export
- Labels and metric identification
- Metrics reset
"""

import pytest
import tempfile
from pathlib import Path

from rudy.observability.metrics import (
    MetricsCollector,
    MetricType,
    Metric,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.sqlite"
        yield db_path


@pytest.fixture
def collector(temp_db):
    """Create a MetricsCollector with temp database."""
    return MetricsCollector(db_path=temp_db)


class TestMetricsCollectorCreation:
    """Test collector initialization."""

    def test_collector_creation(self, collector):
        """Test creating a metrics collector."""
        assert collector._db_path is not None
        assert isinstance(collector._metrics, dict)

    def test_collector_with_default_db(self):
        """Test collector with default database."""
        collector = MetricsCollector()
        assert collector._db_path is not None
        assert "rudy-data" in str(collector._db_path)


class TestCounter:
    """Test counter metric type."""

    def test_increment_counter(self, collector):
        """Test incrementing a counter."""
        collector.increment("requests_total")

        value = collector.get_metric("requests_total")
        assert value == 1.0

    def test_increment_counter_multiple_times(self, collector):
        """Test incrementing counter multiple times."""
        collector.increment("requests_total")
        collector.increment("requests_total")
        collector.increment("requests_total")

        value = collector.get_metric("requests_total")
        assert value == 3.0

    def test_increment_counter_by_value(self, collector):
        """Test incrementing counter by specific value."""
        collector.increment("requests_total", value=5.0)

        value = collector.get_metric("requests_total")
        assert value == 5.0

    def test_increment_counter_with_labels(self, collector):
        """Test incrementing counter with labels."""
        collector.increment("requests_total", labels={"method": "GET"})
        collector.increment("requests_total", labels={"method": "POST"})

        get_value = collector.get_metric("requests_total", labels={"method": "GET"})
        post_value = collector.get_metric("requests_total", labels={"method": "POST"})

        assert get_value == 1.0
        assert post_value == 1.0

    def test_counter_accumulates(self, collector):
        """Test that counters accumulate values."""
        collector.increment("events", value=10)
        collector.increment("events", value=20)

        value = collector.get_metric("events")
        assert value == 30.0


class TestGauge:
    """Test gauge metric type."""

    def test_set_gauge(self, collector):
        """Test setting a gauge."""
        collector.gauge("temperature", 72.5)

        value = collector.get_metric("temperature")
        assert value == 72.5

    def test_gauge_overwrites_value(self, collector):
        """Test that gauge overwrites previous value."""
        collector.gauge("temperature", 70.0)
        collector.gauge("temperature", 75.0)

        value = collector.get_metric("temperature")
        assert value == 75.0

    def test_gauge_with_labels(self, collector):
        """Test gauge with labels."""
        collector.gauge("temperature", 72.5, labels={"location": "room1"})
        collector.gauge("temperature", 68.0, labels={"location": "room2"})

        room1 = collector.get_metric("temperature", labels={"location": "room1"})
        room2 = collector.get_metric("temperature", labels={"location": "room2"})

        assert room1 == 72.5
        assert room2 == 68.0

    def test_gauge_accepts_negative(self, collector):
        """Test gauge can hold negative values."""
        collector.gauge("delta", -42.5)

        value = collector.get_metric("delta")
        assert value == -42.5

    def test_gauge_accepts_zero(self, collector):
        """Test gauge can be set to zero."""
        collector.gauge("memory_used", 0)

        value = collector.get_metric("memory_used")
        assert value == 0


class TestHistogram:
    """Test histogram metric type."""

    def test_observe_histogram(self, collector):
        """Test observing histogram value."""
        collector.observe("request_duration", 100.5)

        # Histogram get_metric returns count of observations
        value = collector.get_metric("request_duration")
        assert value == 1.0

    def test_histogram_multiple_observations(self, collector):
        """Test multiple histogram observations."""
        for val in [10, 20, 30, 40, 50]:
            collector.observe("latency", val)

        count = collector.get_metric("latency")
        assert count == 5.0

    def test_histogram_with_labels(self, collector):
        """Test histogram with labels."""
        collector.observe("response_size", 1024, labels={"endpoint": "/api/users"})
        collector.observe("response_size", 2048, labels={"endpoint": "/api/users"})
        collector.observe("response_size", 512, labels={"endpoint": "/api/posts"})

        api_users = collector.get_metric("response_size", labels={"endpoint": "/api/users"})
        api_posts = collector.get_metric("response_size", labels={"endpoint": "/api/posts"})

        assert api_users == 2.0
        assert api_posts == 1.0


class TestMetricRetrieval:
    """Test retrieving metric values."""

    def test_get_metric_nonexistent(self, collector):
        """Test getting non-existent metric returns None."""
        value = collector.get_metric("nonexistent")
        assert value is None

    def test_get_all_metrics(self, collector):
        """Test getting all metrics."""
        collector.increment("counter1")
        collector.gauge("gauge1", 42)
        collector.observe("histogram1", 100)

        all_metrics = collector.get_all_metrics()

        assert "counter1" in all_metrics
        assert "gauge1" in all_metrics
        assert "histogram1" in all_metrics

    def test_get_all_metrics_with_labels(self, collector):
        """Test getting all metrics with labels."""
        collector.increment("requests", labels={"method": "GET"})
        collector.increment("requests", labels={"method": "POST"})

        all_metrics = collector.get_all_metrics()

        # Keys should include label information
        get_key = "requests[method=GET]"
        post_key = "requests[method=POST]"
        assert all_metrics[get_key] == 1.0
        assert all_metrics[post_key] == 1.0


class TestHistogramStats:
    """Test histogram statistics calculation."""

    def test_histogram_stats_count(self, collector):
        """Test histogram count statistic."""
        for val in [10, 20, 30]:
            collector.observe("values", val)

        stats = collector.get_histogram_stats("values")
        assert stats["count"] == 3

    def test_histogram_stats_min_max(self, collector):
        """Test histogram min and max."""
        for val in [10, 50, 30, 20]:
            collector.observe("values", val)

        stats = collector.get_histogram_stats("values")
        assert stats["min"] == 10
        assert stats["max"] == 50

    def test_histogram_stats_average(self, collector):
        """Test histogram average calculation."""
        for val in [10, 20, 30, 40]:
            collector.observe("values", val)

        stats = collector.get_histogram_stats("values")
        assert stats["avg"] == 25.0

    def test_histogram_stats_percentiles(self, collector):
        """Test histogram percentile calculations."""
        # Create 100 values from 1 to 100
        for val in range(1, 101):
            collector.observe("values", val)

        stats = collector.get_histogram_stats("values")

        # P50 should be around 50, P95 around 95, P99 around 99
        assert 40 < stats["p50"] < 60
        assert 85 < stats["p95"] < 100
        assert 90 < stats["p99"] <= 100

    def test_histogram_stats_empty(self, collector):
        """Test histogram stats for empty histogram."""
        stats = collector.get_histogram_stats("nonexistent")
        assert stats is None

    def test_histogram_stats_single_value(self, collector):
        """Test histogram stats with single value."""
        collector.observe("single", 42)

        stats = collector.get_histogram_stats("single")
        assert stats["count"] == 1
        assert stats["min"] == 42
        assert stats["max"] == 42
        assert stats["avg"] == 42.0
        assert stats["p50"] == 42
        assert stats["p95"] == 42
        assert stats["p99"] == 42

    def test_histogram_stats_with_labels(self, collector):
        """Test histogram stats with labels."""
        for val in [100, 200, 300]:
            collector.observe("duration", val, labels={"endpoint": "/api"})

        stats = collector.get_histogram_stats("duration", labels={"endpoint": "/api"})

        assert stats["count"] == 3
        assert stats["min"] == 100
        assert stats["max"] == 300
        assert stats["avg"] == 200.0


class TestMetricReset:
    """Test resetting metrics."""

    def test_reset_counter(self, collector):
        """Test resetting a counter."""
        collector.increment("counter", value=10)
        assert collector.get_metric("counter") == 10.0

        collector.reset("counter")
        assert collector.get_metric("counter") is None

    def test_reset_gauge(self, collector):
        """Test resetting a gauge."""
        collector.gauge("gauge", 42)
        assert collector.get_metric("gauge") == 42

        collector.reset("gauge")
        assert collector.get_metric("gauge") is None

    def test_reset_histogram(self, collector):
        """Test resetting a histogram."""
        collector.observe("histogram", 100)
        assert collector.get_metric("histogram") == 1.0

        collector.reset("histogram")
        assert collector.get_metric("histogram") is None

    def test_reset_with_labels(self, collector):
        """Test resetting metric with specific labels."""
        collector.increment("requests", labels={"method": "GET"})
        collector.increment("requests", labels={"method": "POST"})

        collector.reset("requests", labels={"method": "GET"})

        get_value = collector.get_metric("requests", labels={"method": "GET"})
        post_value = collector.get_metric("requests", labels={"method": "POST"})

        assert get_value is None
        assert post_value == 1.0


class TestPrometheusExport:
    """Test Prometheus format export."""

    def test_export_prometheus_format(self, collector):
        """Test exporting metrics in Prometheus format."""
        collector.increment("requests_total", value=100)
        collector.gauge("temperature", 72.5)

        prometheus = collector.export_prometheus()

        assert "requests_total" in prometheus
        assert "temperature" in prometheus
        assert "TYPE" in prometheus
        assert "HELP" in prometheus

    def test_prometheus_includes_metric_type(self, collector):
        """Test that Prometheus export includes metric type."""
        collector.increment("counter")
        collector.gauge("gauge_val", 10)
        collector.observe("histogram", 50)

        prometheus = collector.export_prometheus()

        assert "# TYPE counter counter" in prometheus
        assert "# TYPE gauge_val gauge" in prometheus
        assert "# TYPE histogram histogram" in prometheus

    def test_prometheus_with_labels(self, collector):
        """Test Prometheus export with labels."""
        collector.increment("requests", labels={"method": "GET", "status": "200"})

        prometheus = collector.export_prometheus()

        assert 'method="GET"' in prometheus
        assert 'status="200"' in prometheus

    def test_prometheus_histogram_export(self, collector):
        """Test histogram export in Prometheus format."""
        for val in [10, 20, 30]:
            collector.observe("latency", val)

        prometheus = collector.export_prometheus()

        assert "latency_total" in prometheus

    def test_prometheus_multiline_format(self, collector):
        """Test that Prometheus export is properly formatted."""
        collector.increment("counter")
        collector.gauge("gauge", 42)

        prometheus = collector.export_prometheus()

        # Should be multiple lines
        lines = prometheus.split("\n")
        assert len(lines) > 2

        # Should have HELP and TYPE before samples
        assert any("HELP" in line for line in lines)
        assert any("TYPE" in line for line in lines)


class TestLabels:
    """Test metric labels and identification."""

    def test_metric_key_without_labels(self, collector):
        """Test metric key generation without labels."""
        key = collector._metric_key("test_metric", {})
        assert key == "test_metric"

    def test_metric_key_with_labels(self, collector):
        """Test metric key generation with labels."""
        labels = {"method": "GET", "status": "200"}
        key = collector._metric_key("requests", labels)

        assert "requests" in key
        assert "method=GET" in key
        assert "status=200" in key

    def test_label_ordering_consistent(self, collector):
        """Test that label ordering is consistent."""
        labels1 = {"b": "2", "a": "1"}
        labels2 = {"a": "1", "b": "2"}

        key1 = collector._metric_key("metric", labels1)
        key2 = collector._metric_key("metric", labels2)

        assert key1 == key2

    def test_different_labels_different_metrics(self, collector):
        """Test that different labels create different metrics."""
        collector.increment("requests", labels={"method": "GET"})
        collector.increment("requests", labels={"method": "POST"})
        collector.increment("requests", labels={"method": "PUT"})

        all_metrics = collector.get_all_metrics()

        # Should have 3 different metric instances
        request_metrics = [k for k in all_metrics.keys() if "requests" in k]
        assert len(request_metrics) == 3


class TestPersistence:
    """Test metric persistence."""

    def test_metrics_saved_to_database(self, temp_db):
        """Test that metrics are persisted to SQLite database."""
        collector = MetricsCollector(db_path=temp_db)
        collector.increment("counter", value=10)
        collector.gauge("gauge", 42)

        # Verify metrics are in memory
        assert collector.get_metric("counter") == 10.0
        assert collector.get_metric("gauge") == 42

        # The database file should exist
        assert temp_db.exists()

    def test_multiple_metrics_in_memory(self, temp_db):
        """Test that multiple metrics are stored in memory."""
        collector = MetricsCollector(db_path=temp_db)

        for i in range(10):
            collector.increment(f"metric_{i}", value=i)

        all_metrics = collector.get_all_metrics()

        # Should have all metrics in memory
        assert len(all_metrics) == 10
