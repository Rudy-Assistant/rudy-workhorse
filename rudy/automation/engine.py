"""
AutomationEngine — Phase 3 Central Automation Coordinator

Manages all automation triggers (webhooks, cron, email) and integrates
with Oracle to decompose triggered workflows into executable tasks.

Features:
- Trigger registration and management (webhook/cron/email/manual)
- Event processing and trigger matching
- Oracle integration for task decomposition
- SQLite persistence for trigger configurations
- Fire tracking and audit trail
"""

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

log = logging.getLogger(__name__)

# Default database path
DESKTOP = Path(__file__).resolve().parent.parent.parent / "Desktop" if not Path(__file__).resolve().parent.parent.parent.name == "push-staging" else Path(__file__).resolve().parent.parent.parent
if str(DESKTOP) == str(Path(__file__).resolve().parent.parent.parent):
    # Running from /sessions/compassionate-peaceful-hamilton/push-staging
    DESKTOP = Path(__file__).resolve().parent.parent.parent / "Desktop"
DEFAULT_DB_PATH = DESKTOP / "rudy-data" / "memory.sqlite"


@dataclass
class WorkflowTrigger:
    """Trigger definition for automated workflows."""
    id: str
    name: str
    trigger_type: str  # webhook | cron | email | manual
    config: Dict[str, Any]
    enabled: bool
    created_at: str
    last_fired: Optional[str] = None
    fire_count: int = 0


