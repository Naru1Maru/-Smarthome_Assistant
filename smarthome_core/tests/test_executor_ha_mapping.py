import pytest

from smarthome_core.executor_ha import build_service_calls_from_validated, ExecutionConfig


class FakeHAClient:
    def __init__(self, states):
        self._states = states

    def get_state(self, entity_id: str):
        return self._states[entity_id]


def _min_validated(action_intent: str, params: dict, target: dict, step_data: dict):
    return {
        "schema_version": "1.0",
        "status": "EXECUTABLE",
        "reason_code": "OK",
        "warnings": [],
        "normalized": {
            "actions": [
                {
                    "domain": "light",
                    "intent": action_intent,
                    "target": target,
                    "params": params,
                }
            ],
            "context_updates": {"last_area_name": None, "last_entity_ids": []},
        },
        "execution_plan": [
            {
                "executor": "HOME_ASSISTANT",
                "service": "light.turn_on" if action_intent != "TURN_OFF" else "light.turn_off",
                "target": {"entity_id": target.get("entity_ids", []), "area_name": target.get("area_name")},
                "data": step_data,
            }
        ],
        "clarification": {"needed": False, "question": None, "options": []},
    }


def test_adjust_color_temp_delta_resolves_kelvin():
    device_registry = {
        "devices": [
            {
                "device_id": "d1",
                "home_assistant": {"entity_id": "light.lampa1"},
                "capabilities": {"color_temp_kelvin_range": {"min": 2000, "max": 6535}},
            }
        ],
        "areas": [],
    }

    fake_state = {"state": "on", "attributes": {"color_temp_kelvin": 4000}}
    client = FakeHAClient({"light.lampa1": fake_state})

    validated = _min_validated(
        "ADJUST_COLOR_TEMP",
        params={"color_temp_delta_k": 800, "transition_s": 0.8},
        target={"scope": "ENTITY", "area_name": None, "entity_ids": ["light.lampa1"]},
        step_data={"transition": 0.8, "color_temp_kelvin": None, "brightness_pct": None, "brightness_step_pct": None, "rgb_color": None},
    )

    calls, errors = build_service_calls_from_validated(validated, device_registry=device_registry, client=client, cfg=ExecutionConfig(dry_run=False))
    assert errors == []
    assert len(calls) == 1
    c = calls[0]
    assert c["service"] == "light.turn_on"
    assert c["entity_id"] == "light.lampa1"
    assert c["data"]["color_temp_kelvin"] == 4800


def test_set_brightness_groups_entities():
    device_registry = {
        "devices": [
            {"device_id": "d1", "home_assistant": {"entity_id": "light.a"}, "capabilities": {}},
            {"device_id": "d2", "home_assistant": {"entity_id": "light.b"}, "capabilities": {}},
        ],
        "areas": [
            {"name": "Спальня", "devices": ["d1", "d2"]},
        ],
    }

    validated = _min_validated(
        "SET_BRIGHTNESS",
        params={"brightness_pct": 20, "transition_s": 0.8},
        target={"scope": "AREA", "area_name": "Спальня", "entity_ids": []},
        step_data={"transition": 0.8, "brightness_pct": 20, "brightness_step_pct": None, "rgb_color": None, "color_temp_kelvin": None},
    )

    calls, errors = build_service_calls_from_validated(validated, device_registry=device_registry, client=None, cfg=ExecutionConfig(dry_run=True))
    assert errors == []
    assert len(calls) == 1
    payload = calls[0]["payload"]
    assert payload["entity_id"] == ["light.a", "light.b"]
    assert payload["brightness_pct"] == 20


def test_adjust_brightness_delta_resolves_to_abs_and_floors():
    device_registry = {
        "devices": [
            {"device_id": "d1", "home_assistant": {"entity_id": "light.lampa1"}, "capabilities": {}},
        ],
        "areas": [],
    }

    # Current brightness 10% (approx 26/255)
    fake_state = {"state": "on", "attributes": {"brightness": 26}}
    client = FakeHAClient({"light.lampa1": fake_state})

    validated = _min_validated(
        "ADJUST_BRIGHTNESS",
        params={"brightness_delta_pct": -20, "transition_s": 0.8},
        target={"scope": "ENTITY", "area_name": None, "entity_ids": ["light.lampa1"]},
        step_data={"transition": 0.8, "brightness_pct": None, "brightness_step_pct": -20, "rgb_color": None, "color_temp_kelvin": None},
    )

    calls, errors = build_service_calls_from_validated(
        validated,
        device_registry=device_registry,
        client=client,
        cfg=ExecutionConfig(dry_run=False, min_adjust_brightness_pct=5),
    )
    assert errors == []
    assert len(calls) == 1
    c = calls[0]
    assert c["service"] == "light.turn_on"
    assert c["entity_id"] == "light.lampa1"
    # Should not go to 0/off; floored to >=5%
    assert c["data"]["brightness_pct"] >= 5
    assert "brightness_step_pct" not in c["data"]
