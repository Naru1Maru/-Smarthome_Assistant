from __future__ import annotations

import argparse
import json
import math
import statistics
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from smarthome_core.assets import AssetPaths
from smarthome_core.executor_ha import ExecutionConfig, build_service_calls_from_validated, execute_validated_on_ha
from smarthome_core.ha_client import HomeAssistantError
from smarthome_core.io import load_json, load_jsonl, write_json
from smarthome_core.llm_client import OpenAICompatibleClient
from smarthome_core.parse_dispatch import parse_light_command_v1_dispatch
from smarthome_core.scenario_llm import run_scenario_authoring_pipeline_v1
from smarthome_core.schema_utils import load_schema, validate_with_schema
from smarthome_core.validator import validate_parsed_command
from smarthome_gateway import main as gateway


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

DEFAULT_SCENARIO_TEXTS = [
    "\u043a\u0430\u0436\u0434\u044b\u0439 \u0434\u0435\u043d\u044c \u0432 20:00 \u0432\u043a\u043b\u044e\u0447\u0430\u0439 \u0432 \u0441\u043f\u0430\u043b\u044c\u043d\u0435 \u0442\u0435\u043f\u043b\u044b\u0439 \u0441\u0432\u0435\u0442, \u0430 \u0432 00:00 \u0432\u044b\u043a\u043b\u044e\u0447\u0430\u0439 \u0435\u0433\u043e",
    "\u0432 19:00 \u0434\u0435\u043b\u0430\u0439 \u0441\u0432\u0435\u0442 \u0432 \u0441\u043f\u0430\u043b\u044c\u043d\u0435 \u0445\u043e\u043b\u043e\u0434\u043d\u0435\u0435",
    "\u043a\u0430\u0436\u0434\u044b\u0439 \u0434\u0435\u043d\u044c \u0432 23:30 \u043f\u0440\u0438\u0433\u043b\u0443\u0448\u0430\u0439 \u0441\u0432\u0435\u0442 \u0432 \u0441\u043f\u0430\u043b\u044c\u043d\u0435 \u0434\u043e 20%",
    "\u0432 07:30 \u0432\u043a\u043b\u044e\u0447\u0430\u0439 \u043d\u0430 \u043a\u0443\u0445\u043d\u0435 \u044f\u0440\u043a\u0438\u0439 \u0434\u043d\u0435\u0432\u043d\u043e\u0439 \u0441\u0432\u0435\u0442",
    "\u043f\u043e \u0432\u044b\u0445\u043e\u0434\u043d\u044b\u043c \u0432 10:00 \u0434\u0435\u043b\u0430\u0439 \u0432 \u0433\u043e\u0441\u0442\u0438\u043d\u043e\u0439 \u0443\u044e\u0442\u043d\u044b\u0439 \u0441\u0432\u0435\u0442",
    "\u0435\u0441\u043b\u0438 \u043f\u043e\u0441\u043b\u0435 19:00 \u0432 \u0441\u043f\u0430\u043b\u044c\u043d\u0435 \u0435\u0441\u0442\u044c \u0434\u0432\u0438\u0436\u0435\u043d\u0438\u0435 \u0438 \u043e\u0441\u0432\u0435\u0449\u0435\u043d\u043d\u043e\u0441\u0442\u044c \u043d\u0438\u0436\u0435 30 \u043b\u044e\u043a\u0441, \u0432\u043a\u043b\u044e\u0447\u0430\u0439 \u0441\u0432\u0435\u0442 \u043d\u0430 40%",
]


def _load_scenario_texts(root: Path, path_value: str | None) -> list[str]:
    if not path_value:
        return list(DEFAULT_SCENARIO_TEXTS)

    path = Path(path_value)
    if not path.is_absolute():
        path = root / path

    if path.suffix.lower() == ".jsonl":
        rows = load_jsonl(path)
        texts: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            text = str(row.get("text") or "").strip()
            if text:
                texts.append(text)
        return texts

    texts = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        texts.append(line)
    return texts


