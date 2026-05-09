"""Text normalization utilities.

Goal: keep deterministic matching consistent across parser/validator while allowing
different punctuation handling modes.

- Parser prefers punctuation->spaces (keeps '%' and '-') to support substring matching.
- Validator prefers punctuation stripping (to build synonym indices robustly).

This module is intentionally lightweight (no external deps, no heavy NLP).
"""

from __future__ import annotations

import re
from typing import Optional

# Parser-compatible default: keep word chars, spaces, '%' and '-'
_DEFAULT_SPACE_PUNCT_RE = re.compile(r"[^\w\s%-]+", re.UNICODE)

# Validator-compatible default: keep letters/digits/spaces only
_DEFAULT_STRIP_PUNCT_RE = re.compile(r"[^0-9a-zA-Zа-яА-Я\s]", re.UNICODE)

_SPACES_RE = re.compile(r"\s+", re.UNICODE)


def normalize_text(
    text: str,
    *,
    trim: bool = True,
    lowercase: bool = True,
    collapse_spaces: bool = True,
    yo_to_e: bool = True,
    punctuation_mode: str = "strip",  # "strip" | "space" | "keep"
    space_punct_re: Optional[re.Pattern] = None,
    strip_punct_re: Optional[re.Pattern] = None,
) -> str:
    """Normalize text deterministically.

    Args:
        text: input string
        trim: strip whitespace at edges
        lowercase: lower-case
        collapse_spaces: collapse runs of whitespace
        yo_to_e: replace 'ё' with 'е'
        punctuation_mode:
            - "strip": remove punctuation
            - "space": replace punctuation with spaces (parser-friendly)
            - "keep": do not change punctuation
        space_punct_re: regex used when punctuation_mode="space"
        strip_punct_re: regex used when punctuation_mode="strip"

    Returns:
        Normalized string.
    """
    out = text

    if trim:
        out = out.strip()
    if lowercase:
        out = out.lower()
    if yo_to_e:
        out = out.replace("ё", "е")

    if punctuation_mode == "strip":
        rx = strip_punct_re or _DEFAULT_STRIP_PUNCT_RE
        out = rx.sub("", out)
    elif punctuation_mode == "space":
        rx = space_punct_re or _DEFAULT_SPACE_PUNCT_RE
        out = rx.sub(" ", out)
    elif punctuation_mode == "keep":
        pass
    else:
        raise ValueError(f"Unsupported punctuation_mode: {punctuation_mode}")

    if collapse_spaces:
        out = _SPACES_RE.sub(" ", out).strip()

    return out
