"""
Tests for rudy.utils module — atomic JSON operations and safe loading.
"""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from rudy.utils import atomic_json_save, safe_json_load


class TestAtomicJsonSave:
    """Tests for atomic_json_save function."""

    def test_atomic_save_creates_file(self, tmp_path):
        """Test that atomic_json_save creates a file with correct content."""
        test_file = tmp_path / "test.json"
        test_data = {"key": "value", "number": 42}

        atomic_json_save(test_file, test_data)

        assert test_file.exists()
        saved_data = json.loads(test_file.read_text(encoding="utf-8"))
        assert saved_data == test_data

    def test_atomic_save_creates_parent_dirs(self, tmp_path):
        """Test that atomic_json_save creates parent directories."""
        test_file = tmp_path / "nested" / "deep" / "path" / "test.json"
        test_data = {"nested": True}

        atomic_json_save(test_file, test_data)

        assert test_file.exists()
        saved_data = json.loads(test_file.read_text(encoding="utf-8"))
        assert saved_data == test_data

    def test_atomic_save_overwrites_existing_file(self, tmp_path):
        """Test that atomic_json_save overwrites existing files."""
        test_file = tmp_path / "test.json"
        old_data = {"old": "data"}
        new_data = {"new": "data"}

        # Write initial data
        test_file.write_text(json.dumps(old_data), encoding="utf-8")
        assert json.loads(test_file.read_text(encoding="utf-8")) == old_data

        # Overwrite with new data
        atomic_json_save(test_file, new_data)

        assert json.loads(test_file.read_text(encoding="utf-8")) == new_data

    def test_atomic_save_uses_temp_file(self, tmp_path):
        """Test that atomic_json_save uses a temporary file during write."""
        test_file = tmp_path / "test.json"
        test_data = {"temp": "test"}

        with patch("os.replace") as mock_replace:
            # Setup mock to capture the temp path
            temp_path_during_call = None

            def capture_replace(src, dst):
                nonlocal temp_path_during_call
                temp_path_during_call = src
                # Create the actual file to avoid errors
                Path(src).write_text(json.dumps(test_data), encoding="utf-8")

            mock_replace.side_effect = capture_replace

            try:
                atomic_json_save(test_file, test_data)
            except Exception:
                pass

            # Verify os.replace was called
            assert mock_replace.called

    def test_atomic_save_handles_non_serializable_data(self, tmp_path):
        """Test that atomic_json_save handles non-serializable data with default=str."""
        test_file = tmp_path / "test.json"

        # Create object with custom __str__
        class CustomObject:
            def __str__(self):
                return "custom_object_string"

        test_data = {"obj": CustomObject()}

        atomic_json_save(test_file, test_data)

        assert test_file.exists()
        saved_data = json.loads(test_file.read_text(encoding="utf-8"))
        assert saved_data == {"obj": "custom_object_string"}

    def test_atomic_save_cleans_up_temp_on_write_failure(self, tmp_path):
        """Test that atomic_json_save handles write failure gracefully."""
        test_file = tmp_path / "test.json"
        test_data = {"test": "data"}

        # Patch os.fdopen to simulate write failure after mkstemp
        with patch("os.fdopen", side_effect=IOError("Write failed")):
            with pytest.raises(IOError):
                atomic_json_save(test_file, test_data)

    def test_atomic_save_replace_fails_cleanup(self, tmp_path):
        """Test cleanup when os.replace fails (doesn't corrupt original)."""
        test_file = tmp_path / "test.json"
        original_data = {"original": "data"}

        # Write original file
        test_file.write_text(json.dumps(original_data), encoding="utf-8")

        with patch("os.replace", side_effect=OSError("Replace failed")):
            with pytest.raises(OSError):
                atomic_json_save(test_file, {"new": "data"})

        # Original file should still have original data
        assert json.loads(test_file.read_text(encoding="utf-8")) == original_data

    def test_atomic_save_with_string_path(self, tmp_path):
        """Test that atomic_json_save accepts string paths."""
        test_file = str(tmp_path / "test.json")
        test_data = {"string": "path"}

        atomic_json_save(test_file, test_data)

        assert Path(test_file).exists()
        saved_data = json.loads(Path(test_file).read_text(encoding="utf-8"))
        assert saved_data == test_data

    def test_atomic_save_formatting(self, tmp_path):
        """Test that atomic_json_save produces indented output."""
        test_file = tmp_path / "test.json"
        test_data = {"key": "value", "nested": {"inner": "data"}}

        atomic_json_save(test_file, test_data)

        content = test_file.read_text(encoding="utf-8")
        # Check that it's indented (not minified)
        assert "\n" in content
        assert "  " in content  # 2-space indent


