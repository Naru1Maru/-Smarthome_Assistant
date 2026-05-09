"""Execution backend: ValidatedCommand -> Home Assistant service calls.

The validator already builds an `execution_plan` that matches Home Assistant service API.
However, some relative operations (e.g., color_temp_delta_k) require current state at runtime.

This module:
- resolves targets (entity_ids) using device_registry
- resolves runtime deltas using HA state
- clamps values to device capabilities when available
- optionally runs in dry-run mode (returns the calls without contacting HA)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .ha_adapter import execution_step_to_service_call, kelvin_to_mired
from .ha_client import HomeAssistantClient, HomeAssistantError


@dataclass(frozen=True)
class ExecutionConfig:
    color_temp_unit: str = "kelvin"  # 'kelvin' or 'mireds'
    dry_run: bool = False

    # Fallback for relative color temperature when current state is unavailable
    default_color_temp_kelvin: int = 4267

    # Fallback for relative brightness when current state is unavailable (0..100)
    default_brightness_pct: int = 50

    # Floor for relative brightness adjustments (avoid turning the light "effectively off")
    min_adjust_brightness_pct: int = 5


@dataclass
class ExecutionResult:
    ok: bool
    calls: List[Dict[str, Any]]
    results: List[Any]
    errors: List[Dict[str, Any]]


def _build_entity_cap_index(device_registry: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Map entity_id -> device capabilities."""
    index: Dict[str, Dict[str, Any]] = {}
    for dev in device_registry.get("devices", []) or []:
        ha = (dev or {}).get("home_assistant") or {}
        ent = ha.get("entity_id")
        if isinstance(ent, str) and ent:
            index[ent] = (dev or {}).get("capabilities") or {}
    return index


def _resolve_area_entities(area_name: str, device_registry: Dict[str, Any]) -> List[str]:
    """Resolve canonical area name -> list of entity_ids."""
    area_name = str(area_name or "").strip()
    if not area_name:
        return []
    # Find area by canonical name
    areas = device_registry.get("areas", []) or []
    area = None
    for a in areas:
        if isinstance(a, dict) and a.get("name") == area_name:
            area = a
            break
    if not isinstance(area, dict):
        return []
    device_ids = list(area.get("devices") or [])
    entity_ids: List[str] = []
    devs = device_registry.get("devices", []) or []
    dev_by_id = {d.get("device_id"): d for d in devs if isinstance(d, dict)}
    for did in device_ids:
        dev = dev_by_id.get(did)
        if not isinstance(dev, dict):
            continue
        ent = ((dev.get("home_assistant") or {}).get("entity_id"))
        if isinstance(ent, str) and ent:
            entity_ids.append(ent)
    return entity_ids


def _resolve_target_entities(step_target: Dict[str, Any], device_registry: Dict[str, Any]) -> List[str]:
    ent_ids = list((step_target or {}).get("entity_id") or [])
    ent_ids = [str(e) for e in ent_ids if str(e).strip()]
    if ent_ids:
        return ent_ids
    area_name = (step_target or {}).get("area_name")
    if isinstance(area_name, str) and area_name:
        return _resolve_area_entities(area_name, device_registry)
    return []


def _clamp_int(x: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, int(x)))


def _extract_current_color_temp_kelvin(state_obj: Dict[str, Any], *, default_k: int) -> int:
    attrs = (state_obj or {}).get("attributes") or {}
    # Prefer explicit Kelvin attribute
    k = attrs.get("color_temp_kelvin")
    if k is not None:
        try:
            return int(k)
        except Exception:
            pass
    # Fall back to mireds
    m = attrs.get("color_temp")
    if m is not None:
        try:
            mired = int(m)
            if mired > 0:
                return int(round(1_000_000 / mired))
        except Exception:
            pass
    return int(default_k)



def _extract_current_brightness_pct(state_obj: Dict[str, Any], *, default_pct: int) -> int:
    """Extract current brightness as percent (0..100).

    Home Assistant stores brightness in attributes as an integer 0..255.
    Some integrations may omit brightness; in that case we fall back to:
    - 100 if the light is on
    - default_pct otherwise
    """
    attrs = (state_obj or {}).get("attributes") or {}

    b = attrs.get("brightness")
    if b is not None:
        try:
            b255 = int(b)
            if b255 <= 0:
                return 0
            # Convert 1..255 -> 1..100
            return int(round((b255 / 255.0) * 100))
        except Exception:
            pass

    b_pct = attrs.get("brightness_pct")
    if b_pct is not None:
        try:
            return int(b_pct)
        except Exception:
            pass

    st = str((state_obj or {}).get("state") or "").lower()
    if st == "on":
        return 100

    return int(default_pct)


