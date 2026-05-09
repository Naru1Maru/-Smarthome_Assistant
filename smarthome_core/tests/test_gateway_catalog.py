from __future__ import annotations

from smarthome_gateway import main


def test_catalog_returns_areas_devices_and_capabilities(tmp_path) -> None:
    main.app.state.assets = {
        "device_registry": {
            "schema_version": "1.0",
            "areas": [
                {
                    "area_id": "area_bedroom",
                    "name": "Bedroom",
                    "devices": ["device_light_bedroom_1", "device_plug_bedroom_1"],
                }
            ],
            "devices": [
                {
                    "device_id": "device_light_bedroom_1",
                    "name": "Lamp",
                    "device_type": "light",
                    "home_assistant": {"entity_id": "light.lampa1"},
                    "capabilities": {
                        "on_off": True,
                        "brightness": True,
                        "rgb": True,
                        "color_temp": True,
                    },
                },
                {
                    "device_id": "device_plug_bedroom_1",
                    "name": "Socket",
                    "device_type": "switch",
                    "home_assistant": {"entity_id": "switch.socket_bed"},
                    "capabilities": {
                        "on_off": True,
                    },
                },
            ],
        }
    }
    main.app.state.log_path = tmp_path / "commands.jsonl"

    resp = main.catalog(x_api_key=None)

    assert resp.ok is True
    assert len(resp.areas) == 1
    assert resp.areas[0].name == "Bedroom"
    assert resp.areas[0].device_types == ["light", "switch"]
    assert resp.areas[0].device_ids == ["device_light_bedroom_1", "device_plug_bedroom_1"]
    assert len(resp.areas[0].target_profiles) == 2
    assert resp.areas[0].target_profiles[0].device_type == "light"
    assert "TURN_ON" in resp.areas[0].target_profiles[0].supported_quick_actions

    devices = {device.device_id: device for device in resp.devices}
    assert devices["device_light_bedroom_1"].area_name == "Bedroom"
    assert devices["device_light_bedroom_1"].control_profile == "color_scene"
    assert devices["device_light_bedroom_1"].capabilities.brightness is True
    assert devices["device_light_bedroom_1"].capabilities.rgb is True
    assert "COZY" in devices["device_light_bedroom_1"].supported_quick_actions
    assert devices["device_plug_bedroom_1"].control_profile == "power_only"
    assert devices["device_plug_bedroom_1"].capabilities.on_off is True
    assert devices["device_plug_bedroom_1"].capabilities.brightness is False
