from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json, load_jsonl, write_json
from smarthome_core.llm_client import OpenAICompatibleClient
from smarthome_core.parse_dispatch import parse_light_command_v1_dispatch
from smarthome_core.schema_utils import load_schema
from smarthome_core.validator import validate_parsed_command


DEFAULT_MODEL_PROFILES = {
    "qwen25-7b-local:latest": "baseline",
    "qwen2.5:3b": "universal",
    "qwen3:8b": "universal",
    "llama3.1:8b": "universal",
    "qwen3:4b-instruct": "universal",
    "gemma3:4b": "baseline",
    "gemma3:12b": "universal",
    "mistral-nemo:12b": "universal",
}


def _avg(values: list[int]) -> float:
    return (sum(values) / len(values)) if values else 0.0


def _pct(value: float) -> str:
    return f"{value * 100:.1f}%"


def _tags(record: dict[str, Any]) -> dict[str, str]:
    out: dict[str, str] = {}
    for tag in record.get("tags") or []:
        if isinstance(tag, str) and ":" in tag:
            key, value = tag.split(":", 1)
            out[key] = value
    return out


def _params(action: dict[str, Any]) -> dict[str, Any]:
    params = action.get("params") or {}
    return params if isinstance(params, dict) else {}


def _rgb(params: dict[str, Any]) -> tuple[int, int, int] | None:
    color = params.get("color")
    if not isinstance(color, dict):
        return None
    raw = color.get("rgb")
    if not isinstance(raw, list) or len(raw) != 3:
        return None
    try:
        return (int(raw[0]), int(raw[1]), int(raw[2]))
    except Exception:
        return None


def _concept_from_action(action: dict[str, Any] | None) -> str:
    if not isinstance(action, dict):
        return "NO_ACTION"
    intent = str(action.get("intent") or "").upper()
    params = _params(action)
    if intent == "TURN_ON":
        if params.get("brightness_delta") is not None:
            return "ADJUST_BRIGHTNESS"
        if params.get("color_temp_delta_k") is not None:
            return "ADJUST_COLOR_TEMP"
        if _rgb(params) is not None:
            return "SET_COLOR"
        if params.get("color_temp_kelvin") is not None:
            return "SET_COLOR_TEMP"
        brightness = params.get("brightness")
        if brightness is not None and brightness != 100:
            return "SET_BRIGHTNESS"
        return "TURN_ON"
    return intent or "NO_ACTION"


def _primary_concept(parsed: dict[str, Any]) -> str:
    if (parsed.get("clarification") or {}).get("needed"):
        return "NEEDS_CLARIFICATION"
    actions = parsed.get("actions") or []
    if not actions:
        return "NO_ACTION"
    return _concept_from_action(actions[0])


def _signature(parsed: dict[str, Any]) -> str:
    if (parsed.get("clarification") or {}).get("needed"):
        return "NEEDS_CLARIFICATION"
    action = (parsed.get("actions") or [None])[0]
    if not isinstance(action, dict):
        return "NO_ACTION"
    target = action.get("target") or {}
    params = _params(action)
    data = {
        "concept": _concept_from_action(action),
        "scope": target.get("scope"),
        "area": target.get("area_name"),
        "brightness": params.get("brightness"),
        "brightness_delta": params.get("brightness_delta"),
        "rgb": _rgb(params),
        "color_temp": params.get("color_temp_kelvin"),
        "color_temp_delta": params.get("color_temp_delta_k"),
    }
    return json.dumps(data, ensure_ascii=False, sort_keys=True)


def _run_parse(
    *,
    text: str,
    context: dict[str, Any],
    model: str,
    prompt_profile: str,
    base_url: str,
    api_key: str | None,
    timeout_s: int,
    parsed_schema: dict[str, Any],
    device_registry: dict[str, Any],
    area_synonyms: dict[str, Any],
    colors: dict[str, Any],
    modifiers: dict[str, Any],
    scene_aliases: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, int, dict[str, int]]:
    client = OpenAICompatibleClient(base_url=base_url, api_key=api_key, model=model, timeout_s=timeout_s)
    started = time.perf_counter()
    parsed = parse_light_command_v1_dispatch(
        text,
        parser_mode="llm",
        context=context,
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
        parsed_schema=parsed_schema,
        llm_client=client,
        llm_prompt_profile=prompt_profile,
    )
    wall_ms = int(round((time.perf_counter() - started) * 1000.0))
    try:
        validated = validate_parsed_command(
            parsed,
            context=context,
            device_registry=device_registry,
            area_synonyms=area_synonyms,
        )
    except Exception:
        validated = None
    info = client.get_last_call_info()
    usage = {
        "duration_ms": int(info.duration_ms if info else wall_ms),
        "prompt_tokens": int(info.prompt_tokens if info else 0),
        "completion_tokens": int(info.completion_tokens if info else 0),
        "total_tokens": int(info.total_tokens if info else 0),
    }
    return parsed, validated, wall_ms, usage