def _apply_brightness_delta_pct(
    *,
    client: Optional[HomeAssistantClient],
    entity_id: str,
    delta_pct: int,
    cfg: ExecutionConfig,
) -> int:
    """Resolve relative brightness delta to an absolute brightness_pct."""
    if cfg.dry_run or client is None:
        current_pct = int(cfg.default_brightness_pct)
    else:
        try:
            st = client.get_state(entity_id)
            current_pct = _extract_current_brightness_pct(st, default_pct=cfg.default_brightness_pct)
        except HomeAssistantError:
            current_pct = int(cfg.default_brightness_pct)

    # Apply delta and clamp
    new_pct = _clamp_int(int(current_pct) + int(delta_pct), 0, 100)

    # For relative adjustments we avoid going effectively "off".
    # Turning a light off should be an explicit intent (TURN_OFF), not a side-effect
    # of a small negative adjustment while already dim.
    floor_pct = int(getattr(cfg, "min_adjust_brightness_pct", 0) or 0)
    if floor_pct > 0:
        new_pct = max(floor_pct, new_pct)
    return new_pct
def _apply_color_temp_delta(
    *,
    client: Optional[HomeAssistantClient],
    entity_id: str,
    delta_k: int,
    caps: Dict[str, Any],
    cfg: ExecutionConfig,
) -> int:
    # Determine current K
    if cfg.dry_run or client is None:
        current_k = int(cfg.default_color_temp_kelvin)
    else:
        try:
            st = client.get_state(entity_id)
            current_k = _extract_current_color_temp_kelvin(st, default_k=cfg.default_color_temp_kelvin)
        except HomeAssistantError:
            current_k = int(cfg.default_color_temp_kelvin)

    # Clamp to device range if known
    rng = (caps or {}).get("color_temp_kelvin_range") or {}
    lo = int(rng.get("min", 1500))
    hi = int(rng.get("max", 6500))
    new_k = _clamp_int(current_k + int(delta_k), lo, hi)
    return new_k


