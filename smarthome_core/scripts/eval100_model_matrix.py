from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json, load_jsonl, write_json
from smarthome_core.llm_client import OpenAICompatibleClient
from smarthome_core.parse_dispatch import parse_light_command_v1_dispatch
from smarthome_core.schema_utils import load_schema, validate_with_schema
from smarthome_core.validator import validate_parsed_command


SPLITS = ("full", "direct", "creative")


def _pct(v: float) -> str:
    return f"{v * 100:.2f}%"


def _avg(values: list[int]) -> float:
    return (sum(values) / len(values)) if values else 0.0


def _p(values: list[int], q: float) -> int:
    if not values:
        return 0
    s = sorted(values)
    idx = max(0, min(len(s) - 1, math.ceil(q * len(s)) - 1))
    return int(s[idx])


def _split_of(rec: dict[str, Any]) -> str:
    tags = rec.get("tags") or []
    for t in tags:
        if isinstance(t, str) and t.startswith("style:"):
            value = t.split(":", 1)[1].strip().lower()
            if value in {"direct", "creative"}:
                return value
    rid = str(rec.get("id") or "")
    if rid.startswith("C"):
        return "creative"
    return "direct"


def _action_params(action: dict[str, Any]) -> dict[str, Any]:
    params = action.get("params") or {}
    if not isinstance(params, dict):
        return {}
    return params


def _color_rgb(params: dict[str, Any]) -> Optional[tuple[int, int, int]]:
    color = params.get("color")
    if not isinstance(color, dict):
        return None
    rgb = color.get("rgb")
    if not isinstance(rgb, list) or len(rgb) != 3:
        return None
    try:
        return (int(rgb[0]), int(rgb[1]), int(rgb[2]))
    except Exception:
        return None


def _intent_concept(action: dict[str, Any]) -> str:
    intent = str(action.get("intent") or "").upper()
    params = _action_params(action)
    brightness = params.get("brightness")
    brightness_delta = params.get("brightness_delta")
    color_temp = params.get("color_temp_kelvin")
    color_temp_delta = params.get("color_temp_delta_k")
    color_rgb = _color_rgb(params)

    if intent == "TURN_ON":
        if brightness_delta is not None:
            return "ADJUST_BRIGHTNESS"
        if color_temp_delta is not None:
            return "ADJUST_COLOR_TEMP"
        if color_rgb is not None:
            return "SET_COLOR"
        if color_temp is not None:
            return "SET_COLOR_TEMP"
        # Treat full-brightness TURN_ON as plain TURN_ON default.
        if brightness == 100:
            return "TURN_ON"
        if brightness is not None:
            return "SET_BRIGHTNESS"
        return "TURN_ON"

    return intent


def _strict_action_sig(action: dict[str, Any]) -> tuple[Any, ...]:
    target = action.get("target") or {}
    params = _action_params(action)
    return (
        str(action.get("intent") or "").upper(),
        str(target.get("scope") or ""),
        str(target.get("area_name") or ""),
        tuple(sorted(str(x) for x in (target.get("entity_ids") or []))),
        params.get("brightness"),
        params.get("brightness_delta"),
        _color_rgb(params),
        params.get("color_temp_kelvin"),
        params.get("color_temp_delta_k"),
        params.get("transition_s"),
    )


def _soft_action_sig(action: dict[str, Any]) -> tuple[Any, ...]:
    target = action.get("target") or {}
    params = _action_params(action)

    concept = _intent_concept(action)
    brightness = params.get("brightness")
    brightness_delta = params.get("brightness_delta")
    color_temp = params.get("color_temp_kelvin")
    color_temp_delta = params.get("color_temp_delta_k")
    color_rgb = _color_rgb(params)

    # Ignore transition and boilerplate defaults.
    if concept == "TURN_ON" and brightness == 100 and color_rgb is None and color_temp is None:
        brightness = None

    return (
        concept,
        str(target.get("scope") or ""),
        str(target.get("area_name") or ""),
        tuple(sorted(str(x) for x in (target.get("entity_ids") or []))),
        brightness if concept in {"SET_BRIGHTNESS", "TURN_ON"} else None,
        brightness_delta if concept == "ADJUST_BRIGHTNESS" else None,
        color_rgb if concept == "SET_COLOR" else None,
        color_temp if concept == "SET_COLOR_TEMP" else None,
        color_temp_delta if concept == "ADJUST_COLOR_TEMP" else None,
    )


