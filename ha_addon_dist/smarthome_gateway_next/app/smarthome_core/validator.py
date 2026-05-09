"""Validator: ParsedCommand -> ValidatedCommand (v1).

Design goals:
- deterministic outputs (good for evaluation)
- minimal clarifications (ask only if unavoidable)
- keep enough info for executor to resolve deltas requiring current state
  (e.g., color_temp_delta_k)
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple, Union

from .text_templates import (
    missing_target_question,
    unknown_area_question,
    too_many_actions_question,
    option_label_for_action,
)


Warning = Dict[str, Any]


@dataclass(frozen=True)
class ValidatorConfig:
    """Subset of device_registry settings that impacts validation."""

    max_actions_per_utterance: int
    brightness_zero_policy: str

    @staticmethod
    def from_registry(device_registry: Dict[str, Any]) -> "ValidatorConfig":
        rules = device_registry.get("resolution_rules", {})
        return ValidatorConfig(
            max_actions_per_utterance=int(rules.get("max_actions_per_utterance", 3)),
            brightness_zero_policy=str(rules.get("brightness_zero_policy", "treat_as_turn_off")),
        )


def _available_areas(device_registry: Dict[str, Any]) -> List[str]:
    """Return canonical area names in stable order from the registry."""
    areas = device_registry.get("areas", [])
    if isinstance(areas, list) and areas and isinstance(areas[0], dict):
        return [str(a.get("name")) for a in areas if isinstance(a, dict) and a.get("name")]
    return [str(a) for a in areas]


def _normalize_text(s: str, *, rules: Dict[str, Any]) -> str:
    """Normalize text using the lexicon rules (best-effort, deterministic)."""
    out = s.strip()
    if rules.get("trim", True):
        out = out.strip()
    if rules.get("lowercase", True):
        out = out.lower()
    if rules.get("collapse_spaces", True):
        out = " ".join(out.split())
    if rules.get("yo_to_e", True):
        out = out.replace("ё", "е")
    if rules.get("punctuation_strip", True):
        # Keep letters/digits/spaces only
        import re

        out = re.sub(r"[^0-9a-zA-Zа-яА-Я\s]", "", out)
        out = " ".join(out.split())
    return out


def _build_area_synonym_index(area_synonyms: Dict[str, Any]) -> Tuple[Dict[str, Union[str, List[str]]], Dict[str, Any]]:
    """Build a map: normalized synonym -> canonical area name.

    Supports direct synonym maps and structured lexicon entries.
    """
    normalization = (area_synonyms.get("normalization") if isinstance(area_synonyms, dict) else None) or {
        "lowercase": True,
        "trim": True,
        "collapse_spaces": True,
        "yo_to_e": True,
        "punctuation_strip": True,
    }

    direct_synonyms = area_synonyms.get("synonyms") if isinstance(area_synonyms, dict) else None
    if isinstance(direct_synonyms, dict):
        idx: Dict[str, Union[str, List[str]]] = {}
        for k, v in direct_synonyms.items():
            nk = _normalize_text(str(k), rules=normalization)
            idx[nk] = str(v)
        return idx, normalization

    idx = {}
    canonical_areas = area_synonyms.get("canonical_areas") if isinstance(area_synonyms, dict) else None
    if isinstance(canonical_areas, list):
        for entry in canonical_areas:
            if not isinstance(entry, dict):
                continue
            name = entry.get("name")
            if not name:
                continue
            canonical_name = str(name)
            candidates = [canonical_name] + list(entry.get("synonyms") or [])
            for syn in candidates:
                ns = _normalize_text(str(syn), rules=normalization)
                prev = idx.get(ns)
                if prev is None:
                    idx[ns] = canonical_name
                else:
                    if isinstance(prev, list):
                        if canonical_name not in prev:
                            prev.append(canonical_name)
                    elif prev != canonical_name:
                        idx[ns] = [prev, canonical_name]
    return idx, normalization


def _resolve_area_name(
    area_raw: str, available: List[str], area_synonyms: Dict[str, Any]
) -> Tuple[Optional[str], Optional[Warning], bool]:
    """Resolve a raw area name into a canonical one, using synonyms.

    Returns:
        (canonical_area_name or None, warning or None, is_ambiguous)
    """
    raw = str(area_raw or "")
    if not raw.strip():
        return None, None, False

    idx, norm_rules = _build_area_synonym_index(area_synonyms)
    raw_norm = _normalize_text(raw, rules=norm_rules)

    # Direct canonical match (case/yo/punct insensitive)
    canon_norm_map = {_normalize_text(a, rules=norm_rules): a for a in available}
    if raw_norm in canon_norm_map:
        canonical = canon_norm_map[raw_norm]
        # If casing/etc differs, still report synonym resolution as a benign warning
        warn = None
        if raw != canonical:
            warn = {
                "code": "SYNONYM_RESOLVED",
                "message": f"area synonym: {raw_norm} → {canonical}",
                "path": "/normalized/actions/0/target/area_name",
            }
        return canonical, warn, False

    # Synonym index lookup
    hit = idx.get(raw_norm)
    if isinstance(hit, str):
        canonical = hit
        warn = {
            "code": "SYNONYM_RESOLVED",
            "message": f"area synonym: {raw_norm} → {canonical}",
            "path": "/normalized/actions/0/target/area_name",
        }
        return canonical, warn, False
    if isinstance(hit, list) and hit:
        warn = {
            "code": "AMBIGUOUS_SYNONYM",
            "message": f"area synonym '{raw_norm}' matches multiple areas: {', '.join(hit)}",
            "path": "/normalized/actions/0/target/area_name",
        }
        return None, warn, True

    return None, None, False


def _target_key(target: Dict[str, Any]) -> Tuple[str, Optional[str], Tuple[str, ...]]:
    return (str(target.get("scope")), target.get("area_name"), tuple(target.get("entity_ids") or []))


def _is_conflicting_intents(actions: List[Dict[str, Any]]) -> bool:
    """Detect simple conflicts: TURN_OFF + anything else on the same target."""
    if len(actions) < 2:
        return False
    by_target: Dict[Tuple[str, Optional[str], Tuple[str, ...]], List[str]] = {}
    for a in actions:
        by_target.setdefault(_target_key(a.get("target", {})), []).append(str(a.get("intent")))
    for intents in by_target.values():
        if "TURN_OFF" in intents and any(i != "TURN_OFF" for i in intents):
            return True
    return False


def _normalize_action(parsed_action: Dict[str, Any], idx: int, config: ValidatorConfig, warnings: List[Warning]) -> Dict[str, Any]:
    """Convert ParsedAction to NormalizedAction."""
    intent = str(parsed_action.get("intent"))
    params = parsed_action.get("params") or {}

    brightness = params.get("brightness")
    brightness_delta = params.get("brightness_delta")
    color = params.get("color")
    color_temp_kelvin = params.get("color_temp_kelvin")
    color_temp_delta_k = params.get("color_temp_delta_k")
    transition_s = params.get("transition_s")

    # Brightness=0 policy
    if (
        intent == "SET_BRIGHTNESS"
        and str(config.brightness_zero_policy) in {"treat_as_turn_off", "TURN_OFF"}
        and brightness == 0
    ):
        intent = "TURN_OFF"
        brightness = None
        warnings.append({
            "code": "FALLBACK_APPLIED",
            "message": "brightness=0 treated as TURN_OFF",
            "path": f"/normalized/actions/{idx}/intent",
        })

    # Once intent is TURN_OFF, drop all "turn_on" parameters that could violate schema (e.g., brightness_pct=0)
    # and/or confuse the executor. Keeping only transition is OK.
    if intent == "TURN_OFF":
        brightness = None
        brightness_delta = None
        color = None
        color_temp_kelvin = None
        color_temp_delta_k = None

    normalized = {
        "domain": "light",
        "intent": intent,
        "target": parsed_action.get("target"),
        "params": {
            "brightness_pct": brightness,
            "brightness_delta_pct": brightness_delta,
            "rgb_color": (color or {}).get("rgb") if isinstance(color, dict) else None,
            "color_temp_kelvin": color_temp_kelvin,
            "color_temp_delta_k": color_temp_delta_k,
            "transition_s": transition_s,
        },
    }
    return normalized


def _execution_step_for_action(normalized_action: Dict[str, Any], idx: int, warnings: List[Warning]) -> Dict[str, Any]:
    """Build Home Assistant execution step.

    Notes:
    - Most light intents map to `light.turn_on`, except `TURN_OFF`.
    - For `TURN_ON`, we *do* pass through optional params (brightness/color/temp) if the parser provided them.
    - For `ADJUST_COLOR_TEMP`, we intentionally leave `color_temp_kelvin=None` and attach a warning.
      Executor is expected to resolve the delta against current state at runtime.
    """
    intent = str(normalized_action.get("intent"))
    target = normalized_action.get("target") or {}
    params = normalized_action.get("params") or {}

    service = "light.turn_off" if intent == "TURN_OFF" else "light.turn_on"

    data = {
        "brightness_pct": None,
        "brightness_step_pct": None,
        "rgb_color": None,
        "color_temp_kelvin": None,
        "transition": params.get("transition_s", 0.8),
    }

    # Absolute params can be passed through for TURN_ON as well.
    if params.get("brightness_pct") is not None and intent in {"TURN_ON", "SET_BRIGHTNESS"}:
        data["brightness_pct"] = params.get("brightness_pct")
    if params.get("rgb_color") is not None and intent in {"TURN_ON", "SET_COLOR"}:
        data["rgb_color"] = params.get("rgb_color")
    if params.get("color_temp_kelvin") is not None and intent in {"TURN_ON", "SET_COLOR_TEMP"}:
        data["color_temp_kelvin"] = params.get("color_temp_kelvin")

    # Relative brightness can be applied via HA step API.
    if intent == "ADJUST_BRIGHTNESS":
        data["brightness_step_pct"] = params.get("brightness_delta_pct")

    # Relative color temperature needs the current state -> executor will resolve later.
    if intent == "ADJUST_COLOR_TEMP":
        warnings.append({
            "code": "PARAM_DROPPED",
            "message": "color_temp_delta_k requires current state; executor will resolve",
            "path": f"/execution_plan/{idx}/data/color_temp_kelvin",
        })

    exec_target = {
        "entity_id": list(target.get("entity_ids") or []),
        "area_name": target.get("area_name"),
    }

    return {
        "executor": "HOME_ASSISTANT",
        "service": service,
        "target": exec_target,
        "data": data,
    }


def validate_parsed_command(
    parsed_command: Dict[str, Any],
    *,
    context: Dict[str, Any],
    device_registry: Dict[str, Any],
    area_synonyms: Dict[str, Any],
) -> Dict[str, Any]:
    """Main entrypoint: validate ParsedCommand and produce ValidatedCommand.

    Args:
        parsed_command: ParsedCommand dict (parser output).
        context: dict, must contain at least {"last_area_name": <str|None>}.
        device_registry: registry/device_registry_v1.json loaded dict.
        area_synonyms: lexicon/area_synonyms_v1.json loaded dict.

    Returns:
        ValidatedCommand dict.
    """
    config = ValidatorConfig.from_registry(device_registry)
    available_areas = _available_areas(device_registry)

    actions = list(parsed_command.get("actions") or [])
    parsed_clar = parsed_command.get("clarification") or {}    # Meta cancel / stop: recognized NO-OP command.
    # We acknowledge the cancellation and produce no execution plan.
    if any(a.get("intent") == "CANCEL" for a in actions):
        # Keep existing context unless user explicitly mentioned an area.
        explicit_area: Optional[str] = None
        for a in actions:
            if a.get("intent") == "CANCEL":
                t = a.get("target") or {}
                if t.get("scope") == "AREA" and isinstance(t.get("area_name"), str):
                    explicit_area = t.get("area_name")
                break

        last_area_name = explicit_area if explicit_area is not None else (
            context.get("selected_area_name") or context.get("last_area_name")
        )

        return {
            "schema_version": "1.0",
            "status": "NOOP",
            "reason_code": "OK",
            "warnings": [{"code": "META_CANCEL", "message": "User cancelled / stop command. No execution.", "path": "/"}],
            "normalized": {"actions": [], "context_updates": {"last_area_name": last_area_name, "last_entity_ids": []}},
            "execution_plan": [],
        }

    # 0) Too many actions -> clarification (minimal UI)
    if len(actions) > config.max_actions_per_utterance:
        # Try to infer single shared area for a nicer question
        area_name: Optional[str] = None
        if actions:
            t0 = actions[0].get("target") or {}
            if all((a.get("target") or {}).get("area_name") == t0.get("area_name") for a in actions):
                area_name = t0.get("area_name")

        # Options: exclude TURN_ON (often implied); take up to 3 unique labels
        options: List[str] = []
        for a in actions:
            if str(a.get("intent")) == "TURN_ON":
                continue
            label = option_label_for_action(str(a.get("intent")), a.get("params") or {})
            if label not in options:
                options.append(label)
            if len(options) >= 3:
                break

        return {
            "schema_version": "1.0",
            "status": "NEEDS_CLARIFICATION",
            "reason_code": "TOO_MANY_ACTIONS",
            "warnings": [],
            "normalized": {"actions": [], "context_updates": {"last_area_name": None, "last_entity_ids": []}},
            "execution_plan": [],
            "clarification": {"needed": True, "question": too_many_actions_question(area_name), "options": options},
        }

    warnings: List[Warning] = []

    # 1) Resolve targets (incl. context + synonyms)
    resolved_actions: List[Dict[str, Any]] = []
    for idx, a in enumerate(actions):
        a = dict(a)  # shallow copy
        target = dict(a.get("target") or {})
        scope = str(target.get("scope"))

        if scope == "UNSPECIFIED":
            last_entity_ids = [str(e).strip() for e in (context.get("last_entity_ids") or []) if str(e).strip()]
            last_area = context.get("selected_area_name") or context.get("last_area_name")
            if last_entity_ids:
                target["scope"] = "ENTITY"
                target["area_name"] = None
                target["entity_ids"] = last_entity_ids
                warnings.append({
                    "code": "TARGET_RESOLVED_FROM_CONTEXT_ENTITY",
                    "message": f"target resolved from last_entity_ids={','.join(last_entity_ids)}",
                    "path": f"/normalized/actions/{idx}/target/entity_ids",
                })
            elif last_area:
                target["scope"] = "AREA"
                target["area_name"] = last_area
                target["entity_ids"] = []
                warnings.append({
                    "code": "TARGET_RESOLVED_FROM_CONTEXT",
                    "message": f"target resolved from last_area={last_area}",
                    "path": f"/normalized/actions/{idx}/target/area_name",
                })
            else:
                # need clarification
                question = (parsed_clar.get("question") if parsed_clar.get("needed") else None) or missing_target_question(str(a.get("intent")), a.get("params") or {})
                return {
                    "schema_version": "1.0",
                    "status": "NEEDS_CLARIFICATION",
                    "reason_code": "MISSING_TARGET",
                    "warnings": [],
                    "normalized": {"actions": [], "context_updates": {"last_area_name": None, "last_entity_ids": []}},
                    "execution_plan": [],
                    "clarification": {"needed": True, "question": question, "options": available_areas},
                }

        elif scope == "AREA":
            raw_area = target.get("area_name")
            if not isinstance(raw_area, str) or not raw_area.strip():
                question = (parsed_clar.get("question") if parsed_clar.get("needed") else None) or missing_target_question(str(a.get("intent")), a.get("params") or {})
                return {
                    "schema_version": "1.0",
                    "status": "NEEDS_CLARIFICATION",
                    "reason_code": "MISSING_TARGET",
                    "warnings": [],
                    "normalized": {"actions": [], "context_updates": {"last_area_name": None, "last_entity_ids": []}},
                    "execution_plan": [],
                    "clarification": {"needed": True, "question": question, "options": available_areas},
                }

            canonical, warn, is_ambiguous = _resolve_area_name(raw_area, available_areas, area_synonyms)
            if canonical is None:
                if is_ambiguous and warn is not None:
                    question = "Уточните комнату, пожалуйста."
                    # Try to expose the ambiguous options from the warning message if present.
                    options = available_areas
                    return {
                        "schema_version": "1.0",
                        "status": "NEEDS_CLARIFICATION",
                        "reason_code": "AMBIGUOUS_TARGET",
                        "warnings": [warn],
                        "normalized": {"actions": [], "context_updates": {"last_area_name": None, "last_entity_ids": []}},
                        "execution_plan": [],
                        "clarification": {"needed": True, "question": question, "options": options},
                    }

                # unknown area
                question = unknown_area_question(str(a.get("intent")))
                return {
                    "schema_version": "1.0",
                    "status": "NEEDS_CLARIFICATION",
                    "reason_code": "UNKNOWN_AREA",
                    "warnings": [],
                    "normalized": {"actions": [], "context_updates": {"last_area_name": None, "last_entity_ids": []}},
                    "execution_plan": [],
                    "clarification": {"needed": True, "question": question, "options": available_areas},
                }
            if warn is not None and canonical != raw_area:
                warn["path"] = f"/normalized/actions/{idx}/target/area_name"
                warnings.append(warn)
            target["area_name"] = canonical

        elif scope == "ALL_LIGHTS":
            target["area_name"] = None
            target["entity_ids"] = []
        else:
            question = "Не понял, к какому устройству применить команду. Где выполнить?"
            return {
                "schema_version": "1.0",
                "status": "NEEDS_CLARIFICATION",
                "reason_code": "AMBIGUOUS_TARGET",
                "warnings": [],
                "normalized": {"actions": [], "context_updates": {"last_area_name": None, "last_entity_ids": []}},
                "execution_plan": [],
                "clarification": {"needed": True, "question": question, "options": available_areas},
            }

        a["target"] = target
        resolved_actions.append(a)

    # 2) Conflicts -> clarification
    if _is_conflicting_intents(resolved_actions):
        # Prefer parser-provided clarification if available
        clar_q = parsed_clar.get("question") if parsed_clar.get("needed") else None
        clar_opts = parsed_clar.get("options") if parsed_clar.get("needed") else None
        if not clar_q or not clar_opts:
            # Construct generic options from actions
            clar_opts = []
            for a in resolved_actions:
                clar_opts.append(option_label_for_action(str(a.get("intent")), a.get("params") or {}))
        return {
            "schema_version": "1.0",
            "status": "NEEDS_CLARIFICATION",
            "reason_code": "CONFLICTING_INTENTS",
            "warnings": [],
            "normalized": {"actions": [], "context_updates": {"last_area_name": None, "last_entity_ids": []}},
            "execution_plan": [],
            "clarification": {"needed": True, "question": clar_q or "Что сделать?", "options": clar_opts},
        }

    # 2.5) Parser-provided clarification for ambiguous parameters (e.g., "поуютнее").
    # At this point targets are resolved and there are no intent conflicts.
    if bool(parsed_clar.get("needed")):
        last_area_name = context.get("selected_area_name") or context.get("last_area_name")
        last_entity_ids: List[str] = []

        if resolved_actions:
            t0 = resolved_actions[0].get("target") or {}
            scope0 = str(t0.get("scope"))
            if scope0 == "AREA":
                last_area_name = t0.get("area_name")
            elif scope0 == "ENTITY":
                last_entity_ids = [str(e) for e in (t0.get("entity_ids") or [])]

        question = str(parsed_clar.get("question") or "Уточните команду, пожалуйста.")
        options = [str(o) for o in (parsed_clar.get("options") or [])]

        return {
            "schema_version": "1.0",
            "status": "NEEDS_CLARIFICATION",
            "reason_code": "INVALID_PARAMS",
            "warnings": [],
            "normalized": {"actions": [], "context_updates": {"last_area_name": last_area_name, "last_entity_ids": last_entity_ids}},
            "execution_plan": [],
            "clarification": {"needed": True, "question": question, "options": options},
        }

    # 3) Normalize actions
    normalized_actions: List[Dict[str, Any]] = []
    for idx, a in enumerate(resolved_actions):
        normalized_actions.append(_normalize_action(a, idx, config, warnings))

    # 4) Build execution plan
    execution_plan: List[Dict[str, Any]] = []
    for idx, na in enumerate(normalized_actions):
        execution_plan.append(_execution_step_for_action(na, idx, warnings))

    # 5) Context updates: last_area from the *last* AREA action
    last_area_name: Optional[str] = context.get("selected_area_name") or context.get("last_area_name")
    last_entity_ids: List[str] = []
    for na in normalized_actions[::-1]:
        t = na.get("target") or {}
        if t.get("scope") == "ENTITY":
            ent_ids = [str(e) for e in (t.get("entity_ids") or []) if str(e).strip()]
            if ent_ids:
                last_entity_ids = ent_ids
                break
        if t.get("scope") == "AREA" and isinstance(t.get("area_name"), str):
            last_area_name = t.get("area_name")
            break

    validated = {
        "schema_version": "1.0",
        "status": "EXECUTABLE",
        "reason_code": "OK",
        "warnings": warnings,
        "normalized": {"actions": normalized_actions, "context_updates": {"last_area_name": last_area_name, "last_entity_ids": last_entity_ids}},
        "execution_plan": execution_plan,
    }

    return validated