def build_service_calls_from_validated(
    validated: Dict[str, Any],
    *,
    device_registry: Dict[str, Any],
    client: Optional[HomeAssistantClient] = None,
    cfg: Optional[ExecutionConfig] = None,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Build HA service call payloads.

    Returns:
        (calls, errors)
    """
    cfg = cfg or ExecutionConfig()
    errors: List[Dict[str, Any]] = []
    calls: List[Dict[str, Any]] = []

    if validated.get("status") != "EXECUTABLE":
        errors.append({"code": "NOT_EXECUTABLE", "message": f"ValidatedCommand status={validated.get('status')}"})
        return [], errors

    entity_caps = _build_entity_cap_index(device_registry)

    normalized_actions = ((validated.get("normalized") or {}).get("actions") or [])
    execution_plan = list(validated.get("execution_plan") or [])

    # We expect 1:1 order match, but keep best-effort handling.
    n = min(len(normalized_actions), len(execution_plan))
    for i in range(n):
        na = normalized_actions[i] or {}
        step = execution_plan[i] or {}

        # Convert ExecutionStep to service/target/data and drop nulls
        svc_call = execution_step_to_service_call(step, color_temp_unit="kelvin")
        service = svc_call["service"]
        target = svc_call.get("target") or {}
        data = svc_call.get("data") or {}

        # Resolve targets to entity_ids (always prefer entity_id for REST calls)
        entities = _resolve_target_entities(target, device_registry)
        if not entities:
            errors.append({"code": "NO_TARGET", "message": "No entity_ids resolved", "index": i})
            continue

        intent = str(na.get("intent"))
        params = (na.get("params") or {})

        # Special case: relative color temp requires runtime state.
        if intent == "ADJUST_COLOR_TEMP":
            delta_k = params.get("color_temp_delta_k")
            if delta_k is None:
                errors.append({"code": "MISSING_DELTA", "message": "color_temp_delta_k is missing", "index": i})
                continue

            # Build calls per entity to respect per-device ranges/current state.
            for ent in entities:
                caps = entity_caps.get(ent, {})
                new_k = _apply_color_temp_delta(
                    client=client,
                    entity_id=ent,
                    delta_k=int(delta_k),
                    caps=caps,
                    cfg=cfg,
                )
                per_data = dict(data)
                per_data.pop("brightness_step_pct", None)  # irrelevant here
                per_data.pop("brightness_pct", None)
                per_data.pop("rgb_color", None)
                per_data["color_temp_kelvin"] = new_k

                # Optionally convert to mireds for installations that prefer it.
                if cfg.color_temp_unit == "mireds":
                    per_data.pop("color_temp_kelvin", None)
                    per_data["color_temp"] = kelvin_to_mired(new_k)

                calls.append({"service": service, "entity_id": ent, "data": per_data})
            continue


        # Special case: relative brightness delta is more robust when resolved against current state.
        # Using HA's brightness_step_pct directly can turn the light off when current brightness is low.
        if intent == "ADJUST_BRIGHTNESS":
            delta_pct = params.get("brightness_delta_pct")
            if delta_pct is None:
                errors.append({"code": "MISSING_DELTA", "message": "brightness_delta_pct is missing", "index": i})
                continue

            for ent in entities:
                new_pct = _apply_brightness_delta_pct(
                    client=client,
                    entity_id=ent,
                    delta_pct=int(delta_pct),
                    cfg=cfg,
                )
                per_data = dict(data)
                # Remove the step field and use absolute brightness instead
                per_data.pop("brightness_step_pct", None)
                per_data.pop("rgb_color", None)
                per_data.pop("color_temp_kelvin", None)
                per_data["brightness_pct"] = new_pct
                calls.append({"service": service, "entity_id": ent, "data": per_data})
            continue

        # For other intents, we can group all entities into one call.
        payload = dict(data)
        payload["entity_id"] = entities if len(entities) > 1 else entities[0]

        # Defensive clamping for brightness_pct
        if payload.get("brightness_pct") is not None:
            try:
                b = int(payload["brightness_pct"])
                # 0 is allowed by HA, but we prefer TURN_OFF; validator should already handle it.
                payload["brightness_pct"] = _clamp_int(b, 0, 100)
            except Exception:
                payload.pop("brightness_pct", None)

        # Defensive clamping for brightness_step_pct
        if payload.get("brightness_step_pct") is not None:
            try:
                d = int(payload["brightness_step_pct"])
                payload["brightness_step_pct"] = _clamp_int(d, -100, 100)
            except Exception:
                payload.pop("brightness_step_pct", None)

        # Defensive clamp for Kelvin (absolute)
        if payload.get("color_temp_kelvin") is not None:
            try:
                k = int(payload["color_temp_kelvin"])
                # Use first entity's range if present; otherwise common defaults.
                caps0 = entity_caps.get(entities[0], {})
                rng = (caps0 or {}).get("color_temp_kelvin_range") or {}
                lo = int(rng.get("min", 1500))
                hi = int(rng.get("max", 6500))
                payload["color_temp_kelvin"] = _clamp_int(k, lo, hi)
                if cfg.color_temp_unit == "mireds":
                    payload.pop("color_temp_kelvin", None)
                    payload["color_temp"] = kelvin_to_mired(k)
            except Exception:
                payload.pop("color_temp_kelvin", None)

        # Defensive check for rgb_color
        if payload.get("rgb_color") is not None:
            rgb = payload.get("rgb_color")
            if (
                not isinstance(rgb, list)
                or len(rgb) != 3
                or any((not isinstance(v, int) or v < 0 or v > 255) for v in rgb)
            ):
                payload.pop("rgb_color", None)

        calls.append({"service": service, "payload": payload})

    return calls, errors


def execute_validated_on_ha(
    validated: Dict[str, Any],
    *,
    device_registry: Dict[str, Any],
    client: HomeAssistantClient,
    cfg: Optional[ExecutionConfig] = None,
) -> ExecutionResult:
    """Execute a ValidatedCommand on Home Assistant."""
    cfg = cfg or ExecutionConfig()
    calls, errors = build_service_calls_from_validated(validated, device_registry=device_registry, client=client, cfg=cfg)

    results: List[Any] = []
    if errors:
        return ExecutionResult(ok=False, calls=calls, results=results, errors=errors)

    if cfg.dry_run:
        return ExecutionResult(ok=True, calls=calls, results=results, errors=[])

    for call in calls:
        service = call["service"]
        # Two shapes:
        # - per-entity: {service, entity_id, data}
        # - grouped: {service, payload}
        if "payload" in call:
            payload = call["payload"]
        else:
            payload = dict(call.get("data") or {})
            payload["entity_id"] = call.get("entity_id")
        try:
            results.append(client.call_service(service, payload))
        except HomeAssistantError as e:
            errors.append({"code": "HA_ERROR", "message": str(e), "service": service, "status": e.status, "body": e.body})
            # Stop on first failure to avoid partial side effects.
            break

    return ExecutionResult(ok=(len(errors) == 0), calls=calls, results=results, errors=errors)
