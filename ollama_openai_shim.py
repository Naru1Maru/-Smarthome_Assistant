from __future__ import annotations

import json
import os
import time
import urllib.request
import uuid
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


OLLAMA_CHAT_URL = os.getenv("OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat")
OLLAMA_TAGS_URL = os.getenv("OLLAMA_TAGS_URL", "http://127.0.0.1:11434/api/tags")
OLLAMA_THINK_DEFAULT = os.getenv("OLLAMA_THINK_DEFAULT", "false").strip().lower()

DEFAULT_MODEL_ALIASES: dict[str, str] = {
    "qwen2.5-7b-instruct": "qwen25-7b-local:latest",
    "qwen2.5-3b-instruct": "qwen2.5:3b",
}

app = FastAPI(title="Ollama OpenAI Shim", version="0.2")


class Message(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    temperature: float = 0.0
    max_tokens: int = 256
    json_schema: Optional[dict] = None
    think: Optional[bool] = None


def _resolve_think_flag(req_think: Optional[bool]) -> Optional[bool]:
    if req_think is not None:
        return bool(req_think)
    if OLLAMA_THINK_DEFAULT in {"", "auto"}:
        return None
    return OLLAMA_THINK_DEFAULT in {"1", "true", "yes", "on"}


def _request_json(url: str, *, data: Optional[dict[str, Any]] = None, timeout_s: int = 60) -> dict[str, Any]:
    raw_data = None
    headers = {}
    if data is not None:
        raw_data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=raw_data, headers=headers, method="POST" if data is not None else "GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw)


def _load_aliases() -> dict[str, str]:
    aliases = dict(DEFAULT_MODEL_ALIASES)
    raw = os.getenv("OLLAMA_MODEL_ALIASES", "").strip()
    if not raw:
        return aliases
    try:
        user_aliases = json.loads(raw)
    except Exception:
        return aliases
    if not isinstance(user_aliases, dict):
        return aliases
    for key, value in user_aliases.items():
        if str(key).strip() and str(value).strip():
            aliases[str(key)] = str(value)
    return aliases


def _list_models() -> list[dict[str, Any]]:
    data = _request_json(OLLAMA_TAGS_URL, timeout_s=20)
    models = data.get("models")
    return models if isinstance(models, list) else []


def _available_model_names() -> set[str]:
    return {str(model.get("name")) for model in _list_models() if model.get("name")}


def _resolve_model(requested: str) -> str:
    requested = str(requested or "").strip()
    aliases = _load_aliases()
    return aliases.get(requested, requested)


@app.get("/health")
def health() -> dict[str, Any]:
    try:
        available = sorted(_available_model_names())
    except Exception as exc:
        return {"ok": False, "backend": "ollama", "detail": str(exc)}
    return {"ok": True, "backend": "ollama", "available_models": available}


@app.get("/v1/models")
def v1_models() -> dict[str, Any]:
    models = _list_models()
    aliases = _load_aliases()
    available = {str(model.get("name")) for model in models if model.get("name")}

    items: list[dict[str, Any]] = []
    for model in models:
        name = str(model.get("name") or "")
        if not name:
            continue
        items.append({"id": name, "object": "model", "owned_by": "ollama"})

    for alias, target in aliases.items():
        if target in available:
            items.append(
                {
                    "id": alias,
                    "object": "model",
                    "owned_by": "ollama-alias",
                    "root": target,
                }
            )

    return {"object": "list", "data": items}


@app.post("/v1/chat/completions")
def chat_completions(req: ChatRequest) -> dict[str, Any]:
    if not req.messages:
        raise HTTPException(status_code=400, detail="messages must not be empty")

    resolved_model = _resolve_model(req.model)
    payload = {
        "model": resolved_model,
        "messages": [m.model_dump() for m in req.messages],
        "stream": False,
        "keep_alive": "10m",
        "options": {
            "temperature": req.temperature,
            "num_predict": req.max_tokens,
        },
    }
    think_flag = _resolve_think_flag(req.think)
    if think_flag is not None:
        payload["think"] = think_flag
    if req.json_schema is not None:
        payload["format"] = req.json_schema

    t0 = time.perf_counter()
    try:
        data = _request_json(OLLAMA_CHAT_URL, data=payload, timeout_s=600)
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"ollama error: {exc}") from exc
    dt_ms = int(round((time.perf_counter() - t0) * 1000))

    content = ((data.get("message") or {}).get("content") or "").strip()
    if not content:
        thinking = str((data.get("message") or {}).get("thinking") or "").strip()
        done_reason = str(data.get("done_reason") or "")
        if thinking and done_reason == "length":
            raise HTTPException(
                status_code=502,
                detail=(
                    "empty content (likely spent tokens in thinking); "
                    "disable thinking or increase max_tokens. "
                    f"resolved_model={resolved_model}"
                ),
            )
        raise HTTPException(status_code=502, detail=f"empty ollama response: {data}")

    prompt_tokens = int(data.get("prompt_eval_count") or 0)
    completion_tokens = int(data.get("eval_count") or 0)
    model = str(data.get("model") or resolved_model)

    return {
        "id": f"chatcmpl-{uuid.uuid4()}",
        "object": "chat.completion",
        "created": int(time.time()),
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": str(data.get("done_reason") or "stop"),
            }
        ],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
        "_shim": {
            "duration_ms": dt_ms,
            "load_duration_ns": int(data.get("load_duration") or 0),
            "prompt_eval_duration_ns": int(data.get("prompt_eval_duration") or 0),
            "eval_duration_ns": int(data.get("eval_duration") or 0),
            "requested_model": req.model,
            "resolved_model": resolved_model,
            "think": think_flag,
        },
    }
