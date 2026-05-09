"""Scenario authoring foundation.

This module provides a deterministic bridge between a structured ScenarioBundle
and Home Assistant automations:
- schema validation
- trigger/condition normalization
- action validation through the existing command validator
- compilation to HA automation dictionaries
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from .assets import AssetPaths
from .ha_adapter import execution_step_to_service_call
from .io import load_json
from .schema_utils import load_schema, validate_with_schema
from .validator import validate_parsed_command


_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?$")
_SUPPORTED_SCENARIO_INTENTS = {
    "TURN_ON",
    "TURN_OFF",
    "SET_BRIGHTNESS",
    "ADJUST_BRIGHTNESS",
    "SET_COLOR",
    "SET_COLOR_TEMP",
}


class ScenarioValidationError(ValueError):
    """Scenario structure is invalid or unsupported for automation compilation."""


@dataclass(frozen=True)
class ScenarioPipelineResult:
    stage: str  # "CLARIFICATION" | "VALIDATED"
    parsed: Dict[str, Any]
    validated: Optional[Dict[str, Any]]
    automations: Optional[List[Dict[str, Any]]]


def _normalize_time_string(value: str, *, field_name: str) -> str:
    raw = str(value or "").strip()
    match = _TIME_RE.fullmatch(raw)
    if not match:
        raise ScenarioValidationError(f"Invalid {field_name}: {value!r}")
    hour, minute, second = match.groups()
    return f"{int(hour):02d}:{int(minute):02d}:{int(second or 0):02d}"


def _seconds_to_hms(total_s: int) -> str:
    total = max(0, int(total_s))
    hours = total // 3600
    minutes = (total % 3600) // 60
    seconds = total % 60
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def _slugify(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "_", str(text or "").strip().lower())
    return cleaned.strip("_") or "scenario"


def _all_light_entity_ids(device_registry: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    for device in device_registry.get("devices", []) or []:
        if not isinstance(device, dict):
            continue
        if str(device.get("device_type") or "") != "light":
            continue
        entity_id = ((device.get("home_assistant") or {}).get("entity_id"))
        if isinstance(entity_id, str) and entity_id.strip():
            out.append(entity_id)
    return out


def _resolve_area_entity_ids(area_name: str, device_registry: Dict[str, Any]) -> List[str]:
    canonical = str(area_name or "").strip()
    if not canonical:
        return []

    device_ids: List[str] = []
    for area in device_registry.get("areas", []) or []:
        if isinstance(area, dict) and str(area.get("name") or "") == canonical:
            device_ids = [str(did) for did in (area.get("devices") or []) if str(did).strip()]
            break

    devices_by_id = {
        str(device.get("device_id")): device
        for device in (device_registry.get("devices", []) or [])
        if isinstance(device, dict) and device.get("device_id")
    }
    entity_ids: List[str] = []
    for device_id in device_ids:
        device = devices_by_id.get(device_id)
        entity_id = ((device or {}).get("home_assistant") or {}).get("entity_id")
        if isinstance(entity_id, str) and entity_id.strip():
            entity_ids.append(entity_id)
    return entity_ids


def _resolve_execution_target_entities(step_target: Dict[str, Any], device_registry: Dict[str, Any]) -> List[str]:
    entity_ids = [str(e) for e in (step_target.get("entity_id") or []) if str(e).strip()]
    if entity_ids:
        return entity_ids
    area_name = step_target.get("area_name")
    if isinstance(area_name, str) and area_name.strip():
        return _resolve_area_entity_ids(area_name, device_registry)
    return []


def _validate_trigger(trigger: Dict[str, Any], *, rule_title: str) -> Dict[str, Any]:
    trig_type = str(trigger.get("type") or "").strip()
    if trig_type == "time":
        return {
            "type": "time",
            "at": _normalize_time_string(trigger.get("at"), field_name=f"{rule_title}.trigger.at"),
            "days_of_week": [str(day) for day in (trigger.get("days_of_week") or []) if str(day).strip()] or None,
        }
    if trig_type == "state":
        entity_id = str(trigger.get("entity_id") or "").strip()
        state_to = str(trigger.get("to") or "").strip()
        if not entity_id or not state_to:
            raise ScenarioValidationError(f"{rule_title}: state trigger requires entity_id and to")
        for_s = trigger.get("for_s")
        return {
            "type": "state",
            "entity_id": entity_id,
            "to": state_to,
            "for_s": None if for_s is None else max(0, int(for_s)),
        }
    if trig_type == "numeric_state":
        entity_id = str(trigger.get("entity_id") or "").strip()
        above = trigger.get("above")
        below = trigger.get("below")
        if not entity_id:
            raise ScenarioValidationError(f"{rule_title}: numeric_state trigger requires entity_id")
        if above is None and below is None:
            raise ScenarioValidationError(f"{rule_title}: numeric_state trigger requires above or below")
        return {
            "type": "numeric_state",
            "entity_id": entity_id,
            "above": None if above is None else float(above),
            "below": None if below is None else float(below),
        }
    raise ScenarioValidationError(f"{rule_title}: unsupported trigger type {trig_type!r}")


def _validate_condition(condition: Dict[str, Any], *, rule_title: str, index: int) -> Dict[str, Any]:
    cond_type = str(condition.get("type") or "").strip()
    path = f"{rule_title}.conditions[{index}]"
    if cond_type == "time_window":
        after = condition.get("after")
        before = condition.get("before")
        if after is None and before is None:
            raise ScenarioValidationError(f"{path}: time_window requires after or before")
        return {
            "type": "time_window",
            "after": None if after is None else _normalize_time_string(after, field_name=f"{path}.after"),
            "before": None if before is None else _normalize_time_string(before, field_name=f"{path}.before"),
        }
    if cond_type == "state":
        entity_id = str(condition.get("entity_id") or "").strip()
        operator = str(condition.get("operator") or "").strip()
        value = str(condition.get("value") or "").strip()
        if not entity_id or operator not in {"==", "!="} or not value:
            raise ScenarioValidationError(f"{path}: invalid state condition")
        for_s = condition.get("for_s")
        return {
            "type": "state",
            "entity_id": entity_id,
            "operator": operator,
            "value": value,
            "for_s": None if for_s is None else max(0, int(for_s)),
        }
    if cond_type == "numeric":
        entity_id = str(condition.get("entity_id") or "").strip()
        operator = str(condition.get("operator") or "").strip()
        value = condition.get("value")
        if not entity_id or operator not in {"<", "<=", ">", ">=", "="} or value is None:
            raise ScenarioValidationError(f"{path}: invalid numeric condition")
        return {
            "type": "numeric",
            "entity_id": entity_id,
            "operator": operator,
            "value": float(value),
        }
    raise ScenarioValidationError(f"{path}: unsupported condition type {cond_type!r}")


def _validate_action_block(
    actions: List[Dict[str, Any]],
    *,
    context: Dict[str, Any],
    device_registry: Dict[str, Any],
    area_synonyms: Dict[str, Any],
    rule_title: str,
    block_name: str,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    parsed_command = {
        "schema_version": "1.0",
        "actions": list(actions),
        "clarification": None,
    }
    validated = validate_parsed_command(
        parsed_command,
        context=context,
        device_registry=device_registry,
        area_synonyms=area_synonyms,
    )
    if str(validated.get("status") or "") != "EXECUTABLE":
        reason = validated.get("reason_code") or validated.get("status") or "INVALID"
        raise ScenarioValidationError(f"{rule_title}.{block_name}: actions are not executable ({reason})")

    normalized_actions = list(((validated.get("normalized") or {}).get("actions") or []))
    for action in normalized_actions:
        intent = str(action.get("intent") or "")
        if intent not in _SUPPORTED_SCENARIO_INTENTS:
            raise ScenarioValidationError(f"{rule_title}.{block_name}: unsupported automation intent {intent}")

    raw_execution_plan = validated.get("execution_plan") or []
    if isinstance(raw_execution_plan, dict):
        execution_steps = list(raw_execution_plan.get("steps") or [])
    else:
        execution_steps = list(raw_execution_plan or [])
    for step in execution_steps:
        data = step.get("data") or {}
        if data.get("color_temp_delta_k") is not None:
            raise ScenarioValidationError(
                f"{rule_title}.{block_name}: relative color temperature is not supported in automations yet"
            )
    warnings = list(validated.get("warnings") or [])
    return normalized_actions, execution_steps, warnings


def validate_scenario_bundle(
    parsed_bundle: Dict[str, Any],
    *,
    context: Optional[Dict[str, Any]] = None,
    root_dir: Optional[Union[str, Path]] = None,
    device_registry: Optional[Dict[str, Any]] = None,
    area_synonyms: Optional[Dict[str, Any]] = None,
    scenario_schema: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Validate a parsed ScenarioBundle and prepare it for HA compilation."""
    ctx = context or {"selected_area_name": None, "last_area_name": None}
    paths = AssetPaths(Path(root_dir) if root_dir is not None else Path(__file__).resolve().parents[1])
    device_registry = device_registry or load_json(paths.device_registry)
    area_synonyms = area_synonyms or load_json(paths.area_synonyms)
    scenario_schema = scenario_schema or load_schema(paths.scenario_bundle_schema)

    validate_with_schema(parsed_bundle, scenario_schema)
    clarification = dict(parsed_bundle.get("clarification") or {})
    if clarification.get("needed"):
        return {
            "schema_version": "1.0",
            "status": "CLARIFICATION",
            "title": parsed_bundle.get("title"),
            "description": parsed_bundle.get("description"),
            "clarification": clarification,
            "rules": [],
            "warnings": [],
        }

    validated_rules: List[Dict[str, Any]] = []
    bundle_warnings: List[Dict[str, Any]] = []
    for idx, raw_rule in enumerate(parsed_bundle.get("rules") or []):
        rule_title = str(raw_rule.get("title") or f"Rule {idx + 1}")
        trigger = _validate_trigger(dict(raw_rule.get("trigger") or {}), rule_title=rule_title)
        conditions = [
            _validate_condition(dict(condition or {}), rule_title=rule_title, index=condition_idx)
            for condition_idx, condition in enumerate(raw_rule.get("conditions") or [])
        ]
        then_actions, then_steps, then_warnings = _validate_action_block(
            list(raw_rule.get("actions") or []),
            context=ctx,
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            rule_title=rule_title,
            block_name="actions",
        )
        else_actions: List[Dict[str, Any]] = []
        else_steps: List[Dict[str, Any]] = []
        else_warnings: List[Dict[str, Any]] = []
        if raw_rule.get("else_actions"):
            else_actions, else_steps, else_warnings = _validate_action_block(
                list(raw_rule.get("else_actions") or []),
                context=ctx,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
                rule_title=rule_title,
                block_name="else_actions",
            )

        rule_id = str(raw_rule.get("rule_id") or "").strip() or f"rule_{idx + 1}_{_slugify(rule_title)}"
        validated_rules.append(
            {
                "rule_id": rule_id,
                "title": raw_rule.get("title") or rule_title,
                "enabled": bool(raw_rule.get("enabled", True)),
                "trigger": trigger,
                "conditions": conditions,
                "actions": then_actions,
                "else_actions": else_actions,
                "then_execution_steps": then_steps,
                "else_execution_steps": else_steps,
                "warnings": then_warnings + else_warnings,
            }
        )
        bundle_warnings.extend(then_warnings)
        bundle_warnings.extend(else_warnings)

    return {
        "schema_version": "1.0",
        "status": "VALIDATED",
        "title": parsed_bundle.get("title"),
        "description": parsed_bundle.get("description"),
        "clarification": clarification,
        "rules": validated_rules,
        "warnings": bundle_warnings,
    }


