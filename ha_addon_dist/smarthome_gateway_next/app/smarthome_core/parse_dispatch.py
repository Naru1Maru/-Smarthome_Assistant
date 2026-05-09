"""Parser selection / dispatch for v1 pipeline."""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, Optional

from .llm_client import LLMClient
from .parser import parse_light_command_v1
from .parser_llm import parse_light_command_llm_v1

_MATCH_CLEAN_RE = re.compile(r"[^\w\s%-]+", flags=re.UNICODE)
_SPACE_RE = re.compile(r"\s+", flags=re.UNICODE)
_BRIGHTNESS_MARKERS = (
    "ярче",
    "ярк",
    "тускл",
    "потускл",
    "темн",
    "светлее",
    "не слишком ярко",
)
_TEMP_MARKERS = (
    "тепл",
    "холодн",
    "похолоднее",
    "потеплее",
    "нейтральн",
    "прохладн",
)


def parse_light_command_v1_dispatch(
    text: str,
    *,
    parser_mode: str,
    context: Dict[str, Any],
    device_registry: Dict[str, Any],
    area_synonyms: Dict[str, Any],
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
    scene_aliases: Optional[Dict[str, Any]] = None,
    parsed_schema: Optional[Dict[str, Any]] = None,
    llm_client: Optional[LLMClient] = None,
    llm_fallback_to_rules: bool = True,
) -> Dict[str, Any]:
    """Select parser implementation.

    parser_mode:
      - "rules": robust rule parser (baseline)
      - "llm_safe": rules first, then LLM when rules are insufficient
      - "llm": strict LLM-only parser without fallback

    Notes:
      - For llm_* modes you must pass parsed_schema + llm_client.
      - `llm_fallback_to_rules` is kept only for backward compatibility and is
        ignored for canonical `llm`; use `llm_safe` for the hybrid mode.
    """
    mode = (parser_mode or "rules").strip().lower()
    # normalize aliases
    if mode == "rule":
        mode = "rules"
    if mode in {"llm_only", "llm_strict"}:
        mode = "llm"
    if mode == "llm_fallback":
        mode = "llm_safe"

    def _run_rules() -> Dict[str, Any]:
        return parse_light_command_v1(
            text,
            context=context,
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
        )

    def _run_llm(fallback: bool, *, semantic_rescue: bool) -> Dict[str, Any]:
        if parsed_schema is None or llm_client is None:
            raise ValueError("parsed_schema and llm_client are required for llm parser modes")
        return parse_light_command_llm_v1(
            text,
            context=context,
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
            scene_aliases=scene_aliases or {},
            parsed_schema=parsed_schema,
            client=llm_client,
            fallback_to_rules=fallback,
            semantic_rescue=semantic_rescue,
        )

    if mode == "rules":
        return _run_rules()

    if mode == "llm_safe":
        # Rules stay on the fast path; LLM is only for genuinely hard cases.
        rules_parsed = _run_rules()
        if _should_accept_rules(
            text,
            rules_parsed,
            colors=colors,
            scene_aliases=scene_aliases or {},
        ):
            return rules_parsed
        # Avoid a second inner fallback so the hybrid path does not do duplicate work.
        return _run_llm(fallback=False, semantic_rescue=False)

    if mode == "llm":
        return _run_llm(fallback=False, semantic_rescue=False)

    raise ValueError(f"Unknown parser_mode: {parser_mode}")


def _should_accept_rules(
    text: str,
    parsed: Dict[str, Any],
    *,
    colors: Optional[Dict[str, Any]] = None,
    scene_aliases: Optional[Dict[str, Any]] = None,
) -> bool:
    """Return True if rule parser output is good enough to skip the LLM."""
    actions = parsed.get("actions") or []
    if not actions:
        return False

    if parsed.get("clarification") is not None:
        return False

    primary_intent = actions[0].get("intent")
    if primary_intent == "UNKNOWN":
        return False

    norm_text = _normalize_match_text(text)
    dims = _semantic_dimensions(actions)

    # Scene- and mood-like requests are exactly where the hybrid mode should
    # defer to the LLM unless rules extracted enough concrete control signals.
    if _text_matches_scene_pattern(norm_text, scene_aliases or {}) and len(dims) < 2:
        return False

    mentions_brightness = any(marker in norm_text for marker in _BRIGHTNESS_MARKERS)
    mentions_temp = any(marker in norm_text for marker in _TEMP_MARKERS)
    mentions_color = _text_mentions_color(norm_text, colors or {})

    if mentions_brightness and mentions_temp and not {"brightness", "temp"}.issubset(dims):
        return False

    if mentions_brightness and mentions_color and not {"brightness", "color"}.issubset(dims):
        return False

    if _is_generic_turn_on(actions, dims) and (mentions_brightness or mentions_temp or mentions_color):
        return False

    return True


def _normalize_match_text(text: str) -> str:
    lowered = (text or "").casefold().replace("ё", "е")
    cleaned = _MATCH_CLEAN_RE.sub(" ", lowered).replace("_", " ")
    return _SPACE_RE.sub(" ", cleaned).strip()


def _semantic_dimensions(actions: Iterable[Dict[str, Any]]) -> set[str]:
    dims: set[str] = set()
    for action in actions:
        intent = str(action.get("intent") or "").upper()
        params = action.get("params") or {}
        if intent in {"SET_BRIGHTNESS", "ADJUST_BRIGHTNESS"}:
            dims.add("brightness")
        if intent == "SET_COLOR":
            dims.add("color")
        if intent in {"SET_COLOR_TEMP", "ADJUST_COLOR_TEMP"}:
            dims.add("temp")
        if params.get("brightness") is not None or params.get("brightness_delta") is not None:
            dims.add("brightness")
        if params.get("color"):
            dims.add("color")
        if params.get("color_temp_kelvin") is not None or params.get("color_temp_delta_k") is not None:
            dims.add("temp")
    return dims


def _text_matches_scene_pattern(norm_text: str, scene_aliases: Dict[str, Any]) -> bool:
    for pattern in _iter_scene_patterns(scene_aliases):
        if pattern in norm_text:
            return True
    return False


def _iter_scene_patterns(scene_aliases: Dict[str, Any]) -> Iterable[str]:
    for scene in scene_aliases.get("scenes") or []:
        if not isinstance(scene, dict):
            continue
        for pattern in scene.get("patterns") or []:
            if isinstance(pattern, str):
                norm_pattern = _normalize_match_text(pattern)
                if norm_pattern:
                    yield norm_pattern


def _text_mentions_color(norm_text: str, colors: Dict[str, Any]) -> bool:
    for alias in _iter_color_aliases(colors):
        if alias in norm_text:
            return True
    return False


def _iter_color_aliases(colors: Dict[str, Any]) -> Iterable[str]:
    for color_entry in colors.get("palette_rgb") or []:
        if not isinstance(color_entry, dict):
            continue
        for alias in color_entry.get("aliases") or []:
            if isinstance(alias, str):
                norm_alias = _normalize_match_text(alias)
                if norm_alias:
                    yield norm_alias
        name = color_entry.get("name")
        if isinstance(name, str):
            norm_name = _normalize_match_text(name)
            if norm_name:
                yield norm_name


def _is_generic_turn_on(actions: Iterable[Dict[str, Any]], dims: set[str]) -> bool:
    action_list = list(actions)
    if not action_list or dims:
        return False
    return all(str(action.get("intent") or "").upper() == "TURN_ON" for action in action_list)
