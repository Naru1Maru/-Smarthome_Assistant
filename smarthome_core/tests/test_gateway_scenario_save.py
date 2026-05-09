from __future__ import annotations

import json
from pathlib import Path

from smarthome_gateway import main


def _prepare_state(tmp_path: Path) -> Path:
    root_dir = tmp_path
    main.app.state.root_dir = root_dir
    main.app.state.assets = {}
    main.app.state.log_path = tmp_path / "commands.jsonl"
    scenarios_dir = root_dir / "gateway_scenarios"
    scenarios_dir.mkdir(parents=True, exist_ok=True)
    return scenarios_dir


def test_scenario_save_writes_generated_file_and_requests_include(tmp_path: Path) -> None:
    scenarios_dir = _prepare_state(tmp_path)
    automations = [
        {
            "id": "rule_1_20_00",
            "alias": "20:00 TURN_ON",
            "mode": "single",
            "trigger": [{"trigger": "time", "at": "20:00:00"}],
            "action": [{"action": "light.turn_on", "target": {"entity_id": ["light.lampa1"]}, "data": {"brightness_pct": 50}}],
        }
    ]

    resp = main.scenario_save(
        main.ScenarioSaveRequest(automations=automations, auto_activate=False),
        x_api_key=None,
    )

    assert resp.ok is True
    assert resp.status == "SAVED_NEEDS_INCLUDE"
    assert resp.saved_automation_count == 1
    assert resp.file_automation_count == 1
    assert resp.include_detected is False
    saved_file = scenarios_dir / "smarthome_gateway_automations.yaml"
    assert saved_file.exists()
    saved = json.loads(saved_file.read_text(encoding="utf-8"))
    assert saved[0]["id"] == "rule_1_20_00"


def test_scenario_save_reloads_when_include_detected(tmp_path: Path, monkeypatch) -> None:
    scenarios_dir = _prepare_state(tmp_path)
    (scenarios_dir / "configuration.yaml").write_text(
        "automation: !include smarthome_gateway_automations.yaml\n",
        encoding="utf-8",
    )

    calls: list[tuple[str, dict]] = []

    class StubHAClient:
        def call_service(self, service: str, payload: dict):
            calls.append((service, payload))
            return {"ok": True}

    monkeypatch.setattr(main, "_make_ha_client", lambda: StubHAClient())

    resp = main.scenario_save(
        main.ScenarioSaveRequest(
            automations=[
                {
                    "id": "rule_2_00_00",
                    "alias": "00:00 TURN_OFF",
                    "mode": "single",
                    "trigger": [{"trigger": "time", "at": "00:00:00"}],
                    "action": [{"action": "light.turn_off", "target": {"entity_id": ["light.lampa1"]}, "data": {"transition": 3}}],
                }
            ]
        ),
        x_api_key=None,
    )

    assert resp.ok is True
    assert resp.status == "SAVED_ACTIVE"
    assert resp.include_detected is True
    assert resp.reloaded is True
    assert calls == [("automation.reload", {})]


def test_scenario_save_does_not_reload_when_auto_activate_false_even_if_include_detected(tmp_path: Path, monkeypatch) -> None:
    scenarios_dir = _prepare_state(tmp_path)
    (scenarios_dir / "configuration.yaml").write_text(
        "automation: !include smarthome_gateway_automations.yaml\n",
        encoding="utf-8",
    )

    calls: list[tuple[str, dict]] = []

    class StubHAClient:
        def call_service(self, service: str, payload: dict):
            calls.append((service, payload))
            return {"ok": True}

    monkeypatch.setattr(main, "_make_ha_client", lambda: StubHAClient())

    resp = main.scenario_save(
        main.ScenarioSaveRequest(
            automations=[
                {
                    "id": "rule_no_reload",
                    "alias": "NO RELOAD",
                    "mode": "single",
                    "trigger": [{"trigger": "time", "at": "19:00:00"}],
                    "action": [{"action": "light.turn_on", "target": {"entity_id": ["light.lampa1"]}, "data": {"brightness_pct": 20}}],
                }
            ],
            auto_activate=False,
        ),
        x_api_key=None,
    )

    assert resp.ok is True
    assert resp.status == "SAVED_NEEDS_INCLUDE"
    assert resp.include_detected is True
    assert resp.reloaded is False
    assert calls == []


def test_scenario_save_addon_without_config_mount_returns_needs_include(tmp_path: Path, monkeypatch) -> None:
    _prepare_state(tmp_path)
    monkeypatch.setattr(main, "_running_in_ha_addon", lambda: True)
    monkeypatch.setattr(main, "_ha_config_mount_available", lambda: False)

    calls: list[tuple[str, dict]] = []

    class StubHAClient:
        def call_service(self, service: str, payload: dict):
            calls.append((service, payload))
            return {"ok": True}

    monkeypatch.setattr(main, "_make_ha_client", lambda: StubHAClient())

    resp = main.scenario_save(
        main.ScenarioSaveRequest(
            automations=[
                {
                    "id": "rule_mount_check",
                    "alias": "MOUNT CHECK",
                    "mode": "single",
                    "trigger": [{"trigger": "time", "at": "18:00:00"}],
                    "action": [{"action": "light.turn_on", "target": {"entity_id": ["light.lampa1"]}, "data": {"brightness_pct": 40}}],
                }
            ],
            auto_activate=True,
        ),
        x_api_key=None,
    )

    assert resp.ok is True
    assert resp.status == "SAVED_NEEDS_INCLUDE"
    assert resp.include_detected is False
    assert resp.reloaded is False
    assert calls == []
    assert any((err.get("code") == "CONFIG_MOUNT_MISSING") for err in resp.errors)