def _intent_list(parsed: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for action in parsed.get("actions") or []:
        if isinstance(action, dict):
            out.append(str(action.get("intent") or "").upper())
    return out


def _action_sigs(parsed: dict[str, Any], *, soft: bool) -> list[tuple[Any, ...]]:
    fn = _soft_action_sig if soft else _strict_action_sig
    sigs: list[tuple[Any, ...]] = []
    for action in parsed.get("actions") or []:
        if isinstance(action, dict):
            sigs.append(fn(action))
    return sorted(sigs)


@dataclass
class SplitStats:
    total: int = 0
    parse_exception: int = 0
    parsed_schema_ok: int = 0
    parsed_exact: int = 0
    clarification_match: int = 0
    intents_order_match: int = 0
    intents_multiset_match: int = 0
    strict_action_match: int = 0
    soft_action_match: int = 0
    validate_exception: int = 0
    validated_schema_ok: int = 0
    validated_exact: int = 0
    status_match: int = 0
    reason_match: int = 0
    exec_plan_match: int = 0
    parse_wall_ms: list[int] = field(default_factory=list)
    llm_ms: list[int] = field(default_factory=list)
    prompt_tokens: list[int] = field(default_factory=list)
    completion_tokens: list[int] = field(default_factory=list)
    total_tokens: list[int] = field(default_factory=list)

    def as_metrics(self) -> dict[str, Any]:
        denom = self.total or 1
        return {
            "total": self.total,
            "parse_exception": self.parse_exception,
            "validate_exception": self.validate_exception,
            "parsed_schema_ok_rate": self.parsed_schema_ok / denom,
            "parsed_exact_rate": self.parsed_exact / denom,
            "clarification_match_rate": self.clarification_match / denom,
            "parsed_intents_order_match_rate": self.intents_order_match / denom,
            "parsed_intents_multiset_match_rate": self.intents_multiset_match / denom,
            "parsed_strict_action_match_rate": self.strict_action_match / denom,
            "parsed_soft_semantic_match_rate": self.soft_action_match / denom,
            "validated_schema_ok_rate": self.validated_schema_ok / denom,
            "validated_exact_rate": self.validated_exact / denom,
            "status_match_rate": self.status_match / denom,
            "reason_match_rate": self.reason_match / denom,
            "exec_plan_match_rate": self.exec_plan_match / denom,
            "parse_wall_avg_ms": int(round(_avg(self.parse_wall_ms))),
            "parse_wall_p50_ms": _p(self.parse_wall_ms, 0.50),
            "parse_wall_p95_ms": _p(self.parse_wall_ms, 0.95),
            "llm_calls": len(self.llm_ms),
            "llm_duration_avg_ms": int(round(_avg(self.llm_ms))),
            "llm_duration_p50_ms": _p(self.llm_ms, 0.50),
            "llm_duration_p95_ms": _p(self.llm_ms, 0.95),
            "prompt_tokens_avg": round(_avg(self.prompt_tokens), 2),
            "completion_tokens_avg": round(_avg(self.completion_tokens), 2),
            "total_tokens_avg": round(_avg(self.total_tokens), 2),
        }


def _new_split_stats() -> dict[str, SplitStats]:
    return {k: SplitStats() for k in SPLITS}


def _update_record_stats(
    stats_by_split: dict[str, SplitStats],
    split: str,
    *,
    parsed_expected: dict[str, Any],
    parsed_pred: dict[str, Any],
    validated_expected: Optional[dict[str, Any]],
    validated_pred: Optional[dict[str, Any]],
    parsed_schema_ok: bool,
    validated_schema_ok: bool,
    parse_exception: bool,
    validate_exception: bool,
    parse_wall_ms: Optional[int] = None,
    llm_info: Optional[dict[str, int]] = None,
) -> None:
    for key in ("full", split):
        s = stats_by_split[key]
        s.total += 1
        if parse_wall_ms is not None:
            s.parse_wall_ms.append(int(parse_wall_ms))
        if llm_info is not None:
            s.llm_ms.append(int(llm_info.get("duration_ms", 0)))
            s.prompt_tokens.append(int(llm_info.get("prompt_tokens", 0)))
            s.completion_tokens.append(int(llm_info.get("completion_tokens", 0)))
            s.total_tokens.append(int(llm_info.get("total_tokens", 0)))

        if parse_exception:
            s.parse_exception += 1
            continue

        if parsed_schema_ok:
            s.parsed_schema_ok += 1

        if parsed_pred == parsed_expected:
            s.parsed_exact += 1

        if bool(parsed_pred.get("clarification")) == bool(parsed_expected.get("clarification")):
            s.clarification_match += 1

        pred_intents = _intent_list(parsed_pred)
        exp_intents = _intent_list(parsed_expected)
        if pred_intents == exp_intents:
            s.intents_order_match += 1
        if sorted(pred_intents) == sorted(exp_intents):
            s.intents_multiset_match += 1

        if _action_sigs(parsed_pred, soft=False) == _action_sigs(parsed_expected, soft=False):
            s.strict_action_match += 1
        if _action_sigs(parsed_pred, soft=True) == _action_sigs(parsed_expected, soft=True):
            s.soft_action_match += 1

        if validate_exception:
            s.validate_exception += 1
            continue

        if validated_schema_ok:
            s.validated_schema_ok += 1

        if validated_pred == validated_expected:
            s.validated_exact += 1

        if (validated_pred or {}).get("status") == (validated_expected or {}).get("status"):
            s.status_match += 1
        if (validated_pred or {}).get("reason_code") == (validated_expected or {}).get("reason_code"):
            s.reason_match += 1
        if ((validated_pred or {}).get("execution_plan") or []) == ((validated_expected or {}).get("execution_plan") or []):
            s.exec_plan_match += 1


def run_eval(
    *,
    mode: str,
    model: Optional[str],
    records: list[dict[str, Any]],
    parsed_schema: dict[str, Any],
    validated_schema: dict[str, Any],
    device_registry: dict[str, Any],
    area_synonyms: dict[str, Any],
    colors: dict[str, Any],
    modifiers: dict[str, Any],
    base_url: str,
    api_key: Optional[str],
    timeout_s: int,
    prompt_profile: str,
) -> dict[str, Any]:
    parser_mode = "rules" if mode == "rules" else "llm"
    llm_client: Optional[OpenAICompatibleClient] = None
    if mode == "llm":
        llm_client = OpenAICompatibleClient(
            base_url=base_url,
            api_key=api_key,
            model=str(model),
            timeout_s=timeout_s,
        )

    stats = _new_split_stats()
    t0 = time.perf_counter()

    for rec in records:
        split = _split_of(rec)
        text = str(rec.get("text") or "")
        context = rec.get("context") or {"last_area_name": None}
        exp_parsed = rec["expected_parsed"]
        exp_validated = rec["expected_validated"]

        parse_exception = False
        validate_exception = False
        parsed_schema_ok = False
        validated_schema_ok = False
        parse_wall_ms = 0
        llm_info: Optional[dict[str, int]] = None

        try:
            t_parse = time.perf_counter()
            pred_parsed = parse_light_command_v1_dispatch(
                text,
                parser_mode=parser_mode,
                context=context,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
                parsed_schema=parsed_schema,
                llm_client=llm_client,
                llm_prompt_profile=prompt_profile,
            )
            parse_wall_ms = int(round((time.perf_counter() - t_parse) * 1000.0))
        except Exception:
            parse_exception = True
            pred_parsed = {"schema_version": "1.0", "actions": []}

        if llm_client is not None:
            info = llm_client.get_last_call_info()
            if info is not None:
                llm_info = {
                    "duration_ms": int(info.duration_ms),
                    "prompt_tokens": int(info.prompt_tokens),
                    "completion_tokens": int(info.completion_tokens),
                    "total_tokens": int(info.total_tokens),
                }

        if not parse_exception:
            try:
                validate_with_schema(pred_parsed, parsed_schema)
                parsed_schema_ok = True
            except Exception:
                parsed_schema_ok = False

        pred_validated: Optional[dict[str, Any]] = None
        if not parse_exception:
            try:
                pred_validated = validate_parsed_command(
                    pred_parsed,
                    context=context,
                    device_registry=device_registry,
                    area_synonyms=area_synonyms,
                )
            except Exception:
                validate_exception = True

        if pred_validated is not None:
            try:
                validate_with_schema(pred_validated, validated_schema)
                validated_schema_ok = True
            except Exception:
                validated_schema_ok = False

        _update_record_stats(
            stats,
            split,
            parsed_expected=exp_parsed,
            parsed_pred=pred_parsed,
            validated_expected=exp_validated,
            validated_pred=pred_validated,
            parsed_schema_ok=parsed_schema_ok,
            validated_schema_ok=validated_schema_ok,
            parse_exception=parse_exception,
            validate_exception=validate_exception,
            parse_wall_ms=parse_wall_ms,
            llm_info=llm_info,
        )

    elapsed_ms = int(round((time.perf_counter() - t0) * 1000.0))
    return {
        "mode": mode,
        "model": model,
        "parser_mode": parser_mode,
        "prompt_profile": prompt_profile if mode == "llm" else None,
        "elapsed_ms": elapsed_ms,
        "splits": {k: v.as_metrics() for k, v in stats.items()},
    }


def _md_table(results: list[dict[str, Any]], split: str) -> str:
    lines = []
    lines.append(
        "| run | parsed_intents | parsed_soft_semantic | status_match | reason_match | exec_plan_match | llm_avg_ms | llm_p95_ms | prompt_tok | completion_tok |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        m = r["splits"][split]
        run_name = "rules" if r["mode"] == "rules" else str(r["model"])
        lines.append(
            "| "
            + " | ".join(
                [
                    run_name,
                    _pct(m["parsed_intents_order_match_rate"]),
                    _pct(m["parsed_soft_semantic_match_rate"]),
                    _pct(m["status_match_rate"]),
                    _pct(m["reason_match_rate"]),
                    _pct(m["exec_plan_match_rate"]),
                    str(m["llm_duration_avg_ms"]),
                    str(m["llm_duration_p95_ms"]),
                    f'{m["prompt_tokens_avg"]:.2f}',
                    f'{m["completion_tokens_avg"]:.2f}',
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate 100-phrase light dataset across all local models")
    parser.add_argument("--root", type=str, default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--reports-dir", type=str, default="reports")
    parser.add_argument("--dataset", type=str, default="data/light_gold_eval100_ru_v1.jsonl")
    parser.add_argument(
        "--models",
        type=str,
        default="qwen25-7b-local:latest,qwen2.5:3b,qwen3:8b,llama3.1:8b",
    )
    parser.add_argument("--base-url", type=str, default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--timeout-s", type=int, default=180)
    parser.add_argument("--include-rules", action="store_true")
    parser.add_argument("--prompt-profile", type=str, default="baseline", choices=["baseline", "universal"])
    args = parser.parse_args()

    root = Path(args.root)
    paths = AssetPaths(root)
    reports_dir = root / args.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)

    records = load_jsonl(root / args.dataset)
    parsed_schema = load_schema(paths.parsed_schema)
    validated_schema = load_schema(paths.validated_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)

    models = [x.strip() for x in str(args.models or "").split(",") if x.strip()]
    results: list[dict[str, Any]] = []

    if args.include_rules:
        print("[matrix] run=rules")
        results.append(
            run_eval(
                mode="rules",
                model=None,
                records=records,
                parsed_schema=parsed_schema,
                validated_schema=validated_schema,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
                base_url=args.base_url,
                api_key=args.api_key,
                timeout_s=int(args.timeout_s),
                prompt_profile="baseline",
            )
        )

    for model in models:
        print(f"[matrix] run=llm model={model} prompt_profile={args.prompt_profile}")
        results.append(
            run_eval(
                mode="llm",
                model=model,
                records=records,
                parsed_schema=parsed_schema,
                validated_schema=validated_schema,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
                base_url=args.base_url,
                api_key=args.api_key,
                timeout_s=int(args.timeout_s),
                prompt_profile=str(args.prompt_profile),
            )
        )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = reports_dir / f"eval100_model_matrix.{stamp}.json"
    out_md = reports_dir / f"eval100_model_matrix.{stamp}.md"

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": {"path": str(root / args.dataset), "total": len(records)},
        "models": models,
        "include_rules": bool(args.include_rules),
        "prompt_profile": str(args.prompt_profile),
        "results": results,
    }
    write_json(out_json, payload)

    md_lines = [
        "# Eval100 Model Matrix",
        "",
        f"- dataset: `{args.dataset}`",
        f"- base_url: `{args.base_url}`",
        f"- prompt_profile: `{args.prompt_profile}`",
        "",
        "## Full",
        _md_table(results, "full"),
        "",
        "## Direct",
        _md_table(results, "direct"),
        "",
        "## Creative",
        _md_table(results, "creative"),
        "",
    ]
    out_md.write_text("\n".join(md_lines), encoding="utf-8")

    print(f"[matrix] wrote {out_json}")
    print(f"[matrix] wrote {out_md}")
    print("\n".join(md_lines))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
