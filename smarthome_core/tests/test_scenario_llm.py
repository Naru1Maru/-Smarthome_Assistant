from __future__ import annotations

import json
from pathlib import Path

from smarthome_core.io import load_json
from smarthome_core.scenario_llm import (
    ScenarioAuthoringLLMParser,
    _collect_scene_hints,
    _build_scenario_prompt_payload,
    _infer_lighting_params,
    _normalize_scenario_bundle,
    _try_load_json_object,
    run_scenario_authoring_pipeline_v1,
)


ROOT = Path(__file__).resolve().parents[1]


class ScenarioStubClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.calls: list[dict] = []

    def generate_json(self, *, system: str, user: str, temperature: float = 0.0, max_tokens: int = 512, json_schema=None) -> str:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "json_schema": json_schema,
            }
        )
        return json.dumps(self.payload, ensure_ascii=False)


def test_build_scenario_prompt_payload_contains_contract_and_context() -> None:
    device_registry = load_json(ROOT / "registry/device_registry_v1.json")
    scene_aliases = load_json(ROOT / "lexicon/scene_aliases_v1.json")
    colors = load_json(ROOT / "lexicon/colors_v1.json")
    modifiers = load_json(ROOT / "lexicon/modifiers_v1.json")
    payload = _build_scenario_prompt_payload(
        "каждый день в 20:00 включай в спальне тёплый свет",
        context={"selected_area_name": "Спальня", "last_area_name": "Спальня", "last_entity_ids": []},
        device_registry=device_registry,
        scene_aliases=scene_aliases,
        colors=colors,
        modifiers=modifiers,
    )

    assert payload["utterance"].startswith("каждый день")
    assert payload["context"]["selected_area_name"] == "Спальня"
    assert "supported_triggers" in payload["scenario_contract"]
    assert any(item["area_name"] == "Спальня" for item in payload["known_targets"])
    assert payload["lighting_knowledge"]["color"]["white_profiles"][0]["color_temp_kelvin"] == 2700


def test_run_scenario_authoring_pipeline_compiles_stub_bundle() -> None:
    stub_payload = {
        "schema_version": "1.0",
        "title": "Ночной сценарий",
        "description": None,
        "clarification": {"needed": False, "question": None, "missing_fields": []},
        "rules": [
            {
                "rule_id": "night_off",
                "title": "Выключить свет",
                "enabled": True,
                "trigger": {"type": "time", "at": "00:00"},
                "conditions": [],
                "actions": [
                    {
                        "domain": "light",
                        "intent": "TURN_OFF",
                        "target": {"scope": "UNSPECIFIED", "area_name": None, "entity_ids": []},
                        "params": {
                            "brightness": None,
                            "brightness_delta": None,
                            "color": None,
                            "color_temp_kelvin": None,
                            "color_temp_delta_k": None,
                            "transition_s": 0.5,
                        },
                    }
                ],
                "else_actions": [],
            }
        ],
    }
    client = ScenarioStubClient(stub_payload)
    result = run_scenario_authoring_pipeline_v1(
        "в полночь выключай свет",
        llm_client=client,
        context={"selected_area_name": "Спальня", "last_area_name": "Спальня", "last_entity_ids": []},
        root_dir=ROOT,
    )

    assert result.stage == "VALIDATED"
    assert result.validated is not None
    assert result.automations is not None
    assert result.automations[0]["action"][0]["target"]["entity_id"] == ["light.lampa1"]
    assert client.calls


def test_scenario_parser_accepts_clarification_bundle() -> None:
    client = ScenarioStubClient(
        {
            "schema_version": "1.0",
            "title": None,
            "description": None,
            "clarification": {
                "needed": True,
                "question": "Для какой комнаты создать сценарий?",
                "missing_fields": ["area_name"],
            },
            "rules": [],
        }
    )
    parser = ScenarioAuthoringLLMParser(client=client)
    parsed = parser.parse(
        "вечером включай уютный свет",
        context={"selected_area_name": None, "last_area_name": None, "last_entity_ids": []},
        root_dir=ROOT,
    )

    assert parsed["clarification"]["needed"] is True
    assert parsed["rules"] == []


def test_collect_scene_hints_returns_only_relevant_scenes() -> None:
    scene_aliases = load_json(ROOT / "lexicon/scene_aliases_v1.json")
    hints = _collect_scene_hints("сделай свет как в закате", scene_aliases)

    assert hints
    assert any(item["id"] == "SUNSET" for item in hints)

    no_hints = _collect_scene_hints("каждый день в 20:00 включай свет на 40 процентов", scene_aliases)
    assert no_hints == []


