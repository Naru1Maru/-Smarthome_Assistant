"""LLM-based parser (v1) for light commands.

Key principles:
- The LLM outputs a ParsedCommand JSON object (schema_version=1.0).
- We validate the output against the ParsedCommand schema.
- If output is invalid or unsafe, we either:
  - fallback to the robust rule parser (recommended for production), or
  - return a clarification error (LLM-only mode, for evaluation).

The prompt is intentionally domain-specific rather than example-heavy:
- a compact command contract tells the model which intents/params exist;
- a small retrieved knowledge slice gives only the relevant color/brightness
  hints for the current utterance.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Optional

from .llm_client import LLMClient
from .parser import parse_light_command_v1
from .schema_utils import validate_with_schema

GENERIC_CLARIFICATION_HINTS = (
    "\u043d\u0435 \u0441\u043c\u043e\u0433 \u043f\u043e\u043d\u044f\u0442\u044c",
    "\u0441\u043a\u0430\u0436\u0438 \u0438\u043d\u0430\u0447\u0435",
    "\u043f\u043e\u0432\u0442\u043e\u0440\u0438 \u043a\u043e\u043c\u0430\u043d\u0434\u0443",
    "\u0443\u0442\u043e\u0447\u043d\u0438\u0442\u0435 \u043a\u043e\u043c\u0430\u043d\u0434\u0443",
)

MAX_HINT_ITEMS = 15
MAX_RELEVANT_KNOWLEDGE_ITEMS = 4
MAX_MATCHED_PATTERNS = 3
MAX_COLOR_ALIAS_HINTS = 3
LLM_MAX_OUTPUT_TOKENS = 180
_ABSOLUTE_GOAL_TYPES = {"TURN_ON", "SET_BRIGHTNESS", "SET_COLOR", "SET_COLOR_TEMP"}
_GOAL_TYPE_ENUM = [
    "TURN_ON",
    "TURN_OFF",
    "SET_BRIGHTNESS",
    "ADJUST_BRIGHTNESS",
    "SET_COLOR",
    "SET_COLOR_TEMP",
    "ADJUST_COLOR_TEMP",
    "MOOD_SCENE",
    "CANCEL",
    "UNKNOWN",
]
PRIORITY_COLORS = ["белый", "теплый белый", "холодный белый", "желтый", "оранжевый"]

_MATCH_CLEAN_RE = re.compile(r"[^0-9a-zA-Zа-яА-ЯёЁ\s%/-]+", flags=re.UNICODE)
_SPACE_RE = re.compile(r"\s+", flags=re.UNICODE)
_WORD_RE = re.compile(r"[0-9a-zA-Zа-яА-ЯёЁ]+", flags=re.UNICODE)
_TURN_OFF_HINT_RE = re.compile(r"\b(?:выключи|выключай|выруби|вырубай|погаси|гаси|отключи|потуши)\b", flags=re.IGNORECASE)
_TURN_ON_HINT_RE = re.compile(r"\b(?:включи|включай|вруби|врубай|зажги|зажигай)\b", flags=re.IGNORECASE)


def _build_target_schema() -> Dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["scope", "area_name", "entity_ids"],
        "properties": {
            "scope": {"type": "string", "enum": ["UNSPECIFIED", "AREA", "ENTITY", "ALL_LIGHTS"]},
            "area_name": {"type": ["string", "null"]},
            "entity_ids": {
                "type": "array",
                "maxItems": 50,
                "items": {"type": "string", "minLength": 1},
            },
        },
    }


def _build_lighting_goal_schema(scene_aliases: Dict[str, Any]) -> Dict[str, Any]:
    params_schema: Dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "brightness",
            "brightness_delta",
            "color_name",
            "color_rgb",
            "color_temp_kelvin",
            "color_temp_delta_k",
            "transition_s",
        ],
        "properties": {
            "brightness": {"type": ["integer", "null"], "minimum": 0, "maximum": 100},
            "brightness_delta": {"type": ["integer", "null"], "minimum": -100, "maximum": 100},
            "color_name": {"type": ["string", "null"]},
            "color_rgb": {
                "type": ["array", "null"],
                "minItems": 3,
                "maxItems": 3,
                "items": {"type": "integer", "minimum": 0, "maximum": 255},
            },
            "color_temp_kelvin": {"type": ["integer", "null"], "minimum": 1500, "maximum": 6500},
            "color_temp_delta_k": {"type": ["integer", "null"], "minimum": -3000, "maximum": 3000},
            "transition_s": {"type": ["number", "null"], "minimum": 0, "maximum": 10},
        },
    }
    clarification_schema: Dict[str, Any] = {
        "type": "object",
        "additionalProperties": False,
        "required": ["needed", "question", "options"],
        "properties": {
            "needed": {"type": "boolean"},
            "question": {"type": "string", "minLength": 1},
            "options": {
                "type": "array",
                "maxItems": 20,
                "items": {"type": "string", "minLength": 1},
            },
        },
    }
    scene_ids = [
        str(scene.get("id"))
        for scene in (scene_aliases.get("scenes") or [])
        if isinstance(scene, dict) and scene.get("id")
    ]
    if scene_ids:
        scene_id_schema: Dict[str, Any] = {"enum": scene_ids + [None]}
    else:
        scene_id_schema = {"type": ["string", "null"]}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["schema_version", "goal_type", "target", "params", "scene_id"],
        "properties": {
            "schema_version": {"type": "string", "const": "1.0"},
            "goal_type": {"type": "string", "enum": _GOAL_TYPE_ENUM},
            "target": _build_target_schema(),
            "params": params_schema,
            "scene_id": scene_id_schema,
            "clarification": clarification_schema,
        },
    }


def _extract_first_json_object(text: str) -> Optional[str]:
    """Extract the first top-level JSON object from a string.

    Handles common cases where the model adds commentary.
    Conservative: returns None if no balanced object found.
    """
    if not text:
        return None

    stripped = text.strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped

    start = stripped.find("{")
    if start == -1:
        return None

    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(stripped)):
        ch = stripped[i]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue

        if ch == '"':
            in_str = True
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : i + 1]
    return None


def _unknown_action() -> Dict[str, Any]:
    return {
        "domain": "light",
        "intent": "UNKNOWN",
        "target": {"scope": "UNSPECIFIED", "area_name": None, "entity_ids": []},
        "params": {
            "brightness": None,
            "brightness_delta": None,
            "color": None,
            "color_temp_kelvin": None,
            "color_temp_delta_k": None,
            "transition_s": None,
        },
    }


def _parsed_clarification(
    *, question: str, options: Optional[list[str]] = None
) -> Dict[str, Any]:
    opts = options or ["Повтори команду другими словами."]
    return {
        "schema_version": "1.0",
        "actions": [_unknown_action()],
        "clarification": {
            "needed": True,
            "question": question,
            "options": opts[:20],
        },
    }


def _clarification_from_freeform(text: str, *, options: Optional[list[str]] = None) -> Optional[Dict[str, Any]]:
    """Try to reuse a natural-language reply from the LLM as clarification."""
    if not text:
        return None

    cleaned = text.strip()
    if not cleaned:
        return None

    cleaned = cleaned.replace("<|im_end|>", " ").replace("</s>", " ").strip()
    cleaned = re.sub(r"^assistant\s*[:\-]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned)

    if not cleaned:
        return None

    if "?" not in cleaned and len(cleaned) > 160:
        return None

    if len(cleaned) > 280:
        cleaned = cleaned[:277].rstrip() + "..."

    return _parsed_clarification(question=cleaned, options=options)


def _is_generic_clarification_payload(parsed: Dict[str, Any] | None) -> bool:
    clarification = (parsed or {}).get("clarification") or {}
    if not clarification.get("needed"):
        return False

    raw_question = str(clarification.get("question") or "").strip()
    if raw_question.startswith("{") or raw_question.startswith("["):
        return True

    question = _normalize_hint_text(raw_question)
    if not question:
        return True

    if "schema_version" in question or "goal_type" in question or question.startswith("{"):
        return True

    return any(_normalize_hint_text(hint) in question for hint in GENERIC_CLARIFICATION_HINTS)


def _has_unknown_area_targets(parsed: Dict[str, Any], area_options: list[str]) -> bool:
    known = {_normalize_hint_text(area) for area in area_options if str(area).strip()}
    if not known:
        return False

    for action in parsed.get("actions") or []:
        if not isinstance(action, dict):
            continue
        target = action.get("target") or {}
        if str(target.get("scope") or "") != "AREA":
            continue
        area_name = str(target.get("area_name") or "").strip()
        if area_name and _normalize_hint_text(area_name) not in known:
            return True
    return False


def _text_mentions_known_area(text: str, area_options: list[str]) -> bool:
    text_norm = _normalize_hint_text(text)
    if not text_norm:
        return False
    return any(_normalize_hint_text(area) in text_norm for area in area_options if str(area).strip())


def _should_rescue_llm_clarification(
    parsed: Dict[str, Any] | None,
    *,
    text: str,
    context: Dict[str, Any],
    area_options: list[str],
) -> bool:
    if _is_generic_clarification_payload(parsed):
        return True

    clarification = (parsed or {}).get("clarification") or {}
    question_raw = str(clarification.get("question") or "").strip()
    question = _normalize_hint_text(question_raw)
    text_norm = _normalize_hint_text(text)

    if not question:
        return True

    if question == text_norm:
        return True

    if len(question) >= 16 and question in text_norm:
        return True

    asks_for_room = any(
        phrase in question
        for phrase in (
            "в какой комнат",
            "какую комнат",
            "какой комнат",
            "где включить",
            "где сделать",
            "где применить",
        )
    )
    if asks_for_room and (
        _text_mentions_known_area(text, area_options)
        or context.get("selected_area_name")
        or context.get("last_area_name")
    ):
        return True

    return False


def _normalize_hint_text(text: str) -> str:
    out = str(text or "").lower().replace("ё", "е")
    out = _MATCH_CLEAN_RE.sub(" ", out)
    out = _SPACE_RE.sub(" ", out).strip()
    return out


def _tokenize_hint(text: str) -> list[str]:
    return [t.lower().replace("ё", "е") for t in _WORD_RE.findall(str(text or ""))]


def _match_phrase_score(text_norm: str, phrase: str) -> int:
    pattern = _normalize_hint_text(phrase)
    if not pattern:
        return 0

    if pattern in text_norm:
        return 100 + len(pattern)

    pat_tokens = _tokenize_hint(pattern)
    if not pat_tokens:
        return 0

    text_tokens = set(_tokenize_hint(text_norm))
    overlap = sum(1 for token in pat_tokens if token in text_tokens)
    if overlap == len(pat_tokens):
        return 60 + overlap * 5
    if len(pat_tokens) == 1 and overlap == 1:
        return 25
    if overlap >= 2:
        return 15 + overlap * 3
    return 0


def _unique_keep_order(items: Iterable[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _order_color_entries(entries: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    priorities = [p.lower().replace("ё", "е") for p in PRIORITY_COLORS]

    def key(entry: Dict[str, Any]) -> tuple[int, str]:
        name = str(entry.get("name") or "")
        norm = name.lower().replace("ё", "е")
        priority_idx = next((idx for idx, p in enumerate(priorities) if p in norm), len(priorities))
        return (priority_idx, norm)

    return sorted(entries, key=key)


def _select_matching_aliases(text_norm: str, aliases: Iterable[str]) -> tuple[int, list[str]]:
    matches: list[tuple[int, str]] = []
    for alias in _unique_keep_order(aliases):
        score = _match_phrase_score(text_norm, alias)
        if score > 0:
            matches.append((score, alias))

    if not matches:
        return 0, []

    matches.sort(key=lambda item: (-item[0], -len(item[1]), item[1]))
    selected = [alias for _, alias in matches[:MAX_COLOR_ALIAS_HINTS]]
    return matches[0][0], selected


def _select_pattern_items(
    text_norm: str,
    entries: Iterable[Dict[str, Any]],
    *,
    value_fields: Dict[str, str],
) -> list[Dict[str, Any]]:
    selected: list[tuple[int, Dict[str, Any]]] = []
    for entry in entries or []:
        patterns = [str(p) for p in entry.get("patterns") or [] if str(p).strip()]
        scored_patterns: list[tuple[int, str]] = []
        for pattern in patterns:
            score = _match_phrase_score(text_norm, pattern)
            if score > 0:
                scored_patterns.append((score, pattern))
        if not scored_patterns:
            continue

        scored_patterns.sort(key=lambda item: (-item[0], -len(item[1]), item[1]))
        item: Dict[str, Any] = {}
        if entry.get("id"):
            item["id"] = entry["id"]
        for src_key, dst_key in value_fields.items():
            value = entry.get(src_key)
            if value is not None:
                item[dst_key] = int(value) if isinstance(value, (int, float)) else value
        item["trigger"] = [pattern for _, pattern in scored_patterns[:MAX_MATCHED_PATTERNS]]
        selected.append((scored_patterns[0][0], item))

    selected.sort(key=lambda item: (-item[0], json.dumps(item[1], ensure_ascii=False, sort_keys=True)))
    return [item for _, item in selected[:MAX_RELEVANT_KNOWLEDGE_ITEMS]]


def _build_goal_contract(scene_aliases: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "target": {
            "scope": ["UNSPECIFIED", "AREA", "ENTITY", "ALL_LIGHTS"],
            "area_name": "string|null",
            "entity_ids": "[] or [entity_id, ...]",
        },
        "goal_types": {
            "TURN_ON": "turn on, can combine brightness/color/color temperature",
            "TURN_OFF": "explicit off",
            "SET_BRIGHTNESS": "absolute brightness only",
            "ADJUST_BRIGHTNESS": "relative brighter/dimmer",
            "SET_COLOR": "absolute RGB color only",
            "SET_COLOR_TEMP": "absolute white temperature",
            "ADJUST_COLOR_TEMP": "relative warmer/cooler shift",
            "MOOD_SCENE": "atmosphere preset from scene_id with optional overrides",
            "CANCEL": "cancel or stop",
            "UNKNOWN": "clarification required",
        },
        "params": {
            "brightness": "0..100 absolute",
            "brightness_delta": "-100..100 relative",
            "color_name": "string|null",
            "color_rgb": "[0..255, 0..255, 0..255] or null",
            "color_temp_kelvin": "1500..6500 absolute",
            "color_temp_delta_k": "-3000..3000 relative",
            "transition_s": "0..10 optional",
        },
    }


def _build_color_knowledge(text: str, colors: Dict[str, Any]) -> Dict[str, Any]:
    text_norm = _normalize_hint_text(text)
    tokens = set(_tokenize_hint(text))
    has_white_word = any(token.startswith("бел") for token in tokens)

    rgb_entries: list[Dict[str, Any]] = []
    for entry in _order_color_entries(list(colors.get("palette_rgb") or [])):
        name = str(entry.get("name") or "").strip()
        rgb = entry.get("rgb")
        if not name or not isinstance(rgb, list) or len(rgb) != 3:
            continue

        aliases = [name] + list(entry.get("aliases") or [])
        score, matched_aliases = _select_matching_aliases(text_norm, aliases)
        if score <= 0:
            if has_white_word and "бел" in name.lower().replace("ё", "е"):
                rgb_entries.append({"name": name, "rgb": [int(v) for v in rgb], "matched_aliases": ["белый"]})
            continue

        rgb_entries.append(
            {
                "name": name,
                "rgb": [int(v) for v in rgb],
                "matched_aliases": matched_aliases or [name],
            }
        )

    white_profiles: list[Dict[str, Any]] = []
    for entry in _order_color_entries(list(colors.get("whites_color_temp") or [])):
        name = str(entry.get("name") or "").strip()
        kelvin = entry.get("color_temp_kelvin")
        if not name or not isinstance(kelvin, (int, float)):
            continue

        aliases = [name] + list(entry.get("aliases") or [])
        score, matched_aliases = _select_matching_aliases(text_norm, aliases)
        if score <= 0:
            continue

        white_profiles.append(
            {
                "name": name,
                "color_temp_kelvin": int(kelvin),
                "matched_aliases": matched_aliases or [name],
            }
        )

    knowledge: Dict[str, Any] = {}
    if rgb_entries:
        knowledge["rgb_colors"] = rgb_entries[:MAX_RELEVANT_KNOWLEDGE_ITEMS]
    if white_profiles:
        knowledge["white_profiles"] = white_profiles[:MAX_RELEVANT_KNOWLEDGE_ITEMS]
    if has_white_word:
        knowledge["white_disambiguation"] = (
            "Просто 'белый' => SET_COLOR с RGB white. "
            "Тёплый/холодный/дневной/нейтральный белый => SET_COLOR_TEMP."
        )
    return knowledge


def _build_brightness_knowledge(text: str, modifiers: Dict[str, Any]) -> Dict[str, Any]:
    text_norm = _normalize_hint_text(text)
    brightness = modifiers.get("brightness") or {}

    brighter = _select_pattern_items(
        text_norm,
        brightness.get("relative_up") or [],
        value_fields={"delta_pct": "brightness_delta"},
    )
    dimmer = _select_pattern_items(
        text_norm,
        brightness.get("relative_down") or [],
        value_fields={"delta_pct": "brightness_delta"},
    )
    absolute = _select_pattern_items(
        text_norm,
        brightness.get("absolute") or [],
        value_fields={"brightness_pct": "brightness"},
    )

    numeric_percent = re.search(r"\b(100|[1-9]?\d)\s*%", text_norm)
    if numeric_percent:
        absolute.insert(
            0,
            {
                "brightness": int(numeric_percent.group(1)),
                "trigger": [f"{numeric_percent.group(1)}%"],
            },
        )

    knowledge: Dict[str, Any] = {}
    if brighter:
        knowledge["brighter"] = brighter[:MAX_RELEVANT_KNOWLEDGE_ITEMS]
    if dimmer:
        knowledge["dimmer"] = dimmer[:MAX_RELEVANT_KNOWLEDGE_ITEMS]
    if absolute:
        knowledge["absolute"] = absolute[:MAX_RELEVANT_KNOWLEDGE_ITEMS]
    return knowledge


def _build_color_temperature_knowledge(text: str, modifiers: Dict[str, Any]) -> Dict[str, Any]:
    text_norm = _normalize_hint_text(text)
    color_temp = modifiers.get("color_temperature") or {}

    warmer = _select_pattern_items(
        text_norm,
        color_temp.get("relative_warmer") or [],
        value_fields={"delta_k": "color_temp_delta_k"},
    )
    cooler = _select_pattern_items(
        text_norm,
        color_temp.get("relative_cooler") or [],
        value_fields={"delta_k": "color_temp_delta_k"},
    )

    ambiguous_terms: list[Dict[str, Any]] = []
    for entry in color_temp.get("ambiguous_semantics") or []:
        matched = _select_pattern_items(
            text_norm,
            [entry],
            value_fields={"meaning": "meaning"},
        )
        if not matched:
            continue
        policy = entry.get("policy") or {}
        ambiguous_terms.append(
            {
                "meaning": entry.get("meaning"),
                "trigger": matched[0].get("trigger") or [],
                "question": policy.get("question"),
                "options": list(policy.get("options") or []),
            }
        )

    knowledge: Dict[str, Any] = {}
    if warmer:
        knowledge["warmer"] = warmer[:MAX_RELEVANT_KNOWLEDGE_ITEMS]
    if cooler:
        knowledge["cooler"] = cooler[:MAX_RELEVANT_KNOWLEDGE_ITEMS]
    if ambiguous_terms:
        knowledge["ambiguous_terms"] = ambiguous_terms[:MAX_RELEVANT_KNOWLEDGE_ITEMS]
    return knowledge


def _build_scene_knowledge(text: str, scene_aliases: Dict[str, Any]) -> Dict[str, Any]:
    text_norm = _normalize_hint_text(text)
    selected: list[tuple[int, Dict[str, Any]]] = []
    for entry in scene_aliases.get("scenes") or []:
        if not isinstance(entry, dict):
            continue
        scene_id = str(entry.get("id") or "").strip()
        if not scene_id:
            continue

        patterns = [str(p) for p in entry.get("patterns") or [] if str(p).strip()]
        scored_patterns: list[tuple[int, str]] = []
        for pattern in patterns:
            score = _match_phrase_score(text_norm, pattern)
            if score > 0:
                scored_patterns.append((score, pattern))
        if not scored_patterns:
            continue

        scored_patterns.sort(key=lambda item: (-item[0], -len(item[1]), item[1]))
        defaults = entry.get("defaults") or {}
        item: Dict[str, Any] = {
            "id": scene_id,
            "summary": entry.get("summary"),
            "trigger": [pattern for _, pattern in scored_patterns[:MAX_MATCHED_PATTERNS]],
        }
        for key in ("brightness", "color_temp_kelvin", "color_name", "color_rgb"):
            value = defaults.get(key)
            if value is not None:
                item[key] = value
        selected.append((scored_patterns[0][0], item))

    selected.sort(key=lambda item: (-item[0], json.dumps(item[1], ensure_ascii=False, sort_keys=True)))
    scene_items = [item for _, item in selected[:MAX_RELEVANT_KNOWLEDGE_ITEMS]]
    if not scene_items:
        return {}
    return {
        "scene_presets": scene_items,
        "primary_scene_id": scene_items[0].get("id"),
    }


def _build_llm_prompt_payload(
    text: str,
    *,
    context: Dict[str, Any],
    area_synonyms: Dict[str, Any],
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
    scene_aliases: Dict[str, Any],
) -> Dict[str, Any]:
    canonical_areas = area_synonyms.get("canonical_areas", []) or []
    areas = [a.get("name") for a in canonical_areas if isinstance(a, dict) and a.get("name")]
    areas = areas[:MAX_HINT_ITEMS]

    knowledge: Dict[str, Any] = {}
    color_knowledge = _build_color_knowledge(text, colors)
    brightness_knowledge = _build_brightness_knowledge(text, modifiers)
    color_temp_knowledge = _build_color_temperature_knowledge(text, modifiers)
    scene_knowledge = _build_scene_knowledge(text, scene_aliases)
    intent_hint = _build_intent_hint(text)
    carryover_examples = _build_carryover_examples(context)
    if color_knowledge:
        knowledge["color"] = color_knowledge
    if brightness_knowledge:
        knowledge["brightness"] = brightness_knowledge
    if color_temp_knowledge:
        knowledge["color_temperature"] = color_temp_knowledge
    if scene_knowledge:
        knowledge["scenes"] = scene_knowledge

    payload = {
        "utterance": text,
        "context": {
            "selected_area_name": context.get("selected_area_name"),
            "last_area_name": context.get("last_area_name"),
            "last_entity_ids": list(context.get("last_entity_ids") or []),
            "last_color_name": context.get("last_color_name"),
            "last_brightness": context.get("last_brightness"),
            "last_color_temp_kelvin": context.get("last_color_temp_kelvin"),
            "pending_clarification_slot": context.get("pending_clarification_slot"),
        },
        "domain": "light",
        "areas": areas,
        "goal_contract": _build_goal_contract(scene_aliases),
        "decision_policy": [
            "Minimize actions.",
            "Explicit on/off verbs -> TURN_ON/TURN_OFF.",
            "Absolute params -> TURN_ON with params.",
            "Scene or mood -> MOOD_SCENE + scene_id from knowledge.scenes.",
            "If knowledge.scenes.primary_scene_id exists, scene_id must not be null.",
            "Relative changes -> brightness_delta or color_temp_delta_k.",
            "If utterance names a room, keep that room in target.area_name.",
            "If room is omitted, prefer context.selected_area_name, then context.last_area_name, never invent another room.",
            "Insufficient data -> UNKNOWN + clarification.",
        ],
        "knowledge": knowledge,
        "output_format": "single JSON object",
    }
    if intent_hint:
        payload["intent_hint"] = intent_hint
    if carryover_examples:
        payload["carryover_examples"] = carryover_examples
    return payload


def _build_intent_hint(text: str) -> Optional[Dict[str, Any]]:
    normalized = _normalize_hint_text(text)
    if not normalized:
        return None
    if _TURN_OFF_HINT_RE.search(normalized):
        return {"primary_goal_type": "TURN_OFF", "reason": "off_verb"}
    if _TURN_ON_HINT_RE.search(normalized):
        return {"primary_goal_type": "TURN_ON", "reason": "on_verb"}
    return None


def _explicit_goal_type_from_text(text: str) -> Optional[str]:
    normalized = _normalize_hint_text(text)
    if not normalized:
        return None
    if _TURN_OFF_HINT_RE.search(normalized):
        return "TURN_OFF"
    if _TURN_ON_HINT_RE.search(normalized):
        return "TURN_ON"
    return None


def _build_carryover_examples(context: Dict[str, Any]) -> list[Dict[str, Any]]:
    preferred_area = str(context.get("selected_area_name") or context.get("last_area_name") or "").strip()
    if not preferred_area:
        return []
    return [
        {
            "utterance": "выключи свет",
            "expected_goal_type": "TURN_OFF",
            "expected_area_name": preferred_area,
        },
        {
            "utterance": "включи свет",
            "expected_goal_type": "TURN_ON",
            "expected_area_name": preferred_area,
        },
    ]


def _preferred_context_area(context: Dict[str, Any]) -> Optional[str]:
    selected = str(context.get("selected_area_name") or "").strip()
    if selected:
        return selected
    last_area = str(context.get("last_area_name") or "").strip()
    return last_area or None


def _expand_area_alias_forms(alias: str) -> set[str]:
    alias_norm = _normalize_hint_text(alias)
    if not alias_norm:
        return set()

    forms = {alias_norm}
    if re.fullmatch(r"[a-z0-9 _-]+", alias_norm):
        return forms

    if alias_norm.endswith("ая"):
        forms.add(f"{alias_norm[:-2]}ой")
    elif alias_norm.endswith("я"):
        forms.add(f"{alias_norm[:-1]}е")
    elif alias_norm.endswith("а"):
        forms.add(f"{alias_norm[:-1]}е")
    elif alias_norm.endswith("й"):
        forms.add(f"{alias_norm[:-1]}е")
    elif alias_norm[-1].isalpha():
        forms.add(f"{alias_norm}е")
    return forms


def _contains_exact_token_phrase(text_norm: str, phrase_norm: str) -> bool:
    text_tokens = _tokenize_hint(text_norm)
    phrase_tokens = _tokenize_hint(phrase_norm)
    if not text_tokens or not phrase_tokens:
        return False
    span = len(phrase_tokens)
    for idx in range(len(text_tokens) - span + 1):
        if text_tokens[idx : idx + span] == phrase_tokens:
            return True
    return False


def _extract_explicit_area_from_text(text: str, area_synonyms: Dict[str, Any]) -> Optional[str]:
    text_norm = _normalize_hint_text(text)
    if not text_norm:
        return None

    best_match: tuple[int, int, str] | None = None
    for entry in area_synonyms.get("canonical_areas", []) or []:
        if not isinstance(entry, dict):
            continue
        canonical = str(entry.get("name") or "").strip()
        if not canonical:
            continue
        aliases = [canonical] + [str(item).strip() for item in (entry.get("synonyms") or []) if str(item).strip()]
        for alias in aliases:
            for alias_norm in _expand_area_alias_forms(alias):
                if not _contains_exact_token_phrase(text_norm, alias_norm):
                    continue
                alias_tokens = _tokenize_hint(alias_norm)
                candidate = (len(alias_tokens), len(alias_norm), canonical)
                if best_match is None or candidate > best_match:
                    best_match = candidate

    return best_match[2] if best_match is not None else None


def _stabilize_target_areas(
    parsed: Dict[str, Any],
    *,
    text: str,
    context: Dict[str, Any],
    area_synonyms: Dict[str, Any],
) -> Dict[str, Any]:
    actions = parsed.get("actions")
    if not isinstance(actions, list):
        return parsed

    explicit_area = _extract_explicit_area_from_text(text, area_synonyms)
    preferred_area = _preferred_context_area(context)
    if not explicit_area and not preferred_area:
        return parsed

    for action in actions:
        if not isinstance(action, dict):
            continue
        target = action.setdefault("target", {})
        entity_ids = [str(item).strip() for item in (target.get("entity_ids") or []) if str(item).strip()]
        if entity_ids:
            continue

        scope = str(target.get("scope") or "UNSPECIFIED")
        if explicit_area:
            target["scope"] = "AREA"
            target["area_name"] = explicit_area
            continue

        if preferred_area and scope in {"UNSPECIFIED", "AREA"}:
            target["scope"] = "AREA"
            target["area_name"] = preferred_area

    return parsed


def _recover_explicit_switch_command(
    *,
    parsed: Dict[str, Any],
    text: str,
    context: Dict[str, Any],
    area_synonyms: Dict[str, Any],
    area_options: list[str],
) -> Optional[Dict[str, Any]]:
    actions = parsed.get("actions")
    if not isinstance(actions, list) or not actions:
        return None

    first_action = actions[0] if isinstance(actions[0], dict) else None
    if not first_action or str(first_action.get("intent") or "") != "UNKNOWN":
        return None

    explicit_goal_type = _explicit_goal_type_from_text(text)
    if explicit_goal_type not in {"TURN_ON", "TURN_OFF"}:
        return None

    explicit_area = _extract_explicit_area_from_text(text, area_synonyms)
    preferred_area = _preferred_context_area(context)
    resolved_area = explicit_area or preferred_area
    if not resolved_area:
        return None

    options = {str(item).strip() for item in area_options if str(item).strip()}
    if options and resolved_area not in options:
        return None

    return {
        "schema_version": "1.0",
        "actions": [
            _action(
                explicit_goal_type,
                {
                    "scope": "AREA",
                    "area_name": resolved_area,
                    "entity_ids": [],
                },
                _empty_parsed_params(),
            )
        ],
    }


def _first_knowledge_value(items: Any, key: str) -> Any:
    if not isinstance(items, list) or not items:
        return None
    first = items[0]
    if not isinstance(first, dict):
        return None
    return first.get(key)


def _recover_semantic_llm_clarification(
    *,
    text: str,
    context: Dict[str, Any],
    area_synonyms: Dict[str, Any],
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
    scene_aliases: Dict[str, Any],
    area_options: list[str],
) -> Optional[Dict[str, Any]]:
    text_norm = _normalize_hint_text(text)
    explicit_area = _extract_explicit_area_from_text(text, area_synonyms)
    preferred_area = _preferred_context_area(context)
    resolved_area = explicit_area or preferred_area
    if not resolved_area:
        return None

    options = {str(item).strip() for item in area_options if str(item).strip()}
    if options and resolved_area not in options:
        return None

    target = {
        "scope": "AREA",
        "area_name": resolved_area,
        "entity_ids": [],
    }

    explicit_goal_type = _explicit_goal_type_from_text(text)
    if explicit_goal_type == "TURN_OFF" or "без света" in text_norm:
        return {
            "schema_version": "1.0",
            "actions": [_action("TURN_OFF", target, _empty_parsed_params())],
        }

    scene_knowledge = _build_scene_knowledge(text, scene_aliases)
    color_knowledge = _build_color_knowledge(text, colors)
    brightness_knowledge = _build_brightness_knowledge(text, modifiers)
    color_temp_knowledge = _build_color_temperature_knowledge(text, modifiers)

    goal_params: Dict[str, Any] = {
        "brightness": _first_knowledge_value(brightness_knowledge.get("absolute"), "brightness"),
        "brightness_delta": None,
        "color_name": None,
        "color_rgb": None,
        "color_temp_kelvin": None,
        "color_temp_delta_k": None,
        "transition_s": 0.8,
    }

    brighter_delta = _first_knowledge_value(brightness_knowledge.get("brighter"), "brightness_delta")
    dimmer_delta = _first_knowledge_value(brightness_knowledge.get("dimmer"), "brightness_delta")
    if brighter_delta is not None:
        goal_params["brightness_delta"] = brighter_delta
    elif dimmer_delta is not None:
        goal_params["brightness_delta"] = dimmer_delta

    warmer_delta = _first_knowledge_value(color_temp_knowledge.get("warmer"), "color_temp_delta_k")
    cooler_delta = _first_knowledge_value(color_temp_knowledge.get("cooler"), "color_temp_delta_k")
    if warmer_delta is not None:
        goal_params["color_temp_delta_k"] = warmer_delta
    elif cooler_delta is not None:
        goal_params["color_temp_delta_k"] = cooler_delta

    rgb_items = color_knowledge.get("rgb_colors") or []
    if isinstance(rgb_items, list) and rgb_items:
        first_rgb = rgb_items[0] if isinstance(rgb_items[0], dict) else None
        if first_rgb:
            goal_params["color_name"] = first_rgb.get("name")
            goal_params["color_rgb"] = first_rgb.get("rgb")

    white_items = color_knowledge.get("white_profiles") or []
    if goal_params["color_rgb"] is None and isinstance(white_items, list) and white_items:
        first_white = white_items[0] if isinstance(white_items[0], dict) else None
        if first_white:
            goal_params["color_name"] = first_white.get("name")
            goal_params["color_temp_kelvin"] = first_white.get("color_temp_kelvin")

    if scene_knowledge.get("primary_scene_id"):
        actions = _resolve_scene_goal(
            target=target,
            goal_params=goal_params,
            scene_aliases=scene_aliases,
            scene_id=str(scene_knowledge["primary_scene_id"]),
        )
        if actions:
            parsed = {"schema_version": "1.0", "actions": actions}
            parsed = _apply_context_defaults(parsed, context=context)
            parsed = _ensure_target_or_clarify(parsed, context=context, area_options=area_options)
            return parsed

    parsed_params = _goal_params_to_parsed_params(goal_params)
    inferred_goal_type: Optional[str] = explicit_goal_type
    if inferred_goal_type is None:
        if (
            parsed_params.get("color") is not None
            or parsed_params.get("color_temp_kelvin") is not None
            or parsed_params.get("brightness") is not None
        ):
            inferred_goal_type = "TURN_ON"
        elif parsed_params.get("brightness_delta") is not None:
            inferred_goal_type = "ADJUST_BRIGHTNESS"
        elif parsed_params.get("color_temp_delta_k") is not None:
            inferred_goal_type = "ADJUST_COLOR_TEMP"

    if inferred_goal_type is None:
        return None

    actions = _build_direct_actions(goal_type=inferred_goal_type, target=target, parsed_params=parsed_params)
    if not actions:
        return None

    parsed = {"schema_version": "1.0", "actions": actions}
    parsed = _apply_context_defaults(parsed, context=context)
    parsed = _ensure_target_or_clarify(parsed, context=context, area_options=area_options)
    return parsed


def _copy_target(raw: Dict[str, Any] | None) -> Dict[str, Any]:
    target = dict(raw or {})
    scope = str(target.get("scope") or "UNSPECIFIED")
    area_name = target.get("area_name")
    entity_ids = [str(e) for e in (target.get("entity_ids") or []) if str(e).strip()]

    # Some local models return a semantically-correct room together with
    # scope=ALL_LIGHTS. Normalize this contradiction before schema validation.
    if area_name and scope == "ALL_LIGHTS" and not entity_ids:
        scope = "AREA"

    return {
        "scope": scope,
        "area_name": area_name,
        "entity_ids": entity_ids,
    }


def _make_rgb_color(name: Optional[str], rgb: Optional[list[Any]]) -> Optional[Dict[str, Any]]:
    if not isinstance(rgb, list) or len(rgb) != 3:
        return None
    try:
        normalized = [max(0, min(255, int(v))) for v in rgb]
    except Exception:
        return None
    return {"mode": "rgb", "name": name, "rgb": normalized}


def _empty_parsed_params() -> Dict[str, Any]:
    return {
        "brightness": None,
        "brightness_delta": None,
        "color": None,
        "color_temp_kelvin": None,
        "color_temp_delta_k": None,
        "transition_s": None,
    }


def _goal_params_to_parsed_params(params_raw: Dict[str, Any] | None) -> Dict[str, Any]:
    params = dict(params_raw or {})
    parsed = _empty_parsed_params()
    parsed["brightness"] = params.get("brightness")
    parsed["brightness_delta"] = params.get("brightness_delta")
    parsed["color"] = _make_rgb_color(params.get("color_name"), params.get("color_rgb"))
    parsed["color_temp_kelvin"] = params.get("color_temp_kelvin")
    parsed["color_temp_delta_k"] = params.get("color_temp_delta_k")
    parsed["transition_s"] = params.get("transition_s")
    return parsed


def _clamp_int(value: Any, low: int, high: int) -> Optional[int]:
    if value is None:
        return None
    try:
        return max(low, min(high, int(value)))
    except Exception:
        return None


def _action(intent: str, target: Dict[str, Any], params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "domain": "light",
        "intent": intent,
        "target": {
            "scope": target.get("scope") or "UNSPECIFIED",
            "area_name": target.get("area_name"),
            "entity_ids": list(target.get("entity_ids") or []),
        },
        "params": {
            "brightness": params.get("brightness"),
            "brightness_delta": params.get("brightness_delta"),
            "color": params.get("color"),
            "color_temp_kelvin": params.get("color_temp_kelvin"),
            "color_temp_delta_k": params.get("color_temp_delta_k"),
            "transition_s": params.get("transition_s"),
        },
    }


def _prefer_color_over_color_temp(params: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(params)
    if out.get("color") is not None and out.get("color_temp_kelvin") is not None:
        out["color_temp_kelvin"] = None
    return out


def _build_direct_actions(*, goal_type: str, target: Dict[str, Any], parsed_params: Dict[str, Any]) -> list[Dict[str, Any]]:
    params = _prefer_color_over_color_temp(parsed_params)
    actions: list[Dict[str, Any]] = []

    if goal_type in {"TURN_OFF", "CANCEL"}:
        actions.append(_action(goal_type, target, _empty_parsed_params()))
        return actions

    absolute_params = {
        "brightness": params.get("brightness"),
        "brightness_delta": None,
        "color": params.get("color"),
        "color_temp_kelvin": params.get("color_temp_kelvin"),
        "color_temp_delta_k": None,
        "transition_s": params.get("transition_s"),
    }
    has_abs_brightness = absolute_params["brightness"] is not None
    has_abs_color = absolute_params["color"] is not None
    has_abs_temp = absolute_params["color_temp_kelvin"] is not None
    absolute_count = sum(1 for flag in (has_abs_brightness, has_abs_color, has_abs_temp) if flag)

    if goal_type in _ABSOLUTE_GOAL_TYPES:
        if goal_type == "TURN_ON" or absolute_count > 1:
            actions.append(_action("TURN_ON", target, absolute_params))
        elif has_abs_brightness:
            actions.append(_action("SET_BRIGHTNESS", target, absolute_params))
        elif has_abs_color:
            actions.append(_action("SET_COLOR", target, absolute_params))
        elif has_abs_temp:
            actions.append(_action("SET_COLOR_TEMP", target, absolute_params))
        elif goal_type == "TURN_ON":
            actions.append(_action("TURN_ON", target, absolute_params))

    if params.get("brightness_delta") is not None:
        actions.append(
            _action(
                "ADJUST_BRIGHTNESS",
                target,
                {
                    "brightness": None,
                    "brightness_delta": params.get("brightness_delta"),
                    "color": None,
                    "color_temp_kelvin": None,
                    "color_temp_delta_k": None,
                    "transition_s": params.get("transition_s"),
                },
            )
        )

    if params.get("color_temp_delta_k") is not None:
        actions.append(
            _action(
                "ADJUST_COLOR_TEMP",
                target,
                {
                    "brightness": None,
                    "brightness_delta": None,
                    "color": None,
                    "color_temp_kelvin": None,
                    "color_temp_delta_k": params.get("color_temp_delta_k"),
                    "transition_s": params.get("transition_s"),
                },
            )
        )

    return actions


def _resolve_scene_goal(
    *,
    target: Dict[str, Any],
    goal_params: Dict[str, Any],
    scene_aliases: Dict[str, Any],
    scene_id: Optional[str],
) -> Optional[list[Dict[str, Any]]]:
    scene_map = {
        str(scene.get("id")): scene
        for scene in (scene_aliases.get("scenes") or [])
        if isinstance(scene, dict) and scene.get("id")
    }
    scene = scene_map.get(str(scene_id or ""))
    if scene is None:
        return None

    defaults = dict(scene.get("defaults") or {})
    resolved: Dict[str, Any] = {
        "brightness": _clamp_int(defaults.get("brightness"), 0, 100),
        "brightness_delta": None,
        "color": _make_rgb_color(defaults.get("color_name"), defaults.get("color_rgb")),
        "color_temp_kelvin": _clamp_int(defaults.get("color_temp_kelvin"), 1500, 6500),
        "color_temp_delta_k": None,
        "transition_s": defaults.get("transition_s") if defaults.get("transition_s") is not None else goal_params.get("transition_s"),
    }

    if goal_params.get("brightness") is not None:
        resolved["brightness"] = _clamp_int(goal_params.get("brightness"), 0, 100)
    elif goal_params.get("brightness_delta") is not None and resolved["brightness"] is not None:
        resolved["brightness"] = _clamp_int(resolved["brightness"] + int(goal_params["brightness_delta"]), 0, 100)

    explicit_color = _make_rgb_color(goal_params.get("color_name"), goal_params.get("color_rgb"))
    if explicit_color is not None:
        resolved["color"] = explicit_color
        resolved["color_temp_kelvin"] = None
    elif goal_params.get("color_temp_kelvin") is not None:
        resolved["color"] = None
        resolved["color_temp_kelvin"] = _clamp_int(goal_params.get("color_temp_kelvin"), 1500, 6500)
    elif goal_params.get("color_temp_delta_k") is not None and resolved["color_temp_kelvin"] is not None:
        resolved["color_temp_kelvin"] = _clamp_int(
            resolved["color_temp_kelvin"] + int(goal_params["color_temp_delta_k"]),
            1500,
            6500,
        )

    if goal_params.get("transition_s") is not None:
        resolved["transition_s"] = goal_params.get("transition_s")

    resolved = _prefer_color_over_color_temp(resolved)
    return [_action("TURN_ON", target, resolved)]


def _scene_id_from_goal(goal: Dict[str, Any]) -> Optional[str]:
    scene_id = goal.get("scene_id")
    if scene_id is None:
        return None
    scene_id_str = str(scene_id).strip()
    return scene_id_str or None


def _goal_should_resolve_via_scene(goal: Dict[str, Any]) -> bool:
    if _scene_id_from_goal(goal) is None:
        return False
    goal_type = str(goal.get("goal_type") or "UNKNOWN")
    return goal_type not in {"TURN_OFF", "CANCEL"}


def _stabilize_scene_target(target: Dict[str, Any], *, context: Dict[str, Any]) -> Dict[str, Any]:
    stable = _copy_target(target)
    if stable.get("entity_ids") or stable.get("area_name"):
        return stable
    preferred_area = _preferred_context_area(context)
    if preferred_area:
        stable["scope"] = "AREA"
        stable["area_name"] = preferred_area
        return stable
    if stable.get("scope") != "ALL_LIGHTS":
        stable["scope"] = "UNSPECIFIED"
    return stable


def _goal_to_parsed_command(
    goal: Dict[str, Any],
    *,
    context: Dict[str, Any],
    scene_aliases: Dict[str, Any],
    area_options: list[str],
) -> Dict[str, Any]:
    goal_type = str(goal.get("goal_type") or "UNKNOWN")
    target = _copy_target(goal.get("target"))
    parsed_params = _goal_params_to_parsed_params(goal.get("params"))

    if _goal_should_resolve_via_scene(goal):
        actions = _resolve_scene_goal(
            target=_stabilize_scene_target(target, context=context),
            goal_params=dict(goal.get("params") or {}),
            scene_aliases=scene_aliases,
            scene_id=_scene_id_from_goal(goal),
        )
        if actions:
            parsed = {"schema_version": "1.0", "actions": actions}
            parsed = _apply_context_defaults(parsed, context=context)
            parsed = _ensure_target_or_clarify(parsed, context=context, area_options=area_options)
            return parsed

    if goal_type == "UNKNOWN":
        clarification = goal.get("clarification") or {}
        question = str(clarification.get("question") or "\u042f \u043d\u0435 \u0441\u043c\u043e\u0433 \u043f\u043e\u043d\u044f\u0442\u044c \u043a\u043e\u043c\u0430\u043d\u0434\u0443. \u0421\u043a\u0430\u0436\u0438 \u0438\u043d\u0430\u0447\u0435.")
        options = [str(o) for o in (clarification.get("options") or []) if str(o).strip()]
        return _parsed_clarification(question=question, options=options or area_options[:5] or None)

    if goal_type == "MOOD_SCENE":
        actions = _resolve_scene_goal(
            target=target,
            goal_params=dict(goal.get("params") or {}),
            scene_aliases=scene_aliases,
            scene_id=_scene_id_from_goal(goal),
        )
        if not actions:
            return _parsed_clarification(
                question="\u041a\u0430\u043a\u0443\u044e \u0430\u0442\u043c\u043e\u0441\u0444\u0435\u0440\u0443 \u0441\u0432\u0435\u0442\u0430 \u0432\u044b \u0445\u043e\u0442\u0438\u0442\u0435 \u043f\u043e\u043b\u0443\u0447\u0438\u0442\u044c?",
                options=["\u043a\u0430\u043a \u0432 \u0437\u0430\u043a\u0430\u0442\u0435", "\u043a\u0430\u043a \u0432 \u043a\u0438\u043d\u043e\u0442\u0435\u0430\u0442\u0440\u0435", "\u0434\u043b\u044f \u043d\u043e\u0447\u043d\u043e\u0433\u043e \u043f\u0440\u043e\u0445\u043e\u0434\u0430"],
            )
    else:
        actions = _build_direct_actions(goal_type=goal_type, target=target, parsed_params=parsed_params)
        if not actions:
            return _parsed_clarification(question="\u0423\u0442\u043e\u0447\u043d\u0438\u0442\u0435 \u043a\u043e\u043c\u0430\u043d\u0434\u0443 \u0434\u043b\u044f \u0441\u0432\u0435\u0442\u0430, \u043f\u043e\u0436\u0430\u043b\u0443\u0439\u0441\u0442\u0430.")

    parsed = {"schema_version": "1.0", "actions": actions}
    parsed = _apply_context_defaults(parsed, context=context)
    parsed = _ensure_target_or_clarify(parsed, context=context, area_options=area_options)
    return parsed


def _apply_context_defaults(parsed: Dict[str, Any], *, context: Dict[str, Any]) -> Dict[str, Any]:
    """Inject preferred context area when target scope is unspecified."""
    preferred_area = _preferred_context_area(context)
    if not preferred_area:
        return parsed

    actions = parsed.get("actions")
    if not isinstance(actions, list):
        return parsed

    for action in actions:
        if not isinstance(action, dict):
            continue
        target = action.setdefault("target", {})
        scope = target.get("scope") or "UNSPECIFIED"
        ent_ids = target.get("entity_ids") or []
        area_name = target.get("area_name")

        if ent_ids:
            continue

        if scope in {"UNSPECIFIED", "AREA"} and not area_name:
            target["scope"] = "AREA"
            target["area_name"] = preferred_area

    return parsed


def _ensure_target_or_clarify(
    parsed: Dict[str, Any],
    *,
    context: Dict[str, Any],
    area_options: list[str],
) -> Dict[str, Any]:
    """Ensure that each action has a resolvable target or ask the user."""
    actions = parsed.get("actions")
    if not isinstance(actions, list):
        return parsed

    for action in actions:
        if not isinstance(action, dict):
            continue
        target = action.get("target") or {}
        ent_ids = target.get("entity_ids") or []
        area_name = (target.get("area_name") or "").strip()

        if ent_ids or area_name:
            continue

        preferred_area = _preferred_context_area(context or {})
        if preferred_area:
            target["scope"] = "AREA"
            target["area_name"] = preferred_area
            continue

        question = "В какой комнате выполнить команду?"
        opts = area_options[:5] if area_options else []
        return _parsed_clarification(question=question, options=opts or None)

    return parsed


@dataclass(frozen=True)
class LLMParserV1:
    """LLM parser wrapper."""

    client: LLMClient
    parsed_schema: Dict[str, Any]
    fallback_to_rules: bool = True
    semantic_rescue: bool = True

    def parse(
        self,
        text: str,
        *,
        context: Dict[str, Any],
        device_registry: Dict[str, Any],
        area_synonyms: Dict[str, Any],
        colors: Dict[str, Any],
        modifiers: Dict[str, Any],
        scene_aliases: Dict[str, Any],
    ) -> Dict[str, Any]:
        system = (
            "You are a strict NLU module for a smart home. "
            "Convert the Russian user command into LightingGoal v1 JSON. "
            "Use goal_contract, decision_policy, context, and knowledge. "
            "Return exactly one JSON object and no markdown. "
            "For atmosphere-style requests use goal_type='MOOD_SCENE' with scene_id. "
            "If knowledge.scenes.primary_scene_id exists, scene_id must not be null. "
            "When room is omitted, prefer context.selected_area_name, then context.last_area_name, over ALL_LIGHTS. "
            "If clarification is needed, return goal_type='UNKNOWN' with clarification."
        )

        prompt_payload = _build_llm_prompt_payload(
            text,
            context=context,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
            scene_aliases=scene_aliases,
        )
        areas = list(prompt_payload.get("areas") or [])
        goal_schema = _build_lighting_goal_schema(scene_aliases)
        user = json.dumps(prompt_payload, ensure_ascii=False, separators=(",", ":"))

        def _run_rule_parser() -> Dict[str, Any]:
            parsed_rule = parse_light_command_v1(
                text,
                context=context,
                device_registry=device_registry,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
            )
            return _apply_context_defaults(parsed_rule, context=context)

        def _run_semantic_rescue() -> Optional[Dict[str, Any]]:
            if not self.semantic_rescue:
                return None
            rescued = _run_rule_parser()
            if rescued.get("clarification", {}).get("needed"):
                return rescued if self.fallback_to_rules else None
            return rescued

        try:
            raw = self.client.generate_json(
                system=system,
                user=user,
                temperature=0.0,
                max_tokens=LLM_MAX_OUTPUT_TOKENS,
                json_schema=goal_schema,
            )
        except Exception:
            rescued = _run_semantic_rescue()
            if rescued is not None:
                return rescued
            if self.fallback_to_rules:
                return _run_rule_parser()
            return _parsed_clarification(question="\u042f \u043d\u0435 \u0441\u043c\u043e\u0433 \u043f\u043e\u043d\u044f\u0442\u044c \u043a\u043e\u043c\u0430\u043d\u0434\u0443. \u0421\u043a\u0430\u0436\u0438 \u0438\u043d\u0430\u0447\u0435.")

        json_str = _extract_first_json_object(raw)
        if json_str is None:
            semantic_rescue = _recover_semantic_llm_clarification(
                text=text,
                context=context,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
                scene_aliases=scene_aliases,
                area_options=areas,
            )
            if semantic_rescue is not None:
                return semantic_rescue
            clar = _clarification_from_freeform(raw, options=areas[:5] or None)
            if clar and not _should_rescue_llm_clarification(clar, text=text, context=context, area_options=areas):
                return clar

            rescued = _run_semantic_rescue()
            if rescued is not None:
                return rescued
            if self.fallback_to_rules:
                return _run_rule_parser()
            if clar:
                return clar
            return _parsed_clarification(question="\u042f \u043d\u0435 \u0441\u043c\u043e\u0433 \u043f\u043e\u043d\u044f\u0442\u044c \u043a\u043e\u043c\u0430\u043d\u0434\u0443. \u0421\u043a\u0430\u0436\u0438 \u0438\u043d\u0430\u0447\u0435.")

        try:
            goal = json.loads(json_str)
            validate_with_schema(goal, goal_schema)
        except Exception:
            semantic_rescue = _recover_semantic_llm_clarification(
                text=text,
                context=context,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
                scene_aliases=scene_aliases,
                area_options=areas,
            )
            if semantic_rescue is not None:
                return semantic_rescue
            rescued = _run_semantic_rescue()
            if rescued is not None:
                return rescued
            if self.fallback_to_rules:
                return _run_rule_parser()
            clar = _clarification_from_freeform(raw, options=areas[:5] or None)
            if clar:
                return clar
            return _parsed_clarification(question="\u042f \u043d\u0435 \u0441\u043c\u043e\u0433 \u043f\u043e\u043d\u044f\u0442\u044c \u043a\u043e\u043c\u0430\u043d\u0434\u0443. \u0421\u043a\u0430\u0436\u0438 \u0438\u043d\u0430\u0447\u0435.")

        parsed = _goal_to_parsed_command(
            goal,
            context=context,
            scene_aliases=scene_aliases,
            area_options=areas,
        )
        parsed = _stabilize_target_areas(
            parsed,
            text=text,
            context=context,
            area_synonyms=area_synonyms,
        )
        recovered = _recover_explicit_switch_command(
            parsed=parsed,
            text=text,
            context=context,
            area_synonyms=area_synonyms,
            area_options=areas,
        )
        if recovered is not None:
            parsed = recovered
        if parsed.get("clarification", {}).get("needed"):
            semantic_rescue = _recover_semantic_llm_clarification(
                text=text,
                context=context,
                area_synonyms=area_synonyms,
                colors=colors,
                modifiers=modifiers,
                scene_aliases=scene_aliases,
                area_options=areas,
            )
            if semantic_rescue is not None:
                return semantic_rescue
            if _should_rescue_llm_clarification(parsed, text=text, context=context, area_options=areas):
                rescued = _run_semantic_rescue()
                if rescued is not None:
                    return rescued
            return parsed

        if _has_unknown_area_targets(parsed, areas):
            rescued = _run_semantic_rescue()
            if rescued is not None:
                return rescued

        try:
            validate_with_schema(parsed, self.parsed_schema)
        except Exception:
            rescued = _run_semantic_rescue()
            if rescued is not None:
                return rescued
            if self.fallback_to_rules:
                return _run_rule_parser()
            return _parsed_clarification(question="\u042f \u043d\u0435 \u0441\u043c\u043e\u0433 \u043f\u043e\u043d\u044f\u0442\u044c \u043a\u043e\u043c\u0430\u043d\u0434\u0443. \u0421\u043a\u0430\u0436\u0438 \u0438\u043d\u0430\u0447\u0435.")

        return parsed


def parse_light_command_llm_v1(
    text: str,
    *,
    context: Dict[str, Any],
    device_registry: Dict[str, Any],
    area_synonyms: Dict[str, Any],
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
    scene_aliases: Dict[str, Any],
    parsed_schema: Dict[str, Any],
    client: LLMClient,
    fallback_to_rules: bool = True,
    semantic_rescue: bool = True,
) -> Dict[str, Any]:
    """Functional wrapper (for CLI/eval)."""
    return LLMParserV1(
        client=client,
        parsed_schema=parsed_schema,
        fallback_to_rules=fallback_to_rules,
        semantic_rescue=semantic_rescue,
    ).parse(
        text,
        context=context,
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
    )
