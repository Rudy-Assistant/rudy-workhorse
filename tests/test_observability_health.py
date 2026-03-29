"""
Comprehensive tests for HealthAggregator and ComponentHealth.

Tests cover:
- Component health status values
- Component registration and checks
- System-wide health aggregation
- Dependency chain propagation
- Health status summary generation
"""

import pytest
from datetime import datetime
from unittest.mock import MagicMock

from rudy.observability.health import (
    HealthStatus,
    ComponentHealth,
    SystemHealth,
    HealthAggregator,
)


@pytest.fixture
def aggregator():
    """Create a HealthAggregator for testing."""
    return HealthAggregator()


class TestHealthStatus:
    """Test HealthStatus enum."""

    def test_health_status_values(self):
        """Test that all health status values exist."""
        assert HealthStatus.HEALTHY.value == "healthy"
        assert HealthStatus.DEGRADED.value == "degraded"
        assert HealthStatus.UNHEALTHY.value == "unhealthy"
        assert HealthStatus.UNKNOWN.value == "unknown"

    def test_health_status_string_conversion(self):
        """Test converting health status to string."""
        assert str(HealthStatus.HEALTHY) == "HealthStatus.HEALTHY"


class TestComponentHealth:
    """Test ComponentHealth data class."""

    def test_component_health_creation(self):
        """Test creating ComponentHealth."""
        health = ComponentHealth(
            name="test_component",
            status=HealthStatus.HEALTHY,
            last_check=datetime.now().isoformat(),
            message="All good",
        )

        assert health.name == "test_component"
        assert health.status == HealthStatus.HEALTHY
        assert health.message == "All good"

    def test_component_health_with_metrics(self):
        """Test ComponentHealth with metrics."""
        metrics = {"cpu_usage": 45.2, "memory_mb": 512}
        health = ComponentHealth(
            name="system",
            status=HealthStatus.HEALTHY,
            last_check=datetime.now().isoformat(),
            metrics=metrics,
        )

        assert health.metrics == metrics

    def test_component_health_with_dependencies(self):
        """Test ComponentHealth with dependencies."""
        dependencies = ["database", "cache"]
        health = ComponentHealth(
            name="api_service",
            status=HealthStatus.HEALTHY,
            last_check=datetime.now().isoformat(),
            dependencies=dependencies,
        )

        assert health.dependencies == dependencies


class TestHealthAggregator:
    """Test HealthAggregator functionality."""

    def test_aggregator_initialization(self, aggregator):
        """Test aggregator initialization."""
        assert aggregator._components == {}
        assert aggregator._start_time is not None

    def test_register_component(self, aggregator):
        """Test registering a component."""
        def check_fn():
            return ComponentHealth(
                name="test",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
            )

        aggregator.register_component("test", check_fn)

        assert "test" in aggregator._components
        assert aggregator._components["test"]["check_fn"] == check_fn

    def test_register_component_with_dependencies(self, aggregator):
        """Test registering component with dependencies."""
        def check_fn():
            return ComponentHealth(
                name="test",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
            )

        aggregator.register_component(
            "service",
            check_fn,
            dependencies=["database", "cache"],
        )

        assert aggregator._components["service"]["dependencies"] == ["database", "cache"]

    def test_check_component_success(self, aggregator):
        """Test checking a component."""
        def check_fn():
            return ComponentHealth(
                name="test",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
                message="OK",
            )

        aggregator.register_component("test", check_fn)
        health = aggregator.check_component("test")

        assert health is not None
        assert health.status == HealthStatus.HEALTHY
        assert health.message == "OK"

    def test_check_nonexistent_component(self, aggregator):
        """Test checking a non-existent component."""
        health = aggregator.check_component("nonexistent")
        assert health is None

    def test_check_component_with_exception(self, aggregator):
        """Test handling exception in component check."""
        def check_fn():
            raise ValueError("Check failed")

        aggregator.register_component("failing", check_fn)
        health = aggregator.check_component("failing")

        assert health is not None
        assert health.status == HealthStatus.UNHEALTHY
        assert "Check failed" in health.message


