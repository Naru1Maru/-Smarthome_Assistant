from __future__ import annotations

import argparse
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json, load_jsonl, write_json
from smarthome_core.llm_client import OpenAICompatibleClient
from smarthome_core.parse_dispatch import parse_light_command_v1_dispatch
from smarthome_core.schema_utils import load_schema, validate_with_schema
from smarthome_core.validator import validate_parsed_command


def _avg(values: list[int]) -> float:
    if not values:
        return 0.0
    return float(sum(values)) / float(len(values))


def _pct(values: list[int], p: float) -> int:
    if not values:
        return 0
    sorted_values = sorted(values)
    idx = max(0, min(len(sorted_values) - 1, math.ceil(len(sorted_values) * p) - 1))
    return int(sorted_values[idx])


def _rate(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return float(numerator) / float(denominator)


def _model_slug(model: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in model).strip("_")


def _format_table(results: list[dict[str, Any]]) -> str:
    headers = [
        "model",
        "parsed_exact%",
        "validated_exact%",
        "status_match%",
        "llm_avg_ms",
        "llm_p50_ms",
        "llm_p95_ms",
        "prompt_avg_tok",
        "completion_avg_tok",
        "errors",
    ]
    lines = ["| " + " | ".join(headers) + " |", "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in results:
        lines.append(
            "| "
            + " | ".join(
                [
                    str(r["model"]),
                    f'{100.0 * r["parsed_exact_rate"]:.1f}',
                    f'{100.0 * r["validated_exact_rate"]:.1f}',
                    f'{100.0 * r["status_match_rate"]:.1f}',
                    str(r["llm_duration_avg_ms"]),
                    str(r["llm_duration_p50_ms"]),
                    str(r["llm_duration_p95_ms"]),
                    f'{r["prompt_tokens_avg"]:.1f}',
                    f'{r["completion_tokens_avg"]:.1f}',
                    str(r["errors_total"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines) + "\n"


def run_benchmark_for_model(
    *,
    model: str,
    records: list[dict[str, Any]],
    base_url: str,
    api_key: str | None,
    timeout_s: int,
    device_registry: dict[str, Any],
    area_synonyms: dict[str, Any],
    colors: dict[str, Any],
    modifiers: dict[str, Any],
    parsed_schema: dict[str, Any],
) -> dict[str, Any]:
    client = OpenAICompatibleClient(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout_s=timeout_s,
    )

    total = len(records)
    parsed_exact = 0
    parsed_schema_ok = 0
    validated_exact = 0
    status_match = 0
    reason_match = 0

    errors_parse_exception = 0
    errors_parse_schema = 0
    errors_validate_exception = 0

    parse_wall_ms: list[int] = []
    llm_duration_ms: list[int] = []
    prompt_tokens: list[int] = []
    completion_tokens: list[int] = []
    total_tokens: list[int] = []

    t0_model = time.perf_counter()

    for rec in records:
        text = str(rec.get("text") or "")
        ctx = rec.get("context") or {"last_area_name": None}
        exp_parsed = rec["expected_parsed"]
        exp_validated = rec["expected_validated"]

        t0_parse = time.perf_counter()
        try:
            pred_parsed = parse_light_command_v1_dispatch(
                text,
                parser_mode="llm",
                context=ctx,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
                parsed_schema=parsed_schema,
                llm_client=client,
            )
        except Exception:
            errors_parse_exception += 1
            continue

        parse_ms = max(0, int(round((time.perf_counter() - t0_parse) * 1000.0)))
        parse_wall_ms.append(parse_ms)

        info = client.get_last_call_info()
        if info is not None:
            llm_duration_ms.append(int(info.duration_ms))
            prompt_tokens.append(int(info.prompt_tokens))
            completion_tokens.append(int(info.completion_tokens))
            total_tokens.append(int(info.total_tokens))

        try:
            validate_with_schema(pred_parsed, parsed_schema)
            parsed_schema_ok += 1
        except Exception:
            errors_parse_schema += 1

        if pred_parsed == exp_parsed:
            parsed_exact += 1

        try:
            pred_validated = validate_parsed_command(
                pred_parsed,
                context=ctx,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
            )
        except Exception:
            errors_validate_exception += 1
            continue

        if pred_validated.get("status") == exp_validated.get("status"):
            status_match += 1
        if pred_validated.get("reason_code") == exp_validated.get("reason_code"):
            reason_match += 1
        if pred_validated == exp_validated:
            validated_exact += 1

    model_elapsed_ms = max(0, int(round((time.perf_counter() - t0_model) * 1000.0)))

    return {
        "model": model,
        "dataset_total": total,
        "parsed_schema_ok": parsed_schema_ok,
        "parsed_schema_ok_rate": _rate(parsed_schema_ok, total),
        "parsed_exact": parsed_exact,
        "parsed_exact_rate": _rate(parsed_exact, total),
        "validated_exact": validated_exact,
        "validated_exact_rate": _rate(validated_exact, total),
        "status_match": status_match,
        "status_match_rate": _rate(status_match, total),
        "reason_match": reason_match,
        "reason_match_rate": _rate(reason_match, total),
        "parse_wall_avg_ms": int(round(_avg(parse_wall_ms))),
        "parse_wall_p50_ms": _pct(parse_wall_ms, 0.50),
        "parse_wall_p95_ms": _pct(parse_wall_ms, 0.95),
        "llm_duration_avg_ms": int(round(_avg(llm_duration_ms))),
        "llm_duration_p50_ms": _pct(llm_duration_ms, 0.50),
        "llm_duration_p95_ms": _pct(llm_duration_ms, 0.95),
        "prompt_tokens_avg": round(_avg(prompt_tokens), 2),
        "completion_tokens_avg": round(_avg(completion_tokens), 2),
        "total_tokens_avg": round(_avg(total_tokens), 2),
        "errors_parse_exception": errors_parse_exception,
        "errors_parse_schema": errors_parse_schema,
        "errors_validate_exception": errors_validate_exception,
        "errors_total": errors_parse_exception + errors_parse_schema + errors_validate_exception,
        "elapsed_ms": model_elapsed_ms,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="LLM model benchmark on SmartHome NLU dataset")
    parser.add_argument(
        "--models",
        type=str,
        required=True,
        help="Comma separated model list, e.g. qwen25-7b-local:latest,qwen3:8b,llama3.1:8b",
    )
    parser.add_argument("--base-url", type=str, default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--timeout-s", type=int, default=120)
    parser.add_argument("--root", type=str, default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--reports-dir", type=str, default="reports")
    parser.add_argument("--dataset", type=str, default="data/light_gold_dual_v1.jsonl")
    args = parser.parse_args()

    root = Path(args.root)
    dataset_path = root / args.dataset
    reports_dir = root / args.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)

    paths = AssetPaths(root)
    records = load_jsonl(dataset_path)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    parsed_schema = load_schema(paths.parsed_schema)

    models = [m.strip() for m in args.models.split(",") if m.strip()]
    if not models:
        raise ValueError("No models provided.")

    started_at = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    results: list[dict[str, Any]] = []

    for model in models:
        print(f"[benchmark] model={model} records={len(records)}")
        out = run_benchmark_for_model(
            model=model,
            records=records,
            base_url=args.base_url,
            api_key=args.api_key,
            timeout_s=int(args.timeout_s),
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
            parsed_schema=parsed_schema,
        )
        results.append(out)
        print(
            f"[benchmark] done model={model} "
            f"parsed_exact={100.0 * out['parsed_exact_rate']:.1f}% "
            f"validated_exact={100.0 * out['validated_exact_rate']:.1f}% "
            f"llm_p95={out['llm_duration_p95_ms']}ms"
        )

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": {"path": str(dataset_path), "total": len(records)},
        "base_url": args.base_url,
        "models": models,
        "results": results,
    }

    out_json = reports_dir / f"llm_model_benchmark.{started_at}.json"
    out_md = reports_dir / f"llm_model_benchmark.{started_at}.md"
    write_json(out_json, payload)
    out_md.write_text(_format_table(results), encoding="utf-8")

    print(f"[benchmark] wrote {out_json}")
    print(f"[benchmark] wrote {out_md}")
    print(_format_table(results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
