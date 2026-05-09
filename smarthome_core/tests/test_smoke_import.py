from smarthome_core.validator import validate_parsed_command


def test_import_and_basic_call() -> None:
    parsed = {
        "schema_version": "1.0",
        "actions": [
            {
                "domain": "light",
                "intent": "TURN_ON",
                "target": {"scope": "AREA", "area_name": "Кухня", "entity_ids": []},
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
    }
    # Minimal registry/synonyms for this test
    registry = {"resolution_rules": {"max_actions_per_utterance": 3, "brightness_zero_policy": "TURN_OFF"}, "areas": ["Кухня"]}
    synonyms = {"synonyms": {}}

    out = validate_parsed_command(parsed, context={"last_area_name": None}, device_registry=registry, area_synonyms=synonyms)
    assert out["status"] == "EXECUTABLE"
    assert out["execution_plan"][0]["service"] == "light.turn_on"
