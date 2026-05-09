"""Small IO utilities (JSON, JSONL)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterator, List


def load_json(path: str | Path) -> Dict[str, Any]:
    """Load a JSON file as a dict with UTF-8."""
    p = Path(path)
    return json.loads(p.read_text(encoding="utf-8"))


def dump_json(obj: Any, path: str | Path, *, indent: int = 2) -> None:
    """Write JSON with UTF-8 and stable formatting."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=indent), encoding="utf-8")


def load_jsonl(path: str | Path) -> List[Dict[str, Any]]:
    """Load a JSONL file into a list of dicts."""
    p = Path(path)
    out: List[Dict[str, Any]] = []
    for line_no, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSONL at {p}:{line_no}: {e}") from e
    return out


def iter_jsonl(path: str | Path) -> Iterator[Dict[str, Any]]:
    """Stream JSONL objects."""
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSONL at {p}:{line_no}: {e}") from e


def write_json(path: str | Path, obj: Any, *, indent: int = 2) -> None:
    """Alias for dump_json (preferred name in reports tooling)."""
    dump_json(obj, path, indent=indent)


def write_jsonl(path: str | Path, records: List[Dict[str, Any]]) -> None:
    """Write records as JSONL (UTF-8)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps(r, ensure_ascii=False) for r in records]
    p.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