class TestSystemHealthAggregation:
    """Test system-wide health aggregation."""

    def test_check_all_healthy(self, aggregator):
        """Test check_all when all components are healthy."""
        def healthy_check():
            return ComponentHealth(
                name="comp1",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
            )

        aggregator.register_component("comp1", healthy_check)
        aggregator.register_component("comp2", healthy_check)

        system_health = aggregator.check_all()

        assert system_health.overall_status == HealthStatus.HEALTHY
        assert len(system_health.components) == 2

    def test_check_all_with_unhealthy(self, aggregator):
        """Test check_all with unhealthy component."""
        def healthy_check():
            return ComponentHealth(
                name="healthy",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
            )

        def unhealthy_check():
            return ComponentHealth(
                name="unhealthy",
                status=HealthStatus.UNHEALTHY,
                last_check=datetime.now().isoformat(),
            )

        aggregator.register_component("comp1", healthy_check)
        aggregator.register_component("comp2", unhealthy_check)

        system_health = aggregator.check_all()

        assert system_health.overall_status == HealthStatus.UNHEALTHY

    def test_check_all_with_degraded(self, aggregator):
        """Test check_all with degraded component."""
        def healthy_check():
            return ComponentHealth(
                name="healthy",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
            )

        def degraded_check():
            return ComponentHealth(
                name="degraded",
                status=HealthStatus.DEGRADED,
                last_check=datetime.now().isoformat(),
            )

        aggregator.register_component("comp1", healthy_check)
        aggregator.register_component("comp2", degraded_check)

        system_health = aggregator.check_all()

        assert system_health.overall_status == HealthStatus.DEGRADED

    def test_check_all_empty(self, aggregator):
        """Test check_all with no registered components."""
        system_health = aggregator.check_all()
        assert system_health.overall_status == HealthStatus.UNKNOWN


class TestDependencyPropagation:
    """Test health dependency chain propagation."""

    def test_unhealthy_dependency_propagates(self, aggregator):
        """Test that unhealthy dependency marks dependent as degraded."""
        def unhealthy_check():
            return ComponentHealth(
                name="database",
                status=HealthStatus.UNHEALTHY,
                last_check=datetime.now().isoformat(),
            )

        def dependent_check():
            return ComponentHealth(
                name="api",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
                dependencies=["database"],
            )

        aggregator.register_component("database", unhealthy_check)
        aggregator.register_component("api", dependent_check)

        system_health = aggregator.check_all()

        # API should be degraded because its dependency is unhealthy
        assert system_health.components["api"].status == HealthStatus.DEGRADED

    def test_healthy_dependency_no_propagation(self, aggregator):
        """Test that healthy dependency doesn't degrade dependent."""
        def healthy_check():
            return ComponentHealth(
                name="database",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
            )

        def dependent_check():
            return ComponentHealth(
                name="api",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
                dependencies=["database"],
            )

        aggregator.register_component("database", healthy_check)
        aggregator.register_component("api", dependent_check)

        system_health = aggregator.check_all()

        # API should remain healthy
        assert system_health.components["api"].status == HealthStatus.HEALTHY

    def test_multiple_dependencies(self, aggregator):
        """Test component with multiple dependencies."""
        def healthy_check():
            return ComponentHealth(
                name="healthy",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
            )

        def unhealthy_check():
            return ComponentHealth(
                name="unhealthy",
                status=HealthStatus.UNHEALTHY,
                last_check=datetime.now().isoformat(),
            )

        def service_check():
            return ComponentHealth(
                name="service",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
                dependencies=["dep1", "dep2"],
            )

        aggregator.register_component("dep1", healthy_check)
        aggregator.register_component("dep2", unhealthy_check)
        aggregator.register_component("service", service_check)

        system_health = aggregator.check_all()

        # Service should be degraded (one dependency unhealthy)
        assert system_health.components["service"].status == HealthStatus.DEGRADED

    def test_chain_dependency(self, aggregator):
        """Test chain of dependencies."""
        def unhealthy_check():
            return ComponentHealth(
                name="root",
                status=HealthStatus.UNHEALTHY,
                last_check=datetime.now().isoformat(),
            )

        def level1_check():
            return ComponentHealth(
                name="level1",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
                dependencies=["root"],
            )

        def level2_check():
            return ComponentHealth(
                name="level2",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
                dependencies=["level1"],
            )

        aggregator.register_component("root", unhealthy_check)
        aggregator.register_component("level1", level1_check)
        aggregator.register_component("level2", level2_check)

        system_health = aggregator.check_all()

        # level1 should be degraded (depends on unhealthy root)
        assert system_health.components["level1"].status == HealthStatus.DEGRADED
        # level2 should remain healthy (only depends on level1 which is degraded, not unhealthy)
        # This tests the specific logic: only UNHEALTHY deps cause DEGRADED status
        assert system_health.components["level2"].status == HealthStatus.HEALTHY


