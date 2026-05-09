"""Privacy helpers.

Core principles for this project:
- Default: do not persist raw audio.
- Avoid storing raw user utterances in logs.
- If logging is required for debugging/evaluation, redact by policy.

This module provides deterministic redaction utilities (no external dependencies).
"""

from __future__ import annotations

import re
from typing import Any, Dict, Optional

_EMAIL_RE = re.compile(r"\b[\w.%-]+@[\w.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\+?\d[\d\s().-]{7,}\d")
_NUMBER_RE = re.compile(r"\b\d{1,6}\b")


def redact_text(text: str, *, mode: str = "minimal") -> str:
    """Redact potentially sensitive fragments from text.

    Args:
        text: input
        mode:
            - "minimal": redact emails/phones, keep other info
            - "strict": also redact standalone numbers (e.g. brightness/percentages)

    Returns:
        Redacted string.
    """
    out = _EMAIL_RE.sub("<EMAIL>", text)
    out = _PHONE_RE.sub("<PHONE>", out)
    if mode == "strict":
        out = _NUMBER_RE.sub("<NUM>", out)
    return out


def should_log_raw_text(device_registry: Dict[str, Any]) -> bool:
    """Policy gate: whether raw user text is allowed to be logged."""
    privacy = device_registry.get("privacy", {})
    return bool(privacy.get("allow_raw_text_logging", False))


def get_redaction_mode(device_registry: Dict[str, Any]) -> str:
    privacy = device_registry.get("privacy", {})
    return str(privacy.get("log_redaction_mode", "minimal"))
