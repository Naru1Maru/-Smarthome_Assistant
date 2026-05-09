"""Evaluation utilities for parser and validator.

Generates:
- reports/eval_parsed_v1.json
- reports/eval_validated_v1.json
- reports/failures_parsed.jsonl
- reports/failures_validated.jsonl

The gold dataset records contain:
- expected_parsed
- expected_validated
"""

from __future__ import annotations

import dataclasses
import datetime as _dt
import difflib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .llm_client import LLMClient

from .io import load_json, load_jsonl, write_json, write_jsonl
from .schema_utils import load_schema, validate_with_schema
from .parser import parse_light_command_v1
from .parse_dispatch import parse_light_command_v1_dispatch
from .validator import validate_parsed_command


def _utc_now_iso() -> str:
    return _dt.datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _pretty(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)


def _diff_str(pred: Any, exp: Any, *, max_chars: int = 4000) -> str:
    a = _pretty(pred).splitlines()
    b = _pretty(exp).splitlines()
    diff = "\n".join(difflib.unified_diff(a, b, fromfile="pred", tofile="exp", lineterm=""))
    return diff[:max_chars]


def _action_signature(action: Dict[str, Any]) -> Tuple[Any, ...]:
    """Order-insensitive signature for coarse metrics."""
    target = action.get("target") or {}
    params = action.get("params") or {}
    # Keep only relevant params keys (stable set)
    stable_param_keys = (
        "brightness_pct",
        "brightness_step_pct",
        "color_temp_kelvin",
        "color_temp_delta_k",
        "rgb",
        "transition_s",
    )
    param_tuple = tuple((k, params.get(k)) for k in stable_param_keys if params.get(k) is not None)
    return (
        action.get("intent"),
        target.get("scope"),
        target.get("area_name"),
        param_tuple,
    )


