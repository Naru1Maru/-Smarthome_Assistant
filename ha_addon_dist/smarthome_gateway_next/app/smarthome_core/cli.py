"""CLI helpers for quick local checks (no external services needed).

Examples:
    python -m smarthome_core.cli schema-check
    python -m smarthome_core.cli smoke
    python -m smarthome_core.cli validate-gold
    python -m smarthome_core.cli eval-all
    python -m smarthome_core.cli make-smoke-set
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .assets import AssetPaths
from .io import load_json, load_jsonl
from .schema_utils import load_schema, validate_with_schema
from .validator import validate_parsed_command
from .llm_client import OpenAICompatibleClient, StubClient
from .eval_tools import eval_parsed_on_dataset, eval_validated_on_dataset, eval_pipeline_on_dataset, make_smoke_subset


def _cmd_schema_check(paths: AssetPaths) -> int:
    parsed_schema = load_schema(paths.parsed_schema)
    validated_schema = load_schema(paths.validated_schema)

    # Just ensure schemas load and are valid Draft 2020-12 (jsonschema will raise if not)
    validate_with_schema(
    {
        "schema_version": "1.0",
        "actions": [
            {
                "domain": "light",
                "intent": "TURN_ON",
                "target": {"scope": "UNSPECIFIED", "area_name": None, "entity_ids": []},
                "params": {
                    "brightness": None,
                    "brightness_delta": None,
                    "color": None,
                    "color_temp_kelvin": None,
                    "color_temp_delta_k": None,
                    "transition_s": None,
                },
            }
        ],
    },
    parsed_schema,
)
    # Minimal validated command skeleton for schema sanity check is harder; skip strict check here.
    print("OK: schemas loaded")
    return 0


def _cmd_validate_gold(paths: AssetPaths) -> int:
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    parsed_schema = load_schema(paths.parsed_schema)
    validated_schema = load_schema(paths.validated_schema)

    dataset = load_jsonl(paths.gold_dataset)
    mismatches = 0

    for rec in dataset:
        parsed = rec["expected_parsed"]
        ctx = rec.get("context") or {"last_area_name": None}
        validate_with_schema(parsed, parsed_schema)

        pred_validated = validate_parsed_command(
            parsed, context=ctx, device_registry=device_registry, area_synonyms=area_synonyms
        )
        validate_with_schema(pred_validated, validated_schema)

        if pred_validated != rec["expected_validated"]:
            mismatches += 1

    print(f"gold records: {len(dataset)}, mismatches: {mismatches}")
    return 0 if mismatches == 0 else 2




def _cmd_validate_dataset(paths: AssetPaths, dataset_path: Path) -> int:
    """Validate that a dataset jsonl conforms to schemas and validator produces schema-ok outputs."""
    records = load_jsonl(dataset_path)
    parsed_schema = load_schema(paths.parsed_schema)
    validated_schema = load_schema(paths.validated_schema)

    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)

    ok = 0
    for r in records:
        # schema checks for expected objects
        validate_with_schema(r["expected_parsed"], parsed_schema)
        validate_with_schema(r["expected_validated"], validated_schema)

        # re-run validator and ensure it remains schema-ok
        out = validate_parsed_command(
            r["expected_parsed"],
            context=r.get("context") or {},
            device_registry=device_registry,
            area_synonyms=area_synonyms,
        )
        validate_with_schema(out, validated_schema)
        ok += 1

    print(f"OK: validated {ok} records in {dataset_path}")
    return 0
def _cmd_smoke(paths: AssetPaths) -> int:
    # Runs validator on the first 5 gold examples and prints execution plans
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    dataset = load_jsonl(paths.gold_dataset)[:5]

    for rec in dataset:
        pred = validate_parsed_command(
            rec["expected_parsed"],
            context=rec.get("context") or {"last_area_name": None},
            device_registry=device_registry,
            area_synonyms=area_synonyms,
        )
        print(f"\n{rec['id']} | {rec['text']}")
        print(json.dumps(pred, ensure_ascii=False, indent=2))

    return 0


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "command",
        choices=[
            "schema-check",
            "smoke",
            "validate-gold",
            # compact aliases
            "eval",
            "eval-nlu",
            "eval-val",
            "eval-e2e",
            # Compatibility aliases
            "eval-all",
            "eval-parsed",
            "eval-validated",
            "eval-pipeline",
            "make-smoke-set",
            "ha-dry-run",
            "ha-exec",
        ],
    )
    parser.add_argument("--root", type=str, default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--reports-dir", type=str, default="reports")
    parser.add_argument(
        "--dataset",
        type=str,
        default=None,
        help="override dataset jsonl path (default: data/light_gold_dual_v1.jsonl)",
    )

    # HA execution flags (used by ha-dry-run / ha-exec)
    parser.add_argument(
        "--text",
        type=str,
        default=None,
        help="utterance to parse/execute (for ha-* commands)",
    )
    parser.add_argument(
        "--ha-url",
        type=str,
        default="http://homeassistant.local:8123",
        help="Home Assistant base URL",
    )
    parser.add_argument(
        "--ha-token-env",
        type=str,
        default="HA_TOKEN",
        help="Env var name that contains HA token",
    )
    parser.add_argument(
        "--ha-color-temp-unit",
        type=str,
        default="kelvin",
        choices=["kelvin", "mireds"],
        help="Send color temp in this unit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Do not call HA; only print planned calls",
    )

    # Parser selection
    # Canonical: rules | llm | llm_safe
    # Legacy: rule | llm_only | llm_fallback
    parser.add_argument(
        "--parser-mode",
        type=str,
        default="rules",
        choices=["rules", "llm", "llm_safe", "rule", "llm_only", "llm_fallback"],
    )
    parser.add_argument("--llm-backend", type=str, default="stub", choices=["stub", "openai_compat"])
    parser.add_argument("--llm-base-url", type=str, default="http://127.0.0.1:8000")
    parser.add_argument("--llm-model", type=str, default="local-model")
    parser.add_argument("--llm-api-key", type=str, default=None)

    args = parser.parse_args()

    def _canonical_parser_mode(mode: str) -> str:
        m = (mode or "rules").strip().lower()
        if m == "rule":
            return "rules"
        if m == "llm_only":
            return "llm"
        if m == "llm_fallback":
            return "llm_safe"
        return m

    def _canonical_command(cmd: str) -> str:
        c = (cmd or "").strip().lower()
        mapping = {
            "eval": "eval",
            "eval-all": "eval",
            "eval-nlu": "eval-nlu",
            "eval-parsed": "eval-nlu",
            "eval-val": "eval-val",
            "eval-validated": "eval-val",
            "eval-e2e": "eval-e2e",
            "eval-pipeline": "eval-e2e",
        }
        return mapping.get(c, c)

    paths = AssetPaths(Path(args.root))
    dataset_path = Path(args.dataset) if args.dataset else paths.gold_dataset
    reports_dir = Path(args.root) / args.reports_dir

    cmd = _canonical_command(args.command)
    mode = _canonical_parser_mode(args.parser_mode)

    def _make_llm_client():
        if args.llm_backend == "stub":
            return StubClient()
        if args.llm_backend == "openai_compat":
            return OpenAICompatibleClient(
                base_url=args.llm_base_url,
                api_key=args.llm_api_key,
                model=args.llm_model,
            )
        raise ValueError(f"Unknown llm backend: {args.llm_backend}")

    llm_client = _make_llm_client() if mode in {"llm", "llm_safe"} else None

    if cmd == "schema-check":
        raise SystemExit(_cmd_schema_check(paths))

    if cmd == "smoke":
        raise SystemExit(_cmd_smoke(paths))

    if cmd == "validate-gold":
        raise SystemExit(_cmd_validate_dataset(paths, dataset_path))

    if cmd == "eval-nlu":
        device_registry = load_json(paths.device_registry)
        area_synonyms = load_json(paths.area_synonyms)
        colors = load_json(paths.colors)
        modifiers = load_json(paths.modifiers)
        parsed_schema = load_schema(paths.parsed_schema)

        eval_parsed_on_dataset(
            dataset_jsonl=dataset_path,
            out_eval_json=reports_dir / f"nlu_parsed.{mode}.json",
            out_failures_jsonl=reports_dir / f"nlu_parsed_fail.{mode}.jsonl",
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
            parsed_schema=parsed_schema,
            parser_mode=mode,
            llm_client=llm_client,
        )
        print("Wrote:", reports_dir / f"nlu_parsed.{mode}.json")
        print("Wrote:", reports_dir / f"nlu_parsed_fail.{mode}.jsonl")
        raise SystemExit(0)

    if cmd == "eval-val":
        device_registry = load_json(paths.device_registry)
        area_synonyms = load_json(paths.area_synonyms)
        validated_schema = load_schema(paths.validated_schema)

        eval_validated_on_dataset(
            dataset_jsonl=dataset_path,
            out_eval_json=reports_dir / "validator.json",
            out_failures_jsonl=reports_dir / "validator_fail.jsonl",
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            validated_schema=validated_schema,
        )
        print("Wrote:", reports_dir / "validator.json")
        print("Wrote:", reports_dir / "validator_fail.jsonl")
        raise SystemExit(0)

    if cmd == "eval-e2e":
        device_registry = load_json(paths.device_registry)
        area_synonyms = load_json(paths.area_synonyms)
        colors = load_json(paths.colors)
        modifiers = load_json(paths.modifiers)
        parsed_schema = load_schema(paths.parsed_schema)
        validated_schema = load_schema(paths.validated_schema)

        eval_pipeline_on_dataset(
            dataset_jsonl=dataset_path,
            out_eval_json=reports_dir / f"nlu_e2e.{mode}.json",
            out_failures_jsonl=reports_dir / f"nlu_e2e_fail.{mode}.jsonl",
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
            parsed_schema=parsed_schema,
            validated_schema=validated_schema,
            parser_mode=mode,
            llm_client=llm_client,
        )
        print("Wrote:", reports_dir / f"nlu_e2e.{mode}.json")
        print("Wrote:", reports_dir / f"nlu_e2e_fail.{mode}.jsonl")
        raise SystemExit(0)

    if cmd == "eval":
        device_registry = load_json(paths.device_registry)
        area_synonyms = load_json(paths.area_synonyms)
        colors = load_json(paths.colors)
        modifiers = load_json(paths.modifiers)
        parsed_schema = load_schema(paths.parsed_schema)
        validated_schema = load_schema(paths.validated_schema)

        eval_parsed_on_dataset(
            dataset_jsonl=dataset_path,
            out_eval_json=reports_dir / f"nlu_parsed.{mode}.json",
            out_failures_jsonl=reports_dir / f"nlu_parsed_fail.{mode}.jsonl",
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
            parsed_schema=parsed_schema,
            parser_mode=mode,
            llm_client=llm_client,
        )
        eval_validated_on_dataset(
            dataset_jsonl=dataset_path,
            out_eval_json=reports_dir / "validator.json",
            out_failures_jsonl=reports_dir / "validator_fail.jsonl",
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            validated_schema=validated_schema,
        )
        eval_pipeline_on_dataset(
            dataset_jsonl=dataset_path,
            out_eval_json=reports_dir / f"nlu_e2e.{mode}.json",
            out_failures_jsonl=reports_dir / f"nlu_e2e_fail.{mode}.jsonl",
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
            parsed_schema=parsed_schema,
            validated_schema=validated_schema,
            parser_mode=mode,
            llm_client=llm_client,
        )
        print("Wrote:", reports_dir / f"nlu_parsed.{mode}.json")
        print("Wrote:", reports_dir / "validator.json")
        print("Wrote:", reports_dir / f"nlu_e2e.{mode}.json")
        raise SystemExit(0)

    if cmd in {"ha-dry-run", "ha-exec"}:
        if not args.text:
            print("ERROR: --text is required for ha-* commands")
            raise SystemExit(2)

        from .pipeline import run_light_pipeline_v1
        from .executor_ha import execute_validated_on_ha, build_service_calls_from_validated, ExecutionConfig
        from .ha_client import HomeAssistantClient

        device_registry = load_json(paths.device_registry)
        area_synonyms = load_json(paths.area_synonyms)
        colors = load_json(paths.colors)
        modifiers = load_json(paths.modifiers)

        mode = _canonical_parser_mode(args.parser_mode)
        parsed_schema = load_schema(paths.parsed_schema)
        llm_client = _make_llm_client() if mode in {"llm", "llm_safe"} else None

        # Run NLU pipeline
        result = run_light_pipeline_v1(
            args.text,
            context={"last_area_name": None, "last_entity_ids": []},
            root_dir=args.root,
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
            parser_mode=mode,
            llm_client=llm_client,
            parsed_schema=parsed_schema,
        )

        if result.validated is None:
            # Needs clarification at PARSED stage
            print(json.dumps({"stage": result.stage, "parsed": result.parsed}, ensure_ascii=False, indent=2))
            raise SystemExit(0)

        import os

        dry_run = bool(args.dry_run or cmd == "ha-dry-run")
        exec_cfg = ExecutionConfig(color_temp_unit=args.ha_color_temp_unit, dry_run=dry_run)

        token_env = str(args.ha_token_env or "HA_TOKEN")
        token = os.environ.get(token_env) or ""

        if dry_run:
            calls, errors = build_service_calls_from_validated(
                result.validated, device_registry=device_registry, client=None, cfg=exec_cfg
            )
            print(json.dumps({"ok": len(errors) == 0, "calls": calls, "errors": errors}, ensure_ascii=False, indent=2))
            raise SystemExit(0)

        if not token:
            print(f"ERROR: HA token not found in env var {token_env!r}. Set it and retry.")
            raise SystemExit(2)

        client = HomeAssistantClient(base_url=args.ha_url, token=token)
        exec_res = execute_validated_on_ha(result.validated, device_registry=device_registry, client=client, cfg=exec_cfg)

        print(
            json.dumps(
                {
                    "ok": exec_res.ok,
                    "calls": exec_res.calls,
                    "errors": exec_res.errors,
                    "results_count": len(exec_res.results),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        raise SystemExit(0)

    if cmd == "make-smoke-set":
        ids = [
            "L001",
            "L002",
            "L005",
            "L006",
            "L009",
            "L010",
            "L014",
            "L015",
            "L018",
            "L020",
            "L046",
            "L062",
            "L021",
            "L045",
            "L044",
        ]
        out_path = Path(args.root) / "tests" / "smoke.jsonl"
        make_smoke_subset(dataset_jsonl=dataset_path, out_jsonl=out_path, ids=ids)
        print("Wrote:", out_path)
        raise SystemExit(0)

    raise SystemExit(2)


if __name__ == "__main__":
    main()
