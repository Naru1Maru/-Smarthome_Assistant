"""LLM client interfaces (offline-friendly).

Design goals:
- No vendor lock-in: support "OpenAI-compatible" HTTP endpoints that many local servers expose.
- Pure stdlib (urllib) to keep dependencies minimal.
- Pluggable: you can replace the client with anything (vLLM, llama.cpp, Ollama via a bridge, etc.).

This module does NOT include any model weights or networking by default.
"""

from __future__ import annotations

import json
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Protocol


class LLMClient(Protocol):
    def generate_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Return raw model output as a string (expected to contain JSON)."""


@dataclass(frozen=True)
class LLMCallInfo:
    duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: Optional[str] = None


@dataclass
class OpenAICompatibleClient:
    """OpenAI-compatible chat/completions endpoint client.

    Works with many local deployments that expose /v1/chat/completions.
    """

    base_url: str  # e.g., http://127.0.0.1:8000
    api_key: Optional[str] = None
    model: str = "local-model"
    timeout_s: int = 30
    _last_call_info: Optional[LLMCallInfo] = field(default=None, init=False, repr=False)

    def clear_last_call_info(self) -> None:
        self._last_call_info = None

    def get_last_call_info(self) -> Optional[LLMCallInfo]:
        return self._last_call_info

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        self._last_call_info = None
        url = self.base_url.rstrip("/") + "/v1/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if json_schema is not None:
            payload["json_schema"] = json_schema

        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                body = resp.read().decode("utf-8")
            dt = time.time() - t0

            data = json.loads(body)
            usage = data.get("usage") or {}
            prompt_tokens = int(usage.get("prompt_tokens") or 0)
            completion_tokens = int(usage.get("completion_tokens") or 0)
            total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens))
            self._last_call_info = LLMCallInfo(
                duration_ms=max(0, int(round(dt * 1000))),
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                model=str(data.get("model") or self.model or ""),
            )
        except Exception:
            dt = time.time() - t0
            self._last_call_info = LLMCallInfo(
                duration_ms=max(0, int(round(dt * 1000))),
                prompt_tokens=0,
                completion_tokens=0,
                total_tokens=0,
                model=str(self.model or ""),
            )
            raise
        # Standard OpenAI-style structure:
        # choices[0].message.content
        try:
            return data["choices"][0]["message"]["content"]
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"Unexpected LLM response format after {dt:.3f}s: {body[:500]}") from e


@dataclass(frozen=True)
class StubClient:
    """Offline stub to test the LLM parser wiring.

    It deliberately returns a small subset of commands and is NOT expected
    to match the gold dataset well.
    """

    def generate_json(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.0,
        max_tokens: int = 512,
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> str:
        text = user.lower()
        if "выключ" in text or "погаси" in text:
            return json.dumps({"schema_version": "1.0", "actions": [{"domain": "light", "intent": "TURN_OFF", "target": {"scope": "UNSPECIFIED", "area_name": None, "entity_ids": []}, "params": {"brightness": None, "brightness_delta": None, "color": None, "color_temp_kelvin": None, "color_temp_delta_k": None, "transition_s": None}}]})
        if "включ" in text or "зажг" in text:
            return json.dumps({"schema_version": "1.0", "actions": [{"domain": "light", "intent": "TURN_ON", "target": {"scope": "UNSPECIFIED", "area_name": None, "entity_ids": []}, "params": {"brightness": None, "brightness_delta": None, "color": None, "color_temp_kelvin": None, "color_temp_delta_k": None, "transition_s": None}}]})
        if "отмена" in text or "стоп" in text:
            return json.dumps({"schema_version": "1.0", "actions": [{"domain": "light", "intent": "CANCEL", "target": {"scope": "UNSPECIFIED", "area_name": None, "entity_ids": []}, "params": {"brightness": None, "brightness_delta": None, "color": None, "color_temp_kelvin": None, "color_temp_delta_k": None, "transition_s": None}}]})
        return "{not-json"
