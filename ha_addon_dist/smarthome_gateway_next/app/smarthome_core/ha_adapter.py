"""Home Assistant adapter utilities.

The validated execution_plan v1 stores color temperature in Kelvin (color_temp_kelvin).
Some HA installations historically used mireds (color_temp). This adapter allows
conversion if needed without changing core schemas.
"""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional


def kelvin_to_mired(k: int) -> int:
    # mired = 1_000_000 / kelvin
    return int(round(1_000_000 / max(k, 1)))


def execution_step_to_service_call(
    step: Dict[str, Any],
    *,
    color_temp_unit: Literal["kelvin", "mireds"] = "kelvin",
) -> Dict[str, Any]:
    """Convert an ExecutionStep into a HA-compatible service call payload.

    Returns dict with keys: service, target, data.
    """
    service = step["service"]
    target = step["target"]
    data = dict(step["data"])

    if color_temp_unit == "mireds" and data.get("color_temp_kelvin") is not None:
        k = int(data["color_temp_kelvin"])
        data.pop("color_temp_kelvin", None)
        data["color_temp"] = kelvin_to_mired(k)

    # Drop null keys for cleaner HA calls (optional; HA accepts missing keys)
    clean_data = {k: v for k, v in data.items() if v is not None}

    return {"service": service, "target": target, "data": clean_data}
