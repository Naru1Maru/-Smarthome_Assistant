from __future__ import annotations

from smarthome_core import parse_dispatch


def _ok_parsed(intent: str = "TURN_ON") -> dict:
    return {
        "schema_version": "1.0",
        "actions": [
            {
                "domain": "light",
                "intent": intent,
                "target": {"scope": "AREA", "area_name": "Спальня", "entity_ids": []},
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
    }


def test_dispatch_llm_mode_is_strict(monkeypatch) -> None:
    seen: list[tuple[bool, bool]] = []

    def fake_llm(*args, fallback_to_rules: bool, semantic_rescue: bool, **kwargs):
        seen.append((fallback_to_rules, semantic_rescue))
        return _ok_parsed()

    monkeypatch.setattr(parse_dispatch, "parse_light_command_llm_v1", fake_llm)

    parsed = parse_dispatch.parse_light_command_v1_dispatch(
        "включи свет",
        parser_mode="llm",
        context={"last_area_name": None},
        device_registry={},
        area_synonyms={},
        colors={},
        modifiers={},
        parsed_schema={},
        llm_client=object(),
    )

    assert parsed["actions"][0]["intent"] == "TURN_ON"
    assert seen == [(False, False)]


def test_dispatch_llm_only_alias_is_also_strict(monkeypatch) -> None:
    seen: list[tuple[bool, bool]] = []

    def fake_llm(*args, fallback_to_rules: bool, semantic_rescue: bool, **kwargs):
        seen.append((fallback_to_rules, semantic_rescue))
        return _ok_parsed()

    monkeypatch.setattr(parse_dispatch, "parse_light_command_llm_v1", fake_llm)

    parse_dispatch.parse_light_command_v1_dispatch(
        "включи свет",
        parser_mode="llm_only",
        context={"last_area_name": None},
        device_registry={},
        area_synonyms={},
        colors={},
        modifiers={},
        parsed_schema={},
        llm_client=object(),
    )

    assert seen == [(False, False)]


def test_dispatch_llm_safe_runs_rules_first_and_skips_llm_when_rules_are_good(monkeypatch) -> None:
    llm_calls = 0

    def fake_rules(*args, **kwargs):
        return _ok_parsed(intent="TURN_OFF")

    def fake_llm(*args, **kwargs):
        nonlocal llm_calls
        llm_calls += 1
        return _ok_parsed()

    monkeypatch.setattr(parse_dispatch, "parse_light_command_v1", fake_rules)
    monkeypatch.setattr(parse_dispatch, "parse_light_command_llm_v1", fake_llm)

    parsed = parse_dispatch.parse_light_command_v1_dispatch(
        "выключи свет",
        parser_mode="llm_safe",
        context={"last_area_name": None},
        device_registry={},
        area_synonyms={},
        colors={},
        modifiers={},
        parsed_schema={},
        llm_client=object(),
    )

    assert parsed["actions"][0]["intent"] == "TURN_OFF"
    assert llm_calls == 0


def test_dispatch_llm_safe_calls_llm_without_inner_fallback_when_rules_are_insufficient(monkeypatch) -> None:
    seen: list[tuple[bool, bool]] = []

    def fake_rules(*args, **kwargs):
        parsed = _ok_parsed(intent="UNKNOWN")
        parsed["clarification"] = {"needed": True, "question": "Уточните комнату", "options": []}
        return parsed

    def fake_llm(*args, fallback_to_rules: bool, semantic_rescue: bool, **kwargs):
        seen.append((fallback_to_rules, semantic_rescue))
        return _ok_parsed(intent="SET_COLOR")

    monkeypatch.setattr(parse_dispatch, "parse_light_command_v1", fake_rules)
    monkeypatch.setattr(parse_dispatch, "parse_light_command_llm_v1", fake_llm)

    parsed = parse_dispatch.parse_light_command_v1_dispatch(
        "сделай свет синим",
        parser_mode="llm_safe",
        context={"last_area_name": None},
        device_registry={},
        area_synonyms={},
        colors={},
        modifiers={},
        parsed_schema={},
        llm_client=object(),
    )

    assert parsed["actions"][0]["intent"] == "SET_COLOR"
    assert seen == [(False, False)]


def test_dispatch_llm_safe_calls_llm_for_scene_like_phrase_when_rules_collapse_to_turn_on(monkeypatch) -> None:
    llm_calls = 0

    def fake_rules(*args, **kwargs):
        return _ok_parsed(intent="TURN_ON")

    def fake_llm(*args, **kwargs):
        nonlocal llm_calls
        llm_calls += 1
        return _ok_parsed(intent="SET_COLOR_TEMP")

    monkeypatch.setattr(parse_dispatch, "parse_light_command_v1", fake_rules)
    monkeypatch.setattr(parse_dispatch, "parse_light_command_llm_v1", fake_llm)

    parsed = parse_dispatch.parse_light_command_v1_dispatch(
        "\u0441\u0434\u0435\u043b\u0430\u0439 \u0441\u0432\u0435\u0442 \u043a\u0430\u043a \u0432 \u0437\u0430\u043a\u0430\u0442\u0435",
        parser_mode="llm_safe",
        context={"last_area_name": None},
        device_registry={},
        area_synonyms={},
        colors={},
        modifiers={},
        scene_aliases={"scenes": [{"id": "SUNSET", "patterns": ["\u043a\u0430\u043a \u0432 \u0437\u0430\u043a\u0430\u0442\u0435"]}]},
        parsed_schema={},
        llm_client=object(),
    )

    assert parsed["actions"][0]["intent"] == "SET_COLOR_TEMP"
    assert llm_calls == 1


def test_dispatch_llm_safe_keeps_rules_for_multi_dimensional_parse(monkeypatch) -> None:
    llm_calls = 0

    def fake_rules(*args, **kwargs):
        return {
            "schema_version": "1.0",
            "actions": [
                {
                    "domain": "light",
                    "intent": "ADJUST_BRIGHTNESS",
                    "target": {"scope": "AREA", "area_name": "\u0421\u043f\u0430\u043b\u044c\u043d\u044f", "entity_ids": []},
                    "params": {
                        "brightness": None,
                        "brightness_delta": 20,
                        "color": None,
                        "color_temp_kelvin": None,
                        "color_temp_delta_k": None,
                        "transition_s": 0.8,
                    },
                },
                {
                    "domain": "light",
                    "intent": "ADJUST_COLOR_TEMP",
                    "target": {"scope": "AREA", "area_name": "\u0421\u043f\u0430\u043b\u044c\u043d\u044f", "entity_ids": []},
                    "params": {
                        "brightness": None,
                        "brightness_delta": None,
                        "color": None,
                        "color_temp_kelvin": None,
                        "color_temp_delta_k": 800,
                        "transition_s": 0.8,
                    },
                },
            ],
        }

    def fake_llm(*args, **kwargs):
        nonlocal llm_calls
        llm_calls += 1
        return _ok_parsed(intent="UNKNOWN")

    monkeypatch.setattr(parse_dispatch, "parse_light_command_v1", fake_rules)
    monkeypatch.setattr(parse_dispatch, "parse_light_command_llm_v1", fake_llm)

    parsed = parse_dispatch.parse_light_command_v1_dispatch(
        "\u0432 \u0432\u0430\u043d\u043d\u043e\u0439 \u043f\u043e\u0445\u043e\u043b\u043e\u0434\u043d\u0435\u0435 \u0438 \u043f\u043e\u044f\u0440\u0447\u0435",
        parser_mode="llm_safe",
        context={"last_area_name": None},
        device_registry={},
        area_synonyms={},
        colors={},
        modifiers={},
        scene_aliases={},
        parsed_schema={},
        llm_client=object(),
    )

    assert len(parsed["actions"]) == 2
    assert llm_calls == 0
