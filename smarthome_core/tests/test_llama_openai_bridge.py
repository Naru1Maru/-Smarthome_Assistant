from __future__ import annotations

from llama_openai_bridge import ChatRequest, SYSTEM_HINT, Message, _build_llama_completion_payload, _build_qwen_prompt


def test_build_qwen_prompt_injects_default_system_hint_only_when_missing() -> None:
    prompt = _build_qwen_prompt([Message(role="user", content="включи свет")])

    assert SYSTEM_HINT in prompt
    assert prompt.count("<|im_start|>system") == 1
    assert prompt.endswith("<|im_start|>assistant\n")


def test_build_qwen_prompt_does_not_duplicate_system_hint_when_system_is_provided() -> None:
    system = "Ты уже получил строгую инструкцию."
    prompt = _build_qwen_prompt(
        [
            Message(role="system", content=system),
            Message(role="user", content="сделай свет синим"),
        ]
    )

    assert system in prompt
    assert prompt.count(SYSTEM_HINT) == 0
    assert prompt.count("<|im_start|>system") == 1


def test_build_llama_completion_payload_forwards_json_schema() -> None:
    schema = {"type": "object", "properties": {"schema_version": {"const": "1.0"}}}
    payload = _build_llama_completion_payload(
        ChatRequest(
            model="qwen",
            messages=[Message(role="user", content="выключи свет")],
            max_tokens=128,
            json_schema=schema,
        )
    )

    assert payload["n_predict"] == 128
    assert payload["json_schema"] == schema
    assert "prompt" in payload
