from __future__ import annotations

from smarthome_core.validator import validate_parsed_command


def test_validator_resolves_unspecified_target_from_last_entity_ids() -> None:
    parsed = {
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
    }

    validated = validate_parsed_command(
        parsed,
        context={"last_area_name": "Спальня", "last_entity_ids": ["light.lampa1"]},
        device_registry={"areas": ["Спальня"]},
        area_synonyms={},
    )

    action = validated["normalized"]["actions"][0]
    assert action["target"]["scope"] == "ENTITY"
    assert action["target"]["entity_ids"] == ["light.lampa1"]
    assert validated["normalized"]["context_updates"]["last_entity_ids"] == ["light.lampa1"]


def test_validator_prefers_selected_area_name_over_last_area_name() -> None:
    parsed = {
        "schema_version": "1.0",
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
                    "transition_s": None,
                },
            }
        ],
    }

    validated = validate_parsed_command(
        parsed,
        context={"selected_area_name": "Спальня", "last_area_name": "Гостиная", "last_entity_ids": []},
        device_registry={"areas": ["Гостиная", "Спальня"]},
        area_synonyms={},
    )

    action = validated["normalized"]["actions"][0]
    assert action["target"]["scope"] == "AREA"
    assert action["target"]["area_name"] == "Спальня"
    assert validated["normalized"]["context_updates"]["last_area_name"] == "Спальня"
