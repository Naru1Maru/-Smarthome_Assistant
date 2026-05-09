from __future__ import annotations

import json
from pathlib import Path

from fastapi import HTTPException

from smarthome_gateway import main


ROOT = Path(__file__).resolve().parents[1]


class ScenarioPreviewStubClient:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def clear_last_call_info(self) -> None:
        return None

    def get_last_call_info(self):
        return None

    def generate_json(self, *, system: str, user: str, temperature: float = 0.0, max_tokens: int = 512, json_schema=None) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


def _prepare_state(tmp_path: Path) -> None:
    main.app.state.root_dir = ROOT
    main.app.state.assets = main._load_assets(ROOT)
    main.app.state.log_path = tmp_path / "commands.jsonl"


def test_scenario_preview_returns_automation_preview(tmp_path) -> None:
    _prepare_state(tmp_path)
    main.app.state.llm_client = ScenarioPreviewStubClient(
        {
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
                }
            ],
        }
    )

    resp = main.scenario_preview(
        main.ScenarioPreviewRequest(
            text="каждый день в 20:00 включай в спальне тёплый свет",
            context=main.CommandContext(selected_area_name="Спальня", last_area_name="Спальня"),
        ),
        x_api_key=None,
    )

    assert resp.ok is True
    assert resp.status == "PREVIEW_READY"
    assert resp.validated_bundle is not None
    assert len(resp.automations) == 1
    assert resp.automations[0]["trigger"][0]["at"] == "20:00:00"
    assert resp.automations[0]["action"][0]["target"]["entity_id"] == ["light.lampa1"]


def test_scenario_preview_returns_clarification(tmp_path) -> None:
    _prepare_state(tmp_path)
    main.app.state.llm_client = ScenarioPreviewStubClient(
        {
            "schema_version": "1.0",
            "title": None,
            "description": None,
            "clarification": {
                "needed": True,
                "question": "Для какой комнаты создать сценарий?",
                "missing_fields": ["area_name"],
            },
            "rules": [],
        }
    )

    resp = main.scenario_preview(
        main.ScenarioPreviewRequest(text="вечером включай уютный свет"),
        x_api_key=None,
    )

    assert resp.ok is True
    assert resp.status == "NEEDS_CLARIFICATION"
    assert resp.clarification is not None
    assert resp.clarification["question"] == "Для какой комнаты создать сценарий?"
    assert resp.automations == []


def test_scenario_preview_requires_llm_configuration(tmp_path) -> None:
    _prepare_state(tmp_path)
    main.app.state.llm_client = None

    try:
        main.scenario_preview(
            main.ScenarioPreviewRequest(text="в полночь выключай свет"),
            x_api_key=None,
        )
    except HTTPException as exc:
        assert exc.status_code == 400
        assert "LLM is not configured" in str(exc.detail)
    else:
        raise AssertionError("Expected HTTPException when LLM client is missing")

