from __future__ import annotations

import pathlib

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json
from smarthome_core.parser_llm import LLMParserV1, _extract_explicit_area_from_text
from smarthome_core.schema_utils import load_schema


TURN_OFF_WITH_ROOM = "\u0432\u044b\u043a\u043b\u044e\u0447\u0438 \u0441\u0432\u0435\u0442 \u0432 \u0441\u043f\u0430\u043b\u044c\u043d\u0435"
TURN_OFF_SHORT = "\u0432\u044b\u043a\u043b\u044e\u0447\u0438 \u0441\u0432\u0435\u0442"
BEDROOM = "\u0421\u043f\u0430\u043b\u044c\u043d\u044f"


class UnknownClient:
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
            '{"schema_version":"1.0","goal_type":"UNKNOWN","scene_id":null,'
            '"target":{"scope":"UNSPECIFIED","area_name":null,"entity_ids":[]},'
            '"params":{"brightness":null,"brightness_delta":null,"color_name":null,'
            '"color_rgb":null,"color_temp_kelvin":null,"color_temp_delta_k":null,"transition_s":null},'
            '"clarification":{"needed":true,"question":"clarify","options":[]}}'
        )


class SceneWithoutTargetClient:
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


class FreeformClarificationClient:
    def generate_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_schema: dict | None = None,
    ) -> str:
        return "Я не смог понять команду. Скажи иначе."


class TurnOffAllLightsAreaClient:
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
            '{"schema_version":"1.0","goal_type":"TURN_OFF","scene_id":null,'
            '"target":{"scope":"ALL_LIGHTS","area_name":"Спальня","entity_ids":[]},'
            '"params":{"brightness":null,"brightness_delta":null,"color_name":null,'
            '"color_rgb":null,"color_temp_kelvin":null,"color_temp_delta_k":null,"transition_s":null}}'
        )


class SceneAllLightsAreaClient:
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
            '{"schema_version":"1.0","goal_type":"MOOD_SCENE","scene_id":"CINEMA",'
            '"target":{"scope":"ALL_LIGHTS","area_name":"Спальня","entity_ids":[]},'
            '"params":{"brightness":18,"brightness_delta":null,"color_name":null,'
            '"color_rgb":null,"color_temp_kelvin":2700,"color_temp_delta_k":-400,"transition_s":null}}'
        )


class ColorAllLightsAreaClient:
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
            '{"schema_version":"1.0","goal_type":"TURN_ON","scene_id":null,'
            '"target":{"scope":"ALL_LIGHTS","area_name":"Спальня","entity_ids":[]},'
            '"params":{"brightness":32,"brightness_delta":null,"color_name":"розовый",'
            '"color_rgb":[255,80,180],"color_temp_kelvin":null,"color_temp_delta_k":null,"transition_s":null}}'
        )


def _load_assets():
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    paths = AssetPaths(repo_root)
    return {
        "parsed_schema": load_schema(paths.parsed_schema),
        "device_registry": load_json(paths.device_registry),
        "area_synonyms": load_json(paths.area_synonyms),
        "colors": load_json(paths.colors),
        "modifiers": load_json(paths.modifiers),
        "scene_aliases": load_json(paths.scene_aliases),
    }


