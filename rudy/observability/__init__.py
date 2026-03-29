"""
Phase 4: Observability & Hardening System

Provides self-healing patterns, circuit breaker protection, structured logging,
health aggregation, and metrics collection for robust Workhorse operations.

Exports:
    - ReflexionEngine: Self-healing via error → hypothesis → restructure → retry
    - CircuitBreaker: Prevents cascading failures across agent boundaries
    - StructuredLogger: JSON structured logging with correlation tracking
    - HealthAggregator: System-wide health monitoring with dependencies
    - MetricsCollector: Lightweight metrics (counter, gauge, histogram)
"""

from rudy.observability.reflexion import ReflexionEngine, ReflexionCycle
from rudy.observability.circuit_breaker import CircuitBreaker, CircuitBreakerRegistry, CircuitState
from rudy.observability.logger import StructuredLogger
from rudy.observability.health import HealthAggregator, HealthStatus, ComponentHealth, SystemHealth
from rudy.observability.metrics import MetricsCollector, MetricType, Metric

__all__ = [
    "ReflexionEngine",
    "ReflexionCycle",
    "CircuitBreaker",
    "CircuitBreakerRegistry",
    "CircuitState",
    "StructuredLogger",
    "HealthAggregator",
    "HealthStatus",
    "ComponentHealth",
    "SystemHealth",
    "MetricsCollector",
    "MetricType",
    "Metric",
]