class TestStatusSummary:
    """Test health status summary."""

    def test_get_status_summary(self, aggregator):
        """Test getting status summary."""
        def healthy_check():
            return ComponentHealth(
                name="comp1",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
            )

        aggregator.register_component("comp1", healthy_check)
        aggregator.register_component("comp2", healthy_check)

        summary = aggregator.get_status_summary()

        assert summary["overall_status"] == "healthy"
        assert summary["total_components"] == 2
        assert summary["healthy_count"] == 2
        assert summary["degraded_count"] == 0
        assert summary["unhealthy_count"] == 0

    def test_status_summary_structure(self, aggregator):
        """Test that status summary has all required fields."""
        def check_fn():
            return ComponentHealth(
                name="test",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
            )

        aggregator.register_component("test", check_fn)
        summary = aggregator.get_status_summary()

        assert "overall_status" in summary
        assert "checked_at" in summary
        assert "uptime_seconds" in summary
        assert "total_components" in summary
        assert "healthy_count" in summary
        assert "degraded_count" in summary
        assert "unhealthy_count" in summary
        assert "unhealthy_components" in summary
        assert "degraded_components" in summary

    def test_status_summary_with_mixed_states(self, aggregator):
        """Test summary with components in different states."""
        def healthy_check():
            return ComponentHealth(
                name="healthy",
                status=HealthStatus.HEALTHY,
                last_check=datetime.now().isoformat(),
            )

        def degraded_check():
            return ComponentHealth(
                name="degraded",
                status=HealthStatus.DEGRADED,
                last_check=datetime.now().isoformat(),
            )

        def unhealthy_check():
            return ComponentHealth(
                name="unhealthy",
                status=HealthStatus.UNHEALTHY,
                last_check=datetime.now().isoformat(),
            )

        aggregator.register_component("c1", healthy_check)
        aggregator.register_component("c2", degraded_check)
        aggregator.register_component("c3", unhealthy_check)

        summary = aggregator.get_status_summary()

        assert summary["healthy_count"] == 1
        assert summary["degraded_count"] == 1
        assert summary["unhealthy_count"] == 1
        assert "c3" in summary["unhealthy_components"]
        assert "c2" in summary["degraded_components"]

    def test_status_summary_lists_unhealthy_components(self, aggregator):
        """Test that unhealthy components are listed."""
        def unhealthy_check():
            return ComponentHealth(
                name="failing_service",
                status=HealthStatus.UNHEALTHY,
                last_check=datetime.now().isoformat(),
            )

        aggregator.register_component("bad1", unhealthy_check)
        aggregator.register_component("bad2", unhealthy_check)

        summary = aggregator.get_status_summary()

        assert len(summary["unhealthy_components"]) == 2
        assert "bad1" in summary["unhealthy_components"]
        assert "bad2" in summary["unhealthy_components"]


class TestBuiltinChecks:
    """Test built-in health checks."""

    def test_register_builtin_checks(self, aggregator, tmp_path):
        """Test registering built-in checks."""
        db_path = tmp_path / "test.sqlite"
        aggregator.register_builtin_checks(db_path=db_path)

        # Should have registered memory, database, and disk checks
        assert "memory_system" in aggregator._components
        assert "database" in aggregator._components
        assert "disk_space" in aggregator._components

    def test_builtin_database_check(self, aggregator, tmp_path):
        """Test built-in database health check."""
        db_path = tmp_path / "test.sqlite"
        aggregator.register_builtin_checks(db_path=db_path)

        health = aggregator.check_component("database")
        assert health is not None
        assert health.status in [HealthStatus.HEALTHY, HealthStatus.UNKNOWN]

    def test_builtin_disk_check(self, aggregator, tmp_path):
        """Test built-in disk space check."""
        aggregator.register_builtin_checks()

        health = aggregator.check_component("disk_space")
        assert health is not None
        assert health.status in [HealthStatus.HEALTHY, HealthStatus.DEGRADED, HealthStatus.UNHEALTHY, HealthStatus.UNKNOWN]
        assert "free_percent" in health.metrics
