"""
Metrics Collector — Lightweight metrics for monitoring and observability.

Supports three metric types:
  - COUNTER: Monotonically increasing counter
  - GAUGE: Point-in-time measurement
  - HISTOGRAM: Distribution of values (stored in buckets)

All metrics are stored in SQLite for persistence and can be exported
in Prometheus format for integration with monitoring systems.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List
import threading

log = logging.getLogger(__name__)


class MetricType(str, Enum):
    """Type of metric."""
    COUNTER = "counter"
    GAUGE = "gauge"
    HISTOGRAM = "histogram"


@dataclass
class Metric:
    """A metric data point."""
    name: str
    type: MetricType
    value: float
    labels: Dict[str, str]
    timestamp: str  # ISO timestamp


class MetricsCollector:
    """Lightweight metrics collection for system monitoring."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize Metrics Collector.

        Args:
            db_path: Path to SQLite database (default: memory.sqlite)
        """
        if db_path is None:
            import os
            desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
            db_path = desktop / "rudy-data" / "memory.sqlite"

        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # In-memory metric cache
        self._metrics: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()

        self._init_db()
        log.info(f"MetricsCollector initialized with db: {self._db_path}")

    def _init_db(self) -> None:
        """Create metrics tables if they don't exist."""
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS metrics (
                    id TEXT PRIMARY KEY,
                    timestamp TEXT NOT NULL,
                    name TEXT NOT NULL,
                    type TEXT,
                    value REAL,
                    labels TEXT
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_metrics_name_timestamp
                ON metrics(name, timestamp)
            """)
            conn.commit()

    def _connect(self) -> sqlite3.Connection:
        """Create a database connection."""
        conn = sqlite3.connect(str(self._db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def increment(self, name: str, value: float = 1.0, labels: Optional[Dict[str, str]] = None) -> None:
        """Increment a counter.

        Args:
            name: Metric name
            value: Increment amount (default: 1.0)
            labels: Optional label dict for categorization
        """
        labels = labels or {}
        key = self._metric_key(name, labels)

        with self._lock:
            if key not in self._metrics:
                self._metrics[key] = {
                    "name": name,
                    "type": MetricType.COUNTER,
                    "value": 0.0,
                    "labels": labels,
                }

            self._metrics[key]["value"] += value
            current_value = self._metrics[key]["value"]

        self._save_metric(name, MetricType.COUNTER, current_value, labels)
        log.debug(f"Counter '{name}' incremented to {current_value}")

    def gauge(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Set a gauge to a specific value.

        Args:
            name: Metric name
            value: Gauge value
            labels: Optional label dict
        """
        labels = labels or {}
        key = self._metric_key(name, labels)

        with self._lock:
            self._metrics[key] = {
                "name": name,
                "type": MetricType.GAUGE,
                "value": value,
                "labels": labels,
            }

        self._save_metric(name, MetricType.GAUGE, value, labels)
        log.debug(f"Gauge '{name}' set to {value}")

    def observe(self, name: str, value: float, labels: Optional[Dict[str, str]] = None) -> None:
        """Observe a histogram value.

        Args:
            name: Metric name
            value: Value to observe
            labels: Optional label dict
        """
        labels = labels or {}
        key = self._metric_key(name, labels)

        with self._lock:
            if key not in self._metrics:
                self._metrics[key] = {
                    "name": name,
                    "type": MetricType.HISTOGRAM,
                    "values": [],
                    "labels": labels,
                }

            self._metrics[key]["values"].append(value)

        self._save_metric(name, MetricType.HISTOGRAM, value, labels)
        log.debug(f"Histogram '{name}' observed value {value}")

    def get_metric(self, name: str, labels: Optional[Dict[str, str]] = None) -> Optional[float]:
        """Get the current value of a metric.

        Args:
            name: Metric name
            labels: Optional label dict

        Returns:
            Metric value or None if not found
        """
        labels = labels or {}
        key = self._metric_key(name, labels)

        with self._lock:
            if key in self._metrics:
                metric = self._metrics[key]
                if metric["type"] == MetricType.HISTOGRAM:
                    # Return count of observations
                    return float(len(metric.get("values", [])))
                else:
                    return metric.get("value")

        return None

    def get_all_metrics(self) -> Dict[str, Any]:
        """Get all current metric values.

        Returns:
            Dict mapping metric keys to values
        """
        with self._lock:
            result = {}
            for key, metric in self._metrics.items():
                if metric["type"] == MetricType.HISTOGRAM:
                    result[key] = len(metric.get("values", []))
                else:
                    result[key] = metric.get("value")
            return result

    def get_histogram_stats(self, name: str, labels: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
        """Get statistics for a histogram metric.

        Args:
            name: Metric name
            labels: Optional label dict

        Returns:
            Dict with count, min, max, avg, p50, p95, p99
        """
        labels = labels or {}
        key = self._metric_key(name, labels)

        with self._lock:
            if key not in self._metrics:
                return None

            metric = self._metrics[key]
            if metric["type"] != MetricType.HISTOGRAM:
                return None

            values = metric.get("values", [])
            if not values:
                return {
                    "count": 0,
                    "min": None,
                    "max": None,
                    "avg": None,
                    "p50": None,
                    "p95": None,
                    "p99": None,
                }

            # Calculate stats
            sorted_values = sorted(values)
            count = len(sorted_values)
            min_val = sorted_values[0]
            max_val = sorted_values[-1]
            avg_val = sum(sorted_values) / count

            # Percentiles
            p50 = sorted_values[int(count * 0.50)]
            p95 = sorted_values[int(count * 0.95)] if count > 1 else sorted_values[0]
            p99 = sorted_values[int(count * 0.99)] if count > 1 else sorted_values[0]

            return {
                "count": count,
                "min": min_val,
                "max": max_val,
                "avg": round(avg_val, 2),
                "p50": p50,
                "p95": p95,
                "p99": p99,
            }

    def reset(self, name: str, labels: Optional[Dict[str, str]] = None) -> None:
        """Reset a metric.

        Args:
            name: Metric name
            labels: Optional label dict
        """
        labels = labels or {}
        key = self._metric_key(name, labels)

        with self._lock:
            if key in self._metrics:
                del self._metrics[key]

        log.info(f"Metric '{name}' reset")

    def export_prometheus(self) -> str:
        """Export metrics in Prometheus text format.

        Returns:
            Prometheus format string (TYPE and HELP lines + samples)
        """
        lines = []
        seen_metrics = set()

        with self._lock:
            for key, metric in self._metrics.items():
                name = metric["name"]

                # Add TYPE and HELP lines once per metric
                if name not in seen_metrics:
                    metric_type = metric["type"].value
                    lines.append(f"# HELP {name} {name}")
                    lines.append(f"# TYPE {name} {metric_type}")
                    seen_metrics.add(name)

                # Format labels
                labels = metric.get("labels", {})
                labels_str = ""
                if labels:
                    label_parts = [f'{k}="{v}"' for k, v in labels.items()]
                    labels_str = "{" + ",".join(label_parts) + "}"

                # Format sample line
                if metric["type"] == MetricType.HISTOGRAM:
                    # For histogram, output count
                    count = len(metric.get("values", []))
                    lines.append(f"{name}_total{labels_str} {count}")
                else:
                    value = metric.get("value", 0)
                    lines.append(f"{name}{labels_str} {value}")

        return "\n".join(lines)

    def _metric_key(self, name: str, labels: Dict[str, str]) -> str:
        """Generate a unique key for a metric with labels."""
        if not labels:
            return name

        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}[{label_str}]"

    def _save_metric(
        self,
        name: str,
        metric_type: MetricType,
        value: float,
        labels: Dict[str, str],
    ) -> None:
        """Persist a metric to database."""
        try:
            import uuid
            with self._connect() as conn:
                conn.execute(
                    """INSERT INTO metrics (id, timestamp, name, type, value, labels)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        str(uuid.uuid4()),
                        datetime.now().isoformat(),
                        name,
                        metric_type.value,
                        value,
                        json.dumps(labels),
                    ),
                )
                conn.commit()
        except Exception as e:
            log.debug(f"Failed to save metric: {e}")
