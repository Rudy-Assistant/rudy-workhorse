"""
Tests for rudy.sanitize — shared sanitization utilities.
"""
import sys
import os
import pytest

# Ensure repo root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from rudy.sanitize import (
    sanitize_str,
    validate_payload,
    MAX_PAYLOAD_SIZE,
    MAX_MESSAGE_AGE_HOURS,
)


# ── sanitize_str ─────────────────────────────────────────

class TestSanitizeStr:
    def test_passthrough_safe_string(self):
        assert sanitize_str("hello world") == "hello world"

    def test_strips_unsafe_chars(self):
        assert sanitize_str("hello<script>alert(1)</script>") == "helloscriptalert(1)/script"

    def test_max_length_truncation(self):
        long = "a" * 1000
        result = sanitize_str(long, max_length=50)
        assert len(result) == 50

    def test_default_max_length_is_500(self):
        long = "a" * 600
        assert len(sanitize_str(long)) == 500

    def test_non_string_input(self):
        assert sanitize_str(12345) == "12345"
        assert sanitize_str(None) == "None"

    def test_url_mode_allows_special_chars(self):
        url = "https://example.com/path?q=hello&page=2#top"
        result = sanitize_str(url, max_length=200, url_mode=True)
        assert "?" in result
        assert "&" in result
        assert "#" in result

    def test_normal_mode_strips_url_chars(self):
        url = "https://example.com/path?q=hello"
        result = sanitize_str(url, max_length=200, url_mode=False)
        assert "?" not in result
    def test_preserves_paths(self):
        path = r"C:\Users\test\file.txt"
        assert sanitize_str(path, max_length=200) == path

    def test_preserves_brackets_parens(self):
        s = "task[0] (important)"
        assert sanitize_str(s) == s

    def test_empty_string(self):
        assert sanitize_str("") == ""

    def test_newlines_preserved(self):
        s = "line1\nline2\nline3"
        assert sanitize_str(s) == s


# ── validate_payload ─────────────────────────────────────

class TestValidatePayload:
    def test_valid_dict(self):
        d = {"key": "value", "count": 42}
        assert validate_payload(d) == d

    def test_rejects_non_dict(self):
        with pytest.raises(ValueError, match="must be a dict"):
            validate_payload("not a dict")
        with pytest.raises(ValueError, match="must be a dict"):
            validate_payload([1, 2, 3])
    def test_rejects_oversized_payload(self):
        big = {"data": "x" * (MAX_PAYLOAD_SIZE + 1)}
        with pytest.raises(ValueError, match="too large"):
            validate_payload(big)

    def test_custom_max_size(self):
        d = {"data": "x" * 100}
        with pytest.raises(ValueError, match="too large"):
            validate_payload(d, max_size=10)

    def test_empty_dict(self):
        assert validate_payload({}) == {}

    def test_nested_dict(self):
        d = {"a": {"b": {"c": [1, 2, 3]}}}
        assert validate_payload(d) == d


# ── Constants ────────────────────────────────────────────

class TestConstants:
    def test_max_payload_size(self):
        assert MAX_PAYLOAD_SIZE == 50_000

    def test_max_message_age_hours(self):
        assert MAX_MESSAGE_AGE_HOURS == 72


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