class FlakyHAClient:
    def __init__(self) -> None:
        self.calls = 0

    def call_service(self, service: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            raise HomeAssistantError("temporary network error", status=503, body="temporary")
        return {"ok": True}


class ReloadOKClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def call_service(self, service: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append((service, payload))
        return {"ok": True}


def _p(values: list[int], q: float) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    idx = max(0, min(len(ordered) - 1, math.ceil(q * len(ordered)) - 1))
    return int(ordered[idx])


def _avg(values: list[int]) -> int:
    return int(round(sum(values) / len(values))) if values else 0


def _std(values: list[int]) -> float:
    return round(float(statistics.pstdev(values)), 2) if values else 0.0


def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


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


def _timing_summary(values: list[int]) -> dict[str, Any]:
    return {
        "count": len(values),
        "avg_ms": _avg(values),
        "p50_ms": _p(values, 0.50),
        "p95_ms": _p(values, 0.95),
        "p99_ms": _p(values, 0.99),
        "std_ms": _std(values),
    }


def _run_command_metrics(
    *,
    records: list[dict[str, Any]],
    model: str,
    prompt_profile: str,
    base_url: str,
    api_key: str | None,
    timeout_s: int,
    repeats: int,
    parsed_schema: dict[str, Any],
    device_registry: dict[str, Any],
    area_synonyms: dict[str, Any],
    colors: dict[str, Any],
    modifiers: dict[str, Any],
    scene_aliases: dict[str, Any],
) -> dict[str, Any]:
    e2e_ms: list[int] = []
    parse_ms: list[int] = []
    validate_ms: list[int] = []
    execute_ms: list[int] = []
    llm_ms: list[int] = []
    per_request_e2e: dict[str, list[int]] = {}
    statuses = Counter()
    execution_errors = 0
    total = 0

    for rec in records:
        rid = str(rec.get("id") or rec.get("text") or "")
        per_request_e2e.setdefault(rid, [])
        for _ in range(repeats):
            total += 1
            text = str(rec.get("text") or "")
            context = rec.get("context") or {"last_area_name": None}
            client = OpenAICompatibleClient(base_url=base_url, api_key=api_key, model=model, timeout_s=timeout_s)

            t0 = time.perf_counter()
            t_parse0 = time.perf_counter()
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
            t_parse1 = time.perf_counter()
            info = client.get_last_call_info()
            if info:
                llm_ms.append(int(info.duration_ms))

            t_val0 = time.perf_counter()
            validated = validate_parsed_command(
                parsed,
                context=context,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
            )
            t_val1 = time.perf_counter()

            t_ex0 = time.perf_counter()
            calls, errors = build_service_calls_from_validated(
                validated,
                device_registry=device_registry,
                client=None,
                cfg=ExecutionConfig(dry_run=True),
            )
            t_ex1 = time.perf_counter()

            if errors:
                execution_errors += 1
                statuses["ERROR"] += 1
            elif validated.get("status") == "NEEDS_CLARIFICATION":
                statuses["NEEDS_CLARIFICATION"] += 1
            elif calls:
                statuses["DRY_RUN"] += 1
            else:
                statuses[str(validated.get("status") or "NO_CALLS")] += 1

            e2e = int(round((time.perf_counter() - t0) * 1000.0))
            e2e_ms.append(e2e)
            per_request_e2e[rid].append(e2e)
            parse_ms.append(int(round((t_parse1 - t_parse0) * 1000.0)))
            validate_ms.append(int(round((t_val1 - t_val0) * 1000.0)))
            execute_ms.append(int(round((t_ex1 - t_ex0) * 1000.0)))

    per_request_std = [_std(v) for v in per_request_e2e.values() if len(v) > 1]
    return {
        "model": model,
        "prompt_profile": prompt_profile,
        "total_runs": total,
        "status_counts": dict(statuses),
        "execution_error_rate": execution_errors / total if total else 0.0,
        "e2e": _timing_summary(e2e_ms),
        "parse": _timing_summary(parse_ms),
        "validate": _timing_summary(validate_ms),
        "execute": _timing_summary(execute_ms),
        "llm": _timing_summary(llm_ms),
        "stability": {
            "per_request_latency_std_avg_ms": round(sum(per_request_std) / len(per_request_std), 2) if per_request_std else 0.0,
            "per_request_latency_std_p95_ms": _p([int(round(v)) for v in per_request_std], 0.95) if per_request_std else 0,
        },
    }


def _retry_recovery_probe(device_registry: dict[str, Any]) -> dict[str, Any]:
    validated = {
        "schema_version": "1.0",
        "status": "EXECUTABLE",
        "reason_code": "OK",
        "warnings": [],
        "normalized": {
            "actions": [
                {
                    "domain": "light",
                    "intent": "TURN_ON",
                    "target": {"scope": "AREA", "area_name": "\u0421\u043f\u0430\u043b\u044c\u043d\u044f", "entity_ids": []},
                    "params": {
                        "brightness_pct": 50,
                        "brightness_delta_pct": None,
                        "rgb_color": None,
                        "color_temp_kelvin": None,
                        "color_temp_delta_k": None,
                        "transition_s": 0.5,
                    },
                }
            ],
            "context_updates": {"last_area_name": "\u0421\u043f\u0430\u043b\u044c\u043d\u044f", "last_entity_ids": []},
        },
        "execution_plan": [
            {
                "executor": "HOME_ASSISTANT",
                "service": "light.turn_on",
                "target": {"entity_id": [], "area_name": "\u0421\u043f\u0430\u043b\u044c\u043d\u044f"},
                "data": {"brightness_pct": 50, "brightness_step_pct": None, "rgb_color": None, "color_temp_kelvin": None, "transition": 0.5},
            }
        ],
    }
    client = FlakyHAClient()
    result = execute_validated_on_ha(
        validated,
        device_registry=device_registry,
        client=client,
        cfg=ExecutionConfig(dry_run=False),
    )
    recovered = bool(result.ok and client.calls > 1)
    return {
        "implemented_retry": False,
        "temporary_error_recovered": recovered,
        "retry_recovery_rate": 1.0 if recovered else 0.0,
        "calls_attempted": client.calls,
        "errors": result.errors,
    }


def _prepare_gateway_state(root: Path, tmp_root: Path, llm_client: Any | None) -> None:
    gateway.app.state.root_dir = tmp_root
    gateway.app.state.assets = gateway._load_assets(root)
    gateway.app.state.log_path = tmp_root / "commands.jsonl"
    gateway.app.state.llm_client = llm_client
    scenarios_dir = tmp_root / "gateway_scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    (scenarios_dir / "configuration.yaml").write_text("automation: !include smarthome_gateway_automations.yaml\n", encoding="utf-8")


def _run_scenario_metrics(
    *,
    root: Path,
    model: str,
    scenario_texts: list[str],
    base_url: str,
    api_key: str | None,
    timeout_s: int,
    device_registry: dict[str, Any],
    area_synonyms: dict[str, Any],
    scene_aliases: dict[str, Any],
    scenario_schema: dict[str, Any],
) -> dict[str, Any]:
    preview_total = 0
    preview_ready = 0
    valid_json_schema = 0
    save_total = 0
    save_active = 0
    upsert_total = 0
    upsert_success = 0
    delete_total = 0
    delete_consistent = 0
    parse_ms: list[int] = []
    validate_ms: list[int] = []
    compile_ms: list[int] = []
    llm_ms: list[int] = []

    with tempfile.TemporaryDirectory(prefix="smarthome_scenario_metrics_") as tmp:
        tmp_root = Path(tmp)
        reload_client = ReloadOKClient()
        original_make_ha_client = gateway._make_ha_client
        gateway._make_ha_client = lambda: reload_client  # type: ignore[assignment]
        try:
            for idx, text in enumerate(scenario_texts, start=1):
                preview_total += 1
                client = OpenAICompatibleClient(base_url=base_url, api_key=api_key, model=model, timeout_s=timeout_s)
                _prepare_gateway_state(root, tmp_root, client)
                t0 = time.perf_counter()
                try:
                    result = run_scenario_authoring_pipeline_v1(
                        text,
                        llm_client=client,
                        context={"selected_area_name": "\u0421\u043f\u0430\u043b\u044c\u043d\u044f", "last_area_name": "\u0421\u043f\u0430\u043b\u044c\u043d\u044f", "last_entity_ids": []},
                        root_dir=root,
                        device_registry=device_registry,
                        area_synonyms=area_synonyms,
                        scene_aliases=scene_aliases,
                        scenario_schema=scenario_schema,
                    )
                    t1 = time.perf_counter()
                    info = client.get_last_call_info()
                    if info:
                        llm_ms.append(int(info.duration_ms))
                    parse_ms.append(int(round((t1 - t0) * 1000.0)))
                    validate_ms.append(0)
                    compile_ms.append(0)
                    validate_with_schema(result.parsed, scenario_schema)
                    valid_json_schema += 1
                except Exception:
                    continue

                if result.stage != "VALIDATED" or not result.automations:
                    continue
                preview_ready += 1
                save_total += 1
                save_resp = gateway.scenario_save(
                    gateway.ScenarioSaveRequest(automations=result.automations, auto_activate=True),
                    x_api_key=None,
                )
                if save_resp.ok and save_resp.status == "SAVED_ACTIVE":
                    save_active += 1

                automation = dict(result.automations[0])
                automation["alias"] = f"{automation.get('alias', automation.get('id', 'scenario'))} edited"
                upsert_total += 1
                upsert_resp = gateway.scenario_upsert(
                    gateway.ScenarioUpsertRequest(automation=automation, auto_activate=True),
                    x_api_key=None,
                )
                listed = gateway.scenario_list(x_api_key=None)
                found = [item for item in listed.items if item.automation_id == automation.get("id")]
                if upsert_resp.ok and found and found[0].alias == automation["alias"]:
                    upsert_success += 1

                delete_total += 1
                before_project_files = set(save_resp.project_files)
                delete_resp = gateway.scenario_delete(
                    gateway.ScenarioDeleteRequest(automation_id=str(automation.get("id")), auto_activate=True),
                    x_api_key=None,
                )
                listed_after = gateway.scenario_list(x_api_key=None)
                still_exists = any(item.automation_id == automation.get("id") for item in listed_after.items)
                removed_files = set(delete_resp.project_files_removed)
                project_removed = bool(before_project_files) and bool(before_project_files & removed_files)
                if delete_resp.ok and not still_exists and project_removed:
                    delete_consistent += 1
        finally:
            gateway._make_ha_client = original_make_ha_client  # type: ignore[assignment]

    return {
        "model": model,
        "scenario_count": preview_total,
        "scenario_preview_ready_rate": preview_ready / preview_total if preview_total else 0.0,
        "valid_json_schema_rate": valid_json_schema / preview_total if preview_total else 0.0,
        "ha_save_active_rate": save_active / save_total if save_total else 0.0,
        "manual_edit_success_rate": upsert_success / upsert_total if upsert_total else 0.0,
        "delete_consistency_rate": delete_consistent / delete_total if delete_total else 0.0,
        "preview_timing": {
            "parse": _timing_summary(parse_ms),
            "validate": _timing_summary(validate_ms),
            "compile": _timing_summary(compile_ms),
            "llm": _timing_summary(llm_ms),
        },
        "counts": {
            "preview_total": preview_total,
            "preview_ready": preview_ready,
            "valid_json_schema": valid_json_schema,
            "save_total": save_total,
            "save_active": save_active,
            "upsert_total": upsert_total,
            "upsert_success": upsert_success,
            "delete_total": delete_total,
            "delete_consistent": delete_consistent,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Operational metrics for SmartHome commands and scenarios")
    parser.add_argument("--root", type=str, default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--dataset", type=str, default="data/light_gold_eval100_ru_v1.jsonl")
    parser.add_argument("--reports-dir", type=str, default="reports")
    parser.add_argument("--model-profiles", type=str, default=None)
    parser.add_argument("--command-sample-size", type=int, default=20)
    parser.add_argument("--command-repeats", type=int, default=3)
    parser.add_argument("--scenario-model", type=str, default="qwen3:8b")
    parser.add_argument("--scenario-texts-file", type=str, default=None)
    parser.add_argument("--base-url", type=str, default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", type=str, default=None)
    parser.add_argument("--timeout-s", type=int, default=300)
    args = parser.parse_args()

    root = Path(args.root)
    paths = AssetPaths(root)
    reports_dir = root / args.reports_dir
    reports_dir.mkdir(parents=True, exist_ok=True)

    records = load_jsonl(root / args.dataset)[: max(1, int(args.command_sample_size))]
    parsed_schema = load_schema(paths.parsed_schema)
    scenario_schema = load_schema(paths.scenario_bundle_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)
    scenario_texts = _load_scenario_texts(root, args.scenario_texts_file)

    command_results = []
    for model, profile in _model_profiles(args.model_profiles).items():
        print(f"[ops] command model={model} prompt={profile}")
        command_results.append(
            _run_command_metrics(
                records=records,
                model=model,
                prompt_profile=profile,
                base_url=args.base_url,
                api_key=args.api_key,
                timeout_s=int(args.timeout_s),
                repeats=int(args.command_repeats),
                parsed_schema=parsed_schema,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
                scene_aliases=scene_aliases,
            )
        )

    retry_probe = _retry_recovery_probe(device_registry)

    print(f"[ops] scenario model={args.scenario_model}")
    scenario_result = _run_scenario_metrics(
        root=root,
        model=str(args.scenario_model),
        scenario_texts=scenario_texts,
        base_url=args.base_url,
        api_key=args.api_key,
        timeout_s=int(args.timeout_s),
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        scene_aliases=scene_aliases,
        scenario_schema=scenario_schema,
    )

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_json = reports_dir / f"operational_metrics.{stamp}.json"
    out_md = reports_dir / f"operational_metrics.{stamp}.md"
    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "dataset": str(root / args.dataset),
        "command_sample_size": len(records),
        "command_repeats": int(args.command_repeats),
        "command_metrics": command_results,
        "reliability": {
            "retry_recovery_probe": retry_probe,
            "soak_24h": {
                "measured": False,
                "reason": "Requires a real 24-hour run against the target Home Assistant environment.",
                "recommended_command": "python scripts/operational_metrics.py --command-repeats 1 --command-sample-size 100",
            },
        },
        "scenario_metrics": scenario_result,
        "scenario_texts_file": args.scenario_texts_file,
        "ux_metrics": {
            "measured": False,
            "reason": "Task Completion Rate, Task Time, and SUS/Likert require a user study or recorded usability sessions.",
        },
    }
    write_json(out_json, payload)

    ranked = sorted(command_results, key=lambda r: (r["e2e"]["p95_ms"], r["e2e"]["p50_ms"]))
    lines = [
        "# Operational Metrics",
        "",
        f"- command sample size: `{len(records)}`",
        f"- command repeats: `{args.command_repeats}`",
        "- command mode: LLM, dry-run execution",
        "",
        "## Command Performance",
        "| model | prompt | e2e p50 | e2e p95 | e2e p99 | e2e std | parse p95 | validate p95 | execute p95 | llm p95 | exec error |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in ranked:
        lines.append(
            "| "
            + " | ".join(
                [
                    r["model"],
                    r["prompt_profile"],
                    str(r["e2e"]["p50_ms"]),
                    str(r["e2e"]["p95_ms"]),
                    str(r["e2e"]["p99_ms"]),
                    str(r["e2e"]["std_ms"]),
                    str(r["parse"]["p95_ms"]),
                    str(r["validate"]["p95_ms"]),
                    str(r["execute"]["p95_ms"]),
                    str(r["llm"]["p95_ms"]),
                    _pct(float(r["execution_error_rate"])),
                ]
            )
            + " |"
        )
    lines.extend(
        [
            "",
            "## Command Stability",
            "| model | prompt | per-request std avg | per-request std p95 |",
            "|---|---|---:|---:|",
        ]
    )
    for r in ranked:
        lines.append(
            f"| {r['model']} | {r['prompt_profile']} | {r['stability']['per_request_latency_std_avg_ms']} | {r['stability']['per_request_latency_std_p95_ms']} |"
        )
    lines.extend(
        [
            "",
            "## Reliability",
            "| metric | value | note |",
            "|---|---:|---|",
            f"| Retry Recovery Rate | {_pct(float(retry_probe['retry_recovery_rate']))} | executor currently stops after first HA error; retry is not implemented |",
            "| 24h soak success rate | not measured | requires real 24-hour run against HA |",
            "",
            "## Scenario Quality",
            f"- scenario sample size: `{len(scenario_texts)}`",
            f"- scenario source: `{args.scenario_texts_file or 'embedded default set'}`",
            "| model | Preview Ready | Valid JSON/Schema | HA Save Active | Manual Edit Success | Delete Consistency | preview p95 | llm p95 |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
            "| "
            + " | ".join(
                [
                    scenario_result["model"],
                    _pct(float(scenario_result["scenario_preview_ready_rate"])),
                    _pct(float(scenario_result["valid_json_schema_rate"])),
                    _pct(float(scenario_result["ha_save_active_rate"])),
                    _pct(float(scenario_result["manual_edit_success_rate"])),
                    _pct(float(scenario_result["delete_consistency_rate"])),
                    str(scenario_result["preview_timing"]["parse"]["p95_ms"]),
                    str(scenario_result["preview_timing"]["llm"]["p95_ms"]),
                ]
            )
            + " |",
            "",
            "## UX Metrics",
            "| metric | status |",
            "|---|---|",
            "| Task Completion Rate | not measured; requires 8-10 task user study |",
            "| Task Time median | not measured; requires recorded user sessions |",
            "| SUS / Likert survey | not measured; requires respondent answers |",
            "",
        ]
    )
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"[ops] wrote {out_json}")
    print(f"[ops] wrote {out_md}")
    print("\n".join(lines[:28]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
