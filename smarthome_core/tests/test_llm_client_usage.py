from __future__ import annotations

import json

import pytest

from smarthome_core.llm_client import OpenAICompatibleClient


class _FakeHTTPResponse:
    def __init__(self, body: str) -> None:
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return self._body


def test_openai_compatible_client_tracks_last_call_info(monkeypatch) -> None:
    body = json.dumps(
        {
            "model": "local-qwen",
            "choices": [{"message": {"content": '{"schema_version":"1.0","actions":[]}'}}],
            "usage": {
                "prompt_tokens": 123,
                "completion_tokens": 17,
                "total_tokens": 140,
            },
        },
        ensure_ascii=False,
    )

    def fake_urlopen(req, timeout):  # noqa: ANN001
        return _FakeHTTPResponse(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = OpenAICompatibleClient(base_url="http://127.0.0.1:8000", model="fallback-model")
    content = client.generate_json(system="sys", user="usr")

    assert '"schema_version":"1.0"' in content
    info = client.get_last_call_info()
    assert info is not None
    assert info.prompt_tokens == 123
    assert info.completion_tokens == 17
    assert info.total_tokens == 140
    assert info.model == "local-qwen"
    assert info.duration_ms >= 0


def test_openai_compatible_client_can_clear_last_call_info() -> None:
    client = OpenAICompatibleClient(base_url="http://127.0.0.1:8000")
    client.clear_last_call_info()
    assert client.get_last_call_info() is None


def test_openai_compatible_client_forwards_json_schema(monkeypatch) -> None:
    seen_payload: dict | None = None
    body = json.dumps(
        {
            "model": "local-qwen",
            "choices": [{"message": {"content": '{"schema_version":"1.0","actions":[]}'}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        },
        ensure_ascii=False,
    )

    def fake_urlopen(req, timeout):  # noqa: ANN001
        nonlocal seen_payload
        seen_payload = json.loads(req.data.decode("utf-8"))
        return _FakeHTTPResponse(body)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = OpenAICompatibleClient(base_url="http://127.0.0.1:8000")
    schema = {"type": "object", "properties": {"schema_version": {"const": "1.0"}}}
    client.generate_json(system="sys", user="usr", json_schema=schema)

    assert seen_payload is not None
    assert seen_payload["json_schema"] == schema


def test_openai_compatible_client_tracks_failed_call_duration(monkeypatch) -> None:
    def fake_urlopen(req, timeout):  # noqa: ANN001
        raise TimeoutError("llm timed out")

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)

    client = OpenAICompatibleClient(base_url="http://127.0.0.1:8000", model="qwen-timeout")

    with pytest.raises(TimeoutError):
        client.generate_json(system="sys", user="usr")

    info = client.get_last_call_info()
    assert info is not None
    assert info.duration_ms >= 0
    assert info.prompt_tokens == 0
    assert info.completion_tokens == 0
    assert info.total_tokens == 0
    assert info.model == "qwen-timeout"