def _compile_trigger(trigger: Dict[str, Any]) -> Dict[str, Any]:
    trig_type = str(trigger.get("type") or "")
    if trig_type == "time":
        out: Dict[str, Any] = {"trigger": "time", "at": trigger["at"]}
        if trigger.get("days_of_week"):
            out["weekday"] = list(trigger["days_of_week"])
        return out
    if trig_type == "state":
        out = {
            "trigger": "state",
            "entity_id": trigger["entity_id"],
            "to": trigger["to"],
        }
        if trigger.get("for_s") is not None:
            out["for"] = _seconds_to_hms(int(trigger["for_s"]))
        return out
    if trig_type == "numeric_state":
        out = {
            "trigger": "numeric_state",
            "entity_id": trigger["entity_id"],
        }
        if trigger.get("above") is not None:
            out["above"] = trigger["above"]
        if trigger.get("below") is not None:
            out["below"] = trigger["below"]
        return out
    raise ScenarioValidationError(f"Unsupported trigger type for compile: {trig_type!r}")


def _compile_numeric_template(entity_id: str, operator: str, value: float) -> str:
    value_literal = int(value) if float(value).is_integer() else float(value)
    return f"{{{{ states('{entity_id}') | float(0) {operator} {value_literal} }}}}"


def _compile_conditions(conditions: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for condition in conditions:
        cond_type = str(condition.get("type") or "")
        if cond_type == "time_window":
            item: Dict[str, Any] = {"condition": "time"}
            if condition.get("after"):
                item["after"] = condition["after"]
            if condition.get("before"):
                item["before"] = condition["before"]
            out.append(item)
            continue
        if cond_type == "state":
            state_condition = {
                "condition": "state",
                "entity_id": condition["entity_id"],
                "state": condition["value"],
            }
            if condition.get("for_s") is not None:
                state_condition["for"] = _seconds_to_hms(int(condition["for_s"]))
            if condition.get("operator") == "!=":
                out.append({"condition": "not", "conditions": [state_condition]})
            else:
                out.append(state_condition)
            continue
        if cond_type == "numeric":
            out.append(
                {
                    "condition": "template",
                    "value_template": _compile_numeric_template(
                        condition["entity_id"],
                        condition["operator"],
                        float(condition["value"]),
                    ),
                }
            )
            continue
        raise ScenarioValidationError(f"Unsupported condition type for compile: {cond_type!r}")
    return out


def _compile_action_sequence(
    steps: List[Dict[str, Any]],
    *,
    device_registry: Dict[str, Any],
    color_temp_unit: str,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    all_lights = _all_light_entity_ids(device_registry)
    for step in steps:
        call = execution_step_to_service_call(step, color_temp_unit=color_temp_unit)
        target = dict(call.get("target") or {})
        entity_ids = _resolve_execution_target_entities(target, device_registry)
        if not entity_ids and target.get("area_name") is None:
            entity_ids = list(all_lights)
        action_step: Dict[str, Any] = {
            "action": call["service"],
            "data": dict(call.get("data") or {}),
        }
        if entity_ids:
            action_step["target"] = {"entity_id": entity_ids}
        out.append(action_step)
    return out


def compile_scenario_bundle_to_ha_automations(
    validated_bundle: Dict[str, Any],
    *,
    root_dir: Optional[Union[str, Path]] = None,
    device_registry: Optional[Dict[str, Any]] = None,
    color_temp_unit: str = "kelvin",
) -> List[Dict[str, Any]]:
    """Compile a validated scenario bundle into Home Assistant automations."""
    if str(validated_bundle.get("status") or "") != "VALIDATED":
        raise ScenarioValidationError("Scenario bundle must be VALIDATED before compilation")

    paths = AssetPaths(Path(root_dir) if root_dir is not None else Path(__file__).resolve().parents[1])
    device_registry = device_registry or load_json(paths.device_registry)

    bundle_title = str(validated_bundle.get("title") or "Сценарий").strip()
    automations: List[Dict[str, Any]] = []
    for rule in validated_bundle.get("rules") or []:
        if not bool(rule.get("enabled", True)):
            continue
        alias_title = str(rule.get("title") or rule.get("rule_id") or "rule").strip()
        alias = f"{bundle_title}: {alias_title}"
        conditions = _compile_conditions(list(rule.get("conditions") or []))
        then_sequence = _compile_action_sequence(
            list(rule.get("then_execution_steps") or []),
            device_registry=device_registry,
            color_temp_unit=color_temp_unit,
        )
        else_steps = list(rule.get("else_execution_steps") or [])
        automation: Dict[str, Any] = {
            "id": str(rule.get("rule_id") or _slugify(alias)),
            "alias": alias,
            "mode": "single",
            "trigger": [_compile_trigger(dict(rule.get("trigger") or {}))],
        }
        if conditions and else_steps:
            default_sequence = _compile_action_sequence(
                else_steps,
                device_registry=device_registry,
                color_temp_unit=color_temp_unit,
            )
            automation["action"] = [
                {
                    "choose": [
                        {
                            "conditions": conditions,
                            "sequence": then_sequence,
                        }
                    ],
                    "default": default_sequence,
                }
            ]
        else:
            if conditions:
                automation["condition"] = conditions
            automation["action"] = then_sequence
        automations.append(automation)
    return automations
