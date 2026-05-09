"""LLM parsing for natural-language automation scenarios."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from .assets import AssetPaths
from .io import load_json
from .llm_client import LLMClient
from .scenario_logic import (
    ScenarioPipelineResult,
    compile_scenario_bundle_to_ha_automations,
    validate_scenario_bundle,
)
from .schema_utils import load_schema, validate_with_schema


SCENARIO_LLM_MAX_OUTPUT_TOKENS = 900

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL | re.IGNORECASE)
_TRAILING_COMMA_RE = re.compile(r",\s*([}\]])")
_TIME_TOKEN_RE = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)\b")
_HINT_CLEAN_RE = re.compile(r"[^0-9a-zA-Zа-яА-ЯёЁ\s%/-]+", flags=re.UNICODE)
_SPACE_RE = re.compile(r"\s+", flags=re.UNICODE)
_WORD_RE = re.compile(r"[0-9a-zA-Zа-яА-ЯёЁ]+", flags=re.UNICODE)
_NUMERIC_PERCENT_RE = re.compile(r"\b(100|[1-9]?\d)\s*%")

_SCENARIO_SYSTEM_PROMPT = (
    "You are a deterministic smart-home automation authoring parser. "
    "Return exactly one compact JSON object matching ScenarioBundle v1. "
    "No markdown, no comments, no explanations, no text outside JSON. "
    "Copy room names exactly from known_areas. Do not invent rooms or entity_ids. "
    "Russian inflected room mentions must be normalized to the canonical known_areas value "
    "(for example: 'в спальне' -> 'Спальня', 'на кухне' -> 'Кухня'). "
    "Prefer AREA targets for named rooms; for AREA targets entity_ids must be []. "
    "If room is omitted, use context.selected_area_name first, then context.last_area_name. "
    "Every action must include all params keys; use null for unused params. "
    "Use [] for empty conditions and else_actions. "
    "For two different times/actions create two separate rules, not one rule with two actions. "
    "For the same time, same target, and multiple light attributes, combine brightness, color, "
    "and color temperature into one rule and one action. "
    "For 'каждый день' leave days_of_week null; for weekends use ['sat','sun']. "
    "Warm/cool/daylight white should use color_temp_kelvin; warmer/cooler relative changes "
    "should use color_temp_delta_k only when a relative change is requested. "
    "Named colors should use params.color with RGB. "
    "If essential data is missing, set clarification.needed=true and rules=[]."
)


def _extract_first_json_object(text: str) -> Optional[str]:
    if not text:
        return None
    stripped = text.strip()
    fenced = _JSON_FENCE_RE.search(stripped)
    if fenced:
        stripped = fenced.group(1).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    depth = 0
    start: Optional[int] = None
    for idx, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = idx
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    return text[start : idx + 1]
    return None


def _try_load_json_object(raw_text: str) -> Optional[Dict[str, Any]]:
    if not raw_text:
        return None

    candidates: List[str] = []
    stripped = raw_text.strip()
    if stripped:
        candidates.append(stripped)

    extracted = _extract_first_json_object(raw_text)
    if extracted and extracted not in candidates:
        candidates.append(extracted)

    first_brace = raw_text.find("{")
    last_brace = raw_text.rfind("}")
    if first_brace >= 0 and last_brace > first_brace:
        span = raw_text[first_brace : last_brace + 1].strip()
        if span and span not in candidates:
            candidates.append(span)

    for candidate in candidates:
        for variant in (
            candidate,
            candidate.replace("\ufeff", ""),
            _TRAILING_COMMA_RE.sub(r"\1", candidate),
            _TRAILING_COMMA_RE.sub(r"\1", candidate.replace("\ufeff", "")),
        ):
            try:
                parsed = json.loads(variant)
            except Exception:
                continue
            if isinstance(parsed, dict):
                return parsed
    return None


def _normalize_hint_text(text: str) -> str:
    out = str(text or "").lower().replace("ё", "е")
    out = _HINT_CLEAN_RE.sub(" ", out)
    out = _SPACE_RE.sub(" ", out).strip()
    return out


def _tokenize_hint(text: str) -> List[str]:
    return [token.lower().replace("ё", "е") for token in _WORD_RE.findall(str(text or ""))]


def _match_phrase_score(text_norm: str, phrase: str) -> int:
    pattern = _normalize_hint_text(phrase)
    if not pattern:
        return 0
    if pattern in text_norm:
        return 100 + len(pattern)

    pattern_tokens = _tokenize_hint(pattern)
    if not pattern_tokens:
        return 0
    text_tokens = set(_tokenize_hint(text_norm))
    overlap = sum(1 for token in pattern_tokens if token in text_tokens)
    if overlap == len(pattern_tokens):
        return 60 + overlap * 5
    if len(pattern_tokens) == 1 and overlap == 1:
        return 25
    if overlap >= 2:
        return 20 + overlap * 3
    return 0


def _select_matching_aliases(text_norm: str, aliases: List[str]) -> tuple[int, List[str]]:
    scored: List[tuple[int, str]] = []
    for alias in aliases:
        alias_text = str(alias or "").strip()
        if not alias_text:
            continue
        score = _match_phrase_score(text_norm, alias_text)
        if score > 0:
            scored.append((score, alias_text))
    if not scored:
        return 0, []
    scored.sort(key=lambda item: (-item[0], -len(item[1]), item[1]))
    return scored[0][0], [alias for _, alias in scored[:3]]


def _select_pattern_items(
    text_norm: str,
    entries: List[Dict[str, Any]],
    *,
    value_fields: Dict[str, str],
) -> List[Dict[str, Any]]:
    selected: List[tuple[int, Dict[str, Any]]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        score, matched_aliases = _select_matching_aliases(
            text_norm,
            [str(pattern) for pattern in (entry.get("patterns") or []) if str(pattern).strip()],
        )
        if score <= 0:
            continue
        item: Dict[str, Any] = {"trigger": matched_aliases}
        for src_key, dst_key in value_fields.items():
            value = entry.get(src_key)
            if value is not None:
                item[dst_key] = value
        selected.append((score, item))

    selected.sort(key=lambda item: (-item[0], json.dumps(item[1], ensure_ascii=False, sort_keys=True)))
    return [item for _, item in selected[:4]]


def _infer_implicit_white_profile(text_norm: str) -> Optional[Dict[str, Any]]:
    heuristics = [
        (("тепл", "свет"), {"name": "тёплый белый", "color_temp_kelvin": 2700, "matched_aliases": ["тёплый свет"]}),
        (("холод", "свет"), {"name": "холодный белый", "color_temp_kelvin": 6000, "matched_aliases": ["холодный свет"]}),
        (("нейтральн", "свет"), {"name": "нейтральный белый", "color_temp_kelvin": 4000, "matched_aliases": ["нейтральный свет"]}),
        (("дневн", "свет"), {"name": "дневной белый", "color_temp_kelvin": 5000, "matched_aliases": ["дневной свет"]}),
        (("лампов",), {"name": "тёплый белый", "color_temp_kelvin": 2700, "matched_aliases": ["ламповый"]}),
    ]
    for fragments, payload in heuristics:
        if all(fragment in text_norm for fragment in fragments):
            return payload
    return None


def _build_color_knowledge(text: str, colors: Dict[str, Any]) -> Dict[str, Any]:
    text_norm = _normalize_hint_text(text)
    rgb_entries: List[tuple[int, Dict[str, Any]]] = []
    for entry in colors.get("palette_rgb") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        rgb = entry.get("rgb")
        if not name or not isinstance(rgb, list) or len(rgb) != 3:
            continue
        score, matched_aliases = _select_matching_aliases(
            text_norm,
            [name] + [str(alias) for alias in (entry.get("aliases") or []) if str(alias).strip()],
        )
        if score <= 0:
            continue
        rgb_entries.append(
            (
                score,
                {
                    "name": name,
                    "rgb": [int(component) for component in rgb],
                    "matched_aliases": matched_aliases or [name],
                },
            )
        )

    white_profiles: List[tuple[int, Dict[str, Any]]] = []
    for entry in colors.get("whites_color_temp") or []:
        if not isinstance(entry, dict):
            continue
        name = str(entry.get("name") or "").strip()
        kelvin = entry.get("color_temp_kelvin")
        if not name or not isinstance(kelvin, (int, float)):
            continue
        score, matched_aliases = _select_matching_aliases(
            text_norm,
            [name] + [str(alias) for alias in (entry.get("aliases") or []) if str(alias).strip()],
        )
        if score <= 0:
            continue
        white_profiles.append(
            (
                score,
                {
                    "name": name,
                    "color_temp_kelvin": int(kelvin),
                    "matched_aliases": matched_aliases or [name],
                },
            )
        )

    if not white_profiles:
        implicit_profile = _infer_implicit_white_profile(text_norm)
        if implicit_profile is not None:
            white_profiles.append((40, implicit_profile))

    knowledge: Dict[str, Any] = {}
    if rgb_entries:
        rgb_entries.sort(key=lambda item: (-item[0], json.dumps(item[1], ensure_ascii=False, sort_keys=True)))
        knowledge["rgb_colors"] = [item for _, item in rgb_entries[:4]]
    if white_profiles:
        white_profiles.sort(key=lambda item: (-item[0], json.dumps(item[1], ensure_ascii=False, sort_keys=True)))
        knowledge["white_profiles"] = [item for _, item in white_profiles[:4]]
    return knowledge


def _build_brightness_knowledge(text: str, modifiers: Dict[str, Any]) -> Dict[str, Any]:
    text_norm = _normalize_hint_text(text)
    brightness = modifiers.get("brightness") or {}

    brighter = _select_pattern_items(
        text_norm,
        list(brightness.get("relative_up") or []),
        value_fields={"delta_pct": "brightness_delta"},
    )
    dimmer = _select_pattern_items(
        text_norm,
        list(brightness.get("relative_down") or []),
        value_fields={"delta_pct": "brightness_delta"},
    )
    absolute = _select_pattern_items(
        text_norm,
        list(brightness.get("absolute") or []),
        value_fields={"brightness_pct": "brightness"},
    )

    numeric_percent = _NUMERIC_PERCENT_RE.search(text_norm)
    if numeric_percent:
        absolute.insert(0, {"brightness": int(numeric_percent.group(1)), "trigger": [f"{numeric_percent.group(1)}%"]})

    knowledge: Dict[str, Any] = {}
    if brighter:
        knowledge["brighter"] = brighter[:4]
    if dimmer:
        knowledge["dimmer"] = dimmer[:4]
    if absolute:
        knowledge["absolute"] = absolute[:4]
    return knowledge


def _build_color_temperature_knowledge(text: str, modifiers: Dict[str, Any]) -> Dict[str, Any]:
    text_norm = _normalize_hint_text(text)
    color_temp = modifiers.get("color_temperature") or {}

    warmer = _select_pattern_items(
        text_norm,
        list(color_temp.get("relative_warmer") or []),
        value_fields={"delta_k": "color_temp_delta_k"},
    )
    cooler = _select_pattern_items(
        text_norm,
        list(color_temp.get("relative_cooler") or []),
        value_fields={"delta_k": "color_temp_delta_k"},
    )
    absolute = _select_pattern_items(
        text_norm,
        list(color_temp.get("absolute") or []),
        value_fields={"color_temp_kelvin": "color_temp_kelvin"},
    )

    knowledge: Dict[str, Any] = {}
    if warmer:
        knowledge["warmer"] = warmer[:4]
    if cooler:
        knowledge["cooler"] = cooler[:4]
    if absolute:
        knowledge["absolute"] = absolute[:4]
    return knowledge


def _build_lighting_knowledge(
    text: str,
    *,
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
    scene_aliases: Dict[str, Any],
) -> Dict[str, Any]:
    knowledge: Dict[str, Any] = {}
    color_knowledge = _build_color_knowledge(text, colors)
    brightness_knowledge = _build_brightness_knowledge(text, modifiers)
    color_temp_knowledge = _build_color_temperature_knowledge(text, modifiers)
    scene_knowledge = _collect_scene_hints(text, scene_aliases)
    if color_knowledge:
        knowledge["color"] = color_knowledge
    if brightness_knowledge:
        knowledge["brightness"] = brightness_knowledge
    if color_temp_knowledge:
        knowledge["color_temperature"] = color_temp_knowledge
    if scene_knowledge:
        knowledge["scenes"] = scene_knowledge
    return knowledge


def _first_value(items: Any, key: str) -> Any:
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get(key) is not None:
            return item.get(key)
    return None


def _infer_lighting_params(
    text: str,
    *,
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
    scene_aliases: Dict[str, Any],
) -> Dict[str, Any]:
    knowledge = _build_lighting_knowledge(
        text,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )
    color_info = knowledge.get("color") or {}
    brightness_info = knowledge.get("brightness") or {}
    color_temp_info = knowledge.get("color_temperature") or {}
    scene_info = knowledge.get("scenes") or []
    params: Dict[str, Any] = {
        "brightness": _first_value(brightness_info.get("absolute"), "brightness"),
        "brightness_delta": None,
        "color": None,
        "color_temp_kelvin": None,
        "color_temp_delta_k": None,
        "transition_s": None,
    }

    brighter_delta = _first_value(brightness_info.get("brighter"), "brightness_delta")
    dimmer_delta = _first_value(brightness_info.get("dimmer"), "brightness_delta")
    if brighter_delta is not None:
        params["brightness_delta"] = int(brighter_delta)
    elif dimmer_delta is not None:
        params["brightness_delta"] = int(dimmer_delta)

    warmer_delta = _first_value(color_temp_info.get("warmer"), "color_temp_delta_k")
    cooler_delta = _first_value(color_temp_info.get("cooler"), "color_temp_delta_k")
    if warmer_delta is not None:
        params["color_temp_delta_k"] = int(warmer_delta)
    elif cooler_delta is not None:
        params["color_temp_delta_k"] = int(cooler_delta)

    first_rgb = (color_info.get("rgb_colors") or [None])[0]
    if isinstance(first_rgb, dict) and first_rgb.get("rgb") is not None:
        params["color"] = {
            "name": first_rgb.get("name"),
            "rgb": list(first_rgb.get("rgb") or []),
        }

    first_white = (color_info.get("white_profiles") or [None])[0]
    if isinstance(first_white, dict) and first_white.get("color_temp_kelvin") is not None:
        params["color_temp_kelvin"] = int(first_white.get("color_temp_kelvin"))

    if params["color_temp_kelvin"] is None:
        absolute_temp = _first_value(color_temp_info.get("absolute"), "color_temp_kelvin")
        if absolute_temp is not None:
            params["color_temp_kelvin"] = int(absolute_temp)

    if params["brightness"] is None and isinstance(scene_info, list) and scene_info:
        scene_defaults = scene_info[0]
        if isinstance(scene_defaults, dict) and scene_defaults.get("brightness") is not None:
            params["brightness"] = int(scene_defaults.get("brightness"))
    if params["color"] is None and isinstance(scene_info, list) and scene_info:
        scene_defaults = scene_info[0]
        if isinstance(scene_defaults, dict) and scene_defaults.get("color_rgb") is not None:
            params["color"] = {
                "name": scene_defaults.get("color_name"),
                "rgb": list(scene_defaults.get("color_rgb") or []),
            }
    if params["color"] is None and params["color_temp_kelvin"] is None and isinstance(scene_info, list) and scene_info:
        scene_defaults = scene_info[0]
        if isinstance(scene_defaults, dict) and scene_defaults.get("color_temp_kelvin") is not None:
            params["color_temp_kelvin"] = int(scene_defaults.get("color_temp_kelvin"))

    if params["color"] is not None and params["color_temp_kelvin"] is not None:
        params["color_temp_kelvin"] = None
    return params


def _build_known_targets(device_registry: Dict[str, Any]) -> List[Dict[str, Any]]:
    devices_by_id = {
        str(device.get("device_id")): device
        for device in (device_registry.get("devices") or [])
        if isinstance(device, dict) and device.get("device_id")
    }
    items: List[Dict[str, Any]] = []
    for area in device_registry.get("areas") or []:
        if not isinstance(area, dict) or not area.get("name"):
            continue
        area_name = str(area["name"])
        lights: List[Dict[str, Any]] = []
        switches: List[Dict[str, Any]] = []
        for device_id in area.get("devices") or []:
            device = devices_by_id.get(str(device_id))
            if not isinstance(device, dict):
                continue
            item = {
                "device_id": str(device.get("device_id")),
                "name": str(device.get("name") or ""),
                "entity_id": str(((device.get("home_assistant") or {}).get("entity_id")) or ""),
                "device_type": str(device.get("device_type") or ""),
            }
            if item["device_type"] == "light":
                lights.append(item)
            elif item["device_type"] == "switch":
                switches.append(item)
        items.append(
            {
                "area_name": area_name,
                "lights": lights,
                "switches": switches,
            }
        )
    return items


def _normalize_area_text(text: str) -> str:
    cleaned = str(text or "").lower().replace("ё", "е")
    cleaned = re.sub(r"[^0-9a-zA-Zа-яА-Я\s_-]+", " ", cleaned, flags=re.UNICODE)
    return _SPACE_RE.sub(" ", cleaned).strip()


def _area_match_forms(area: Dict[str, Any]) -> List[str]:
    raw_forms = [str(area.get("name") or "")]
    raw_forms.extend(str(alias) for alias in (area.get("synonyms") or []) if str(alias).strip())

    forms: set[str] = set()
    for raw in raw_forms:
        norm = _normalize_area_text(raw)
        if not norm:
            continue
        forms.add(norm)
        if norm.endswith("ая") and len(norm) > 3:
            stem = norm[:-2]
            forms.add(stem + "ой")
            forms.add(stem + "ую")
        if norm.endswith("я") and len(norm) > 2:
            stem = norm[:-1]
            forms.add(stem + "е")
            forms.add(stem + "ю")
        if norm.endswith("а") and len(norm) > 2:
            stem = norm[:-1]
            forms.add(stem + "е")
            forms.add(stem + "у")
        if norm.endswith("ор"):
            forms.add(norm + "е")
    return sorted(forms, key=lambda item: (-len(item), item))


def _canonicalize_area_name(value: str, device_registry: Dict[str, Any]) -> Optional[str]:
    value_norm = _normalize_area_text(value)
    if not value_norm:
        return None
    for area in device_registry.get("areas") or []:
        if not isinstance(area, dict) or not area.get("name"):
            continue
        area_name = str(area.get("name") or "").strip()
        for form in _area_match_forms(area):
            if value_norm == form:
                return area_name
            if f" {form} " in f" {value_norm} ":
                return area_name
    return None


def _extract_explicit_areas(text: str, device_registry: Dict[str, Any]) -> List[str]:
    text_norm = _normalize_area_text(text)
    matches: List[str] = []
    for area in device_registry.get("areas") or []:
        if not isinstance(area, dict) or not area.get("name"):
            continue
        area_name = str(area["name"]).strip()
        if not area_name:
            continue
        if any(f" {form} " in f" {text_norm} " for form in _area_match_forms(area)):
            matches.append(area_name)
    return matches


def _extract_time_tokens(text: str) -> List[str]:
    return [f"{int(h):02d}:{m}" for h, m in _TIME_TOKEN_RE.findall(str(text or ""))]


def _resolve_single_area_hint(text: str, context: Dict[str, Any], device_registry: Dict[str, Any]) -> Optional[str]:
    explicit = _extract_explicit_areas(text, device_registry)
    if len(explicit) == 1:
        return explicit[0]
    selected = str(context.get("selected_area_name") or "").strip()
    if selected:
        return selected
    last_area = str(context.get("last_area_name") or "").strip()
    return last_area or None


def _normalize_scenario_bundle(
    parsed: Dict[str, Any],
    *,
    text: str,
    context: Dict[str, Any],
    device_registry: Dict[str, Any],
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
    scene_aliases: Dict[str, Any],
) -> Dict[str, Any]:
    bundle = copy.deepcopy(parsed)
    known_areas = {
        str(area.get("name") or "").strip()
        for area in (device_registry.get("areas") or [])
        if isinstance(area, dict) and str(area.get("name") or "").strip()
    }
    resolved_area = _resolve_single_area_hint(text, context, device_registry)
    inferred_params = _infer_lighting_params(
        text,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )

    def _normalize_target(target: Dict[str, Any]) -> Dict[str, Any]:
        scope = str(target.get("scope") or "").strip().upper()
        area_name = str(target.get("area_name") or "").strip()
        if scope == "AREA":
            canonical_area = _canonicalize_area_name(area_name, device_registry)
            if canonical_area:
                target["area_name"] = canonical_area
            elif not area_name or area_name not in known_areas or "?" in area_name:
                if resolved_area:
                    target["area_name"] = resolved_area
            target["entity_ids"] = []
        return target

    def _clean_params_for_intent(action: Dict[str, Any], params: Dict[str, Any]) -> None:
        intent = str(action.get("intent") or "").strip().upper()
        text_norm = _normalize_hint_text(text)
        if intent not in {"TURN_OFF", "SET_BRIGHTNESS"} and params.get("brightness") == 0:
            if "0%" not in text_norm and "0 %" not in text_norm:
                params["brightness"] = None
        if params.get("brightness_delta") == 0:
            params["brightness_delta"] = None
        if params.get("color_temp_delta_k") == 0:
            params["color_temp_delta_k"] = None

    def _merge_actions_for_rule(actions_in: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        actions = [copy.deepcopy(item) for item in actions_in if isinstance(item, dict)]
        if not actions:
            return []

        light_actions = [action for action in actions if str(action.get("domain") or "").strip() == "light"]
        if light_actions:
            actions = light_actions

        merged: List[Dict[str, Any]] = []
        by_target: Dict[str, int] = {}
        for action in actions:
            target = action.get("target")
            if isinstance(target, dict):
                _normalize_target(target)
            params = action.get("params")
            if isinstance(params, dict):
                _clean_params_for_intent(action, params)

            key = json.dumps(target or {}, ensure_ascii=False, sort_keys=True)
            existing_idx = by_target.get(key)
            if existing_idx is None:
                by_target[key] = len(merged)
                merged.append(action)
                continue

            existing = merged[existing_idx]
            existing_params = existing.get("params") or {}
            params = action.get("params") or {}
            for param_key, value in params.items():
                if value is not None and existing_params.get(param_key) is None:
                    existing_params[param_key] = copy.deepcopy(value)

            existing_intent = str(existing.get("intent") or "").strip().upper()
            new_intent = str(action.get("intent") or "").strip().upper()
            if "TURN_OFF" in {existing_intent, new_intent} and "TURN_ON" not in {existing_intent, new_intent}:
                existing["intent"] = "TURN_OFF"
            elif "TURN_ON" in {existing_intent, new_intent}:
                existing["intent"] = "TURN_ON"
            elif existing_intent.startswith("SET_") or new_intent.startswith("SET_"):
                existing["intent"] = "TURN_ON"

        if len(merged) > 3:
            merged = merged[:3]
        return merged

    def _merge_duplicate_rule_attributes(rules_in: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        merged: List[Dict[str, Any]] = []
        index_by_key: Dict[str, int] = {}
        for rule in rules_in:
            actions = list(rule.get("actions") or [])
            if len(actions) != 1 or rule.get("else_actions"):
                merged.append(rule)
                continue
            action = actions[0]
            target = action.get("target")
            if not isinstance(target, dict) or str(action.get("domain") or "") != "light":
                merged.append(rule)
                continue
            key = json.dumps(
                {
                    "trigger": rule.get("trigger") or {},
                    "conditions": rule.get("conditions") or [],
                    "target": target,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
            existing_idx = index_by_key.get(key)
            if existing_idx is None:
                index_by_key[key] = len(merged)
                merged.append(rule)
                continue

            existing_rule = merged[existing_idx]
            existing_action = list(existing_rule.get("actions") or [])[0]
            existing_params = existing_action.get("params") or {}
            params = action.get("params") or {}
            for param_key, value in params.items():
                if value is not None and existing_params.get(param_key) is None:
                    existing_params[param_key] = copy.deepcopy(value)
            existing_intent = str(existing_action.get("intent") or "").strip().upper()
            new_intent = str(action.get("intent") or "").strip().upper()
            if "TURN_ON" in {existing_intent, new_intent}:
                existing_action["intent"] = "TURN_ON"
            elif existing_intent.startswith("SET_") and new_intent.startswith("SET_"):
                existing_action["intent"] = "TURN_ON"
        return merged

    text_norm = _normalize_hint_text(text)
    has_conditional = ("\u0435\u0441\u043b\u0438" in text_norm) or ("\u0438\u043d\u0430\u0447\u0435" in text_norm) or (" if " in f" {text_norm} ")
    time_tokens = _extract_time_tokens(text)
    rules = list(bundle.get("rules") or [])
    should_split_multi_time = len(rules) == 1 and len(time_tokens) >= 2 and not has_conditional
    for rule_index, rule in enumerate(rules):
        raw_actions = list(rule.get("actions") or [])
        if should_split_multi_time and rule_index == 0 and len(raw_actions) >= 2:
            rule["actions"] = [copy.deepcopy(item) for item in raw_actions if isinstance(item, dict)]
        else:
            rule["actions"] = _merge_actions_for_rule(raw_actions)
        for action in list(rule.get("actions") or []):
            target = action.get("target")
            if isinstance(target, dict):
                _normalize_target(target)
            if str(action.get("domain") or "") == "light":
                params = action.get("params")
                if isinstance(params, dict):
                    _clean_params_for_intent(action, params)
                    if params.get("brightness") is None and inferred_params.get("brightness") is not None:
                        params["brightness"] = inferred_params["brightness"]
                    if params.get("brightness_delta") is None and inferred_params.get("brightness_delta") is not None:
                        params["brightness_delta"] = inferred_params["brightness_delta"]
                    if params.get("color") is None and inferred_params.get("color") is not None:
                        params["color"] = copy.deepcopy(inferred_params["color"])
                    if (
                        params.get("color") is None
                        and params.get("color_temp_kelvin") is None
                        and inferred_params.get("color_temp_kelvin") is not None
                    ):
                        params["color_temp_kelvin"] = inferred_params["color_temp_kelvin"]
                    if params.get("color_temp_delta_k") is None and inferred_params.get("color_temp_delta_k") is not None:
                        params["color_temp_delta_k"] = inferred_params["color_temp_delta_k"]
                    if params.get("color") is not None and params.get("color_temp_kelvin") is not None:
                        params["color_temp_kelvin"] = None
        rule["else_actions"] = _merge_actions_for_rule(list(rule.get("else_actions") or []))
        if not has_conditional:
            rule["else_actions"] = []

    if should_split_multi_time:
        first_rule = rules[0]
        actions = [copy.deepcopy(action) for action in list(first_rule.get("actions") or [])]
        if len(actions) >= 2:
            rebuilt_rules: List[Dict[str, Any]] = []
            for idx, action in enumerate(actions[: len(time_tokens)]):
                trigger_time = time_tokens[min(idx, len(time_tokens) - 1)]
                intent = str(action.get("intent") or "TURN_ON")
                rebuilt_rules.append(
                    {
                        "rule_id": f"rule_{idx + 1}_{trigger_time.replace(':', '_')}",
                        "title": f"{trigger_time} {intent}",
                        "enabled": bool(first_rule.get("enabled", True)),
                        "trigger": {"type": "time", "at": trigger_time},
                        "conditions": [],
                        "actions": [action],
                        "else_actions": [],
                    }
            )
            bundle["rules"] = rebuilt_rules

    bundle["rules"] = _merge_duplicate_rule_attributes(list(bundle.get("rules") or []))

    clarification = bundle.get("clarification")
    if isinstance(clarification, dict) and not clarification.get("needed"):
        clarification["question"] = None
        clarification["missing_fields"] = []

    return bundle


def _build_scene_knowledge(scene_aliases: Dict[str, Any]) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    for scene in scene_aliases.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        scene_id = str(scene.get("id") or "").strip()
        if not scene_id:
            continue
        defaults = dict(scene.get("defaults") or {})
        item: Dict[str, Any] = {
            "id": scene_id,
            "summary": str(scene.get("summary") or "").strip() or None,
            "aliases": [str(alias) for alias in (scene.get("patterns") or []) if str(alias).strip()],
        }
        for key in ("brightness", "color_temp_kelvin", "color_name", "color_rgb"):
            value = defaults.get(key)
            if value is not None:
                item[key] = value
        items.append(item)
    return items[:8]


def _collect_scene_hints(text: str, scene_aliases: Dict[str, Any]) -> List[Dict[str, Any]]:
    lowered = str(text or "").lower()
    if not lowered.strip():
        return []

    selected: List[Dict[str, Any]] = []
    for item in _build_scene_knowledge(scene_aliases):
        aliases = [str(alias).lower() for alias in (item.get("aliases") or [])]
        scene_id = str(item.get("id") or "").lower().replace("_", " ")
        if any(alias and alias in lowered for alias in aliases) or (scene_id and scene_id in lowered):
            selected.append(item)
    return selected[:4]


def _build_scenario_prompt_payload(
    text: str,
    *,
    context: Dict[str, Any],
    device_registry: Dict[str, Any],
    scene_aliases: Dict[str, Any],
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
) -> Dict[str, Any]:
    explicit_areas = _extract_explicit_areas(text, device_registry)
    context_areas = [
        str(context.get("selected_area_name") or "").strip(),
        str(context.get("last_area_name") or "").strip(),
    ]
    focus_areas = [area for area in explicit_areas if area]
    if not focus_areas:
        focus_areas = [area for area in context_areas if area]

    all_area_names = [
        str(area.get("name"))
        for area in (device_registry.get("areas") or [])
        if isinstance(area, dict) and area.get("name")
    ]
    area_names = [area for area in all_area_names if area in focus_areas] if focus_areas else all_area_names
    known_targets = _build_known_targets(device_registry)
    if focus_areas:
        known_targets = [item for item in known_targets if item.get("area_name") in focus_areas]

    return {
        "utterance": text,
        "context": {
            "last_area_name": context.get("last_area_name"),
            "selected_area_name": context.get("selected_area_name"),
            "last_entity_ids": list(context.get("last_entity_ids") or []),
        },
        "known_areas": area_names,
        "known_targets": known_targets,
        "target_hint": {
            "explicit_area_mentions": explicit_areas,
            "focused_areas": focus_areas,
        },
        "output_defaults": {
            "schema_version": "1.0",
            "description": None,
            "clarification": {"needed": False, "question": None, "missing_fields": []},
            "target_for_area": {"scope": "AREA", "entity_ids": []},
            "empty_blocks": {"conditions": [], "else_actions": []},
            "unused_action_params": {
                "brightness": None,
                "brightness_delta": None,
                "color": None,
                "color_temp_kelvin": None,
                "color_temp_delta_k": None,
                "transition_s": None,
            },
        },
        "scenario_contract": {
            "bundle_shape": "one bundle can contain multiple rules; use multiple rules for different times/actions",
            "supported_triggers": {
                "time": "specific time like 20:00",
                "state": "entity changes to state like binary_sensor.motion -> on",
                "numeric_state": "entity goes above/below threshold like illuminance below 30",
            },
            "supported_conditions": {
                "time_window": "time range like after 19:00",
                "state": "entity == value or != value",
                "numeric": "entity compared with < <= > >= =",
            },
            "supported_actions": {
                "TURN_ON": "turn on light or switch",
                "TURN_OFF": "turn off light or switch",
                "SET_BRIGHTNESS": "set absolute brightness 0..100",
                "ADJUST_BRIGHTNESS": "relative brighter/dimmer",
                "SET_COLOR": "set absolute RGB color",
                "SET_COLOR_TEMP": "set white temperature in kelvin",
                "ADJUST_COLOR_TEMP": "relative warmer/cooler white temperature",
            },
            "target_policy": "Prefer AREA target when a room is named. If room is omitted, prefer context.selected_area_name or context.last_area_name over ALL_LIGHTS. For AREA target keep entity_ids empty and never invent device/entity ids.",
        },
        "lighting_knowledge": _build_lighting_knowledge(
            text,
            colors=colors,
            modifiers=modifiers,
            scene_aliases=scene_aliases,
        ),
        "scene_knowledge": _collect_scene_hints(text, scene_aliases),
        "decision_policy": [
            "Return only one JSON object matching ScenarioBundle v1.",
            "If the request describes two independent schedules, create two rules.",
            "If the user says if-then, put the event into trigger when possible and extra checks into conditions.",
            "Use else_actions only when the user explicitly asks alternative behavior.",
            "Use safe, concrete automation actions rather than vague descriptions.",
            "Warm/cool/neutral/daylight white requests should set color_temp_kelvin or color_temp_delta_k, not RGB.",
            "Named colors should set params.color with RGB.",
            "Brightness phrases should set brightness or brightness_delta when the utterance implies them.",
            "Do not invent new rooms, device_ids, or entity_ids.",
            "If target_hint.explicit_area_mentions is not empty, use only those rooms.",
            "If target_hint.focused_areas has one room, do not expand actions to other rooms.",
            "For schedule-style requests, keep one action per room unless the user explicitly names multiple rooms.",
            "Keep titles and rule_id short.",
            "If essential data is missing, set clarification.needed=true and keep rules empty.",
        ],
    }


@dataclass(frozen=True)
class ScenarioAuthoringLLMParser:
    client: LLMClient

    def parse(
        self,
        text: str,
        *,
        context: Dict[str, Any],
        root_dir: Optional[Union[str, Path]] = None,
        device_registry: Optional[Dict[str, Any]] = None,
        scene_aliases: Optional[Dict[str, Any]] = None,
        colors: Optional[Dict[str, Any]] = None,
        modifiers: Optional[Dict[str, Any]] = None,
        scenario_schema: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        paths = AssetPaths(Path(root_dir) if root_dir is not None else Path(__file__).resolve().parents[1])
        device_registry = device_registry or load_json(paths.device_registry)
        scene_aliases = scene_aliases or load_json(paths.scene_aliases)
        colors = colors or load_json(paths.colors)
        modifiers = modifiers or load_json(paths.modifiers)
        scenario_schema = scenario_schema or load_schema(paths.scenario_bundle_schema)

        system = _SCENARIO_SYSTEM_PROMPT
        user_payload = _build_scenario_prompt_payload(
            text,
            context=context,
            device_registry=device_registry,
            scene_aliases=scene_aliases,
            colors=colors,
            modifiers=modifiers,
        )
        user = json.dumps(user_payload, ensure_ascii=False, separators=(",", ":"))
        raw = self.client.generate_json(
            system=system,
            user=user,
            temperature=0.0,
            max_tokens=SCENARIO_LLM_MAX_OUTPUT_TOKENS,
            json_schema=scenario_schema,
        )
        parsed = _try_load_json_object(raw)
        if parsed is None:
            raise ValueError("LLM did not return a JSON object for ScenarioBundle")
        normalized = _normalize_scenario_bundle(
            parsed,
            text=text,
            context=context,
            device_registry=device_registry,
            colors=colors,
            modifiers=modifiers,
            scene_aliases=scene_aliases,
        )
        validate_with_schema(normalized, scenario_schema)
        return normalized


def run_scenario_authoring_pipeline_v1(
    text: str,
    *,
    llm_client: LLMClient,
    context: Optional[Dict[str, Any]] = None,
    root_dir: Optional[Union[str, Path]] = None,
    device_registry: Optional[Dict[str, Any]] = None,
    area_synonyms: Optional[Dict[str, Any]] = None,
    scene_aliases: Optional[Dict[str, Any]] = None,
    scenario_schema: Optional[Dict[str, Any]] = None,
) -> ScenarioPipelineResult:
    """LLM -> validated ScenarioBundle -> compiled HA automations."""
    ctx = context or {"selected_area_name": None, "last_area_name": None, "last_entity_ids": []}
    paths = AssetPaths(Path(root_dir) if root_dir is not None else Path(__file__).resolve().parents[1])
    device_registry = device_registry or load_json(paths.device_registry)
    area_synonyms = area_synonyms or load_json(paths.area_synonyms)
    scene_aliases = scene_aliases or load_json(paths.scene_aliases)
    scenario_schema = scenario_schema or load_schema(paths.scenario_bundle_schema)

    parser = ScenarioAuthoringLLMParser(client=llm_client)
    parsed = parser.parse(
        text,
        context=ctx,
        root_dir=paths.root,
        device_registry=device_registry,
        scene_aliases=scene_aliases,
        scenario_schema=scenario_schema,
    )
    validated = validate_scenario_bundle(
        parsed,
        context=ctx,
        root_dir=paths.root,
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        scenario_schema=scenario_schema,
    )
    if str(validated.get("status") or "") == "CLARIFICATION":
        return ScenarioPipelineResult(
            stage="CLARIFICATION",
            parsed=parsed,
            validated=validated,
            automations=None,
        )

    automations = compile_scenario_bundle_to_ha_automations(
        validated,
        root_dir=paths.root,
        device_registry=device_registry,
    )
    return ScenarioPipelineResult(
        stage="VALIDATED",
        parsed=parsed,
        validated=validated,
        automations=automations,
    )
