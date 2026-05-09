"""JSON Schema validation helpers (Draft 2020-12)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict

import jsonschema


@lru_cache(maxsize=32)
def load_schema(schema_path: str | Path) -> Dict[str, Any]:
    """Load JSON schema from disk (cached)."""
    p = Path(schema_path)
    return json.loads(p.read_text(encoding="utf-8"))


def validate_with_schema(instance: Any, schema: Dict[str, Any]) -> None:
    """Validate *instance* against schema dict (raises jsonschema.ValidationError)."""
    jsonschema.Draft202012Validator(schema).validate(instance)


def validate_with_schema_path(instance: Any, schema_path: str | Path) -> None:
    """Validate instance against schema loaded from *schema_path*."""
    validate_with_schema(instance, load_schema(schema_path))
