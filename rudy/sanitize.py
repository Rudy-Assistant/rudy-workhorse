"""
Shared input sanitization utilities for the Batcave.

Used by: robin_taskqueue.py, robin_alfred_protocol.py,
         batcave_memory.py (and future modules).

Canonical location — do NOT duplicate these functions.
"""
import re

# Allowlist patterns
_SAFE_CHARS = re.compile(r'[^a-zA-Z0-9 _\-\./:\\\n\(\)\[\],\'"]')
_SAFE_URL_CHARS = re.compile(
    r'[^a-zA-Z0-9 _\-\./:\\\n\(\)\[\],\'\\"?=&#%+@~]'
)

# Limits
MAX_PAYLOAD_SIZE = 50_000  # 50KB max per message/payload
MAX_MESSAGE_AGE_HOURS = 72  # Messages expire after 3 days


def sanitize_str(
    value: str,
    max_length: int = 500,
    url_mode: bool = False,
) -> str:
    """
    Sanitize a string by stripping unsafe characters.

    Args:
        value: Input string to sanitize.
        max_length: Maximum length of the returned string.
        url_mode: If True, allow URL-safe chars (?=&#%+@~).

    Returns:
        Sanitized, truncated string.
    """
    if not isinstance(value, str):
        return str(value)[:max_length]
    pattern = _SAFE_URL_CHARS if url_mode else _SAFE_CHARS
    cleaned = pattern.sub('', value)
    return cleaned[:max_length]


def validate_payload(payload: dict, max_size: int = MAX_PAYLOAD_SIZE) -> dict:
    """
    Validate a dict payload for safe storage/transmission.

    Raises ValueError if payload is not a dict or exceeds max_size.
    """
    import json
    if not isinstance(payload, dict):
        raise ValueError("Payload must be a dict")
    raw = json.dumps(payload)
    if len(raw) > max_size:
        raise ValueError(
            f"Payload too large: {len(raw)} > {max_size}"
        )
    return payload
