from __future__ import annotations

from pathlib import Path

from smarthome_core.llm_client import LLMCallInfo
from smarthome_core.pipeline import PipelineResult
from smarthome_gateway import main


class _FakeLLMClient:
    def __init__(self, info: LLMCallInfo | None) -> None:
        self._info = info
        self.clear_calls = 0

    def clear_last_call_info(self) -> None:
        self.clear_calls += 1

    def get_last_call_info(self) -> LLMCallInfo | None:
        return self._info


def _parsed(intent: str = "TURN_OFF") -> dict:
    return {
        "schema_version": "1.0",
        "actions": [
            {
                "domain": "light",
                "intent": intent,
                "target": {"scope": "AREA", "area_name": "Спальня", "entity_ids": []},
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


def test_command_returns_llm_timing_for_llm_mode(monkeypatch, tmp_path: Path) -> None:
    llm_info = LLMCallInfo(
        duration_ms=1820,
        prompt_tokens=410,
        completion_tokens=37,
        total_tokens=447,
        model="qwen-test",
    )
    fake_client = _FakeLLMClient(llm_info)

    monkeypatch.setattr(
        main,
        "run_light_pipeline_v1",
        lambda *args, **kwargs: PipelineResult(
            stage="VALIDATED",
            parsed=_parsed(),
            validated={"status": "EXECUTABLE"},
        ),
    )
    monkeypatch.setattr(
        main,
        "build_service_calls_from_validated",
        lambda *args, **kwargs: ([{"service": "light.turn_off", "payload": {"entity_id": "light.lampa1"}}], []),
    )

    main.app.state.root_dir = tmp_path
    main.app.state.assets = {
        "device_registry": {},
        "area_synonyms": {},
        "colors": {},
        "modifiers": {},
        "parsed_schema": None,
    }
    main.app.state.llm_client = fake_client
    main.app.state.log_path = tmp_path / "commands.jsonl"

    resp = main.command(
        main.CommandRequest(text="выключи свет", parser_mode="llm", dry_run=True),
        x_api_key=None,
    )

    assert fake_client.clear_calls == 1
    assert resp.timing_ms.llm is not None
    assert resp.timing_ms.llm.duration_ms == 1820
    assert resp.timing_ms.llm.prompt_tokens == 410
    assert resp.timing_ms.llm.completion_tokens == 37
    assert resp.timing_ms.llm.total_tokens == 447
    assert resp.timing_ms.llm.model == "qwen-test"


def test_command_omits_llm_timing_when_no_llm_call(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(
        main,
        "run_light_pipeline_v1",
        lambda *args, **kwargs: PipelineResult(
            stage="VALIDATED",
            parsed=_parsed(),
            validated={"status": "EXECUTABLE"},
        ),
    )
    monkeypatch.setattr(
        main,
        "build_service_calls_from_validated",
        lambda *args, **kwargs: ([{"service": "light.turn_off", "payload": {"entity_id": "light.lampa1"}}], []),
    )

    main.app.state.root_dir = tmp_path
    main.app.state.assets = {
        "device_registry": {},
        "area_synonyms": {},
        "colors": {},
        "modifiers": {},
        "parsed_schema": None,
    }
    main.app.state.llm_client = None
    main.app.state.log_path = tmp_path / "commands.jsonl"

    resp = main.command(
        main.CommandRequest(text="выключи свет", parser_mode="rules", dry_run=True),
        x_api_key=None,
    )

    assert resp.timing_ms.llm is None