def test_scenario_save_auto_activate_upgrades_simple_include_and_reloads(tmp_path: Path, monkeypatch) -> None:
    scenarios_dir = _prepare_state(tmp_path)
    config_path = scenarios_dir / "configuration.yaml"
    config_path.write_text(
        "default_config:\nautomation: !include automations.yaml\n",
        encoding="utf-8",
    )

    calls: list[tuple[str, dict]] = []

    class StubHAClient:
        def call_service(self, service: str, payload: dict):
            calls.append((service, payload))
            return {"ok": True}

    monkeypatch.setattr(main, "_make_ha_client", lambda: StubHAClient())

    resp = main.scenario_save(
        main.ScenarioSaveRequest(
            automations=[
                {
                    "id": "rule_auto_1",
                    "alias": "AUTO 1",
                    "mode": "single",
                    "trigger": [{"trigger": "time", "at": "20:00:00"}],
                    "action": [{"action": "light.turn_on", "target": {"entity_id": ["light.lampa1"]}, "data": {"brightness_pct": 35}}],
                }
            ]
        ),
        x_api_key=None,
    )

    assert resp.ok is True
    assert resp.status == "SAVED_ACTIVE"
    assert resp.include_detected is True
    assert resp.reloaded is True
    assert calls == [("automation.reload", {})]
    updated = config_path.read_text(encoding="utf-8")
    assert "automation:\n  - !include automations.yaml\n  - !include smarthome_gateway_automations.yaml" in updated


def test_scenario_save_auto_activate_appends_include_when_no_automation_key(tmp_path: Path, monkeypatch) -> None:
    scenarios_dir = _prepare_state(tmp_path)
    config_path = scenarios_dir / "configuration.yaml"
    config_path.write_text("default_config:\n", encoding="utf-8")

    calls: list[tuple[str, dict]] = []

    class StubHAClient:
        def call_service(self, service: str, payload: dict):
            calls.append((service, payload))
            return {"ok": True}

    monkeypatch.setattr(main, "_make_ha_client", lambda: StubHAClient())

    resp = main.scenario_save(
        main.ScenarioSaveRequest(
            automations=[
                {
                    "id": "rule_auto_2",
                    "alias": "AUTO 2",
                    "mode": "single",
                    "trigger": [{"trigger": "time", "at": "00:00:00"}],
                    "action": [{"action": "light.turn_off", "target": {"entity_id": ["light.lampa1"]}, "data": {"transition": 1}}],
                }
            ]
        ),
        x_api_key=None,
    )

    assert resp.ok is True
    assert resp.status == "SAVED_ACTIVE"
    assert resp.include_detected is True
    assert resp.reloaded is True
    assert calls == [("automation.reload", {})]
    updated = config_path.read_text(encoding="utf-8")
    assert "automation: !include smarthome_gateway_automations.yaml" in updated


def test_configuration_include_detection_ignores_comment_with_same_filename(tmp_path: Path) -> None:
    scenarios_dir = _prepare_state(tmp_path)
    config_path = scenarios_dir / "configuration.yaml"
    config_path.write_text(
        "default_config:\n# automation: !include smarthome_gateway_automations.yaml\nautomation: !include automations.yaml\n",
        encoding="utf-8",
    )
    assert main._configuration_includes_generated_automations(config_path, "smarthome_gateway_automations.yaml") is False


def test_scenario_save_with_include_dir_merge_list_saves_into_dir_and_reloads(tmp_path: Path, monkeypatch) -> None:
    scenarios_dir = _prepare_state(tmp_path)
    config_path = scenarios_dir / "configuration.yaml"
    config_path.write_text(
        "automation: !include_dir_merge_list homeassistant\n",
        encoding="utf-8",
    )

    calls: list[tuple[str, dict]] = []

    class StubHAClient:
        def call_service(self, service: str, payload: dict):
            calls.append((service, payload))
            return {"ok": True}

    monkeypatch.setattr(main, "_make_ha_client", lambda: StubHAClient())

    resp = main.scenario_save(
        main.ScenarioSaveRequest(
            automations=[
                {
                    "id": "rule_dir_include",
                    "alias": "DIR INCLUDE",
                    "mode": "single",
                    "trigger": [{"trigger": "time", "at": "21:00:00"}],
                    "action": [{"action": "light.turn_on", "target": {"entity_id": ["light.lampa1"]}, "data": {"brightness_pct": 55}}],
                }
            ],
            auto_activate=True,
        ),
        x_api_key=None,
    )

    assert resp.ok is True
    assert resp.status == "SAVED_ACTIVE"
    assert resp.include_detected is True
    assert resp.reloaded is True
    assert calls == [("automation.reload", {})]
    assert resp.storage_file is not None
    assert "homeassistant" in resp.storage_file.replace("\\", "/")


def test_scenario_save_exports_project_blueprint_files(tmp_path: Path) -> None:
    _prepare_state(tmp_path)
    resp = main.scenario_save(
        main.ScenarioSaveRequest(
            automations=[
                {
                    "id": "rule_project_export",
                    "alias": "PROJECT EXPORT",
                    "mode": "single",
                    "trigger": [{"trigger": "time", "at": "22:00:00"}],
                    "action": [{"action": "light.turn_on", "target": {"entity_id": ["light.lampa1"]}, "data": {"brightness_pct": 35}}],
                }
            ],
            auto_activate=False,
        ),
        x_api_key=None,
    )

    assert resp.ok is True
    assert len(resp.project_files) == 1
    project_path = Path(resp.project_files[0])
    assert project_path.exists()
    exported = json.loads(project_path.read_text(encoding="utf-8"))
    assert (exported.get("blueprint") or {}).get("domain") == "automation"
    assert "source_url" not in (exported.get("blueprint") or {})
    assert (exported.get("blueprint") or {}).get("input") == {}
