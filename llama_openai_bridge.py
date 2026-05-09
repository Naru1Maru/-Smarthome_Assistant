r"""
Lightweight OpenAI-compatible wrapper around llama.cpp's HTTP server.

Usage:
    1. Запустите llama-server с вашей моделью, например:
           .\llama-server.exe -m C:\Models\Qwen25\qwen2.5-7b-instruct-q5_k_m-00001-of-00002.gguf `
               -c 4096 -ngl 99 -t 8 --port 8081
    2. Запустите этот мост:
           uvicorn llama_openai_bridge:app --reload --port 8080
    3. Укажите в SmartHome Gateway переменные окружения:
           LLM_BASE_URL=http://127.0.0.1:8080
           LLM_MODEL=qwen2.5-7b-instruct
"""

from __future__ import annotations

import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import List, Literal, Optional

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


LLAMA_SERVER_URL = os.getenv("LLAMA_SERVER_URL", "http://127.0.0.1:8081")
LLAMA_COMPLETION_ENDPOINT = LLAMA_SERVER_URL.rstrip("/") + "/completion"
DEFAULT_MAX_TOKENS = int(os.getenv("LLAMA_MAX_TOKENS", "256"))
STOP_TOKENS = os.getenv("LLM_STOP", "<|im_end|>,</s>").split(",")
SYSTEM_HINT = os.getenv(
    "LLM_SYSTEM_HINT",
    (
        "Ты — модуль NLU для умного дома. Преобразуй русскоязычную команду в JSON ParsedCommand v1.0. "
        "Верни ТОЛЬКО один JSON-объект без пояснений. Используй формат: "
        '{"schema_version":"1.0","actions":[{"domain":"light","intent":"TURN_ON","target":{"scope":"UNSPECIFIED","area_name":null,"entity_ids":[]},'
        '"params":{"brightness":null,"brightness_delta":null,"color":null,"color_temp_kelvin":null,"color_temp_delta_k":null,"transition_s":null}}]}. '
        "Если нужна уточняющая информация, верни intent \"UNKNOWN\" и объект clarification с полями needed/question/options."
    ),
)


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    model: str
    messages: List[Message]
    temperature: float = 0.0
    max_tokens: int = DEFAULT_MAX_TOKENS
    json_schema: Optional[dict] = None


class ChatResponse(BaseModel):
    id: str
    @staticmethod
    def make(model: str, content: str, prompt_tokens: int, completion_tokens: int) -> "ChatResponse":
        return ChatResponse(
            id=f"chatcmpl-{uuid.uuid4()}",
            object="chat.completion",
            created=int(time.time()),
            model=model,
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            usage={
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
            },
        )

    object: str
    created: int
    model: str
    choices: List[dict]
    usage: dict


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.Client(timeout=60.0)
    try:
        yield
    finally:
        client: Optional[httpx.Client] = getattr(app.state, "http_client", None)
        if client is not None:
            client.close()


app = FastAPI(title="llama.cpp OpenAI bridge", version="0.1", lifespan=lifespan)


def _build_qwen_prompt(messages: List[Message]) -> str:
    """Convert OpenAI-style messages to a Qwen chat prompt.

    If the caller already provided a system message, we trust it and do not
    append our default hint a second time. This keeps the prompt compact and
    avoids redundant prefill work for llama.cpp.
    """
    lines: List[str] = []
    has_system = any(m.role == "system" for m in messages)
    if not has_system:
        lines.append(f"<|im_start|>system\n{SYSTEM_HINT}\n<|im_end|>")

    for m in messages:
        content = m.content.strip()
        lines.append(f"<|im_start|>{m.role}\n{content}\n<|im_end|>")
    lines.append("<|im_start|>assistant\n")
    return "\n".join(lines)


def _build_llama_completion_payload(req: ChatRequest) -> dict:
    payload = {
        "prompt": _build_qwen_prompt(req.messages),
        "temperature": req.temperature,
        "n_predict": min(req.max_tokens, DEFAULT_MAX_TOKENS),
        "stop": STOP_TOKENS,
    }
    if req.json_schema is not None:
        payload["json_schema"] = req.json_schema
    return payload


@app.post("/v1/chat/completions", response_model=ChatResponse)
def chat_completion(req: ChatRequest) -> ChatResponse:
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    payload = _build_llama_completion_payload(req)

    try:
        t0 = time.perf_counter()
        client: Optional[httpx.Client] = getattr(app.state, "http_client", None)
        if client is None:
            client = httpx.Client(timeout=60.0)
            app.state.http_client = client
        response = client.post(LLAMA_COMPLETION_ENDPOINT, json=payload)
        dt = time.perf_counter() - t0
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"llama-server error: {exc}") from exc

    if response.status_code != 200:
        raise HTTPException(status_code=502, detail=f"llama-server HTTP {response.status_code}: {response.text[:200]}")

    data = response.json()
    content = data.get("content")
    if not isinstance(content, str):
        raise HTTPException(status_code=502, detail=f"Unexpected llama response: {data}")

    prompt_tokens = int(data.get("tokens_evaluated") or 0)
    completion_tokens = int(data.get("tokens_predicted") or data.get("tokens_generated") or 0)

    print(f"[bridge] llama served request in {dt*1000:.1f} ms, completion {completion_tokens} tokens")
    return ChatResponse.make(req.model, content.strip(), prompt_tokens, completion_tokens)
