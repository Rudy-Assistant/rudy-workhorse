"""OpenSpace Trigger Registry -- Session 144 (R-006 / R-009).

Minimal dispatcher that maps named runtime events to OpenSpace skill
handlers under ``$OPENSPACE_DIR/<skill>/handler.py``.  # lucius-exempt: docstring example

Replaces the implicit "scaffolds exist but nothing calls them" gap
flagged in S143 handoff (Batman directive S144 Priority 2).

Design constraints:
    * Import isolation (C3): handlers loaded lazily on dispatch.
    * No new dependencies -- stdlib only.
    * Safe-by-default: unknown trigger -> noop, never raise.
    * Returns structured ``{status, trigger, skill, result}`` for
      Robin's verifier and Lucius scoring.

Registered triggers (S144 v0):
    ci_green        -> git_push_on_ci_success
    process_audit   -> count_python_processes

Future triggers should be added via ``register_trigger()`` rather
than editing the constant table, but the constant table is the
canonical bootstrap set.
"""

from __future__ import annotations

import importlib.util
import logging
from pathlib import Path
from typing import Any, Callable

from rudy.paths import OPENSPACE_DIR

log = logging.getLogger("rudy.openspace_trigger_registry")

OPENSPACE_ROOT = OPENSPACE_DIR

# trigger_name -> openspace skill directory name
_REGISTRY: dict[str, str] = {
    "ci_green": "git_push_on_ci_success",
    "process_audit": "count_python_processes",
}


def register_trigger(trigger_name: str, skill_dir: str) -> None:
    """Register or override a trigger -> skill mapping at runtime."""
    _REGISTRY[trigger_name] = skill_dir
    log.info("Registered trigger %s -> %s", trigger_name, skill_dir)


def list_triggers() -> dict[str, str]:
    """Return a copy of the current trigger table."""
    return dict(_REGISTRY)


def _load_handler(skill_dir: str) -> Callable[[dict], dict] | None:
    """Lazy-load ``handler.execute`` from an OpenSpace skill dir."""
    handler_path = OPENSPACE_ROOT / skill_dir / "handler.py"
    if not handler_path.exists():
        log.warning("Handler not found: %s", handler_path)
        return None
    spec = importlib.util.spec_from_file_location(
        f"openspace_skill_{skill_dir}", handler_path
    )
    if spec is None or spec.loader is None:
        return None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001
        log.exception("Failed to load %s: %s", handler_path, exc)
        return None
    fn = getattr(module, "execute", None)
    if not callable(fn):
        log.warning("%s has no callable execute()", handler_path)
        return None
    return fn


def dispatch(
    trigger_name: str,
    context: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Dispatch a trigger to its registered OpenSpace handler.

    Returns a structured envelope; never raises.
    """
    context = context or {}
    skill_dir = _REGISTRY.get(trigger_name)
    if not skill_dir:
        return {
            "status": "noop",
            "trigger": trigger_name,
            "reason": "trigger not registered",
        }
    handler = _load_handler(skill_dir)
    if handler is None:
        return {
            "status": "error",
            "trigger": trigger_name,
            "skill": skill_dir,
            "reason": "handler unavailable",
        }
    try:
        result = handler(context)
    except Exception as exc:  # noqa: BLE001
        log.exception("Handler %s raised", skill_dir)
        return {
            "status": "error",
            "trigger": trigger_name,
            "skill": skill_dir,
            "reason": f"handler raised: {exc}",
        }
    return {
        "status": "dispatched",
        "trigger": trigger_name,
        "skill": skill_dir,
        "result": result,
    }


if __name__ == "__main__":
    import json

    print(json.dumps(list_triggers(), indent=2))
    print(json.dumps(dispatch("process_audit"), indent=2, default=str))
    print(json.dumps(
        dispatch("ci_green", {"ci_status": "success"}),
        indent=2,
        default=str,
    ))
