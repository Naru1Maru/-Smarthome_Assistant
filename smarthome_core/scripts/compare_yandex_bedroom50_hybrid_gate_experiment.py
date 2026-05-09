from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any, Dict

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json, load_jsonl
from smarthome_core.llm_client import OpenAICompatibleClient
from smarthome_core.parse_dispatch import _normalize_match_text, _semantic_dimensions, _should_accept_rules
from smarthome_core.parser import parse_light_command_v1
from smarthome_core.parser_llm import parse_light_command_llm_v1
from smarthome_core.schema_utils import load_schema
from smarthome_core.validator import validate_parsed_command

from compare_yandex_bedroom50 import (
    _extract_primary,
    _load_yandex_rows,
    _semantic_score,
    _summarize,
    _tag_value,
    _yandex_ok,
)


_SOFT_OFF_RE = re.compile(
    r"\b("
    r"без\s+света|"
    r"хватит\s+света|"
    r"убери\s+(?:его|свет)|"
    r"выключайся|"
    r"выключай|"
    r"оставь\s+(?:тут|здесь|спальню)?\s*темноту"
    r")\b",
    flags=re.UNICODE,
)

_SOFT_DIM_RE = re.compile(
    r"\b("
    r"поспокойнее|"
    r"помягче|"
    r"потише|"
    r"приглуш|"
    r"неярк|"
    r"спокойн"
    r")\w*\b",
    flags=re.UNICODE,
)

_MOOD_SCENE_RE = re.compile(
    r"\b("
    r"уют|"
    r"уютн|"
    r"вечерн|"
    r"перед\s+сном|"
    r"сон|"
    r"отдых|"
    r"фильм|"
    r"расслаб"
    r")\w*\b",
    flags=re.UNICODE,
)

_BRIGHTEN_RE = re.compile(
    r"\b("
    r"больше\s+света|"
    r"добавь\s+света|"
    r"прибавь\s+свет|"
    r"посветлее"
    r")\b",
    flags=re.UNICODE,
)


def _primary_intent(parsed: Dict[str, Any]) -> str:
    actions = parsed.get("actions") or []
    if not actions:
        return ""
    return str(actions[0].get("intent") or "").upper()


def _should_accept_rules_experimental(
    text: str,
    parsed: Dict[str, Any],
    *,
    colors: Dict[str, Any],
    scene_aliases: Dict[str, Any],
) -> bool:
    if not _should_accept_rules(text, parsed, colors=colors, scene_aliases=scene_aliases):
        return False

    norm_text = _normalize_match_text(text)
    actions = parsed.get("actions") or []
    dims = _semantic_dimensions(actions)
    intent = _primary_intent(parsed)

    # These free-form commands are often parsed by rules as generic TURN_ON/CANCEL,
    # while the intended effect is closer to TURN_OFF or dim/scene control.
    if _SOFT_OFF_RE.search(norm_text) and intent != "TURN_OFF":
        return False

    if _SOFT_DIM_RE.search(norm_text) and "brightness" not in dims:
        return False

    if _BRIGHTEN_RE.search(norm_text) and "brightness" not in dims:
        return False

    if _MOOD_SCENE_RE.search(norm_text) and len(dims) < 2:
        return False

    return True


def _run_experimental_mode(
    *,
    rec: Dict[str, Any],
    parsed_schema: Dict[str, Any],
    llm_client: OpenAICompatibleClient,
    device_registry: Dict[str, Any],
    area_synonyms: Dict[str, Any],
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
    scene_aliases: Dict[str, Any],
) -> Dict[str, Any]:
    parsed_rules = parse_light_command_v1(
        rec["text"],
        context=rec.get("context") or {"last_area_name": None},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
    )
    gate_source = "rules"
    parsed = parsed_rules
    if not _should_accept_rules_experimental(
        rec["text"],
        parsed_rules,
        colors=colors,
        scene_aliases=scene_aliases,
    ):
        gate_source = "llm"
        parsed = parse_light_command_llm_v1(
            rec["text"],
            context=rec.get("context") or {"last_area_name": None},
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
            scene_aliases=scene_aliases,
            parsed_schema=parsed_schema,
            client=llm_client,
            fallback_to_rules=False,
            semantic_rescue=False,
            prompt_profile="universal",
        )

    validated = None
    if not parsed.get("clarification"):
        validated = validate_parsed_command(
            parsed,
            context=rec.get("context") or {"last_area_name": None},
            device_registry=device_registry,
            area_synonyms=area_synonyms,
        )

    info = _extract_primary(parsed, validated)
    expected = _tag_value(rec.get("tags") or [], "intent:") or "UNKNOWN"
    score, reason = _semantic_score(expected, info)
    info["semantic_score"] = score
    info["semantic_reason"] = reason
    info["semantic_ok"] = score >= 1
    info["semantic_strong"] = score >= 2
    info["gate_source"] = gate_source
    return info


