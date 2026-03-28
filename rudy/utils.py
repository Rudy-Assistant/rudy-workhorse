"""
Shared utility functions for rudy modules.

Provides atomic file operations and safe JSON handling to prevent
data corruption from concurrent access or failed writes.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Optional


def atomic_json_save(path: Path, data: Any) -> None:
    """
    Atomically save data to a JSON file using a temporary file + os.replace().

    This prevents partial writes from corrupting the file if two processes
    attempt to write simultaneously. The operation is atomic on both Windows
    and Linux.

    Args:
        path: Target file path (Path or str)
        data: Data to serialize as JSON

    Raises:
        OSError: If the write or replace operation fails
        TypeError: If data contains non-JSON-serializable types
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    # Write to temporary file in the same directory to ensure same filesystem
    temp_fd, temp_path = tempfile.mkstemp(
        dir=str(path.parent),
        prefix=".tmp-",
        suffix=".json"
    )

    try:
        with os.fdopen(temp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        # Atomic replace: on both Windows and Linux, os.replace() is atomic
        os.replace(temp_path, str(path))
    except Exception:
        # Clean up temp file if something went wrong
        try:
            os.unlink(temp_path)
        except OSError:
            pass
        raise


def safe_json_load(path: Path, default: Optional[Any] = None) -> Any:
    """
    Safely load JSON from a file with proper error handling.

    Returns the default value if:
    - File doesn't exist
    - File is empty
    - JSON is malformed
    - Encoding is invalid

    Args:
        path: File path (Path or str)
        default: Default value to return if load fails (defaults to {})

    Returns:
        Deserialized JSON data or the default value
    """
    path = Path(path)

    if not path.exists():
        return default if default is not None else {}

    try:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return default if default is not None else {}
        return json.loads(content)
    except (json.JSONDecodeError, UnicodeDecodeError, OSError):
        return default if default is not None else {}