def test_llm_parser_recovers_explicit_turn_off_with_room_when_model_returns_unknown():
    assets = _load_assets()
    parser = LLMParserV1(client=UnknownClient(), parsed_schema=assets["parsed_schema"], fallback_to_rules=False)
    parsed = parser.parse(
        TURN_OFF_WITH_ROOM,
        context={},
        device_registry=assets["device_registry"],
        area_synonyms=assets["area_synonyms"],
        colors=assets["colors"],
        modifiers=assets["modifiers"],
        scene_aliases=assets["scene_aliases"],
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["intent"] == "TURN_OFF"
    assert parsed["actions"][0]["target"]["area_name"] == BEDROOM


def test_llm_parser_recovers_short_turn_off_from_selected_area_when_model_returns_unknown():
    assets = _load_assets()
    parser = LLMParserV1(client=UnknownClient(), parsed_schema=assets["parsed_schema"], fallback_to_rules=False)
    parsed = parser.parse(
        TURN_OFF_SHORT,
        context={"selected_area_name": BEDROOM},
        device_registry=assets["device_registry"],
        area_synonyms=assets["area_synonyms"],
        colors=assets["colors"],
        modifiers=assets["modifiers"],
        scene_aliases=assets["scene_aliases"],
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["intent"] == "TURN_OFF"
    assert parsed["actions"][0]["target"]["area_name"] == BEDROOM


def test_llm_scene_defaults_prefer_selected_area_name():
    assets = _load_assets()
    parser = LLMParserV1(client=SceneWithoutTargetClient(), parsed_schema=assets["parsed_schema"], fallback_to_rules=False)
    parsed = parser.parse(
        "\u0441\u0434\u0435\u043b\u0430\u0439 \u0441\u0432\u0435\u0442 \u043a\u0430\u043a \u0432 \u0437\u0430\u043a\u0430\u0442\u0435",
        context={"selected_area_name": BEDROOM, "last_area_name": "\u0413\u043e\u0441\u0442\u0438\u043d\u0430\u044f"},
        device_registry=assets["device_registry"],
        area_synonyms=assets["area_synonyms"],
        colors=assets["colors"],
        modifiers=assets["modifiers"],
        scene_aliases=assets["scene_aliases"],
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["intent"] == "TURN_ON"
    assert parsed["actions"][0]["target"]["area_name"] == BEDROOM


def test_area_extractor_does_not_confuse_rezal_with_gostinaya():
    assets = _load_assets()
    text = "\u0441\u0434\u0435\u043b\u0430\u0439 \u0441\u0432\u0435\u0442 \u043f\u043e\u043f\u0440\u0438\u044f\u0442\u043d\u0435\u0435, \u0447\u0442\u043e\u0431\u044b \u043d\u0435 \u0440\u0435\u0437\u0430\u043b \u0433\u043b\u0430\u0437\u0430"
    assert _extract_explicit_area_from_text(text, assets["area_synonyms"]) is None


def test_llm_parser_recovers_short_turn_off_from_freeform_clarification():
    assets = _load_assets()
    parser = LLMParserV1(client=FreeformClarificationClient(), parsed_schema=assets["parsed_schema"], fallback_to_rules=False)
    parsed = parser.parse(
        TURN_OFF_SHORT,
        context={"selected_area_name": BEDROOM},
        device_registry=assets["device_registry"],
        area_synonyms=assets["area_synonyms"],
        colors=assets["colors"],
        modifiers=assets["modifiers"],
        scene_aliases=assets["scene_aliases"],
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["intent"] == "TURN_OFF"
    assert parsed["actions"][0]["target"]["area_name"] == BEDROOM


def test_llm_parser_recovers_color_turn_on_from_freeform_clarification():
    assets = _load_assets()
    parser = LLMParserV1(client=FreeformClarificationClient(), parsed_schema=assets["parsed_schema"], fallback_to_rules=False)
    parsed = parser.parse(
        "\u0432\u043a\u043b\u044e\u0447\u0438 \u043c\u044f\u0433\u043a\u0438\u0439 \u0440\u043e\u0437\u043e\u0432\u044b\u0439 \u0441\u0432\u0435\u0442",
        context={"selected_area_name": BEDROOM},
        device_registry=assets["device_registry"],
        area_synonyms=assets["area_synonyms"],
        colors=assets["colors"],
        modifiers=assets["modifiers"],
        scene_aliases=assets["scene_aliases"],
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["intent"] == "TURN_ON"
    assert parsed["actions"][0]["target"]["area_name"] == BEDROOM
    assert parsed["actions"][0]["params"]["color"] is not None


def test_llm_parser_recovers_scene_from_freeform_clarification():
    assets = _load_assets()
    parser = LLMParserV1(client=FreeformClarificationClient(), parsed_schema=assets["parsed_schema"], fallback_to_rules=False)
    parsed = parser.parse(
        "\u043d\u0430\u0441\u0442\u0440\u043e\u0439 \u0441\u0432\u0435\u0442 \u043a\u0430\u043a \u0432 \u043a\u0438\u043d\u043e\u0442\u0435\u0430\u0442\u0440\u0435, \u0442\u043e\u043b\u044c\u043a\u043e \u0447\u0443\u0442\u044c \u0442\u0435\u043f\u043b\u0435\u0435",
        context={"selected_area_name": BEDROOM},
        device_registry=assets["device_registry"],
        area_synonyms=assets["area_synonyms"],
        colors=assets["colors"],
        modifiers=assets["modifiers"],
        scene_aliases=assets["scene_aliases"],
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["intent"] == "TURN_ON"
    assert parsed["actions"][0]["target"]["area_name"] == BEDROOM


def test_llm_parser_normalizes_all_lights_with_area_for_turn_off():
    assets = _load_assets()
    parser = LLMParserV1(client=TurnOffAllLightsAreaClient(), parsed_schema=assets["parsed_schema"], fallback_to_rules=False)
    parsed = parser.parse(
        TURN_OFF_SHORT,
        context={"selected_area_name": BEDROOM},
        device_registry=assets["device_registry"],
        area_synonyms=assets["area_synonyms"],
        colors=assets["colors"],
        modifiers=assets["modifiers"],
        scene_aliases=assets["scene_aliases"],
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["intent"] == "TURN_OFF"
    assert parsed["actions"][0]["target"]["scope"] == "AREA"
    assert parsed["actions"][0]["target"]["area_name"] == BEDROOM


def test_llm_parser_normalizes_all_lights_with_area_for_scene():
    assets = _load_assets()
    parser = LLMParserV1(client=SceneAllLightsAreaClient(), parsed_schema=assets["parsed_schema"], fallback_to_rules=False)
    parsed = parser.parse(
        "\u043d\u0430\u0441\u0442\u0440\u043e\u0439 \u0441\u0432\u0435\u0442 \u043a\u0430\u043a \u0432 \u043a\u0438\u043d\u043e\u0442\u0435\u0430\u0442\u0440\u0435, \u0442\u043e\u043b\u044c\u043a\u043e \u0447\u0443\u0442\u044c \u0442\u0435\u043f\u043b\u0435\u0435",
        context={"selected_area_name": BEDROOM},
        device_registry=assets["device_registry"],
        area_synonyms=assets["area_synonyms"],
        colors=assets["colors"],
        modifiers=assets["modifiers"],
        scene_aliases=assets["scene_aliases"],
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["intent"] == "TURN_ON"
    assert parsed["actions"][0]["target"]["scope"] == "AREA"
    assert parsed["actions"][0]["target"]["area_name"] == BEDROOM


def test_llm_parser_normalizes_all_lights_with_area_for_color_turn_on():
    assets = _load_assets()
    parser = LLMParserV1(client=ColorAllLightsAreaClient(), parsed_schema=assets["parsed_schema"], fallback_to_rules=False)
    parsed = parser.parse(
        "\u0432\u043a\u043b\u044e\u0447\u0438 \u043c\u044f\u0433\u043a\u0438\u0439 \u0440\u043e\u0437\u043e\u0432\u044b\u0439 \u0441\u0432\u0435\u0442",
        context={"selected_area_name": BEDROOM},
        device_registry=assets["device_registry"],
        area_synonyms=assets["area_synonyms"],
        colors=assets["colors"],
        modifiers=assets["modifiers"],
        scene_aliases=assets["scene_aliases"],
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["intent"] == "TURN_ON"
    assert parsed["actions"][0]["target"]["scope"] == "AREA"
    assert parsed["actions"][0]["target"]["area_name"] == BEDROOM