def _safe_run_parse(**kwargs: Any) -> tuple[dict[str, Any], dict[str, Any] | None, int, dict[str, int], str | None]:
    try:
        parsed, validated, wall_ms, usage = _run_parse(**kwargs)
        return parsed, validated, wall_ms, usage, None
    except Exception as exc:
        return {"schema_version": "1.0", "actions": []}, None, 0, {"duration_ms": 0, "prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}, str(exc)


def _f1_from_confusion(confusion: dict[str, Counter]) -> dict[str, dict[str, float | int]]:
    labels = sorted(set(confusion.keys()) | {pred for row in confusion.values() for pred in row})
    out: dict[str, dict[str, float | int]] = {}
    for label in labels:
        tp = confusion.get(label, Counter()).get(label, 0)
        fp = sum(row.get(label, 0) for exp, row in confusion.items() if exp != label)
        fn = sum(count for pred, count in confusion.get(label, Counter()).items() if pred != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        out[label] = {
            "support": tp + fn,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
        }
    return out


def _macro_f1(per_label: dict[str, dict[str, float | int]]) -> float:
    values = [float(m["f1"]) for m in per_label.values() if int(m["support"]) > 0]
    return sum(values) / len(values) if values else 0.0


def _weighted_f1(per_label: dict[str, dict[str, float | int]]) -> float:
    total = sum(int(m["support"]) for m in per_label.values())
    if not total:
        return 0.0
    return sum(float(m["f1"]) * int(m["support"]) for m in per_label.values()) / total


def _clarification_records(clear_records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ambiguous = [
        "\u0432\u044b\u043a\u043b\u044e\u0447\u0438 \u0441\u0432\u0435\u0442",
        "\u0432\u043a\u043b\u044e\u0447\u0438 \u0441\u0432\u0435\u0442",
        "\u0441\u0434\u0435\u043b\u0430\u0439 \u044f\u0440\u0447\u0435",
        "\u0441\u0434\u0435\u043b\u0430\u0439 \u0442\u0438\u0448\u0435",
        "\u0441\u0434\u0435\u043b\u0430\u0439 \u0442\u0435\u043f\u043b\u0435\u0435",
        "\u0441\u0434\u0435\u043b\u0430\u0439 \u0445\u043e\u043b\u043e\u0434\u043d\u0435\u0435",
        "\u043f\u043e\u0441\u0442\u0430\u0432\u044c \u0441\u0438\u043d\u0438\u0439 \u0441\u0432\u0435\u0442",
        "\u0441\u0434\u0435\u043b\u0430\u0439 \u0443\u044e\u0442\u043d\u043e",
        "\u043f\u0440\u0438\u0433\u043b\u0443\u0448\u0438",
        "\u043f\u043e\u0433\u0430\u0441\u0438",
    ]
    records: list[dict[str, Any]] = [
        {"id": f"A{i:03d}", "text": text, "context": {"last_area_name": None, "selected_area_name": None}, "expected_clarification": True}
        for i, text in enumerate(ambiguous, start=1)
    ]
    for i, rec in enumerate(clear_records[:10], start=1):
        records.append(
            {
                "id": f"N{i:03d}",
                "text": str(rec.get("text") or ""),
                "context": rec.get("context") or {"last_area_name": None},
                "expected_clarification": False,
            }
        )
    return records


def _model_profiles(raw: str | None) -> dict[str, str]:
    if not raw:
        return dict(DEFAULT_MODEL_PROFILES)
    out: dict[str, str] = {}
    for item in raw.split(","):
        item = item.strip()
        if not item:
            continue
        if "=" in item:
            model, profile = item.split("=", 1)
            out[model.strip()] = profile.strip()
        else:
            out[item] = DEFAULT_MODEL_PROFILES.get(item, "universal")
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Extended LLM metrics for the SmartHome eval100 dataset")
    parser.add_argument("--root", type=str, default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--dataset", type=str, default="data/light_gold_eval100_ru_v1.jsonl")
    parser.add_argument("--reports-dir", type=str, default="reports")
    parser.add_argument("--model-profiles", type=str, default=None)
    parser.add_argument("--base-url", type=str, default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--timeout-s", type=int, default=300)
    parser.add_argument("--repeatability-sample-size", type=int, default=12)
    parser.add_argument("--repeatability-runs", type=int, default=3)
    args = parser.parse_args()

    root = Path(args.root)
    paths = AssetPaths(root)
    reports_dir = root / args.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)

    records = load_jsonl(root / args.dataset)
    parsed_schema = load_schema(paths.parsed_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)
    model_profiles = _model_profiles(args.model_profiles)
    clear_records = [r for r in records if _tags(r).get("style") == "direct"]
    clarification_records = _clarification_records(clear_records)
    repeat_records = records[: max(1, int(args.repeatability_sample_size))]

    model_results: list[dict[str, Any]] = []
    for model, prompt_profile in model_profiles.items():
        print(f"[extended] model={model} prompt={prompt_profile} eval100")
        confusion: dict[str, Counter] = defaultdict(Counter)
        category_confusion: dict[str, Counter] = defaultdict(Counter)
        errors: list[str] = []
        latencies: list[int] = []
        token_totals: list[int] = []
        exact_signature_match = 0

        for rec in records:
            parsed, validated, _wall_ms, usage, error = _safe_run_parse(
                text=str(rec.get("text") or ""),
                context=rec.get("context") or {"last_area_name": None},
                model=model,
                prompt_profile=prompt_profile,
                base_url=args.base_url,
                api_key=args.api_key,
                timeout_s=int(args.timeout_s),
                parsed_schema=parsed_schema,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
                scene_aliases=scene_aliases,
            )
            expected = _primary_concept(rec["expected_parsed"])
            predicted = _primary_concept(parsed)
            confusion[expected][predicted] += 1
            category_confusion[_tags(rec).get("category", "unknown")][predicted] += 1
            if _signature(parsed) == _signature(rec["expected_parsed"]):
                exact_signature_match += 1
            if error:
                errors.append(error)
            if usage["duration_ms"]:
                latencies.append(usage["duration_ms"])
            if usage["total_tokens"]:
                token_totals.append(usage["total_tokens"])

        per_intent = _f1_from_confusion(confusion)
        print(f"[extended] model={model} clarification")
        clarification_counts = Counter()
        for rec in clarification_records:
            parsed, _validated, _wall_ms, _usage, error = _safe_run_parse(
                text=str(rec["text"]),
                context=rec.get("context") or {"last_area_name": None},
                model=model,
                prompt_profile=prompt_profile,
                base_url=args.base_url,
                api_key=args.api_key,
                timeout_s=int(args.timeout_s),
                parsed_schema=parsed_schema,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
                scene_aliases=scene_aliases,
            )
            expected = bool(rec["expected_clarification"])
            predicted = bool((parsed.get("clarification") or {}).get("needed"))
            if expected and predicted:
                clarification_counts["tp"] += 1
            elif not expected and predicted:
                clarification_counts["fp"] += 1
            elif expected and not predicted:
                clarification_counts["fn"] += 1
            else:
                clarification_counts["tn"] += 1
            if error:
                clarification_counts["errors"] += 1

        tp = clarification_counts["tp"]
        fp = clarification_counts["fp"]
        fn = clarification_counts["fn"]
        tn = clarification_counts["tn"]
        clar_precision = tp / (tp + fp) if (tp + fp) else 0.0
        clar_recall = tp / (tp + fn) if (tp + fn) else 0.0
        clar_f1 = 2 * clar_precision * clar_recall / (clar_precision + clar_recall) if (clar_precision + clar_recall) else 0.0

        print(f"[extended] model={model} repeatability")
        stable = 0
        stable_correct = 0
        for rec in repeat_records:
            signatures: list[str] = []
            for _ in range(max(1, int(args.repeatability_runs))):
                parsed, _validated, _wall_ms, _usage, _error = _safe_run_parse(
                    text=str(rec.get("text") or ""),
                    context=rec.get("context") or {"last_area_name": None},
                    model=model,
                    prompt_profile=prompt_profile,
                    base_url=args.base_url,
                    api_key=args.api_key,
                    timeout_s=int(args.timeout_s),
                    parsed_schema=parsed_schema,
                    device_registry=device_registry,
                    area_synonyms=area_synonyms,
                    colors=colors,
                    modifiers=modifiers,
                    scene_aliases=scene_aliases,
                )
                signatures.append(_signature(parsed))
            if len(set(signatures)) == 1:
                stable += 1
                if signatures[0] == _signature(rec["expected_parsed"]):
                    stable_correct += 1

        total = len(records) or 1
        repeat_total = len(repeat_records) or 1
        result = {
            "model": model,
            "prompt_profile": prompt_profile,
            "eval100": {
                "total": len(records),
                "primary_concept_accuracy": exact_signature_match / total,
                "macro_f1": round(_macro_f1(per_intent), 4),
                "weighted_f1": round(_weighted_f1(per_intent), 4),
                "avg_llm_ms": int(round(_avg(latencies))),
                "avg_total_tokens": round(_avg(token_totals), 2),
                "errors": len(errors),
            },
            "per_intent": per_intent,
            "confusion_matrix": {k: dict(v) for k, v in sorted(confusion.items())},
            "category_confusion": {k: dict(v) for k, v in sorted(category_confusion.items())},
            "clarification": {
                "total": len(clarification_records),
                "tp": tp,
                "fp": fp,
                "fn": fn,
                "tn": tn,
                "precision": round(clar_precision, 4),
                "recall": round(clar_recall, 4),
                "f1": round(clar_f1, 4),
                "errors": int(clarification_counts["errors"]),
            },
            "repeatability": {
                "sample_size": len(repeat_records),
                "runs_per_record": int(args.repeatability_runs),
                "stable_rate": stable / repeat_total,
                "stable_and_correct_rate": stable_correct / repeat_total,
            },
        }
        model_results.append(result)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = reports_dir / f"eval100_extended_metrics.{stamp}.json"
    out_md = reports_dir / f"eval100_extended_metrics.{stamp}.md"
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(root / args.dataset),
        "model_profiles": model_profiles,
        "results": model_results,
        "not_measured": [
            "Home Assistant real execution success rate requires live HA execution logs.",
            "CPU/RAM/VRAM telemetry requires a dedicated monitored run around the Ollama process.",
        ],
    }
    write_json(out_json, payload)

    ranked = sorted(model_results, key=lambda r: (r["eval100"]["weighted_f1"], r["eval100"]["macro_f1"]), reverse=True)
    lines = [
        "# Eval100 Extended Metrics",
        "",
        f"- dataset: `{args.dataset}`",
        "- prompt profile: best known profile per model",
        "",
        "## Summary",
        "| rank | model | prompt | weighted F1 | macro F1 | primary action exact | clar F1 | repeat stable | repeat stable+correct | avg ms | errors |",
        "|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for idx, r in enumerate(ranked, start=1):
        lines.append(
            "| "
            + " | ".join(
                [
                    str(idx),
                    str(r["model"]),
                    str(r["prompt_profile"]),
                    _pct(float(r["eval100"]["weighted_f1"])),
                    _pct(float(r["eval100"]["macro_f1"])),
                    _pct(float(r["eval100"]["primary_concept_accuracy"])),
                    _pct(float(r["clarification"]["f1"])),
                    _pct(float(r["repeatability"]["stable_rate"])),
                    _pct(float(r["repeatability"]["stable_and_correct_rate"])),
                    str(r["eval100"]["avg_llm_ms"]),
                    str(r["eval100"]["errors"]),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Per-Intent F1",
        ]
    )
    for r in ranked:
        lines.append(f"### {r['model']} ({r['prompt_profile']})")
        lines.append("| intent | support | precision | recall | F1 |")
        lines.append("|---|---:|---:|---:|---:|")
        for label, metrics in sorted(r["per_intent"].items()):
            if int(metrics["support"]) <= 0:
                continue
            lines.append(
                "| "
                + " | ".join(
                    [
                        label,
                        str(metrics["support"]),
                        _pct(float(metrics["precision"])),
                        _pct(float(metrics["recall"])),
                        _pct(float(metrics["f1"])),
                    ]
                )
                + " |"
            )
        lines.append("")
    lines.extend(
        [
            "## Limits",
            "- HA real execution success was not measured in this run.",
            "- CPU/RAM/VRAM telemetry was not measured in this run.",
            "",
        ]
    )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"[extended] wrote {out_json}")
    print(f"[extended] wrote {out_md}")
    print("\n".join(lines[:22]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