def eval_parsed_on_dataset(
    *,
    dataset_jsonl: Path,
    out_eval_json: Path,
    out_failures_jsonl: Path,
    device_registry: Dict[str, Any],
    area_synonyms: Dict[str, Any],
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
    parsed_schema: Dict[str, Any],
    parser_mode: str = "rules",
    llm_client: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    """Evaluate parser output against expected_parsed."""
    records = load_jsonl(dataset_jsonl)

    total = len(records)
    exact_match = 0
    schema_ok = 0
    clarification_match = 0
    intents_order_match = 0
    intents_multiset_match = 0
    action_sig_multiset_match = 0

    failures: List[Dict[str, Any]] = []

    # Per-intent counts
    expected_intents: Dict[str, int] = {}
    predicted_intents: Dict[str, int] = {}
    correct_intents: Dict[str, int] = {}

    for rec in records:
        rid = rec.get("id", "<no-id>")
        text = rec.get("text", "")
        ctx = rec.get("context") or {"last_area_name": None}

        exp = rec["expected_parsed"]

        try:
            pred = parse_light_command_v1_dispatch(
                text,
                parser_mode=parser_mode,
                context=ctx,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
                parsed_schema=parsed_schema,
                llm_client=llm_client,
            )
        except Exception as e:  # pragma: no cover
            failures.append(
                {
                    "id": rid,
                    "text": text,
                    "context": ctx,
                    "error_type": "EXCEPTION",
                    "error": repr(e),
                }
            )
            continue

        # Schema validation
        try:
            validate_with_schema(pred, parsed_schema)
            schema_ok += 1
        except Exception as e:
            failures.append(
                {
                    "id": rid,
                    "text": text,
                    "context": ctx,
                    "error_type": "SCHEMA_INVALID",
                    "error": repr(e),
                    "pred": pred,
                    "expected": exp,
                    "diff": _diff_str(pred, exp),
                }
            )
            continue

        # Clarification metric
        if bool(pred.get("clarification")) == bool(exp.get("clarification")):
            clarification_match += 1

        # Intent metrics
        pred_intents = [a.get("intent") for a in pred.get("actions", [])]
        exp_intents = [a.get("intent") for a in exp.get("actions", [])]

        if pred_intents == exp_intents:
            intents_order_match += 1
        if sorted(pred_intents) == sorted(exp_intents):
            intents_multiset_match += 1

        # Per-intent counts
        for it in exp_intents:
            expected_intents[it] = expected_intents.get(it, 0) + 1
        for it in pred_intents:
            predicted_intents[it] = predicted_intents.get(it, 0) + 1

        # Coarse action signature multiset match
        pred_sigs = sorted([_action_signature(a) for a in pred.get("actions", [])])
        exp_sigs = sorted([_action_signature(a) for a in exp.get("actions", [])])
        if pred_sigs == exp_sigs:
            action_sig_multiset_match += 1

        # Exact match
        if pred == exp:
            exact_match += 1
            # For correct intents count: count all intents in this record
            for it in exp_intents:
                correct_intents[it] = correct_intents.get(it, 0) + 1
        else:
            failures.append(
                {
                    "id": rid,
                    "text": text,
                    "context": ctx,
                    "error_type": "MISMATCH",
                    "pred": pred,
                    "expected": exp,
                    "diff": _diff_str(pred, exp),
                }
            )

    metrics = {
        "total": total,
        "schema_ok": schema_ok,
        "exact_match": exact_match,
        "exact_match_rate": exact_match / total if total else 0.0,
        "clarification_match": clarification_match,
        "clarification_match_rate": clarification_match / total if total else 0.0,
        "intents_order_match": intents_order_match,
        "intents_order_match_rate": intents_order_match / total if total else 0.0,
        "intents_multiset_match": intents_multiset_match,
        "intents_multiset_match_rate": intents_multiset_match / total if total else 0.0,
        "action_signature_multiset_match": action_sig_multiset_match,
        "action_signature_multiset_match_rate": action_sig_multiset_match / total if total else 0.0,
        "failures": len(failures),
    }

    per_intent = {}
    for it, exp_cnt in sorted(expected_intents.items()):
        pred_cnt = predicted_intents.get(it, 0)
        corr_cnt = correct_intents.get(it, 0)
        # "corr_cnt" here is strict (only when entire record exact-matched),
        # so treat it as a conservative diagnostic.
        per_intent[it] = {
            "expected": exp_cnt,
            "predicted": pred_cnt,
            "correct_in_exact_records": corr_cnt,
        }

    report = {
        "parser_mode": parser_mode,
        "schema_version": "1.0",
        "eval": "parsed_v1",
        "dataset": {"path": str(dataset_jsonl), "total": total},
        "generated_at_utc": _utc_now_iso(),
        "metrics": metrics,
        "per_intent": per_intent,
    }

    out_eval_json.parent.mkdir(parents=True, exist_ok=True)
    out_failures_jsonl.parent.mkdir(parents=True, exist_ok=True)

    write_json(out_eval_json, report)
    write_jsonl(out_failures_jsonl, failures)

    return report


def eval_validated_on_dataset(
    *,
    dataset_jsonl: Path,
    out_eval_json: Path,
    out_failures_jsonl: Path,
    device_registry: Dict[str, Any],
    area_synonyms: Dict[str, Any],
    validated_schema: Dict[str, Any],
) -> Dict[str, Any]:
    """Evaluate validator output against expected_validated, using expected_parsed as input."""
    records = load_jsonl(dataset_jsonl)

    total = len(records)
    exact_match = 0
    schema_ok = 0
    status_match = 0
    reason_match = 0

    failures: List[Dict[str, Any]] = []

    status_counts: Dict[str, int] = {}
    reason_counts: Dict[str, int] = {}
    warning_counts: Dict[str, int] = {}

    for rec in records:
        rid = rec.get("id", "<no-id>")
        text = rec.get("text", "")
        ctx = rec.get("context") or {"last_area_name": None}

        exp = rec["expected_validated"]
        parsed_in = rec["expected_parsed"]

        try:
            pred = validate_parsed_command(
                parsed_in,
                context=ctx,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
            )
        except Exception as e:  # pragma: no cover
            failures.append(
                {
                    "id": rid,
                    "text": text,
                    "context": ctx,
                    "error_type": "EXCEPTION",
                    "error": repr(e),
                }
            )
            continue

        # Schema validation
        try:
            validate_with_schema(pred, validated_schema)
            schema_ok += 1
        except Exception as e:
            failures.append(
                {
                    "id": rid,
                    "text": text,
                    "context": ctx,
                    "error_type": "SCHEMA_INVALID",
                    "error": repr(e),
                    "pred": pred,
                    "expected": exp,
                    "diff": _diff_str(pred, exp),
                }
            )
            continue

        st = str(pred.get("status"))
        status_counts[st] = status_counts.get(st, 0) + 1
        reason = pred.get("reason_code")
        if reason is not None:
            reason_counts[str(reason)] = reason_counts.get(str(reason), 0) + 1
        for w in pred.get("warnings") or []:
            warning_counts[str(w)] = warning_counts.get(str(w), 0) + 1

        if pred.get("status") == exp.get("status"):
            status_match += 1
        if pred.get("reason_code") == exp.get("reason_code"):
            reason_match += 1

        if pred == exp:
            exact_match += 1
        else:
            failures.append(
                {
                    "id": rid,
                    "text": text,
                    "context": ctx,
                    "error_type": "MISMATCH",
                    "pred": pred,
                    "expected": exp,
                    "diff": _diff_str(pred, exp),
                }
            )

    metrics = {
        "total": total,
        "schema_ok": schema_ok,
        "exact_match": exact_match,
        "exact_match_rate": exact_match / total if total else 0.0,
        "status_match": status_match,
        "status_match_rate": status_match / total if total else 0.0,
        "reason_code_match": reason_match,
        "reason_code_match_rate": reason_match / total if total else 0.0,
        "failures": len(failures),
    }

    report = {
        "schema_version": "1.0",
        "eval": "validated_v1",
        "dataset": {"path": str(dataset_jsonl), "total": total},
        "generated_at_utc": _utc_now_iso(),
        "metrics": metrics,
        "status_counts": dict(sorted(status_counts.items())),
        "reason_counts": dict(sorted(reason_counts.items())),
        "warning_counts": dict(sorted(warning_counts.items())),
    }

    out_eval_json.parent.mkdir(parents=True, exist_ok=True)
    out_failures_jsonl.parent.mkdir(parents=True, exist_ok=True)

    write_json(out_eval_json, report)
    write_jsonl(out_failures_jsonl, failures)

    return report



def eval_pipeline_on_dataset(
    *,
    dataset_jsonl: Path,
    out_eval_json: Path,
    out_failures_jsonl: Path,
    device_registry: Dict[str, Any],
    area_synonyms: Dict[str, Any],
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
    parsed_schema: Dict[str, Any],
    validated_schema: Dict[str, Any],
    parser_mode: str = "rules",
    llm_client: Optional[LLMClient] = None,
) -> Dict[str, Any]:
    """Evaluate end-to-end: parser(text)->validated vs expected_validated."""
    from .validator import validate_parsed_command

    records = load_jsonl(dataset_jsonl)
    total = len(records)

    parsed_schema_ok = 0
    validated_schema_ok = 0
    exact_validated_match = 0
    status_match = 0
    reason_code_match = 0
    exec_plan_match = 0

    failures: List[Dict[str, Any]] = []

    for rec in records:
        rid = rec.get("id", "<no-id>")
        text = rec.get("text", "")
        ctx = rec.get("context") or {"last_area_name": None}

        exp_valid = rec["expected_validated"]

        try:
            pred_parsed = parse_light_command_v1_dispatch(
                text,
                parser_mode=parser_mode,
                context=ctx,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
                parsed_schema=parsed_schema,
                llm_client=llm_client,
            )
        except Exception as e:  # pragma: no cover
            failures.append({"id": rid, "text": text, "context": ctx, "error_type": "PARSE_EXCEPTION", "error": repr(e)})
            continue

        try:
            validate_with_schema(pred_parsed, parsed_schema)
            parsed_schema_ok += 1
        except Exception as e:
            failures.append(
                {
                    "id": rid,
                    "text": text,
                    "context": ctx,
                    "error_type": "PARSED_SCHEMA_INVALID",
                    "error": repr(e),
                    "pred_parsed": pred_parsed,
                }
            )
            continue

        try:
            pred_valid = validate_parsed_command(
                pred_parsed,
                context=ctx,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
            )
        except Exception as e:  # pragma: no cover
            failures.append({"id": rid, "text": text, "context": ctx, "error_type": "VALIDATE_EXCEPTION", "error": repr(e), "pred_parsed": pred_parsed})
            continue

        try:
            validate_with_schema(pred_valid, validated_schema)
            validated_schema_ok += 1
        except Exception as e:
            failures.append(
                {
                    "id": rid,
                    "text": text,
                    "context": ctx,
                    "error_type": "VALIDATED_SCHEMA_INVALID",
                    "error": repr(e),
                    "pred_parsed": pred_parsed,
                    "pred_validated": pred_valid,
                    "expected_validated": exp_valid,
                    "diff": _diff_str(pred_valid, exp_valid),
                }
            )
            continue

        if pred_valid.get("status") == exp_valid.get("status"):
            status_match += 1
        if pred_valid.get("reason_code") == exp_valid.get("reason_code"):
            reason_code_match += 1

        if (pred_valid.get("execution_plan") or []) == (exp_valid.get("execution_plan") or []):
            exec_plan_match += 1

        if pred_valid == exp_valid:
            exact_validated_match += 1
        else:
            failures.append(
                {
                    "id": rid,
                    "text": text,
                    "context": ctx,
                    "error_type": "VALIDATED_MISMATCH",
                    "pred_validated": pred_valid,
                    "expected_validated": exp_valid,
                    "diff": _diff_str(pred_valid, exp_valid),
                }
            )

    metrics = {
        "total": total,
        "parsed_schema_ok": parsed_schema_ok,
        "parsed_schema_ok_rate": parsed_schema_ok / total if total else 0.0,
        "validated_schema_ok": validated_schema_ok,
        "validated_schema_ok_rate": validated_schema_ok / total if total else 0.0,
        "exact_validated_match": exact_validated_match,
        "exact_validated_match_rate": exact_validated_match / total if total else 0.0,
        "status_match": status_match,
        "status_match_rate": status_match / total if total else 0.0,
        "reason_code_match": reason_code_match,
        "reason_code_match_rate": reason_code_match / total if total else 0.0,
        "exec_plan_match": exec_plan_match,
        "exec_plan_match_rate": exec_plan_match / total if total else 0.0,
    }

    report = {
        "parser_mode": parser_mode,
        "metrics": metrics,
        "failures_count": len(failures),
    }

    out_eval_json.parent.mkdir(parents=True, exist_ok=True)
    out_failures_jsonl.parent.mkdir(parents=True, exist_ok=True)

    out_eval_json.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    with out_failures_jsonl.open("w", encoding="utf-8") as f:
        for r in failures:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return report

def make_smoke_subset(
    *,
    dataset_jsonl: Path,
    out_jsonl: Path,
    ids: List[str],
) -> None:
    records = load_jsonl(dataset_jsonl)
    by_id = {r.get("id"): r for r in records}
    subset = [by_id[i] for i in ids if i in by_id]
    out_jsonl.parent.mkdir(parents=True, exist_ok=True)
    write_jsonl(out_jsonl, subset)
