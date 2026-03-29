"""
Pytest configuration — ensures test environment directories exist and provides shared fixtures.
"""

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def pytest_configure(config):
    """Create required directories before any imports happen."""
    desktop = Path(os.environ.get("USERPROFILE", os.path.expanduser("~"))) / "Desktop"
    (desktop / "rudy-logs").mkdir(parents=True, exist_ok=True)
    (desktop / "rudy-data").mkdir(parents=True, exist_ok=True)


@pytest.fixture
def tmp_db():
    """Create a temporary SQLite database path for memory tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        # Initialize the database with minimal schema if needed
        conn = sqlite3.connect(db_path)
        conn.close()
        yield db_path


@pytest.fixture
def tmp_personas():
    """Create a temporary directory with test persona YAML files."""
    with tempfile.TemporaryDirectory() as tmpdir:
        personas_dir = Path(tmpdir) / "personas"
        personas_dir.mkdir(parents=True, exist_ok=True)

        # Create sample persona YAML files for testing
        sample_persona = personas_dir / "default.yaml"
        sample_persona.write_text(
            """name: Default Persona
role: Assistant
knowledge: []
memory_enabled: true
"""
        )

        yield personas_dir


@pytest.fixture
def memory_manager(tmp_db, tmp_personas):
    """Create a MemoryManager with temporary database and personas."""
    try:
        from rudy.memory import MemoryManager
    except ImportError:
        pytest.skip("MemoryManager not available")

    manager = MemoryManager(db_path=str(tmp_db), personas_dir=str(tmp_personas))
    yield manager
    # Cleanup is handled by tmp_db and tmp_personas fixtures


@pytest.fixture
def mock_embed():
    """Patch sentence-transformers with a fake embedder."""
    fake_embedder = MagicMock()
    fake_embedder.encode.return_value = [[0.1, 0.2, 0.3]]  # Fake embedding vector

    with patch("sentence_transformers.SentenceTransformer", return_value=fake_embedder):
        yield fake_embedder
