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


def _automation(automation_id: str, *, alias: str, at: str, service: str, data: dict | None = None) -> dict:
    return {
        "id": automation_id,
        "alias": alias,
        "mode": "single",
        "trigger": [{"trigger": "time", "at": at}],
        "action": [{"action": service, "target": {"entity_id": ["light.lampa1"]}, "data": data or {}}],
    }


def test_scenario_list_returns_saved_items(tmp_path: Path) -> None:
    _prepare_state(tmp_path)
    main.scenario_save(
        main.ScenarioSaveRequest(
            automations=[
                _automation(
                    "rule_evening_on",
                    alias="Evening On",
                    at="20:00:00",
                    service="light.turn_on",
                    data={"brightness_pct": 50},
                )
            ],
            auto_activate=False,
        ),
        x_api_key=None,
    )

    resp = main.scenario_list(x_api_key=None)

    assert resp.ok is True
    assert resp.file_automation_count == 1
    assert len(resp.items) == 1
    item = resp.items[0]
    assert item.automation_id == "rule_evening_on"
    assert item.alias == "Evening On"
    assert item.trigger_summary == "time 20:00:00"
    assert item.action_summary == "light.turn_on"


def test_scenario_upsert_replaces_existing_id(tmp_path: Path) -> None:
    _prepare_state(tmp_path)
    main.scenario_save(
        main.ScenarioSaveRequest(
            automations=[
                _automation(
                    "rule_upsert",
                    alias="Before Upsert",
                    at="19:00:00",
                    service="light.turn_on",
                    data={"brightness_pct": 20},
                )
            ],
            auto_activate=False,
        ),
        x_api_key=None,
    )

    upsert_resp = main.scenario_upsert(
        main.ScenarioUpsertRequest(
            automation=_automation(
                "rule_upsert",
                alias="After Upsert",
                at="21:30:00",
                service="light.turn_off",
                data={"transition": 2},
            ),
            auto_activate=False,
        ),
        x_api_key=None,
    )

    assert upsert_resp.ok is True
    assert upsert_resp.saved_automation_count == 1
    assert upsert_resp.file_automation_count == 1

    listed = main.scenario_list(x_api_key=None)
    assert len(listed.items) == 1
    item = listed.items[0]
    assert item.automation_id == "rule_upsert"
    assert item.alias == "After Upsert"
    assert item.trigger_summary == "time 21:30:00"
    assert item.action_summary == "light.turn_off"


def test_scenario_delete_removes_automation_and_project_file(tmp_path: Path) -> None:
    _prepare_state(tmp_path)
    save_resp = main.scenario_save(
        main.ScenarioSaveRequest(
            automations=[
                _automation(
                    "rule_delete_me",
                    alias="Delete Me",
                    at="22:00:00",
                    service="light.turn_off",
                )
            ],
            auto_activate=False,
        ),
        x_api_key=None,
    )
    assert save_resp.ok is True
    assert len(save_resp.project_files) == 1
    project_file = Path(save_resp.project_files[0])
    assert project_file.exists()

    delete_resp = main.scenario_delete(
        main.ScenarioDeleteRequest(automation_id="rule_delete_me", auto_activate=False),
        x_api_key=None,
    )

    assert delete_resp.ok is True
    assert delete_resp.status == "DELETED_PENDING_RELOAD"
    assert delete_resp.deleted_automation_id == "rule_delete_me"
    assert delete_resp.file_automation_count == 0
    assert len(delete_resp.project_files_removed) == 1
    assert not project_file.exists()

    listed = main.scenario_list(x_api_key=None)
    assert listed.file_automation_count == 0
    assert listed.items == []


def test_scenario_delete_not_found(tmp_path: Path) -> None:
    scenarios_dir = _prepare_state(tmp_path)
    file_path = scenarios_dir / "smarthome_gateway_automations.yaml"
    file_path.write_text(json.dumps([], ensure_ascii=False), encoding="utf-8")

    resp = main.scenario_delete(
        main.ScenarioDeleteRequest(automation_id="rule_missing", auto_activate=False),
        x_api_key=None,
    )

    assert resp.ok is True
    assert resp.status == "NOT_FOUND"
    assert resp.deleted_automation_id is None
