import json
from pathlib import Path

import pytest

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json, load_jsonl
from smarthome_core.schema_utils import load_schema, validate_with_schema
from smarthome_core.validator import validate_parsed_command


@pytest.fixture(scope="session")
def paths() -> AssetPaths:
    return AssetPaths(Path(__file__).resolve().parents[1])


def test_gold_expected_outputs_match_validator(paths: AssetPaths) -> None:
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    parsed_schema = load_schema(paths.parsed_schema)
    validated_schema = load_schema(paths.validated_schema)

    dataset = load_jsonl(paths.gold_dataset)

    for rec in dataset:
        parsed = rec["expected_parsed"]
        ctx = rec.get("context") or {"last_area_name": None}

        # Schema checks for gold files
        validate_with_schema(parsed, parsed_schema)
        validate_with_schema(rec["expected_validated"], validated_schema)

        pred_validated = validate_parsed_command(
            parsed, context=ctx, device_registry=device_registry, area_synonyms=area_synonyms
        )

        # Schema check for produced output
        validate_with_schema(pred_validated, validated_schema)

        assert pred_validated == rec["expected_validated"], f"Mismatch for {rec['id']} | {rec['text']}"
