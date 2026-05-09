from __future__ import annotations

from smarthome_gateway import main


def _registry() -> dict:
    return {
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
                "name": "Bed Lamp",
                "device_type": "light",
                "home_assistant": {"entity_id": "light.bed_lamp"},
                "capabilities": {
                    "on_off": True,
                    "brightness": True,
                    "rgb": True,
                    "color_temp": True,
                },
            },
            {
                "device_id": "device_plug_bedroom_1",
                "name": "Bed Plug",
                "device_type": "switch",
                "home_assistant": {"entity_id": "switch.bed_plug"},
                "capabilities": {
                    "on_off": True,
                },
            },
        ],
    }


def test_quick_action_light_dry_run_uses_only_light_entities(tmp_path) -> None:
    main.app.state.assets = {"device_registry": _registry()}
    main.app.state.log_path = tmp_path / "commands.jsonl"

    resp = main.quick_action(
        main.QuickActionRequest(
            action_id="TURN_ON",
            dry_run=True,
            target=main.QuickActionTargetRequest(area_name="Bedroom", device_type="light"),
        ),
        x_api_key=None,
    )

    assert resp.ok is True
    assert resp.status == "DRY_RUN"
    assert resp.parser_mode_used == "rules"
    assert resp.validated_command is not None
    assert resp.validated_command["normalized"]["context_updates"]["last_entity_ids"] == []
    assert resp.calls == [
        {
            "service": "light.turn_on",
            "payload": {"entity_id": "light.bed_lamp", "transition": 0.6},
        }
    ]


def test_quick_action_switch_dry_run_keeps_device_context(tmp_path) -> None:
    main.app.state.assets = {"device_registry": _registry()}
    main.app.state.log_path = tmp_path / "commands.jsonl"

    resp = main.quick_action(
        main.QuickActionRequest(
            action_id="TURN_OFF",
            dry_run=True,
            target=main.QuickActionTargetRequest(device_type="switch", device_id="device_plug_bedroom_1"),
        ),
        x_api_key=None,
    )

    assert resp.ok is True
    assert resp.status == "DRY_RUN"
    assert resp.parsed_command["actions"][0]["target"] == {
        "scope": "ENTITY",
        "area_name": None,
        "entity_ids": ["switch.bed_plug"],
    }
    assert resp.validated_command is not None
    assert resp.validated_command["normalized"]["context_updates"] == {
        "last_area_name": "Bedroom",
        "last_entity_ids": ["switch.bed_plug"],
    }
    assert resp.calls == [
        {
            "service": "switch.turn_off",
            "payload": {"entity_id": "switch.bed_plug"},
        }
    ]
