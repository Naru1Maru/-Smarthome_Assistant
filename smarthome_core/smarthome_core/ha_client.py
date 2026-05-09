"""Home Assistant REST API client (minimal, standard-library only).

This project uses Home Assistant as a local Zigbee hub and execution backend.
We talk to HA via its HTTP REST API (Long-Lived Access Token).

Security notes:
- Never hardcode tokens in code or commit them to git.
- Prefer providing token via environment variable (e.g., HA_TOKEN).
"""

from __future__ import annotations

import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Dict, Optional


class HomeAssistantError(RuntimeError):
    """Raised on network / HTTP / JSON errors from Home Assistant."""

    def __init__(self, message: str, *, status: Optional[int] = None, body: Optional[str] = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


@dataclass(frozen=True)
class HomeAssistantClient:
    """Tiny REST client for Home Assistant.

    Args:
        base_url: e.g. http://homeassistant.local:8123
        token: Long-Lived Access Token
        timeout_s: request timeout in seconds
        verify_tls: if base_url is https://... set to True (default). If you use self-signed TLS,
            you may set verify_tls=False for local testing (not recommended).
    """

    base_url: str
    token: str
    timeout_s: float = 10.0
    verify_tls: bool = True

    def _url(self, path: str) -> str:
        base = (self.base_url or "").strip().rstrip("/")
        if not path.startswith("/"):
            path = "/" + path
        return base + path

    def _ssl_context(self) -> Optional[ssl.SSLContext]:
        # Only relevant for https:// base_url.
        if self.verify_tls:
            return None
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    def _request(self, method: str, path: str, *, json_body: Optional[Dict[str, Any]] = None) -> Any:
        url = self._url(path)

        data_bytes: Optional[bytes] = None
        if json_body is not None:
            data_bytes = json.dumps(json_body, ensure_ascii=False).encode("utf-8")

        req = urllib.request.Request(url=url, data=data_bytes, method=method.upper())
        req.add_header("Authorization", f"Bearer {self.token}")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=float(self.timeout_s), context=self._ssl_context()) as resp:
                raw = resp.read()
                if not raw:
                    return None
                try:
                    return json.loads(raw.decode("utf-8"))
                except json.JSONDecodeError as e:
                    raise HomeAssistantError(f"Invalid JSON response from Home Assistant: {e}") from e
        except urllib.error.HTTPError as e:
            try:
                body = e.read().decode("utf-8", errors="replace")
            except Exception:
                body = None
            raise HomeAssistantError(
                f"Home Assistant HTTP error {e.code} for {method} {path}",
                status=int(e.code),
                body=body,
            ) from e
        except urllib.error.URLError as e:
            raise HomeAssistantError(f"Home Assistant network error for {method} {path}: {e}") from e

    def get_state(self, entity_id: str) -> Dict[str, Any]:
        """Get current entity state object."""
        entity_id = str(entity_id).strip()
        if not entity_id:
            raise ValueError("entity_id is empty")
        out = self._request("GET", f"/api/states/{urllib.parse.quote(entity_id)}")
        if not isinstance(out, dict):
            raise HomeAssistantError("Unexpected response type for get_state")
        return out

    def call_service(self, service: str, payload: Dict[str, Any]) -> Any:
        """Call a HA service, e.g. service='light.turn_on'.

        Args:
            service: '<domain>.<service>' (e.g., 'light.turn_on')
            payload: JSON payload (e.g., {'entity_id': 'light.lampa1', 'brightness_pct': 20})

        Returns:
            HA response (usually list of updated entity objects).
        """
        s = (service or "").strip()
        if "." not in s:
            raise ValueError(f"Invalid service name: {service!r}")
        domain, name = s.split(".", 1)
        domain = domain.strip()
        name = name.strip()
        if not domain or not name:
            raise ValueError(f"Invalid service name: {service!r}")
        if not isinstance(payload, dict):
            raise TypeError("payload must be a dict")
        return self._request("POST", f"/api/services/{urllib.parse.quote(domain)}/{urllib.parse.quote(name)}", json_body=payload)

    def ping(self) -> bool:
        """Best-effort health check."""
        try:
            out = self._request("GET", "/api/")
            return bool(out)
        except Exception:
            return False
