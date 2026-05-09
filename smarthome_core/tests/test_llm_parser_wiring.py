from __future__ import annotations

from smarthome_core.llm_client import StubClient
from smarthome_core.parser_llm import LLMParserV1, _extract_first_json_object
from smarthome_core.schema_utils import load_schema
from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json


def test_extract_first_json_object_balanced():
    s = 'blah blah {"a": 1, "b": {"c": 2}} trailing'
    out = _extract_first_json_object(s)
    assert out == '{"a": 1, "b": {"c": 2}}'


def test_llm_parser_llm_only_keeps_deterministic_rescue_on_invalid_output(tmp_path):
    paths = AssetPaths(tmp_path)
    # Use real schema files from repo by constructing paths from package root instead.
    # Easiest: point AssetPaths to repo root.
    import pathlib
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    paths = AssetPaths(repo_root)

    parsed_schema = load_schema(paths.parsed_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)

    parser = LLMParserV1(
        client=StubClient(),
        parsed_schema=parsed_schema,
        fallback_to_rules=False,
        semantic_rescue=False,
    )
    parsed = parser.parse(
        "сделай в кухне потише",
        context={"last_area_name": None},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    assert parsed.get("clarification") is None
    assert parsed.get("actions")
    assert parsed["actions"][0]["intent"] == "ADJUST_BRIGHTNESS"
    assert parsed["actions"][0]["target"]["area_name"] == "\u041a\u0443\u0445\u043d\u044f"
    

def test_llm_parser_reuses_freeform_question(tmp_path):
    import pathlib

    class QuestionClient:
        def generate_json(
            self,
            *,
            system: str,
            user: str,
            temperature: float = 0.0,
            max_tokens: int = 512,
            json_schema: dict | None = None,
        ) -> str:
            return "В какой комнате включить свет?"

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    paths = AssetPaths(repo_root)

    parsed_schema = load_schema(paths.parsed_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)

    parser = LLMParserV1(
        client=QuestionClient(),
        parsed_schema=parsed_schema,
        fallback_to_rules=False,
        semantic_rescue=False,
    )
    parsed = parser.parse(
        "включи свет",
        context={"last_area_name": None},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    clarification = parsed.get("clarification") or {}
    assert clarification.get("needed") is True
    assert "какой комнате" in (clarification.get("question") or "").lower()


def test_llm_parser_llm_fallback_uses_rules_on_invalid_output(tmp_path):
    import pathlib
    repo_root = pathlib.Path(__file__).resolve().parents[1]
    paths = AssetPaths(repo_root)

    parsed_schema = load_schema(paths.parsed_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)

    parser = LLMParserV1(client=StubClient(), parsed_schema=parsed_schema, fallback_to_rules=True)
    parsed = parser.parse(
        "сделай в кухне потише",
        context={"last_area_name": None},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    # Rule fallback should produce at least one action.
    assert len(parsed.get("actions") or []) >= 1


def test_llm_parser_semantic_rescue_uses_rules_when_model_returns_unknown(tmp_path):
    import pathlib

    class UnknownGoalClient:
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
                '"clarification":{"needed":true,"question":"Я не смог понять команду. Скажи иначе.","options":["Повтори команду другими словами."]}}'
            )

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    paths = AssetPaths(repo_root)

    parsed_schema = load_schema(paths.parsed_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)

    parser = LLMParserV1(client=UnknownGoalClient(), parsed_schema=parsed_schema, fallback_to_rules=False)
    parsed = parser.parse(
        "на кухне нужен тёплый белый, где-то на треть яркости",
        context={"last_area_name": None},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["intent"] in {"SET_COLOR_TEMP", "TURN_ON"}


def test_llm_parser_semantic_rescue_replaces_unknown_area_target(tmp_path):
    import pathlib

    class BrokenAreaClient:
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
                '"target":{"scope":"AREA","area_name":"неизвестная","entity_ids":[]},'
                '"params":{"brightness":null,"brightness_delta":null,"color_name":null,'
                '"color_rgb":null,"color_temp_kelvin":null,"color_temp_delta_k":null,"transition_s":null}}'
            )

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    paths = AssetPaths(repo_root)

    parsed_schema = load_schema(paths.parsed_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)

    parser = LLMParserV1(client=BrokenAreaClient(), parsed_schema=parsed_schema, fallback_to_rules=False)
    parsed = parser.parse(
        "сделай свет поприятнее, но не режь глаза",
        context={"last_area_name": "Спальня"},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["target"]["area_name"] == "Спальня"


def test_llm_parser_semantic_rescue_ignores_json_like_freeform_clarification(tmp_path):
    import pathlib

    class JsonishFreeformClient:
        def generate_json(
            self,
            *,
            system: str,
            user: str,
            temperature: float = 0.0,
            max_tokens: int = 512,
            json_schema: dict | None = None,
        ) -> str:
            return '{ "schema_version": "1.0", "goal_type": "UNKNOWN"'

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    paths = AssetPaths(repo_root)

    parsed_schema = load_schema(paths.parsed_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)

    parser = LLMParserV1(client=JsonishFreeformClient(), parsed_schema=parsed_schema, fallback_to_rules=False)
    parsed = parser.parse(
        "сделай свет поприятнее, но не режь глаза",
        context={"last_area_name": "Спальня"},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["target"]["area_name"] == "Спальня"


def test_llm_parser_semantic_rescue_when_model_reasks_room_that_is_already_in_text(tmp_path):
    import pathlib

    class RedundantRoomQuestionClient:
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
                '"clarification":{"needed":true,"question":"в какую комнату говорить?","options":["Гостиная","Кухня","Спальня"]}}'
            )

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    paths = AssetPaths(repo_root)

    parsed_schema = load_schema(paths.parsed_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)

    parser = LLMParserV1(client=RedundantRoomQuestionClient(), parsed_schema=parsed_schema, fallback_to_rules=False)
    parsed = parser.parse(
        "в ванной похолоднее и поярче",
        context={"last_area_name": "Спальня"},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["target"]["area_name"] == "Ванная"


def test_llm_parser_semantic_rescue_when_clarification_echoes_user_text(tmp_path):
    import pathlib

    class EchoQuestionClient:
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
                '"clarification":{"needed":true,"question":"в спальне не белый, а скорее синий и чуть потусклее","options":[]}}'
            )

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    paths = AssetPaths(repo_root)

    parsed_schema = load_schema(paths.parsed_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)

    parser = LLMParserV1(client=EchoQuestionClient(), parsed_schema=parsed_schema, fallback_to_rules=False)
    parsed = parser.parse(
        "в спальне не белый, а скорее синий и чуть потусклее",
        context={"last_area_name": "Спальня"},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["target"]["area_name"] == "Спальня"


def test_llm_parser_prefers_selected_area_when_room_is_omitted(tmp_path):
    import pathlib

    class WrongAreaClient:
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
                '"target":{"scope":"AREA","area_name":"Гостиная","entity_ids":[]},'
                '"params":{"brightness":null,"brightness_delta":null,"color_name":null,'
                '"color_rgb":null,"color_temp_kelvin":null,"color_temp_delta_k":null,"transition_s":null}}'
            )

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    paths = AssetPaths(repo_root)

    parsed_schema = load_schema(paths.parsed_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)

    parser = LLMParserV1(client=WrongAreaClient(), parsed_schema=parsed_schema, fallback_to_rules=False)
    parsed = parser.parse(
        "выключи свет",
        context={"selected_area_name": "Спальня", "last_area_name": "Гостиная"},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["intent"] == "TURN_OFF"
    assert parsed["actions"][0]["target"]["area_name"] == "Спальня"


def test_llm_parser_keeps_explicit_room_from_text_even_if_selected_area_differs(tmp_path):
    import pathlib

    class WrongAreaClient:
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
                '"target":{"scope":"AREA","area_name":"Гостиная","entity_ids":[]},'
                '"params":{"brightness":null,"brightness_delta":null,"color_name":null,'
                '"color_rgb":null,"color_temp_kelvin":null,"color_temp_delta_k":null,"transition_s":null}}'
            )

    repo_root = pathlib.Path(__file__).resolve().parents[1]
    paths = AssetPaths(repo_root)

    parsed_schema = load_schema(paths.parsed_schema)
    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    scene_aliases = load_json(paths.scene_aliases)

    parser = LLMParserV1(client=WrongAreaClient(), parsed_schema=parsed_schema, fallback_to_rules=False)
    parsed = parser.parse(
        "выключи свет в спальне",
        context={"selected_area_name": "Кухня", "last_area_name": "Кухня"},
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    assert parsed.get("clarification") is None
    assert parsed["actions"][0]["target"]["area_name"] == "Спальня"
