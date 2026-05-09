import json
from pathlib import Path

import pytest

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json, load_jsonl
from smarthome_core.schema_utils import load_schema, validate_with_schema
from smarthome_core.parser import parse_light_command_v1


@pytest.fixture(scope="session")
def paths() -> AssetPaths:
    return AssetPaths(Path(__file__).resolve().parents[1])


def _pretty(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)


def test_gold_expected_outputs_match_parser(paths: AssetPaths) -> None:
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    parsed_schema = load_schema(paths.parsed_schema)

    dataset = load_jsonl(paths.gold_dataset)

    for rec in dataset:
        ctx = rec.get("context") or {"last_area_name": None}

        pred_parsed = parse_light_command_v1(
            rec["text"],
            context=ctx,
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
        )

        # Schema checks for produced and gold output
        validate_with_schema(pred_parsed, parsed_schema)
        validate_with_schema(rec["expected_parsed"], parsed_schema)

        assert pred_parsed == rec["expected_parsed"], (
            f"Mismatch for {rec['id']} | {rec['text']}\n"
            f"--- predicted ---\n{_pretty(pred_parsed)}\n"
            f"--- expected ---\n{_pretty(rec['expected_parsed'])}\n"
        )
