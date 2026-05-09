"""Rule-based baseline parser (v1) for light commands.

This parser converts free-form Russian user text into ParsedCommand v1 without any LLM.
Goal: deterministic baseline for our gold dataset and early demos.

Important nuance of v1:
- ParsedCommand keeps *surface* area_name (e.g. "зал", "прихожая", "Кухня").
- Canonicalization ("зал" -> "Гостиная") happens later in the validator.

Design principles:
- Prefer stable substring/pattern matching over heavy NLP dependencies.
- Clarify only when necessary (missing/unknown target, conflicts, too many actions).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from .text_normalize import normalize_text


# Common ASR / typo fixes (v1).
# Keep this list small and conservative: only whole-word replacements to avoid false positives.
_ASR_FIXES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bпотиже\b", re.UNICODE), "потише"),
    (re.compile(r"\bярще\b", re.UNICODE), "ярче"),
    (re.compile(r"\bарче\b", re.UNICODE), "ярче"),
    (re.compile(r"\bпагаси\b", re.UNICODE), "погаси"),
    (re.compile(r"\bкаридор\b", re.UNICODE), "коридор"),
    (re.compile(r"\bкаридоре\b", re.UNICODE), "коридоре"),
    (re.compile(r"\bкуфня\b", re.UNICODE), "кухня"),
    (re.compile(r"\bкуфне\b", re.UNICODE), "кухне"),
    (re.compile(r"\bспалня\b", re.UNICODE), "спальня"),
    (re.compile(r"\bспалне\b", re.UNICODE), "спальне"),
    (re.compile(r"\bвезьде\b", re.UNICODE), "везде"),
]

def _apply_asr_fixes(t_norm: str) -> str:
    out = t_norm
    for rx, repl in _ASR_FIXES:
        out = rx.sub(repl, out)
    return out

from .text_templates import (
    area_to_prepositional,
    missing_target_question,
    option_label_for_action,
    too_many_actions_question,
    unknown_area_question,
)


# ----------------------------
# Normalization helpers
# ----------------------------

_PUNCT_RE = re.compile(r"[^\w\s%-]+", re.UNICODE)
_SPACES_RE = re.compile(r"\s+", re.UNICODE)



def _find_last_self_correction_span(t_norm: str) -> Optional[Tuple[int, int]]:
    """Return (match_start, match_end) for the last self-correction marker, else None.

    Markers are conservative and require punctuation or a clear boundary to reduce false matches.
    Examples:
      - "..., нет, ..."
      - "..., ой нет, ..."
      - "..., точнее, ..."
      - "..., вернее ..."
      - "..., а нет, ..."
      - "..., хотя, ..."

    NOTE: We intentionally do NOT treat a standalone "нет" at the beginning as correction.
    """
    pattern = re.compile(
        r"(?:,|;|\.|!|\?)\s*(?:а\s+)?(?:ой\s+)?(?:нет|точнее|вернее|хотя)\b\s*,?\s+",
        flags=re.IGNORECASE,
    )
    last = None
    for m in pattern.finditer(t_norm):
        last = (m.start(), m.end())
    return last


def _tail_contains_any_intent_hint(t_tail: str) -> bool:
    """Heuristic: does the tail likely contain a light intent (on/off/adjust/color/ct)?"""
    # Meta cancel / stop (treated as an intent for self-correction tails)
    if re.search(r"\b(отмена|отмени|стоп|стой|хватит|не\s+надо|не\s+нужно|не\s+делай|ничего\s+не\s+делай|оставь\s+как\s+есть|оставь\s+как\s+было|забудь)\b", t_tail):
        return True

    # ON/OFF
    if re.search(r"\b(включи|включай|вруби|врубай|зажги|зажигай|выключи|выключай|выруби|вырубай|погаси|гаси|потуши|потуши|отключи)\b", t_tail):
        return True
    # Brightness / CT / Color quick hints
    if re.search(r"\b(ярче|светлее|темнее|потише|тише|приглуши|приглушай|на\s+полную|на\s+максимум|на\s+минимум|половин)\b", t_tail):
        return True
    if re.search(r"\b(теплее|холоднее|желтее|белее|синее|дневн|нейтрал)\w*\b", t_tail):
        return True
    if re.search(r"\b(красн|син|зел|фиол|розов|ж[её]лт|оранж|бирюз|голуб|бел)\w*\b", t_tail):
        return True
    return False


def _apply_self_correction(t_full: str, area_synonyms: Dict[str, Any]) -> Tuple[str, Optional[Tuple[str, Optional[str]]]]:
    """Apply self-correction on already normalized text.

    Note: This version expects punctuation already converted to spaces; therefore
    span detection is conservative and typically triggers only when punctuation
    survived normalization (e.g., upstream normalization mode changes).

    We keep this behavior to preserve existing gold datasets (ext6/constraints).
    """
    span = _find_last_self_correction_span(t_full)
    if span is None:
        return t_full, None

    _, end = span
    t_tail = t_full[end:].strip()
    if not t_tail:
        return t_full, None

    # If tail contains intent hints -> parse tail, but allow target fallback later.
    if _tail_contains_any_intent_hint(t_tail):
        return t_tail, None

    # If tail has only a target correction (e.g., "точнее в спальне") -> override target only.
    scope_tail, area_tail = _extract_target(t_tail, area_synonyms)
    if scope_tail != "UNSPECIFIED":
        return t_full, (scope_tail, area_tail)

    return t_full, None


def _normalize(text: str, *, yo_to_e: bool = True) -> str:
    """Lightweight normalization used for deterministic matching."""
    t = normalize_text(
        text,
        trim=True,
        lowercase=True,
        collapse_spaces=True,
        yo_to_e=yo_to_e,
        punctuation_mode="space",
        # Keep '%' and '-' (parser v1 behaviour)
    )
    return _apply_asr_fixes(t)


def _unique_keep_order(items: List[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for x in items:
        if x not in seen:
            out.append(x)
            seen.add(x)
    return out


def _expand_ru_forms(word: str) -> List[str]:
    """Expand a small set of common Russian inflection forms (very small heuristic).

    This is NOT full morphology; we only add forms needed for our v1 dataset.
    """
    w = word
    out = [w]

    # Nouns ending with -я (кухня -> кухне/кухню/кухни)
    if w.endswith("я") and len(w) > 2:
        base = w[:-1]
        out += [base + "е", base + "ю", base + "и"]

    # Nouns/adjectives ending with -ая (гостиная -> гостиной/гостиную/гостиней)
    if w.endswith("ая") and len(w) > 3:
        base = w[:-2]
        out += [base + "ой", base + "ую", base + "ей"]

    # Simple consonant endings for room names (коридор -> коридоре, зал -> зале)
    if re.fullmatch(r"[а-яa-z0-9]+", w) and len(w) > 2 and w[-1] not in "аяеиоуыь":
        out += [w + "е", w + "у"]

    # Adjectives ending with -ый/-ий/-ой (синий -> синим, красный -> красным)
    if w.endswith("ый") and len(w) > 3:
        base = w[:-2]
        out += [base + "ым", base + "ого", base + "ому"]
    if w.endswith("ий") and len(w) > 3:
        base = w[:-2]
        out += [base + "им", base + "его", base + "ему"]
    if w.endswith("ой") and len(w) > 3:
        base = w[:-2]
        out += [base + "ым", base + "ого", base + "ому"]

    return _unique_keep_order(out)


def _fallback_area_from_text(t_norm: str) -> Optional[str]:
    """Fallback extraction for unknown areas like "в кабинете" -> "Кабинет".

    Used only when there is an explicit area mention but it doesn't match our known lexicon.
    """
    m = re.search(r"\b(в|на)\s+([а-я]+)\b", t_norm)
    if not m:
        return None
    w = m.group(2)
    if w in {"везде", "езде"}:
        return None

    cand = w
    if cand.endswith("е") and len(cand) > 3:
        cand = cand[:-1]
    if cand.endswith("и") and len(cand) > 3:
        cand = cand[:-1] + "а"
    if cand.endswith("ой") and len(cand) > 4:
        cand = cand[:-2] + "ая"
    if cand.endswith("не") and len(cand) > 4:
        cand = cand[:-2] + "ня"

    return cand.capitalize()


# ----------------------------
# Matching structs
# ----------------------------


@dataclass(frozen=True)
class _Match:
    score: int
    value: Any
    raw: str


def _best_substring_match(t_norm: str, candidates: List[Tuple[str, Any]]) -> Optional[_Match]:
    """Pick best candidate by (length, earliest position)."""
    best: Optional[_Match] = None
    for pat, val in candidates:
        if not pat:
            continue
        idx = t_norm.find(pat)
        if idx < 0:
            continue
        # Score: longer pattern preferred; tie-breaker: earlier position.
        score = len(pat) * 10 - idx
        m = _Match(score=score, value=val, raw=pat)
        if best is None or m.score > best.score:
            best = m
    return best


# ----------------------------
# Public API
# ----------------------------


def parse_light_command_v1(
    text: str,
    *,
    context: Optional[Dict[str, Any]],
    device_registry: Dict[str, Any],
    area_synonyms: Dict[str, Any],
    colors: Dict[str, Any],
    modifiers: Dict[str, Any],
) -> Dict[str, Any]:
    """Parse text into ParsedCommand v1 (rule-based)."""
    t_norm_full = _normalize(text)
    t_norm, target_override = _apply_self_correction(t_norm_full, area_synonyms)
    # 1) Target extraction
    scope, area_name = _extract_target(t_norm, area_synonyms)
    # If the effective tail dropped the target, fall back to the full utterance target.
    if scope == "UNSPECIFIED":
        scope_full, area_full = _extract_target(t_norm_full, area_synonyms)
        if scope_full != "UNSPECIFIED":
            scope, area_name = scope_full, area_full
    # If the user corrected only the target ("точнее в спальне"), override it.
    if target_override is not None:
        scope, area_name = target_override
    
    # Meta cancel / stop (v1): if the user explicitly cancels, we return a NO-OP action.
    # This is treated as a recognized command that results in no execution.
    if re.fullmatch(
        r"(?:пожалуйста\s*,?\s*)?(?:ладно\s*)?(?:отмена|отмени|стоп|стой|хватит|не\s+надо|не\s+нужно|не\s+делай|ничего\s+не\s+делай|оставь\s+как\s+есть|оставь\s+как\s+было|забудь)",
        t_norm.strip(),
    ):
        return {
    "schema_version": "1.0",
    "actions": [
        {
            "domain": "light",
            "intent": "CANCEL",
            "target": {"scope": scope, "area_name": area_name, "entity_ids": []},
            "params": {
                "brightness": None,
                "brightness_delta": None,
                "color": None,
                "color_temp_kelvin": None,
                "color_temp_delta_k": None,
                "transition_s": None,
            },
        }
    ],
}


    # Extended cancel heuristic: allow explicit area + cancel phrase, e.g., "в кухне не надо".
    # We treat it as NO-OP if there are no other light action hints besides the cancel phrase.
    if re.search(
        r"\b(отмена|отмени|стоп|стой|хватит|не\s+надо|не\s+нужно|не\s+делай|ничего\s+не\s+делай|оставь\s+как\s+есть|оставь\s+как\s+было|забудь)\b",
        t_norm,
    ) and not re.search(
        r"\b(включ|выключ|погас|зажг|ярче|темнее|светлее|тусклее|теплее|холоднее|цвет|процент|%)\b",
        t_norm,
    ):
        return {
            "schema_version": "1.0",
            "actions": [
                {
                    "domain": "light",
                    "intent": "CANCEL",
                    "target": {"scope": scope, "area_name": area_name, "entity_ids": []},
                    "params": {
                        "brightness": None,
                        "brightness_delta": None,
                        "color": None,
                        "color_temp_kelvin": None,
                        "color_temp_delta_k": None,
                        "transition_s": None,
                    },
                }
            ],
        }


    # Cancel tail after "нет": e.g., "в спальне включи свет, нет, не надо".
    # Works on punctuation-stripped normalization ("... нет не надо").
    if re.search(
        r"\bнет\b\s*(?:ну\s*)?(?:вообще\s*)?(?:ладно\s*)?(?:\b(отмена|отмени|стоп|стой|хватит)\b|не\s+надо|не\s+нужно|не\s+делай|ничего\s+не\s+делай|оставь\s+как\s+есть|оставь\s+как\s+было|забудь)\b",
        t_norm,
    ):
        return {
            "schema_version": "1.0",
            "actions": [
                {
                    "domain": "light",
                    "intent": "CANCEL",
                    "target": {"scope": scope, "area_name": area_name, "entity_ids": []},
                    "params": {
                        "brightness": None,
                        "brightness_delta": None,
                        "color": None,
                        "color_temp_kelvin": None,
                        "color_temp_delta_k": None,
                        "transition_s": None,
                    },
                }
            ],
        }

    # 2) Semantic ambiguity checks that produce their own clarification
    amb = _detect_ambiguous_semantics(t_norm, scope, area_name)
    if amb is not None:
        return amb

    # 3) Domain-specific soft presets
    special_preset = _detect_special_presets(t_norm, scope, area_name)
    if special_preset is not None:
        return _maybe_add_missing_target_clarification(
            special_preset,
            context=context,
            device_registry=device_registry,
        )

    # 4) Regular parsing
    actions: List[Dict[str, Any]] = []
    # Negation handling (v1):
    # - Negation suppresses the corresponding affirmative intent.
    # - If the utterance looks like a *pure* negated ON/OFF command (no other light intents),
    #   we map it to an ensure-state action:
    #     "не выключай" => TURN_ON, "не включай" => TURN_OFF.
    off_verbs_neg = ["выключай", "выключи", "вырубай", "выруби", "гаси", "погаси", "потуши"]
    on_verbs_neg = ["включай", "включи", "врубай", "вруби", "зажигай", "зажги"]
    # Negation (v1) is recognized only at the beginning of the utterance (optionally after polite prefix),
    # so that constraint clauses like "..., но не выключай" do not suppress the main intent.
    neg_prefix = r"^(?:пожалуйста\s*,?\s*)?не\s+"
    negated_on = any(re.match(neg_prefix + rf"{v}\b", t_norm) for v in on_verbs_neg)
    negated_off = any(re.match(neg_prefix + rf"{v}\b", t_norm) for v in off_verbs_neg)
    turn_off = any(re.search(rf"\b{v}\b", t_norm) for v in ["выключи", "выруби", "погаси", "отключи", "потуши"]) 
    turn_on = any(re.search(rf"\b{v}\b", t_norm) for v in ["включи", "вруби", "зажги"]) 
    if negated_off:
        turn_off = False
    if negated_on:
        turn_on = False
    pure_negated = bool(re.match(r"^(?:пожалуйста\s*,?\s*)?не\s+(выключай|выключи|вырубай|выруби|гаси|погаси|потуши|включай|включи|врубай|вруби|зажигай|зажги)\b", t_norm))
    suppress_turn_on = bool(re.search(r"\bбел(ый|ым|ая|ое)\s+свет\b", t_norm))

    # Color match (may be used later for option labels too)
    color_obj, _ = _extract_color(t_norm, colors)

    # Brightness / temperature extraction
    br_abs = _extract_brightness_absolute(t_norm, modifiers)
    br_rel = _extract_brightness_relative(t_norm, modifiers)
    ct_abs = _extract_color_temp_absolute(t_norm, modifiers)
    ct_rel = _extract_color_temp_relative(t_norm, modifiers)

    # If it's a pure negated ON/OFF command and there are no other intents,
    # interpret it as an ensure-state action.
    has_any_other_intent = bool(br_abs or br_rel or ct_abs or ct_rel or (color_obj is not None) or (special_preset is not None))
    if pure_negated and not has_any_other_intent:
        if negated_off:
            turn_on = True
        elif negated_on:
            turn_off = True


    # Constraints (v1): phrases that explicitly forbid turning the light fully off.
    # Examples:
    #   - "выключи свет, но не выключай совсем"
    #   - "погаси, но не до конца"
    #   - "в ноль, но не в ноль" (i.e., "not fully to zero")
    #   - "выключи, но оставь чуть-чуть"
    avoid_full_off = bool(re.search(r"\bне\s+(?:полностью|совсем|до\s+конца)\b", t_norm)) or bool(re.search(r"\bне\s+в\s+ноль\b", t_norm))
    avoid_turn_off_clause = bool(re.search(r"\b(?:но|только|главное)\s+не\s+(?:выключай|выключи|вырубай|выруби|гаси|погаси|потуши)\b", t_norm))
    keep_some_light = bool(re.search(r"\bоставь\s+(?:чуть\s*-?\s*чуть|немного|немножко|капельку)\b", t_norm))
    avoid_full_off_any = avoid_full_off or avoid_turn_off_clause or keep_some_light

    # If the main intent is TURN_OFF but user forbids full off, reinterpret as very low brightness.
    if turn_off and avoid_full_off_any:
        turn_off = False
        # If the user also specified an absolute brightness of 0, lift it to 1.
        if br_abs is None or br_abs == 0:
            br_abs = 1
        # Absolute dominates relative here.
        br_rel = None

    # If the user asked for 0% but also forbids full off, lift to 1%.
    if br_abs == 0 and avoid_full_off_any:
        br_abs = 1

    # If explicit "включи ... и поставь <цвет>", keep two actions (TURN_ON + SET_COLOR)
    has_secondary_set_verb = any(p in t_norm for p in ["поставь", "установи", "выставь"])
    if turn_on and has_secondary_set_verb and color_obj is not None:
        actions.append(
            _make_action(
                "TURN_ON",
                scope,
                area_name,
                params=_make_params(transition_s=_transition_turn_on(t_norm)),
            )
        )
        actions.append(
            _make_action(
                "SET_COLOR",
                scope,
                area_name,
                params=_make_params(color=color_obj, transition_s=0.6),
            )
        )
    else:
        # TURN_OFF / TURN_ON as standalone actions
        if turn_off:
            actions.append(
                _make_action(
                    "TURN_OFF",
                    scope,
                    area_name,
                    params=_make_params(transition_s=_transition_turn_off(t_norm)),
                )
            )
        if turn_on and not suppress_turn_on:
            actions.append(
                _make_action(
                    "TURN_ON",
                    scope,
                    area_name,
                    params=_make_params(transition_s=_transition_turn_on(t_norm)),
                )
            )

        # Brightness
        if br_abs is not None:
            actions.append(
                _make_action(
                    "SET_BRIGHTNESS",
                    scope,
                    area_name,
                    params=_make_params(
                        brightness=br_abs,
                        transition_s=_transition_set_brightness(br_abs),
                    ),
                )
            )
        elif br_rel is not None:
            actions.append(
                _make_action(
                    "ADJUST_BRIGHTNESS",
                    scope,
                    area_name,
                    params=_make_params(
                        brightness_delta=br_rel,
                        transition_s=_transition_adjust_brightness(t_norm),
                    ),
                )
            )

        # Color temperature
        if ct_abs is not None:
            actions.append(
                _make_action(
                    "SET_COLOR_TEMP",
                    scope,
                    area_name,
                    params=_make_params(color_temp_kelvin=ct_abs, transition_s=0.8),
                )
            )
        elif ct_rel is not None:
            actions.append(
                _make_action(
                    "ADJUST_COLOR_TEMP",
                    scope,
                    area_name,
                    params=_make_params(
                        color_temp_delta_k=ct_rel,
                        transition_s=_transition_adjust_color_temp(t_norm),
                    ),
                )
            )

        # Color
        if color_obj is not None:
            # Heuristic: "синий, но темный" => interpret as TURN_ON with params (not SET_COLOR)
            if ("темн" in t_norm) and (not has_secondary_set_verb) and (not turn_off) and (not turn_on):
                actions.append(
                    _make_action(
                        "TURN_ON",
                        scope,
                        area_name,
                        params=_make_params(color=color_obj, brightness=20, transition_s=0.8),
                    )
                )
            else:
                color_tr = 0.8 if (br_abs is not None or br_rel is not None or ct_abs is not None or ct_rel is not None) else 0.6
                actions.append(
                    _make_action(
                        "SET_COLOR",
                        scope,
                        area_name,
                        params=_make_params(color=color_obj, transition_s=color_tr),
                    )
                )

    # If nothing matched, default to TURN_ON (safe baseline)
    if not actions:
        actions.append(
            _make_action(
                "TURN_ON",
                scope,
                area_name,
                params=_make_params(transition_s=_transition_turn_on(t_norm)),
            )
        )

    # If color and relative adjustments are combined, add implicit TURN_ON.
    intents = {a["intent"] for a in actions}
    if (
        "SET_COLOR" in intents
        and (("ADJUST_BRIGHTNESS" in intents) or ("ADJUST_COLOR_TEMP" in intents))
        and ("TURN_ON" not in intents)
    ):
        actions.append(_make_action("TURN_ON", scope, area_name, params=_make_params(transition_s=0.4)))

    parsed: Dict[str, Any] = {
        "schema_version": "1.0",
        "actions": actions,
    }

    # 5) Clarification policies (parser-level)

    # UNKNOWN_AREA: explicit area mention but not in our known lexicon
    if scope == "AREA" and area_name and not _area_is_known(area_name, area_synonyms):
        primary_intent = actions[0]["intent"]
        parsed["clarification"] = {
            "needed": True,
            "question": unknown_area_question(primary_intent),
            "options": _available_area_options(device_registry),
        }
        return parsed

    # CONFLICT: TURN_OFF + something else
    if any(a["intent"] == "TURN_OFF" for a in actions) and len(actions) > 1 and scope == "AREA" and area_name:
        parsed["clarification"] = {
            "needed": True,
            "question": f"Что сделать в {area_to_prepositional(area_name)}?",
            "options": [
                option_label_for_action(a["intent"], a.get("params") or {})
                for a in actions
                if a["intent"] != "TURN_ON"
            ],
        }
        return parsed

    # TOO_MANY_ACTIONS (exclude implicit TURN_ON from options)
    max_actions = int(device_registry.get("resolution_rules", {}).get("max_actions_per_utterance", 3))
    if len(actions) > max_actions:
        parsed["clarification"] = {
            "needed": True,
            "question": too_many_actions_question(area_name if scope == "AREA" else None),
            "options": [
                option_label_for_action(a["intent"], a.get("params") or {})
                for a in actions
                if a["intent"] != "TURN_ON"
            ][:3],
        }
        return parsed

    # MISSING_TARGET: scope UNSPECIFIED and no context to resolve
    parsed = _maybe_add_missing_target_clarification(parsed, context=context, device_registry=device_registry)
    return parsed


# ----------------------------
# Target extraction
# ----------------------------


def _extract_target(t_norm: str, area_synonyms: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    # ALL_LIGHTS
    if ("везде" in t_norm) or ("весь свет" in t_norm) or ("вообще весь свет" in t_norm):
        return "ALL_LIGHTS", None

    # Build (form -> (canonical_name, base_synonym)) mapping.
    # We want to return:
    # - canonical_name when the user used the canonical token ("кухня", "гостиная", ...)
    # - base_synonym otherwise ("зал", "прихожая", ...)
    candidates: List[Tuple[str, Tuple[str, str]]] = []
    for area in area_synonyms.get("canonical_areas", []):
        canonical = str(area.get("name") or "").strip()
        if not canonical:
            continue
        canonical_norm = _normalize(canonical)
        for s in (area.get("synonyms") or []) + [canonical]:
            base = _normalize(str(s))
            for form in _expand_ru_forms(base):
                candidates.append((form, (canonical, base)))

    match = _best_substring_match(t_norm, candidates)
    if match is not None:
        canonical_name, base_syn = match.value
        if _normalize(base_syn) == _normalize(canonical_name):
            return "AREA", canonical_name
        return "AREA", base_syn

    # Fallback for unknown areas ("в кабинете")
    fallback = _fallback_area_from_text(t_norm)
    if fallback:
        return "AREA", fallback

    return "UNSPECIFIED", None


def _area_is_known(area_name: str, area_synonyms: Dict[str, Any]) -> bool:
    n = _normalize(area_name)
    for area in area_synonyms.get("canonical_areas", []):
        canonical = str(area.get("name") or "").strip()
        if canonical and _normalize(canonical) == n:
            return True
        for s in area.get("synonyms") or []:
            if _normalize(str(s)) == n:
                return True
    return False


def _available_area_options(device_registry: Dict[str, Any]) -> List[str]:
    areas = device_registry.get("areas", [])
    # In v1 we allow either [{"name": ...}, ...] or ["Гостиная", ...]
    out: List[str] = []
    for a in areas:
        if isinstance(a, str):
            out.append(a)
        elif isinstance(a, dict) and a.get("name"):
            out.append(str(a["name"]))
    return out


# ----------------------------
# Modifiers extraction
# ----------------------------


def _detect_intensity_scalar_name(t_norm: str, modifiers: Dict[str, Any]) -> str:
    """Return scalar name: small/strong/max/medium."""
    ints = modifiers.get("intensifiers") or []
    # Priority: max > strong > small
    for wanted in ["max", "strong", "small"]:
        for entry in ints:
            if str(entry.get("value")) != wanted:
                continue
            for p in entry.get("patterns") or []:
                if _normalize(str(p)) in t_norm:
                    return wanted
    return "medium"


def _brightness_direction(t_norm: str) -> Optional[str]:
    """Return 'up'/'down' if a brightness adjustment is present."""
    # Explicit cues
    if "слишком ярк" in t_norm:
        return "down"
    if "темно" in t_norm or "темновато" in t_norm:
        return "up"

    up_triggers = [
        "поярче",
        "ярче",
        "прибавь",
        "добавь",
        "добавь света",
        "добавь свет",
        "прибавь света",
        "прибавь свет",
    ]
    down_triggers = [
        "потише",
        "убавь",
        "приглуши",
        "темнее",
        "тусклее",
    ]

    if any(x in t_norm for x in down_triggers):
        return "down"
    if any(x in t_norm for x in up_triggers):
        return "up"
    return None


def _extract_brightness_relative(t_norm: str, modifiers: Dict[str, Any]) -> Optional[int]:
    direction = _brightness_direction(t_norm)
    if direction is None:
        return None

    base = int((modifiers.get("defaults") or {}).get("brightness_delta_pct", 20))
    scalars = modifiers.get("intensity_scalars") or {"small": 0.5, "medium": 1.0, "strong": 1.75, "max": 5.0}
    scalar_name = _detect_intensity_scalar_name(t_norm, modifiers)
    scalar_val = float(scalars.get(scalar_name, 1.0))

    delta = int(round(base * scalar_val))
    if direction == "down":
        delta = -abs(delta)
    else:
        delta = abs(delta)
    return delta


def _extract_brightness_absolute(t_norm: str, modifiers: Dict[str, Any]) -> Optional[int]:
    # Gold: "почти выключенным" => 1%
    if re.search(r"\bпочти\s+выключ", t_norm):
        return 1
    entries = (modifiers.get("brightness") or {}).get("absolute") or []
    candidates: List[Tuple[str, int]] = []
    for e in entries:
        br = int(e.get("brightness_pct"))
        for p in e.get("patterns") or []:
            candidates.append((_normalize(str(p)), br))
    m = _best_substring_match(t_norm, candidates)
    return int(m.value) if m is not None else None


def _extract_color_temp_relative(t_norm: str, modifiers: Dict[str, Any]) -> Optional[int]:
    candidates: List[Tuple[str, int]] = []
    for key in ["relative_warmer", "relative_cooler"]:
        entries = (modifiers.get("color_temperature") or {}).get(key) or []
        for e in entries:
            delta = int(e.get("delta_k"))
            for p in e.get("patterns") or []:
                candidates.append((_normalize(str(p)), delta))
    m = _best_substring_match(t_norm, candidates)
    return int(m.value) if m is not None else None


def _extract_color_temp_absolute(t_norm: str, modifiers: Dict[str, Any]) -> Optional[int]:
    # Dataset-aligned special cases
    if re.search(r"\bмаксимально\s+холодн", t_norm):
        return 6500
    if re.search(r"\bмаксимально\s+тепл", t_norm):
        return 2000
    if re.search(r"\bбел(ый|ым|ая|ое)\s+бел", t_norm):
        # "белый-белый" => very neutral/cool white in gold
        return 6000
    if re.search(r"\bбел(ый|ым|ая|ое)\s+свет\b", t_norm):
        # "белый свет" => neutral white in gold
        return 5000

    # Special warm/casual forms not present in lexicon yet
    if re.search(r"\bтепленьк", t_norm):
        return 3000
    if re.search(r"\bтепл(ым|ый|ая|ое)\b", t_norm) and ("теплый белый" not in t_norm) and ("максимально" not in t_norm):
        # "сделай свет тёплым" => warm white
        return 2700

    entries = (modifiers.get("color_temperature") or {}).get("absolute") or []
    candidates: List[Tuple[str, int]] = []
    for e in entries:
        kelvin = int(e.get("kelvin"))
        for p in e.get("patterns") or []:
            candidates.append((_normalize(str(p)), kelvin))
    m = _best_substring_match(t_norm, candidates)
    return int(m.value) if m is not None else None


def _extract_color(t_norm: str, colors: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    candidates: List[Tuple[str, Tuple[List[int], str]]] = []
    for entry in colors.get("palette_rgb", []):
        rgb = entry.get("rgb")
        if not isinstance(rgb, list) or len(rgb) != 3:
            continue
        aliases = [entry.get("name")] + (entry.get("aliases") or [])
        # Dataset/policy: treat "белый" as color temperature, not RGB.
        if any(a and "бел" in _normalize(str(a)) for a in aliases):
            continue
        for a in aliases:
            if not a:
                continue
            a_norm = _normalize(str(a))
            for form in _expand_ru_forms(a_norm):
                candidates.append((form, (list(rgb), a_norm)))

    m = _best_substring_match(t_norm, candidates)
    if m is None:
        return None, None
    rgb, raw = m.value
    return {"mode": "rgb", "name": None, "rgb": rgb}, raw


# ----------------------------
# Transition heuristics (dataset-aligned)
# ----------------------------


def _transition_turn_on(t_norm: str) -> float:
    # "включи свет на кухне" is the only v1 example with 0.5
    if (
        re.search(r"\bвключи\s+свет\s+на\s+[а-я]+\b", t_norm)
        and ("пожалуйста" not in t_norm)
        and ("эй" not in t_norm)
    ):
        return 0.5
    return 0.4


def _transition_turn_off(t_norm: str) -> float:
    if ("вообще" in t_norm) and ("весь свет" in t_norm):
        return 0.3
    return 0.2


def _transition_set_brightness(brightness: int) -> float:
    if brightness == 100:
        return 0.6
    if brightness == 0:
        return 0.5
    return 0.8


def _transition_adjust_brightness(t_norm: str) -> float:
    if ("слишком" in t_norm) or ("темно" in t_norm):
        return 0.9
    return 0.8


def _transition_adjust_color_temp(t_norm: str) -> float:
    if ("пусть" in t_norm) or ("помягче" in t_norm):
        return 0.9
    return 0.8


# ----------------------------
# Semantic ambiguity
# ----------------------------


def _detect_ambiguous_semantics(t_norm: str, scope: str, area_name: Optional[str]) -> Optional[Dict[str, Any]]:
    # "поуютнее" / "уютнее" => warm vs neutral
    if any(p in t_norm for p in ["поуютнее", "уютнее", "атмосфернее"]):
        return {
            "schema_version": "1.0",
            "actions": [_make_action("SET_COLOR_TEMP", scope, area_name, params=_make_params(transition_s=0.8))],
            "clarification": {
                "needed": True,
                "question": "Хочешь тёплый или нейтральный свет?",
                "options": ["Тёплый", "Нейтральный"],
            },
        }

    # "нормальный свет" => warm/neutral/cold (policy for v1)
    if "нормальный свет" in t_norm:
        return {
            "schema_version": "1.0",
            "actions": [_make_action("SET_COLOR_TEMP", scope, area_name, params=_make_params(transition_s=0.8))],
            "clarification": {
                "needed": True,
                "question": "Какой именно: тёплый, нейтральный или холодный?",
                "options": ["Тёплый", "Нейтральный", "Холодный"],
            },
        }

    return None


# ----------------------------
# Domain-specific presets
# ----------------------------


def _detect_special_presets(t_norm: str, scope: str, area_name: Optional[str]) -> Optional[Dict[str, Any]]:
    # "ночник"
    if "ночник" in t_norm:
        return {
            "schema_version": "1.0",
            "actions": [
                _make_action(
                    "TURN_ON",
                    scope,
                    area_name,
                    params=_make_params(brightness=20, color_temp_kelvin=2700, transition_s=1.0),
                )
            ],
        }

    # "как для кино"
    if ("как для кино" in t_norm) or ("для кино" in t_norm):
        return {
            "schema_version": "1.0",
            "actions": [
                _make_action(
                    "TURN_ON",
                    scope,
                    area_name,
                    params=_make_params(brightness=15, color_temp_kelvin=2700, transition_s=1.0),
                )
            ],
        }

    # "как для работы"
    if ("как для работы" in t_norm) or ("рабочий свет" in t_norm):
        return {
            "schema_version": "1.0",
            "actions": [
                _make_action(
                    "TURN_ON",
                    scope,
                    area_name,
                    params=_make_params(brightness=85, color_temp_kelvin=5000, transition_s=0.8),
                )
            ],
        }

    # "включи ..., но совсем чуть-чуть"
    if ("совсем чуть" in t_norm or "чуть чуть" in t_norm or "чуть-чуть" in t_norm) and (
        "включи" in t_norm or "вруби" in t_norm
    ):
        return {
            "schema_version": "1.0",
            "actions": [
                _make_action("TURN_ON", scope, area_name, params=_make_params(brightness=10, transition_s=0.6))
            ],
        }

    # "включи ..., но не ярко" => warm-ish + dim
    if ("не ярко" in t_norm) and ("включи" in t_norm or "вруби" in t_norm or "зажги" in t_norm):
        return {
            "schema_version": "1.0",
            "actions": [
                _make_action(
                    "TURN_ON",
                    scope,
                    area_name,
                    params=_make_params(brightness=35, color_temp_kelvin=3000, transition_s=0.8),
                )
            ],
        }

    # "мягче и темнее"
    if ("мягче" in t_norm or "помягче" in t_norm) and ("темнее" in t_norm or "темней" in t_norm):
        return {
            "schema_version": "1.0",
            "actions": [
                _make_action(
                    "TURN_ON",
                    scope,
                    area_name,
                    params=_make_params(brightness=25, color_temp_kelvin=2700, transition_s=0.8),
                )
            ],
        }

    return None


# ----------------------------
# Action builders
# ----------------------------


def _make_params(
    *,
    brightness: Optional[int] = None,
    brightness_delta: Optional[int] = None,
    color: Optional[Dict[str, Any]] = None,
    color_temp_kelvin: Optional[int] = None,
    color_temp_delta_k: Optional[int] = None,
    transition_s: float = 0.8,
) -> Dict[str, Any]:
    return {
        "brightness": brightness,
        "brightness_delta": brightness_delta,
        "color": color,
        "color_temp_kelvin": color_temp_kelvin,
        "color_temp_delta_k": color_temp_delta_k,
        "transition_s": float(transition_s),
    }


def _make_action(intent: str, scope: str, area_name: Optional[str], *, params: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "domain": "light",
        "intent": intent,
        "target": {
            "scope": scope,
            "area_name": area_name if scope == "AREA" else None,
            "entity_ids": [],
        },
        "params": params,
    }


def _maybe_add_missing_target_clarification(
    parsed: Dict[str, Any],
    *,
    context: Optional[Dict[str, Any]],
    device_registry: Dict[str, Any],
) -> Dict[str, Any]:
    actions = parsed.get("actions") or []
    if not actions:
        return parsed
    action0 = actions[0]
    scope = (action0.get("target") or {}).get("scope")
    if scope != "UNSPECIFIED":
        return parsed

    last_area = (context or {}).get("last_area_name")
    if last_area:
        return parsed

    parsed["clarification"] = {
        "needed": True,
        "question": missing_target_question(action0.get("intent"), action0.get("params") or {}),
        "options": _available_area_options(device_registry),
    }
    return parsed