class TestSafeJsonLoad:
    """Tests for safe_json_load function."""

    def test_safe_load_valid_file(self, tmp_path):
        """Test that safe_json_load reads valid JSON files."""
        test_file = tmp_path / "test.json"
        test_data = {"key": "value", "number": 42}
        test_file.write_text(json.dumps(test_data), encoding="utf-8")

        result = safe_json_load(test_file)

        assert result == test_data

    def test_safe_load_missing_file_returns_default(self, tmp_path):
        """Test that safe_json_load returns default for missing file."""
        test_file = tmp_path / "nonexistent.json"
        default = {"default": "value"}

        result = safe_json_load(test_file, default=default)

        assert result == default

    def test_safe_load_missing_file_returns_empty_dict(self, tmp_path):
        """Test that safe_json_load returns {} when file missing and no default."""
        test_file = tmp_path / "nonexistent.json"

        result = safe_json_load(test_file)

        assert result == {}

    def test_safe_load_corrupt_json_returns_default(self, tmp_path):
        """Test that safe_json_load returns default for corrupt JSON."""
        test_file = tmp_path / "corrupt.json"
        test_file.write_text("{ invalid json here", encoding="utf-8")
        default = {"default": "data"}

        result = safe_json_load(test_file, default=default)

        assert result == default

    def test_safe_load_corrupt_json_returns_empty_dict(self, tmp_path):
        """Test that safe_json_load returns {} for corrupt JSON with no default."""
        test_file = tmp_path / "corrupt.json"
        test_file.write_text("{ this is not valid }", encoding="utf-8")

        result = safe_json_load(test_file)

        assert result == {}

    def test_safe_load_empty_file_returns_default(self, tmp_path):
        """Test that safe_json_load returns default for empty file."""
        test_file = tmp_path / "empty.json"
        test_file.write_text("", encoding="utf-8")
        default = {"default": "value"}

        result = safe_json_load(test_file, default=default)

        assert result == default

    def test_safe_load_whitespace_only_returns_default(self, tmp_path):
        """Test that safe_json_load returns default for whitespace-only file."""
        test_file = tmp_path / "whitespace.json"
        test_file.write_text("   \n\t  \n  ", encoding="utf-8")
        default = {"default": "value"}

        result = safe_json_load(test_file, default=default)

        assert result == default

    def test_safe_load_invalid_encoding_returns_default(self, tmp_path):
        """Test that safe_json_load handles invalid encoding gracefully."""
        test_file = tmp_path / "bad_encoding.json"
        # Write some invalid UTF-8 bytes
        test_file.write_bytes(b"\x80\x81\x82\x83")
        default = {"default": "data"}

        result = safe_json_load(test_file, default=default)

        assert result == default

    def test_safe_load_with_string_path(self, tmp_path):
        """Test that safe_json_load accepts string paths."""
        test_file = str(tmp_path / "test.json")
        test_data = {"string": "path"}
        Path(test_file).write_text(json.dumps(test_data), encoding="utf-8")

        result = safe_json_load(test_file)

        assert result == test_data

    def test_safe_load_complex_data(self, tmp_path):
        """Test that safe_json_load handles complex nested structures."""
        test_file = tmp_path / "complex.json"
        test_data = {
            "list": [1, 2, 3],
            "nested": {
                "deep": {
                    "data": ["a", "b", "c"]
                }
            },
            "null": None,
            "bool": True
        }
        test_file.write_text(json.dumps(test_data), encoding="utf-8")

        result = safe_json_load(test_file)

        assert result == test_data

    def test_safe_load_none_default_falls_back_to_empty_dict(self, tmp_path):
        """Test that safe_json_load with default=None falls back to {}."""
        test_file = tmp_path / "nonexistent.json"

        result = safe_json_load(test_file, default=None)

        # When default=None is passed, it returns {} (per implementation)
        assert result == {}

    def test_safe_load_list_default(self, tmp_path):
        """Test that safe_json_load can use non-dict defaults."""
        test_file = tmp_path / "nonexistent.json"
        default = ["default", "list"]

        result = safe_json_load(test_file, default=default)

        assert result == default


class TestIntegration:
    """Integration tests for atomic_json_save and safe_json_load together."""

    def test_roundtrip_save_and_load(self, tmp_path):
        """Test saving and loading data maintains integrity."""
        test_file = tmp_path / "roundtrip.json"
        original_data = {
            "devices": {"device1": {"id": "abc123"}},
            "timestamp": "2026-03-28T00:00:00Z",
            "status": "active"
        }

        atomic_json_save(test_file, original_data)
        loaded_data = safe_json_load(test_file)

        assert loaded_data == original_data

    def test_concurrent_write_simulation(self, tmp_path):
        """Test that atomic write prevents partial file corruption."""
        test_file = tmp_path / "concurrent.json"

        # Write first dataset
        data1 = {"version": 1, "items": list(range(100))}
        atomic_json_save(test_file, data1)

        # Write second dataset (simulates concurrent process)
        data2 = {"version": 2, "items": list(range(200))}
        atomic_json_save(test_file, data2)

        # Load and verify we got complete second dataset, not corrupted mix
        loaded = safe_json_load(test_file)
        assert loaded == data2
        assert "version" in loaded
        assert len(loaded["items"]) == 200

    def test_load_after_atomic_save_encoding(self, tmp_path):
        """Test that atomic save and safe load both use UTF-8."""
        test_file = tmp_path / "encoding.json"
        original_data = {"message": "Hello, 世界! 🌍"}

        atomic_json_save(test_file, original_data)
        loaded_data = safe_json_load(test_file)

        assert loaded_data == original_data
        assert loaded_data["message"] == "Hello, 世界! 🌍"