class AutomationEngine:
    """Central coordinator for all automation triggers.

    Manages trigger registration, event processing, and Oracle integration.
    All triggers persist to SQLite for recovery and audit trails.
    """

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize AutomationEngine.

        Args:
            db_path: Path to memory.sqlite (created if not exists)
        """
        self._db_path = db_path or DEFAULT_DB_PATH
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database
        self._init_db()

        # In-memory trigger cache for fast lookup
        self._triggers_cache: Dict[str, WorkflowTrigger] = {}
        self._load_triggers_cache()

        # Oracle reference (injected later)
        self._oracle = None

        log.info(f"AutomationEngine initialized with db: {self._db_path}")

    def _init_db(self) -> None:
        """Initialize SQLite tables for automation triggers."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            cursor = conn.cursor()

            # Create automation_triggers table if not exists
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS automation_triggers (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    config TEXT NOT NULL,
                    enabled BOOLEAN DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_fired TEXT,
                    fire_count INTEGER DEFAULT 0
                )
            """)

            conn.commit()
            conn.close()
            log.debug("Database initialized")
        except Exception as e:
            log.error(f"Failed to initialize database: {e}")

    def _load_triggers_cache(self) -> None:
        """Load all triggers from database into memory cache."""
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM automation_triggers")
            rows = cursor.fetchall()
            conn.close()

            for row in rows:
                trigger = WorkflowTrigger(
                    id=row[0],
                    name=row[1],
                    trigger_type=row[2],
                    config=json.loads(row[3]),
                    enabled=bool(row[4]),
                    created_at=row[5],
                    last_fired=row[6],
                    fire_count=row[7],
                )
                self._triggers_cache[trigger.id] = trigger

            log.debug(f"Loaded {len(self._triggers_cache)} triggers from database")
        except Exception as e:
            log.error(f"Failed to load triggers cache: {e}")

    def set_oracle(self, oracle) -> None:
        """Inject Oracle reference for task decomposition.

        Args:
            oracle: Oracle orchestrator instance
        """
        self._oracle = oracle
        log.info("Oracle reference injected")

    def register_trigger(
        self,
        name: str,
        trigger_type: str,
        config: Dict[str, Any],
    ) -> str:
        """Register a new automation trigger.

        Args:
            name: Human-readable trigger name
            trigger_type: Type of trigger (webhook | cron | email | manual)
            config: Configuration dict specific to trigger type

        Returns:
            trigger_id (UUID)

        Example:
            engine.register_trigger(
                "daily_standup",
                "cron",
                {"schedule": "0 9 * * *", "task_type": "report", "task_config": {...}}
            )
        """
        trigger_id = str(uuid.uuid4())
        now = datetime.now().isoformat()

        trigger = WorkflowTrigger(
            id=trigger_id,
            name=name,
            trigger_type=trigger_type,
            config=config,
            enabled=True,
            created_at=now,
        )

        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO automation_triggers
                (id, name, trigger_type, config, enabled, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                trigger.id,
                trigger.name,
                trigger.trigger_type,
                json.dumps(trigger.config),
                1,
                trigger.created_at,
            ))
            conn.commit()
            conn.close()

            self._triggers_cache[trigger_id] = trigger
            self.action(f"Registered trigger: {name} ({trigger_type})")
            log.info(f"Trigger registered: {trigger_id} ({name})")
            return trigger_id

        except Exception as e:
            log.error(f"Failed to register trigger: {e}")
            return ""

    def unregister_trigger(self, trigger_id: str) -> bool:
        """Unregister and delete a trigger.

        Args:
            trigger_id: Trigger ID to remove

        Returns:
            True if removed, False if not found
        """
        if trigger_id not in self._triggers_cache:
            return False

        try:
            trigger = self._triggers_cache[trigger_id]
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("DELETE FROM automation_triggers WHERE id = ?", (trigger_id,))
            conn.commit()
            conn.close()

            del self._triggers_cache[trigger_id]
            log.info(f"Trigger unregistered: {trigger_id} ({trigger.name})")
            return True

        except Exception as e:
            log.error(f"Failed to unregister trigger: {e}")
            return False

    def list_triggers(
        self,
        trigger_type: Optional[str] = None,
        enabled_only: bool = False,
    ) -> List[Dict[str, Any]]:
        """List all registered triggers.

        Args:
            trigger_type: Filter by type (optional)
            enabled_only: Only return enabled triggers

        Returns:
            List of trigger dicts
        """
        triggers = list(self._triggers_cache.values())

        if trigger_type:
            triggers = [t for t in triggers if t.trigger_type == trigger_type]

        if enabled_only:
            triggers = [t for t in triggers if t.enabled]

        return [asdict(t) for t in triggers]

    def enable_trigger(self, trigger_id: str) -> bool:
        """Enable a trigger.

        Args:
            trigger_id: Trigger ID

        Returns:
            True if successful
        """
        if trigger_id not in self._triggers_cache:
            return False

        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("UPDATE automation_triggers SET enabled = 1 WHERE id = ?", (trigger_id,))
            conn.commit()
            conn.close()

            self._triggers_cache[trigger_id].enabled = True
            log.info(f"Trigger enabled: {trigger_id}")
            return True

        except Exception as e:
            log.error(f"Failed to enable trigger: {e}")
            return False

    def disable_trigger(self, trigger_id: str) -> bool:
        """Disable a trigger.

        Args:
            trigger_id: Trigger ID

        Returns:
            True if successful
        """
        if trigger_id not in self._triggers_cache:
            return False

        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            cursor.execute("UPDATE automation_triggers SET enabled = 0 WHERE id = ?", (trigger_id,))
            conn.commit()
            conn.close()

            self._triggers_cache[trigger_id].enabled = False
            log.info(f"Trigger disabled: {trigger_id}")
            return True

        except Exception as e:
            log.error(f"Failed to disable trigger: {e}")
            return False

    def process_event(
        self,
        event_type: str,
        event_data: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Process an event and dispatch to matching triggers.

        When a trigger fires, creates a task for Oracle to decompose
        and execute.

        Args:
            event_type: Type of event (webhook | cron | email | manual)
            event_data: Event payload

        Returns:
            List of triggered workflow results
        """
        results = []

        # Find matching triggers
        matching = [
            t for t in self._triggers_cache.values()
            if t.enabled and t.trigger_type == event_type
        ]

        for trigger in matching:
            try:
                result = self._fire_trigger(trigger, event_data)
                results.append(result)
            except Exception as e:
                log.error(f"Failed to fire trigger {trigger.id}: {e}")
                results.append({
                    "trigger_id": trigger.id,
                    "status": "error",
                    "error": str(e),
                })

        log.info(f"Event processed: {event_type}, {len(results)} triggers fired")
        return results

    def _fire_trigger(
        self,
        trigger: WorkflowTrigger,
        event_data: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Fire a single trigger and integrate with Oracle.

        Args:
            trigger: WorkflowTrigger to fire
            event_data: Event data to pass to workflow

        Returns:
            Result dict with status and workflow info
        """
        now = datetime.now().isoformat()

        # Update trigger metadata
        try:
            conn = sqlite3.connect(str(self._db_path))
            cursor = conn.cursor()
            trigger.fire_count += 1
            cursor.execute("""
                UPDATE automation_triggers
                SET last_fired = ?, fire_count = ?
                WHERE id = ?
            """, (now, trigger.fire_count, trigger.id))
            conn.commit()
            conn.close()

            self._triggers_cache[trigger.id] = trigger
        except Exception as e:
            log.error(f"Failed to update trigger metadata: {e}")

        # If Oracle is available, decompose the workflow
        if self._oracle:
            try:
                intent = f"Execute {trigger.name}: {trigger.config.get('description', 'automation task')}"
                plan = self._oracle.decompose(intent, context={"trigger": trigger.id, "event": event_data})
                result = self._oracle.execute_plan(plan)

                return {
                    "trigger_id": trigger.id,
                    "status": "executed",
                    "plan_id": plan.id,
                    "execution_status": result.status,
                    "fired_at": now,
                }
            except Exception as e:
                log.error(f"Oracle execution failed for trigger {trigger.id}: {e}")

        # Fallback: just log the trigger fire
        return {
            "trigger_id": trigger.id,
            "status": "fired",
            "fired_at": now,
            "fire_count": trigger.fire_count,
        }

    def action(self, message: str) -> None:
        """Log an action (for AgentBase compatibility)."""
        log.info(f"ACTION: {message}")
