from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json, load_jsonl
from smarthome_core.llm_client import OpenAICompatibleClient
from smarthome_core.parse_dispatch import parse_light_command_v1_dispatch
from smarthome_core.schema_utils import load_schema
from smarthome_core.validator import validate_parsed_command


def _tag_value(tags: Iterable[str], prefix: str) -> Optional[str]:
    for tag in tags:
        if isinstance(tag, str) and tag.startswith(prefix):
            return tag[len(prefix) :]
    return None


def _normalize_yandex_value(value: str) -> str:
    return (value or "").strip().lower()


def _yandex_ok(value: str) -> bool:
    return _normalize_yandex_value(value) in {"ok", "ок", "yes", "true", "1", "да"}


def _extract_primary(parsed: Dict[str, Any], validated: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    parsed_actions = parsed.get("actions") or []
    parsed_action = parsed_actions[0] if parsed_actions else {}

    normalized = ((validated or {}).get("normalized") or {}).get("actions") or []
    norm_action = normalized[0] if normalized else {}
    norm_params = norm_action.get("params") or {}
    norm_target = norm_action.get("target") or {}

    plan = ((validated or {}).get("execution_plan") or [])
    plan0 = plan[0] if plan else {}
    plan_data = plan0.get("data") or {}
    plan_target = plan0.get("target") or {}

    return {
        "parsed_intent": parsed_action.get("intent"),
        "parsed_area": (parsed_action.get("target") or {}).get("area_name"),
        "status": (validated or {}).get("status"),
        "reason_code": (validated or {}).get("reason_code"),
        "norm_intent": norm_action.get("intent"),
        "norm_area": norm_target.get("area_name"),
        "service": plan0.get("service"),
        "plan_area": plan_target.get("area_name"),
        "brightness_pct": norm_params.get("brightness_pct"),
        "brightness_delta_pct": norm_params.get("brightness_delta_pct"),
        "color_temp_kelvin": norm_params.get("color_temp_kelvin"),
        "color_temp_delta_k": norm_params.get("color_temp_delta_k"),
        "rgb_color": norm_params.get("rgb_color"),
        "transition_s": norm_params.get("transition_s"),
        "clarification_needed": bool(parsed.get("clarification")),
        "clarification_question": (parsed.get("clarification") or {}).get("question"),
        "plan_data": json.dumps(plan_data, ensure_ascii=False),
    }


def _semantic_score(expected: str, info: Dict[str, Any]) -> tuple[int, str]:
    if info["clarification_needed"]:
        return 0, "clarification"
    if info["status"] != "EXECUTABLE":
        return 0, f"status={info['status'] or 'none'}"

    intent = (info["norm_intent"] or info["parsed_intent"] or "").upper()
    area = info["norm_area"] or info["parsed_area"] or info["plan_area"]
    bp = info["brightness_pct"]
    bd = info["brightness_delta_pct"]
    ctk = info["color_temp_kelvin"]
    cdk = info["color_temp_delta_k"]

    if area != "Спальня":
        return 0, f"wrong_area={area}"

    if expected == "TURN_ON":
        if intent in {"TURN_ON", "SET_BRIGHTNESS", "SET_COLOR_TEMP", "SET_COLOR"}:
            return 2, "turn_on_family"
        if intent == "ADJUST_BRIGHTNESS" and (bd is None or (isinstance(bd, (int, float)) and bd > 0)):
            return 2, "turn_on_via_brightness_up"
        return 0, f"wrong_intent={intent}"

    if expected == "TURN_OFF":
        if intent == "TURN_OFF":
            return 2, "turn_off"
        return 0, f"wrong_intent={intent}"

    if expected == "ADJUST_BRIGHTNESS_UP":
        if isinstance(bd, (int, float)) and bd > 0:
            return 2, "brightness_delta_up"
        if isinstance(bp, (int, float)) and bp >= 60:
            return 2, "brightness_abs_high"
        if intent in {"TURN_ON", "SET_BRIGHTNESS", "ADJUST_BRIGHTNESS"}:
            return 1, "brightness_partial"
        return 0, f"wrong_intent={intent}"

    if expected == "ADJUST_BRIGHTNESS_DOWN":
        if isinstance(bd, (int, float)) and bd < 0:
            return 2, "brightness_delta_down"
        if isinstance(bp, (int, float)) and bp <= 50:
            return 2, "brightness_abs_low"
        if intent in {"TURN_ON", "SET_BRIGHTNESS", "ADJUST_BRIGHTNESS"}:
            return 1, "brightness_partial"
        return 0, f"wrong_intent={intent}"

    if expected == "SET_COLOR_TEMP_WARM":
        if isinstance(ctk, (int, float)) and ctk <= 3500:
            return 2, "warm_abs"
        if isinstance(cdk, (int, float)) and cdk < 0:
            return 2, "warm_delta"
        if intent in {"TURN_ON", "SET_COLOR_TEMP", "ADJUST_COLOR_TEMP"}:
            return 1, "warm_partial"
        return 0, f"wrong_intent={intent}"

    if expected == "ADJUST_COLOR_TEMP_COOLER":
        if isinstance(cdk, (int, float)) and cdk > 0:
            return 2, "cooler_delta"
        if isinstance(ctk, (int, float)) and ctk >= 4000:
            return 2, "cooler_abs"
        if intent in {"TURN_ON", "SET_COLOR_TEMP", "ADJUST_COLOR_TEMP"}:
            return 1, "cooler_partial"
        return 0, f"wrong_intent={intent}"

    if expected == "COZY_SCENE":
        warm = (isinstance(ctk, (int, float)) and ctk <= 3300) or (isinstance(cdk, (int, float)) and cdk < 0)
        dim = (isinstance(bp, (int, float)) and bp <= 55) or (isinstance(bd, (int, float)) and bd < 0)
        if warm and dim:
            return 2, "cozy_strong"
        if warm or dim:
            return 1, "cozy_partial"
        return 0, "cozy_missed"

    if expected == "BEDTIME_SCENE":
        warm = (isinstance(ctk, (int, float)) and ctk <= 3000) or (isinstance(cdk, (int, float)) and cdk < 0)
        dim = (isinstance(bp, (int, float)) and bp <= 40) or (isinstance(bd, (int, float)) and bd < 0)
        if warm and dim:
            return 2, "bedtime_strong"
        if warm or dim:
            return 1, "bedtime_partial"
        return 0, "bedtime_missed"

    if expected == "READING_SCENE":
        if isinstance(bp, (int, float)) and bp >= 60:
            return 2, "reading_bright"
        if intent in {"TURN_ON", "SET_BRIGHTNESS", "ADJUST_BRIGHTNESS"}:
            return 1, "reading_partial"
        return 0, f"wrong_intent={intent}"

    return 0, "unknown_expected"


def _run_mode(
    *,
    rec: Dict[str, Any],
    mode: str,
    parsed_schema: Dict[str, Any],
    llm_client: OpenAICompatibleClient,
    device_registry: Dict[str, Any],
    area_synonyms: Dict[str, Any],
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
    scene_aliases: Dict[str, Any],
) -> Dict[str, Any]:
    parsed = parse_light_command_v1_dispatch(
        rec["text"],
        parser_mode=mode,
        context=rec.get("context") or {"last_area_name": None},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
        parsed_schema=parsed_schema,
        llm_client=llm_client,
        llm_prompt_profile="universal",
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
    return info


def _load_yandex_rows(path: Path) -> Dict[str, Dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    out: Dict[str, Dict[str, str]] = {}
    for row in rows:
        rid = (row.get("id") or "").strip()
        if rid.startswith("YB"):
            out[rid] = row
    return out


def _summarize(rows: list[Dict[str, Any]], mode_prefix: str) -> Dict[str, Any]:
    total = len(rows)
    explicit = [r for r in rows if r["room_ref"] == "explicit"]
    implicit = [r for r in rows if r["room_ref"] == "implicit"]

    def _rate(items: list[Dict[str, Any]], field: str) -> str:
        if not items:
            return "0/0 (0.0%)"
        ok = sum(1 for r in items if r[field])
        return f"{ok}/{len(items)} ({ok / len(items) * 100:.1f}%)"

    return {
        "total_strong": _rate(rows, f"{mode_prefix}_semantic_strong"),
        "total_usable": _rate(rows, f"{mode_prefix}_semantic_ok"),
        "explicit_strong": _rate(explicit, f"{mode_prefix}_semantic_strong"),
        "implicit_strong": _rate(implicit, f"{mode_prefix}_semantic_strong"),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=str, default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--dataset", type=str, default="data/light_yandex_compare_bedroom_creative50_ru_v1.jsonl")
    parser.add_argument("--yandex-csv", type=str, required=True)
    parser.add_argument("--base-url", type=str, default="http://127.0.0.1:8000")
    parser.add_argument("--model", type=str, default="qwen3:8b")
    parser.add_argument("--out-csv", type=str, default="reports/yandex_compare_bedroom50_qwen3_8b.csv")
    parser.add_argument("--out-md", type=str, default="reports/yandex_compare_bedroom50_qwen3_8b.md")
    args = parser.parse_args()

    root = Path(args.root)
    dataset_path = root / args.dataset
    out_csv = root / args.out_csv
    out_md = root / args.out_md

    paths = AssetPaths(root)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)
    parsed_schema = load_schema(paths.parsed_schema)

    llm_client = OpenAICompatibleClient(base_url=args.base_url, api_key=None, model=args.model, timeout_s=180)
    records = load_jsonl(dataset_path)
    yandex_rows = _load_yandex_rows(Path(args.yandex_csv))

    merged_rows: list[Dict[str, Any]] = []
    for rec in records:
        rid = rec["id"]
        tags = rec.get("tags") or []
        room_ref = _tag_value(tags, "room_ref:") or ""
        expected_intent = _tag_value(tags, "intent:") or ""
        yrow = yandex_rows.get(rid, {})

        llm_info = _run_mode(
            rec=rec,
            mode="llm",
            parsed_schema=parsed_schema,
            llm_client=llm_client,
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
            scene_aliases=scene_aliases,
        )
        llm_safe_info = _run_mode(
            rec=rec,
            mode="llm_safe",
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
                "yandex_executed_raw": yrow.get("yandex_executed", ""),
                "yandex_ok": _yandex_ok(yrow.get("yandex_executed", "")),
                "yandex_notes": yrow.get("notes", ""),
                "llm_status": llm_info["status"],
                "llm_intent": llm_info["norm_intent"] or llm_info["parsed_intent"],
                "llm_area": llm_info["norm_area"] or llm_info["parsed_area"] or llm_info["plan_area"],
                "llm_service": llm_info["service"],
                "llm_brightness_pct": llm_info["brightness_pct"],
                "llm_brightness_delta_pct": llm_info["brightness_delta_pct"],
                "llm_color_temp_kelvin": llm_info["color_temp_kelvin"],
                "llm_color_temp_delta_k": llm_info["color_temp_delta_k"],
                "llm_clarification": llm_info["clarification_needed"],
                "llm_semantic_score": llm_info["semantic_score"],
                "llm_semantic_ok": llm_info["semantic_ok"],
                "llm_semantic_strong": llm_info["semantic_strong"],
                "llm_semantic_reason": llm_info["semantic_reason"],
                "llm_safe_status": llm_safe_info["status"],
                "llm_safe_intent": llm_safe_info["norm_intent"] or llm_safe_info["parsed_intent"],
                "llm_safe_area": llm_safe_info["norm_area"] or llm_safe_info["parsed_area"] or llm_safe_info["plan_area"],
                "llm_safe_service": llm_safe_info["service"],
                "llm_safe_brightness_pct": llm_safe_info["brightness_pct"],
                "llm_safe_brightness_delta_pct": llm_safe_info["brightness_delta_pct"],
                "llm_safe_color_temp_kelvin": llm_safe_info["color_temp_kelvin"],
                "llm_safe_color_temp_delta_k": llm_safe_info["color_temp_delta_k"],
                "llm_safe_clarification": llm_safe_info["clarification_needed"],
                "llm_safe_semantic_score": llm_safe_info["semantic_score"],
                "llm_safe_semantic_ok": llm_safe_info["semantic_ok"],
                "llm_safe_semantic_strong": llm_safe_info["semantic_strong"],
                "llm_safe_semantic_reason": llm_safe_info["semantic_reason"],
            }
        )

    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(merged_rows[0].keys()))
        writer.writeheader()
        writer.writerows(merged_rows)

    yandex_total = sum(1 for r in merged_rows if r["yandex_ok"])
    explicit = [r for r in merged_rows if r["room_ref"] == "explicit"]
    implicit = [r for r in merged_rows if r["room_ref"] == "implicit"]
    llm_summary = _summarize(merged_rows, "llm")
    llm_safe_summary = _summarize(merged_rows, "llm_safe")

    md = f"""# Yandex vs App Bedroom Creative 50

- dataset: `{dataset_path}`
- yandex manual csv: `{args.yandex_csv}`
- model: `{args.model}`
- base_url: `{args.base_url}`
- rows: {len(merged_rows)}

## Summary

| System / Metric | Overall | Explicit room | Implicit room |
|---|---:|---:|---:|
| Yandex `ok` | {yandex_total}/{len(merged_rows)} ({yandex_total / len(merged_rows) * 100:.1f}%) | {sum(1 for r in explicit if r["yandex_ok"])}/{len(explicit)} ({sum(1 for r in explicit if r["yandex_ok"]) / len(explicit) * 100:.1f}%) | {sum(1 for r in implicit if r["yandex_ok"])}/{len(implicit)} ({sum(1 for r in implicit if r["yandex_ok"]) / len(implicit) * 100:.1f}%) |
| App `llm` strong semantic match | {llm_summary["total_strong"]} | {llm_summary["explicit_strong"]} | {llm_summary["implicit_strong"]} |
| App `llm` usable semantic match | {llm_summary["total_usable"]} | - | - |
| App `llm_safe` strong semantic match | {llm_safe_summary["total_strong"]} | {llm_safe_summary["explicit_strong"]} | {llm_safe_summary["implicit_strong"]} |
| App `llm_safe` usable semantic match | {llm_safe_summary["total_usable"]} | - | - |

## Notes

- `strong semantic match` means score `2`: the result is executable and semantically close to the intended effect.
- `usable semantic match` means score `1` or `2`: the result is executable and at least partially matches the intended effect.
- Yandex results are taken from manual marking in the provided CSV; in the current file only the binary field `yandex_executed` is used for aggregation.
- Full per-phrase comparison is stored in `{out_csv}`.
"""

    out_md.write_text(md, encoding="utf-8")
    print(f"Wrote {out_csv}")
    print(f"Wrote {out_md}")


if __name__ == "__main__":
    main()
