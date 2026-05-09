from __future__ import annotations

from pathlib import Path

from smarthome_core.io import load_json
from smarthome_core.scenario_logic import (
    compile_scenario_bundle_to_ha_automations,
    validate_scenario_bundle,
)


ROOT = Path(__file__).resolve().parents[1]


def test_validate_and_compile_time_schedule_bundle() -> None:
    bundle = {
        "schema_version": "1.0",
        "title": "Вечерний свет",
        "description": None,
        "clarification": {"needed": False, "question": None, "missing_fields": []},
        "rules": [
            {
                "rule_id": "evening_on",
                "title": "Включить вечером",
                "enabled": True,
                "trigger": {"type": "time", "at": "20:00"},
                "conditions": [],
                "actions": [
                    {
                        "domain": "light",
                        "intent": "TURN_ON",
                        "target": {"scope": "AREA", "area_name": "Спальня", "entity_ids": []},
                        "params": {
                            "brightness": 35,
                            "brightness_delta": None,
                            "color": None,
                            "color_temp_kelvin": 2800,
                            "color_temp_delta_k": None,
                            "transition_s": 1.0,
                        },
                    }
                ],
                "else_actions": [],
            },
            {
                "rule_id": "night_off",
                "title": "Выключить ночью",
                "enabled": True,
                "trigger": {"type": "time", "at": "00:00"},
                "conditions": [],
                "actions": [
                    {
                        "domain": "light",
                        "intent": "TURN_OFF",
                        "target": {"scope": "AREA", "area_name": "Спальня", "entity_ids": []},
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
            },
        ],
    }

    validated = validate_scenario_bundle(
        bundle,
        context={"selected_area_name": None, "last_area_name": None, "last_entity_ids": []},
        root_dir=ROOT,
    )

    assert validated["status"] == "VALIDATED"
    assert len(validated["rules"]) == 2

    automations = compile_scenario_bundle_to_ha_automations(validated, root_dir=ROOT)
    assert len(automations) == 2
    assert automations[0]["trigger"][0]["at"] == "20:00:00"
    assert automations[0]["action"][0]["action"] == "light.turn_on"
    assert automations[0]["action"][0]["target"]["entity_id"] == ["light.lampa1"]
    assert automations[1]["action"][0]["action"] == "light.turn_off"


def test_compile_conditional_rule_with_else_actions_and_context_target() -> None:
    bundle = {
        "schema_version": "1.0",
        "title": "Свет по движению",
        "description": None,
        "clarification": {"needed": False, "question": None, "missing_fields": []},
        "rules": [
            {
                "rule_id": "motion_after_dark",
                "title": "Движение после наступления темноты",
                "enabled": True,
                "trigger": {
                    "type": "state",
                    "entity_id": "binary_sensor.bedroom_motion",
                    "to": "on",
                    "for_s": None,
                },
                "conditions": [
                    {
                        "type": "numeric",
                        "entity_id": "sensor.bedroom_illuminance",
                        "operator": "<",
                        "value": 30,
                    },
                    {
                        "type": "time_window",
                        "after": "19:00",
                        "before": None,
                    },
                ],
                "actions": [
                    {
                        "domain": "light",
                        "intent": "SET_BRIGHTNESS",
                        "target": {"scope": "UNSPECIFIED", "area_name": None, "entity_ids": []},
                        "params": {
                            "brightness": 40,
                            "brightness_delta": None,
                            "color": None,
                            "color_temp_kelvin": None,
                            "color_temp_delta_k": None,
                            "transition_s": 0.8,
                        },
                    }
                ],
                "else_actions": [
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
                            "transition_s": 0.2,
                        },
                    }
                ],
            }
        ],
    }

    validated = validate_scenario_bundle(
        bundle,
        context={"selected_area_name": "Спальня", "last_area_name": "Спальня", "last_entity_ids": []},
        root_dir=ROOT,
    )
    automations = compile_scenario_bundle_to_ha_automations(validated, root_dir=ROOT)

    assert len(automations) == 1
    automation = automations[0]
    choose_block = automation["action"][0]
    assert "choose" in choose_block
    assert choose_block["choose"][0]["sequence"][0]["target"]["entity_id"] == ["light.lampa1"]
    assert choose_block["default"][0]["action"] == "light.turn_off"
    assert any(step.get("condition") == "template" for step in choose_block["choose"][0]["conditions"])

