import json
from pathlib import Path

import pytest

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json, load_jsonl
from smarthome_core.pipeline import run_light_pipeline_v1


@pytest.fixture(scope="session")
def paths() -> AssetPaths:
    return AssetPaths(Path(__file__).resolve().parents[1])


def _pretty(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2)


def test_pipeline_matches_gold_validated_when_no_clarification(paths: AssetPaths) -> None:
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)

    dataset = load_jsonl(paths.gold_dataset)

    for rec in dataset:
        res = run_light_pipeline_v1(
            rec["text"],
            context=rec.get("context"),
            root_dir=paths.root,
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
        )

        if rec["expected_parsed"].get("clarification") is not None:
            assert res.stage == "PARSED_CLARIFICATION"
            assert res.validated is None
            assert res.parsed == rec["expected_parsed"], (
                f"Parsed mismatch for {rec['id']} | {rec['text']}\n"
                f"--- got ---\n{_pretty(res.parsed)}\n"
                f"--- exp ---\n{_pretty(rec['expected_parsed'])}\n"
            )
        else:
            assert res.stage == "VALIDATED"
            assert res.validated is not None
            assert res.parsed == rec["expected_parsed"]
            assert res.validated == rec["expected_validated"], (
                f"Validated mismatch for {rec['id']} | {rec['text']}\n"
                f"--- got ---\n{_pretty(res.validated)}\n"
                f"--- exp ---\n{_pretty(rec['expected_validated'])}\n"
            )
