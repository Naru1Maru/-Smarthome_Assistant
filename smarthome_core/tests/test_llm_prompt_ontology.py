from __future__ import annotations

import json
from pathlib import Path

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json
from smarthome_core.parser_llm import (
    LLM_MAX_OUTPUT_TOKENS,
    LLMParserV1,
    _build_llm_prompt_payload,
)
from smarthome_core.schema_utils import load_schema


def _repo_assets() -> tuple[AssetPaths, dict, dict, dict, dict, dict, dict]:
    repo_root = Path(__file__).resolve().parents[1]
    paths = AssetPaths(repo_root)
    parsed_schema = load_schema(paths.parsed_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)
    return paths, parsed_schema, device_registry, area_synonyms, colors, modifiers, scene_aliases


def test_build_prompt_payload_selects_relevant_color_and_brightness_knowledge() -> None:
    _, _, _, area_synonyms, colors, modifiers, scene_aliases = _repo_assets()

    payload = _build_llm_prompt_payload(
        "сделай в спальне свет синим и чуть ярче",
        context={"last_area_name": None},
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    knowledge = payload["knowledge"]
    assert "goal_contract" in payload
    assert "decision_policy" in payload
    assert "modifier_keys" not in payload
    assert "rules" not in payload

    rgb_colors = knowledge["color"]["rgb_colors"]
    assert any(entry["name"] == "синий" for entry in rgb_colors)
    assert len(rgb_colors) <= 4

    brighter = knowledge["brightness"]["brighter"]
    assert any(item["brightness_delta"] > 0 for item in brighter)
    assert any("чуть ярче" in " ".join(item["trigger"]) for item in brighter)


def test_build_prompt_payload_keeps_plain_turn_off_request_compact() -> None:
    _, _, _, area_synonyms, colors, modifiers, scene_aliases = _repo_assets()

    payload = _build_llm_prompt_payload(
        "выключи свет",
        context={"last_area_name": None},
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    assert payload["knowledge"] == {}
    assert payload["intent_hint"]["primary_goal_type"] == "TURN_OFF"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert len(serialized) < 2100


def test_build_prompt_payload_includes_carryover_examples_for_short_contextual_commands() -> None:
    _, _, _, area_synonyms, colors, modifiers, scene_aliases = _repo_assets()

    payload = _build_llm_prompt_payload(
        "выключи свет",
        context={"selected_area_name": "Спальня", "last_area_name": "Гостиная"},
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    examples = payload["carryover_examples"]
    assert examples[0]["expected_goal_type"] == "TURN_OFF"
    assert examples[0]["expected_area_name"] == "Спальня"
    assert payload["context"]["selected_area_name"] == "Спальня"
    assert any("context.selected_area_name" in rule for rule in payload["decision_policy"])


def test_build_prompt_payload_includes_white_disambiguation_for_white_command() -> None:
    _, _, _, area_synonyms, colors, modifiers, scene_aliases = _repo_assets()

    payload = _build_llm_prompt_payload(
        "сделай белый свет",
        context={"last_area_name": None},
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    color_knowledge = payload["knowledge"]["color"]
    assert "white_disambiguation" in color_knowledge
    assert any("бел" in entry["name"].lower() for entry in color_knowledge["rgb_colors"])


def test_llm_parser_uses_reduced_output_token_budget() -> None:
    _, parsed_schema, device_registry, area_synonyms, colors, modifiers, scene_aliases = _repo_assets()

    class SpyClient:
        def __init__(self) -> None:
            self.max_tokens: int | None = None
            self.json_schema: dict | None = None
            self.user: str | None = None

        def generate_json(
            self,
            *,
            system: str,
            user: str,
            temperature: float = 0.0,
            max_tokens: int = 512,
            json_schema: dict | None = None,
        ) -> str:
            self.max_tokens = max_tokens
            self.json_schema = json_schema
            self.user = user
            return (
                '{"schema_version":"1.0","goal_type":"TURN_OFF","scene_id":null,'
                '"target":{"scope":"UNSPECIFIED","area_name":null,"entity_ids":[]},'
                '"params":{"brightness":null,"brightness_delta":null,"color_name":null,'
                '"color_rgb":null,"color_temp_kelvin":null,"color_temp_delta_k":null,"transition_s":null}}'
            )

    spy = SpyClient()
    parser = LLMParserV1(client=spy, parsed_schema=parsed_schema, fallback_to_rules=False)
    parser.parse(
        "выключи свет",
        context={"last_area_name": "Спальня"},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    assert spy.max_tokens == LLM_MAX_OUTPUT_TOKENS
    assert spy.json_schema is not None
    goal_types = spy.json_schema["properties"]["goal_type"]["enum"]
    assert "UNKNOWN" in goal_types
    assert "MOOD_SCENE" in goal_types
    assert spy.user is not None
    assert '": ' not in spy.user


def test_llm_parser_resolves_scene_goal_into_turn_on_action() -> None:
    _, parsed_schema, device_registry, area_synonyms, colors, modifiers, scene_aliases = _repo_assets()

    class SceneClient:
        def generate_json(
            self,
            *,
            system: str,
            user: str,
            temperature: float = 0.0,
            max_tokens: int = 512,
            json_schema: dict | None = None,
        ) -> str:
            return (
                '{"schema_version":"1.0","goal_type":"MOOD_SCENE","scene_id":"SUNSET",'
                '"target":{"scope":"UNSPECIFIED","area_name":null,"entity_ids":[]},'
                '"params":{"brightness":null,"brightness_delta":null,"color_name":null,'
                '"color_rgb":null,"color_temp_kelvin":null,"color_temp_delta_k":null,"transition_s":null}}'
            )

    parser = LLMParserV1(client=SceneClient(), parsed_schema=parsed_schema, fallback_to_rules=False)
    parsed = parser.parse(
        "сделай как в закате",
        context={"last_area_name": "Спальня"},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    action = parsed["actions"][0]
    assert action["intent"] == "TURN_ON"
    assert action["target"]["area_name"] == "Спальня"
    assert action["params"]["brightness"] == 38
    assert action["params"]["color_temp_kelvin"] == 2600


def test_llm_parser_uses_scene_id_even_when_goal_type_is_not_mood_scene() -> None:
    _, parsed_schema, device_registry, area_synonyms, colors, modifiers, scene_aliases = _repo_assets()

    class SceneOverrideClient:
        def generate_json(
            self,
            *,
            system: str,
            user: str,
            temperature: float = 0.0,
            max_tokens: int = 512,
            json_schema: dict | None = None,
        ) -> str:
            return (
                '{"schema_version":"1.0","goal_type":"ADJUST_BRIGHTNESS","scene_id":"SOFT_COMFORT",'
                '"target":{"scope":"ALL_LIGHTS","area_name":null,"entity_ids":[]},'
                '"params":{"brightness":null,"brightness_delta":-20,"color_name":null,'
                '"color_rgb":null,"color_temp_kelvin":3000,"color_temp_delta_k":null,"transition_s":null}}'
            )

    parser = LLMParserV1(client=SceneOverrideClient(), parsed_schema=parsed_schema, fallback_to_rules=False)
    parsed = parser.parse(
        "сделай свет поприятнее, но не режь глаза",
        context={"last_area_name": "Спальня"},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    action = parsed["actions"][0]
    assert action["intent"] == "TURN_ON"
    assert action["target"]["area_name"] == "Спальня"
    assert action["params"]["brightness"] == 12
    assert action["params"]["color_temp_kelvin"] == 3000


def test_llm_parser_can_recover_scene_when_goal_type_is_unknown_but_scene_id_exists() -> None:
    _, parsed_schema, device_registry, area_synonyms, colors, modifiers, scene_aliases = _repo_assets()

    class UnknownSceneClient:
        def generate_json(
            self,
            *,
            system: str,
            user: str,
            temperature: float = 0.0,
            max_tokens: int = 512,
            json_schema: dict | None = None,
        ) -> str:
            return (
                '{"schema_version":"1.0","goal_type":"UNKNOWN","scene_id":"SUNSET",'
                '"target":{"scope":"UNSPECIFIED","area_name":null,"entity_ids":[]},'
                '"params":{"brightness":null,"brightness_delta":null,"color_name":null,'
                '"color_rgb":null,"color_temp_kelvin":null,"color_temp_delta_k":null,"transition_s":null},'
                '"clarification":{"needed":true,"question":"Я не смог понять команду.","options":[]}}'
            )

    parser = LLMParserV1(client=UnknownSceneClient(), parsed_schema=parsed_schema, fallback_to_rules=False)
    parsed = parser.parse(
        "сделай как в закате",
        context={"last_area_name": "Спальня"},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    action = parsed["actions"][0]
    assert parsed.get("clarification") is None
    assert action["intent"] == "TURN_ON"
    assert action["target"]["area_name"] == "Спальня"
    assert action["params"]["brightness"] == 38
    assert action["params"]["color_temp_kelvin"] == 2600
