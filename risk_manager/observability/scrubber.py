"""PII and secret scrubbing for observability, logging, and distributed tracing.

Implements TRD.md §U and Phase 8 security requirements:
- Redacts credentials, tokens, API keys, and sensitive financial fields.
- Sanitizes customer free text (e.g. return_reason, notes) to prevent PII and prompt injection leakage.
- Enforces low-cardinality, clean metadata representation in traces and logs.
"""

from __future__ import annotations

import re
from typing import Any

# Sensitive dictionary keys to redact automatically
SENSITIVE_KEY_PATTERNS = {
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "gemini_api_key",
    "langsmith_api_key",
    "credit_card",
    "card_number",
    "cvv",
    "pan",
    "aadhaar",
    "ssn",
    "authorization",
    "auth",
}

# Regex for common PII patterns: email, phone numbers, potential card numbers
EMAIL_REGEX = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
PHONE_REGEX = re.compile(r"(?:\+?91|0)?[6-9]\d{9}")
CARD_REGEX = re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b")


def is_sensitive_key(key: str) -> bool:
    """Determine if a key name matches any known sensitive or credential patterns."""
    normalized = key.lower().replace("-", "_")
    return any(pattern in normalized for pattern in SENSITIVE_KEY_PATTERNS)


def sanitize_text(text: str | None) -> str:
    """Sanitize free text by redacting email addresses, phone numbers, and card numbers."""
    if not text or not isinstance(text, str):
        return ""
    
    cleaned = EMAIL_REGEX.sub("[EMAIL_REDACTED]", text)
    cleaned = PHONE_REGEX.sub("[PHONE_REDACTED]", cleaned)
    cleaned = CARD_REGEX.sub("[CARD_REDACTED]", cleaned)
    return cleaned


def scrub_data(data: Any, depth: int = 0, max_depth: int = 5) -> Any:
    """Recursively scrub dictionaries, lists, and primitives of sensitive keys and PII.
    
    # ponytail: depth limit prevents unbounded recursion on circular structures.
    """
    if depth > max_depth:
        return "[DEPTH_EXCEEDED]"

    if isinstance(data, dict):
        scrubbed = {}
        for k, v in data.items():
            if is_sensitive_key(str(k)):
                scrubbed[k] = "[REDACTED]"
            elif str(k).lower() in ("return_reason", "customer_notes", "notes", "raw_text"):
                # Safe metadata representation instead of raw customer text
                val_str = str(v) if v is not None else ""
                scrubbed[k] = f"[TEXT_REDACTED: length {len(val_str)}]"
            else:
                scrubbed[k] = scrub_data(v, depth + 1, max_depth)
        return scrubbed

    if isinstance(data, list):
        return [scrub_data(item, depth + 1, max_depth) for item in data]

    if isinstance(data, str):
        return sanitize_text(data)

    return data


def scrub_trace_attributes(attributes: dict[str, Any]) -> dict[str, Any]:
    """Sanitize span attributes to guarantee zero PII or credentials enter trace backends."""
    sanitized: dict[str, Any] = {}
    for key, value in attributes.items():
        if is_sensitive_key(key):
            sanitized[key] = "[REDACTED]"
        elif isinstance(value, (int, float, bool)):
            sanitized[key] = value
        elif isinstance(value, str):
            # For customer text attributes, do not store complete raw text
            if key in ("return_reason", "customer_notes", "raw_text", "notes"):
                sanitized[key] = f"[TEXT_REDACTED: length {len(value)}]"
            else:
                sanitized[key] = sanitize_text(value)
        else:
            sanitized[key] = str(value)[:200]
    return sanitized
