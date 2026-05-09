from __future__ import annotations

from smarthome_gateway import main


def test_readiness_reports_missing_home_assistant_token(monkeypatch) -> None:
    monkeypatch.delenv("GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("HA_TOKEN", raising=False)
    monkeypatch.delenv("SUPERVISOR_TOKEN", raising=False)
    monkeypatch.delenv("LLM_BASE_URL", raising=False)

    resp = main.readiness(x_api_key=None)

    assert resp.ok is True
    assert resp.gateway.ok is True
    assert resp.ready_for_live_commands is False
    assert resp.home_assistant.ok is False
    assert resp.home_assistant.configured is False
    assert resp.home_assistant.detail == "HA_TOKEN is not set"
    assert resp.ready_for_llm_commands is False
    assert resp.llm.configured is False
    assert resp.runtime_fingerprint["features"]["selected_area_context"] is True
    assert resp.runtime_fingerprint["features"]["explicit_switch_recovery"] is True


def test_readiness_reports_reachable_home_assistant_and_llm(monkeypatch) -> None:
    class FakeHomeAssistantClient:
        def _request(self, method: str, path: str):
            assert method == "GET"
            assert path == "/api/"
            return {"message": "ok"}

    monkeypatch.delenv("GATEWAY_API_KEY", raising=False)
    monkeypatch.setenv("HA_TOKEN", "test-token")
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:8080")
    monkeypatch.setenv("LLM_MODEL", "qwen-mini")
    monkeypatch.setattr(main, "_make_ha_client", lambda: FakeHomeAssistantClient())

    resp = main.readiness(x_api_key=None)

    assert resp.ok is True
    assert resp.ready_for_live_commands is True
    assert resp.home_assistant.ok is True
    assert resp.home_assistant.configured is True
    assert resp.home_assistant.detail == "reachable via HA_TOKEN"
    assert resp.ready_for_llm_commands is True
    assert resp.llm.ok is True
    assert resp.llm.configured is True
    assert resp.llm.detail == "configured (model=qwen-mini)"
    assert resp.runtime_fingerprint["parser_llm_sha256_12"]
    assert resp.runtime_fingerprint["gateway_main_sha256_12"]
    assert resp.runtime_fingerprint["pipeline_sha256_12"]
    assert resp.runtime_fingerprint["features"]["prompt_prefers_selected_area"] is True
    assert resp.runtime_fingerprint["features"]["pipeline_selected_area_default"] is True


def test_readiness_supports_supervisor_token_for_addon_path(monkeypatch) -> None:
    class FakeHomeAssistantClient:
        def _request(self, method: str, path: str):
            assert method == "GET"
            assert path == "/api/"
            return {"message": "ok"}

    monkeypatch.delenv("GATEWAY_API_KEY", raising=False)
    monkeypatch.delenv("HA_TOKEN", raising=False)
    monkeypatch.setenv("HA_URL", "http://supervisor/core")
    monkeypatch.setenv("SUPERVISOR_TOKEN", "supervisor-test-token")
    monkeypatch.setenv("USE_SUPERVISOR_TOKEN", "1")
    monkeypatch.setattr(main, "_make_ha_client", lambda: FakeHomeAssistantClient())

    resp = main.readiness(x_api_key=None)

    assert resp.ok is True
    assert resp.ready_for_live_commands is True
    assert resp.home_assistant.ok is True
    assert resp.home_assistant.configured is True
    assert resp.home_assistant.detail == "reachable via SUPERVISOR_TOKEN"
    assert resp.runtime_fingerprint["root_dir"]
