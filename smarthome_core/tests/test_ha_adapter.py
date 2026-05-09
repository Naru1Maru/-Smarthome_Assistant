from smarthome_core.ha_adapter import execution_step_to_service_call, kelvin_to_mired


def test_kelvin_to_mired_basic() -> None:
    assert kelvin_to_mired(2000) == 500
    assert kelvin_to_mired(6500) == round(1_000_000 / 6500)


def test_execution_step_conversion_mireds() -> None:
    step = {
        "executor": "HOME_ASSISTANT",
        "service": "light.turn_on",
        "target": {"entity_id": ["light.kitchen"]},
        "data": {
            "brightness_pct": 50,
            "brightness_step_pct": None,
            "rgb_color": None,
            "color_temp_kelvin": 2000,
            "transition": 1.0,
        },
    }

    call = execution_step_to_service_call(step, color_temp_unit="mireds")
    assert call["service"] == "light.turn_on"
    assert call["target"]["entity_id"] == ["light.kitchen"]
    assert "color_temp" in call["data"]
    assert "color_temp_kelvin" not in call["data"]
    assert call["data"]["color_temp"] == 500