def test_try_load_json_object_recovers_from_malformed_model_output() -> None:
    raw = """
```json
{"schema_version":"1.0","title":"Вечерний свет","rules":[{"rule_id":"evening_on","title":"Включить","enabled":true,"trigger":{"type":"time","at":"20:00"},"conditions":[],"actions":[{"domain":"light","intent":"TURN_ON","target":{"scope":"AREA","area_name":"Спальня","entity_ids":[]},"params":{"brightness":35,"brightness_delta":null,"color":null,"color_temp_kelvin":2800,"color_temp_delta_k":null,"transition_s":1.0}}],"else_actions":[]},],"clarification":{"needed":false,"question":null,"missing_fields":[]}}
```
"""
    parsed = _try_load_json_object(raw)

    assert parsed is not None
    assert parsed["title"] == "Вечерний свет"
    assert parsed["rules"][0]["trigger"]["at"] == "20:00"


def test_normalize_scenario_bundle_splits_two_time_schedule_and_fixes_area() -> None:
    device_registry = load_json(ROOT / "registry/device_registry_v1.json")
    colors = load_json(ROOT / "lexicon/colors_v1.json")
    modifiers = load_json(ROOT / "lexicon/modifiers_v1.json")
    scene_aliases = load_json(ROOT / "lexicon/scene_aliases_v1.json")
    parsed = {
        "schema_version": "1.0",
        "title": "20:00 - 00:00",
        "clarification": {"needed": False, "question": None, "missing_fields": []},
        "rules": [
            {
                "rule_id": "raw",
                "title": "raw",
                "enabled": True,
                "trigger": {"type": "time", "at": "20:00"},
                "conditions": [],
                "actions": [
                    {
                        "domain": "light",
                        "intent": "TURN_ON",
                        "target": {"scope": "AREA", "area_name": "неизвестная", "entity_ids": ["light.fake"]},
                        "params": {
                            "brightness": 40,
                            "brightness_delta": None,
                            "color": None,
                            "color_temp_kelvin": 2800,
                            "color_temp_delta_k": None,
                            "transition_s": 1.0,
                        },
                    },
                    {
                        "domain": "light",
                        "intent": "TURN_OFF",
                        "target": {"scope": "AREA", "area_name": "неизвестная", "entity_ids": ["light.fake"]},
                        "params": {
                            "brightness": None,
                            "brightness_delta": None,
                            "color": None,
                            "color_temp_kelvin": None,
                            "color_temp_delta_k": None,
                            "transition_s": 1.0,
                        },
                    },
                ],
                "else_actions": [
                    {
                        "domain": "light",
                        "intent": "TURN_OFF",
                        "target": {"scope": "AREA", "area_name": "неизвестная", "entity_ids": ["light.fake"]},
                        "params": {
                            "brightness": None,
                            "brightness_delta": None,
                            "color": None,
                            "color_temp_kelvin": None,
                            "color_temp_delta_k": None,
                            "transition_s": 1.0,
                        },
                    }
                ],
            }
        ],
    }

    normalized = _normalize_scenario_bundle(
        parsed,
        text="каждый день в 20:00 включай в спальне тёплый свет, а в 00:00 выключай его",
        context={"selected_area_name": "Спальня", "last_area_name": "Спальня", "last_entity_ids": []},
        device_registry=device_registry,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    assert len(normalized["rules"]) == 2
    assert normalized["rules"][0]["trigger"]["at"] == "20:00"
    assert normalized["rules"][1]["trigger"]["at"] == "00:00"
    assert normalized["rules"][0]["actions"][0]["target"]["area_name"] == "Спальня"
    assert normalized["rules"][0]["actions"][0]["target"]["entity_ids"] == []
    assert normalized["rules"][0]["actions"][0]["params"]["color_temp_kelvin"] == 2800


def test_infer_lighting_params_recovers_warm_light_defaults() -> None:
    colors = load_json(ROOT / "lexicon/colors_v1.json")
    modifiers = load_json(ROOT / "lexicon/modifiers_v1.json")
    scene_aliases = load_json(ROOT / "lexicon/scene_aliases_v1.json")

    params = _infer_lighting_params(
        "каждый день в 20:00 включай в спальне тёплый свет",
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    assert params["color_temp_kelvin"] == 2700
    assert params["color"] is None
