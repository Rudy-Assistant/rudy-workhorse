"""
Session lock manager -- prevents competing Cowork launches.

When Robin's launcher_watcher detects an idle state and wants to
launch a new Cowork session, it must first acquire the session lock.
If an active session is already running (lock held + not stale),
the launcher skips the launch.

Lock file: rudy-data/coordination/session-lock.json
Stale threshold: 10 minutes (no heartbeat update = session dead).

Usage:
    from rudy.session_lock import SessionLock
    lock = SessionLock()
    if lock.acquire(session_id=123, launcher_pid=os.getpid()):
        # safe to launch
        ...
        lock.heartbeat()   # call periodically
        lock.release()
    else:
        print("Session already active, skipping launch")
"""

import json
import os
from datetime import datetime, timedelta
from pathlib import Path


RUDY_DATA = Path(os.environ.get(
    "RUDY_DATA", Path.home() / "rudy-data"
))
LOCK_FILE = RUDY_DATA / "coordination" / "session-lock.json"
STALE_MINUTES = 10


class SessionLock:
    """File-based session lock with heartbeat and stale detection."""

    def __init__(self, lock_path=None, stale_minutes=None):
        self.lock_path = Path(lock_path) if lock_path else LOCK_FILE
        self.stale_minutes = stale_minutes or STALE_MINUTES
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)

    def _read(self):
        """Read current lock state. Returns dict or None."""
        if not self.lock_path.exists():
            return None
        try:
            with open(self.lock_path, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return None

    def _write(self, data):
        """Write lock state atomically."""
        tmp = self.lock_path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2, default=str)
            f.write("\n")
        os.replace(str(tmp), str(self.lock_path))

    def is_locked(self):
        """Check if a non-stale session lock exists."""
        data = self._read()
        if data is None:
            return False
        heartbeat = data.get("last_heartbeat", data.get("acquired_at"))
        if not heartbeat:
            return False
        try:
            hb_time = datetime.fromisoformat(heartbeat)
            cutoff = datetime.now() - timedelta(minutes=self.stale_minutes)
            if hb_time < cutoff:
                return False  # stale lock
            return True
        except (ValueError, TypeError):
            return False

    def get_owner(self):
        """Return lock owner info or None if unlocked/stale."""
        if not self.is_locked():
            return None
        return self._read()

    def acquire(self, session_id, launcher_pid=None):
        """Acquire the session lock. Returns True if acquired."""
        if self.is_locked():
            return False
        data = {
            "session_id": session_id,
            "launcher_pid": launcher_pid or os.getpid(),
            "acquired_at": datetime.now().isoformat(),
            "last_heartbeat": datetime.now().isoformat(),
            "status": "active",
        }
        self._write(data)
        return True

    def heartbeat(self):
        """Update heartbeat timestamp on current lock."""
        data = self._read()
        if data is None:
            return False
        data["last_heartbeat"] = datetime.now().isoformat()
        self._write(data)
        return True

    def release(self):
        """Release the session lock."""
        data = self._read()
        if data:
            data["status"] = "released"
            data["released_at"] = datetime.now().isoformat()
            self._write(data)
        return True

    def force_release(self):
        """Force-release a stale or stuck lock."""
        if self.lock_path.exists():
            self.lock_path.unlink()
        return True

    def __repr__(self):
        data = self._read()
        if data:
            return (
                f"SessionLock(session={data.get('session_id')}, "
                f"status={data.get('status')}, "
                f"heartbeat={data.get('last_heartbeat')})"
            )
        return "SessionLock(unlocked)"

