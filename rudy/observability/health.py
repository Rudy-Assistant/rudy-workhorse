"""
Health Aggregator — System-wide health monitoring with dependency awareness.

Monitors component health (agents, services, resources) and infers overall
system health. Supports dependency chains: if a dependency is unhealthy,
dependent components are marked DEGRADED.

Health Status: HEALTHY, DEGRADED, UNHEALTHY, UNKNOWN
"""

import logging
import shutil
import sqlite3
from dataclasses import dataclass, asdict, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional, Dict, Any, List, Callable
import threading

log = logging.getLogger(__name__)


class HealthStatus(str, Enum):
    """Health status levels."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass
class ComponentHealth:
    """Health status of a single component."""
    name: str
    status: HealthStatus
    last_check: str  # ISO timestamp
    message: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    dependencies: List[str] = field(default_factory=list)


@dataclass
class SystemHealth:
    """Overall system health."""
    overall_status: HealthStatus
    components: Dict[str, ComponentHealth]
    checked_at: str  # ISO timestamp
    uptime_seconds: float


class HealthAggregator:
    """Monitors and aggregates component health across the system."""

    def __init__(self):
        """Initialize Health Aggregator."""
        self._components: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.Lock()
        self._start_time = datetime.now()

        log.info("HealthAggregator initialized")

    def register_component(
        self,
        name: str,
        check_fn: Callable[[], ComponentHealth],
        dependencies: Optional[List[str]] = None,
    ) -> None:
        """Register a component for health checking.

        Args:
            name: Component name
            check_fn: Callable that returns ComponentHealth
            dependencies: Optional list of component names this depends on
        """
        with self._lock:
            self._components[name] = {
                "check_fn": check_fn,
                "dependencies": dependencies or [],
                "last_health": None,
            }
        log.info(f"Registered health check for component: {name}")

    def check_component(self, name: str) -> Optional[ComponentHealth]:
        """Check health of a single component.

        Args:
            name: Component name to check

        Returns:
            ComponentHealth or None if component not found
        """
        with self._lock:
            if name not in self._components:
                return None

            comp_info = self._components[name]

        try:
            health = comp_info["check_fn"]()
            with self._lock:
                comp_info["last_health"] = health
            return health
        except Exception as e:
            log.error(f"Failed to check component '{name}': {e}")
            return ComponentHealth(
                name=name,
                status=HealthStatus.UNHEALTHY,
                last_check=datetime.now().isoformat(),
                message=f"Check failed: {str(e)}",
            )

    def check_all(self) -> SystemHealth:
        """Check health of all registered components.

        Dependency chain: if a dependency is UNHEALTHY, dependent
        components are marked DEGRADED.

        Returns:
            SystemHealth with all component statuses
        """
        components_dict: Dict[str, ComponentHealth] = {}

        with self._lock:
            comp_names = list(self._components.keys())

        # Check each component
        for name in comp_names:
            health = self.check_component(name)
            if health:
                components_dict[name] = health

        # Apply dependency logic
        unhealthy = {
            name for name, h in components_dict.items()
            if h.status == HealthStatus.UNHEALTHY
        }

        # If a dependency is unhealthy, dependent is degraded
        for name, health in components_dict.items():
            if health.dependencies and any(dep in unhealthy for dep in health.dependencies):
                health.status = HealthStatus.DEGRADED

        # Determine overall status
        statuses = [h.status for h in components_dict.values()]
        if not statuses:
            overall_status = HealthStatus.UNKNOWN
        elif any(s == HealthStatus.UNHEALTHY for s in statuses):
            overall_status = HealthStatus.UNHEALTHY
        elif any(s == HealthStatus.DEGRADED for s in statuses):
            overall_status = HealthStatus.DEGRADED
        elif all(s == HealthStatus.HEALTHY for s in statuses):
            overall_status = HealthStatus.HEALTHY
        else:
            overall_status = HealthStatus.UNKNOWN

        uptime = (datetime.now() - self._start_time).total_seconds()

        return SystemHealth(
            overall_status=overall_status,
            components=components_dict,
            checked_at=datetime.now().isoformat(),
            uptime_seconds=uptime,
        )

    def get_status_summary(self) -> Dict[str, Any]:
        """Get a summary of system health for API/dashboard consumption.

        Returns:
            Dict with overall_status, component_count, unhealthy_count, etc.
        """
        system_health = self.check_all()

        unhealthy = [
            name for name, h in system_health.components.items()
            if h.status == HealthStatus.UNHEALTHY
        ]
        degraded = [
            name for name, h in system_health.components.items()
            if h.status == HealthStatus.DEGRADED
        ]

        return {
            "overall_status": system_health.overall_status.value,
            "checked_at": system_health.checked_at,
            "uptime_seconds": system_health.uptime_seconds,
            "total_components": len(system_health.components),
            "healthy_count": len([h for h in system_health.components.values()
                                  if h.status == HealthStatus.HEALTHY]),
            "degraded_count": len(degraded),
            "unhealthy_count": len(unhealthy),
            "unhealthy_components": unhealthy,
            "degraded_components": degraded,
        }

    # ── Built-in Health Checks ──────────────────────────────────────

    def register_builtin_checks(self, db_path: Optional[Path] = None) -> None:
        """Register built-in health checks.

        Args:
            db_path: Path to memory.sqlite for connectivity check
        """
        # Memory system check
        def check_memory() -> ComponentHealth:
            try:
                from rudy.memory.manager import MemoryManager
                mem = MemoryManager()
                stats = mem.get_stats()
                return ComponentHealth(
                    name="memory_system",
                    status=HealthStatus.HEALTHY,
                    last_check=datetime.now().isoformat(),
                    message="Memory system operational",
                    metrics={
                        "episodic_events": stats.get("episodic", {}).get("total_events", 0),
                        "semantic_items": stats.get("semantic", {}).get("total_items", 0),
                    },
                )
            except Exception as e:
                return ComponentHealth(
                    name="memory_system",
                    status=HealthStatus.UNHEALTHY,
                    last_check=datetime.now().isoformat(),
                    message=f"Memory system error: {str(e)}",
                )

        # SQLite connectivity check
        def check_database() -> ComponentHealth:
            try:
                if db_path is None:
                    import os
                    desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
                    check_path = desktop / "rudy-data" / "memory.sqlite"
                else:
                    check_path = db_path

                conn = sqlite3.connect(str(check_path), timeout=5)
                conn.execute("SELECT 1")
                conn.close()

                return ComponentHealth(
                    name="database",
                    status=HealthStatus.HEALTHY,
                    last_check=datetime.now().isoformat(),
                    message="SQLite database operational",
                )
            except Exception as e:
                return ComponentHealth(
                    name="database",
                    status=HealthStatus.UNHEALTHY,
                    last_check=datetime.now().isoformat(),
                    message=f"Database error: {str(e)}",
                )

        # Disk space check
        def check_disk() -> ComponentHealth:
            try:
                import os
                desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
                stat = shutil.disk_usage(str(desktop))

                free_percent = (stat.free / stat.total) * 100
                status = HealthStatus.HEALTHY
                message = f"{free_percent:.1f}% disk free"

                if free_percent < 10:
                    status = HealthStatus.UNHEALTHY
                    message = f"Critical: {free_percent:.1f}% disk free"
                elif free_percent < 20:
                    status = HealthStatus.DEGRADED
                    message = f"Warning: {free_percent:.1f}% disk free"

                return ComponentHealth(
                    name="disk_space",
                    status=status,
                    last_check=datetime.now().isoformat(),
                    message=message,
                    metrics={
                        "total_bytes": stat.total,
                        "free_bytes": stat.free,
                        "free_percent": free_percent,
                    },
                )
            except Exception as e:
                return ComponentHealth(
                    name="disk_space",
                    status=HealthStatus.UNKNOWN,
                    last_check=datetime.now().isoformat(),
                    message=f"Disk check error: {str(e)}",
                )

        self.register_component("memory_system", check_memory)
        self.register_component("database", check_database, dependencies=[])
        self.register_component("disk_space", check_disk, dependencies=[])

        log.info("Built-in health checks registered")