def _rate(rows: list[Dict[str, Any]], field: str) -> str:
    if not rows:
        return "0/0 (0.0%)"
    ok = sum(1 for row in rows if _truthy(row.get(field)))
    return f"{ok}/{len(rows)} ({ok / len(rows) * 100:.1f}%)"


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "ok", "да", "ок"}
    return bool(value)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=str, default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--dataset", type=str, default="data/light_yandex_compare_bedroom_creative50_ru_v1.jsonl")
    parser.add_argument("--baseline-csv", type=str, default="reports/yandex_compare_bedroom50_qwen3_8b.csv")
    parser.add_argument("--yandex-csv", type=str, required=True)
    parser.add_argument("--base-url", type=str, default="http://127.0.0.1:8000")
    parser.add_argument("--model", type=str, default="qwen3:8b")
    parser.add_argument("--out-csv", type=str, default="reports/yandex_compare_bedroom50_qwen3_8b_gate_exp.csv")
    parser.add_argument("--out-md", type=str, default="reports/yandex_compare_bedroom50_qwen3_8b_gate_exp.md")
    args = parser.parse_args()

    root = Path(args.root)
    paths = AssetPaths(root)
    dataset_path = root / args.dataset
    baseline_csv = root / args.baseline_csv
    out_csv = root / args.out_csv
    out_md = root / args.out_md

    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)
    parsed_schema = load_schema(paths.parsed_schema)
    llm_client = OpenAICompatibleClient(base_url=args.base_url, api_key=None, model=args.model, timeout_s=180)

    records = load_jsonl(dataset_path)
    yandex_rows = _load_yandex_rows(Path(args.yandex_csv))
    baseline_by_id: Dict[str, Dict[str, str]] = {}
    if baseline_csv.exists():
        with baseline_csv.open("r", encoding="utf-8", newline="") as f:
            baseline_by_id = {row["id"]: row for row in csv.DictReader(f)}

    merged_rows: list[Dict[str, Any]] = []
    for rec in records:
        rid = rec["id"]
        tags = rec.get("tags") or []
        room_ref = _tag_value(tags, "room_ref:") or ""
        expected_intent = _tag_value(tags, "intent:") or ""
        yrow = yandex_rows.get(rid, {})
        baseline = baseline_by_id.get(rid, {})

        exp_info = _run_experimental_mode(
            rec=rec,
            parsed_schema=parsed_schema,
            llm_client=llm_client,
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
            scene_aliases=scene_aliases,
        )

        merged_rows.append(
            {
                "id": rid,
                "text": rec["text"],
                "room_ref": room_ref,
                "expected_intent": expected_intent,
                "yandex_ok": _yandex_ok(yrow.get("yandex_executed", "")),
                "llm_semantic_strong": baseline.get("llm_semantic_strong", ""),
                "llm_safe_semantic_strong": baseline.get("llm_safe_semantic_strong", ""),
                "llm_safe_exp_status": exp_info["status"],
                "llm_safe_exp_intent": exp_info["norm_intent"] or exp_info["parsed_intent"],
                "llm_safe_exp_area": exp_info["norm_area"] or exp_info["parsed_area"] or exp_info["plan_area"],
                "llm_safe_exp_brightness_pct": exp_info["brightness_pct"],
                "llm_safe_exp_brightness_delta_pct": exp_info["brightness_delta_pct"],
                "llm_safe_exp_color_temp_kelvin": exp_info["color_temp_kelvin"],
                "llm_safe_exp_color_temp_delta_k": exp_info["color_temp_delta_k"],
                "llm_safe_exp_clarification": exp_info["clarification_needed"],
                "llm_safe_exp_gate_source": exp_info["gate_source"],
                "llm_safe_exp_semantic_score": exp_info["semantic_score"],
                "llm_safe_exp_semantic_ok": exp_info["semantic_ok"],
                "llm_safe_exp_semantic_strong": exp_info["semantic_strong"],
                "llm_safe_exp_semantic_reason": exp_info["semantic_reason"],
            }
        )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(merged_rows[0].keys()))
        writer.writeheader()
        writer.writerows(merged_rows)

    explicit = [row for row in merged_rows if row["room_ref"] == "explicit"]
    implicit = [row for row in merged_rows if row["room_ref"] == "implicit"]
    exp_summary = _summarize(merged_rows, "llm_safe_exp")
    gate_rules = sum(1 for row in merged_rows if row["llm_safe_exp_gate_source"] == "rules")
    gate_llm = sum(1 for row in merged_rows if row["llm_safe_exp_gate_source"] == "llm")

    md = f"""# Hybrid Gate Experiment: Bedroom Creative 50

- dataset: `{dataset_path}`
- model: `{args.model}`
- base_url: `{args.base_url}`
- rows: {len(merged_rows)}
- experimental mode: `llm_safe_gate_exp`

## Summary

| System / Metric | Overall | Explicit room | Implicit room |
|---|---:|---:|---:|
| Yandex `ok` | {_rate(merged_rows, "yandex_ok")} | {_rate(explicit, "yandex_ok")} | {_rate(implicit, "yandex_ok")} |
| App `llm` strong semantic match | {_rate(merged_rows, "llm_semantic_strong")} | {_rate(explicit, "llm_semantic_strong")} | {_rate(implicit, "llm_semantic_strong")} |
| App `llm_safe` strong semantic match | {_rate(merged_rows, "llm_safe_semantic_strong")} | {_rate(explicit, "llm_safe_semantic_strong")} | {_rate(implicit, "llm_safe_semantic_strong")} |
| App `llm_safe_gate_exp` strong semantic match | {exp_summary["total_strong"]} | {exp_summary["explicit_strong"]} | {exp_summary["implicit_strong"]} |
| App `llm_safe_gate_exp` usable semantic match | {exp_summary["total_usable"]} | - | - |

## Gate Routing

| Route | Count |
|---|---:|
| rules accepted | {gate_rules} |
| sent to LLM | {gate_llm} |

## Notes

- The production `llm_safe` mode was not changed.
- The experimental gate rejects rules results for soft-off phrases, dimming phrases without brightness parameters, brighten phrases without brightness parameters, and mood/scene phrases without at least two semantic dimensions.
- Full per-phrase comparison is stored in `{out_csv}`.
"""
    out_md.write_text(md, encoding="utf-8")
    print(f"Wrote {out_csv}")
    print(f"Wrote {out_md}")


if __name__ == "__main__":
    main()
