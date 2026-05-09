"""Text templates used by the validator to build clarification prompts/options.

The goal is NOT to be linguistically perfect, but to be:
- deterministic
- minimal (policy: ask only when required)
- stable for evaluation
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


_AREA_PREP = {
    "Гостиная": "гостиной",
    "Кухня": "кухне",
    "Спальня": "спальне",
    "Коридор": "коридоре",
    "Ванная": "ванной",
}


def area_to_prepositional(area_name: str) -> str:
    """Return prepositional form used in prompts: 'в спальне', 'в гостиной', ..."""
    return _AREA_PREP.get(area_name, area_name.lower())


def missing_target_question(action_intent: str, params: Dict[str, Any]) -> str:
    """Build question for MISSING_TARGET."""
    if action_intent == "ADJUST_BRIGHTNESS":
        delta = params.get("brightness_delta")
        if isinstance(delta, (int, float)) and delta < 0:
            return "Где сделать свет потише?"
        return "Где сделать свет поярче?"
    if action_intent == "ADJUST_COLOR_TEMP":
        delta = params.get("color_temp_delta_k")
        if isinstance(delta, (int, float)) and delta > 0:
            return "Где сделать свет белее?"
        return "Где сделать свет теплее?"
    if action_intent == "SET_COLOR_TEMP":
        kelvin = params.get("color_temp_kelvin")
        if isinstance(kelvin, (int, float)) and kelvin <= 3000:
            return "Где сделать свет тёплым?"
        if isinstance(kelvin, (int, float)) and kelvin >= 5500:
            return "Где сделать свет холодным?"
        return "Где сделать свет белым?"
    if action_intent == "TURN_ON":
        return "Где включить свет?"
    if action_intent == "TURN_OFF":
        return "Где выключить свет?"
    return "Где выполнить команду со светом?"


def unknown_area_question(action_intent: str) -> str:
    """Build question for UNKNOWN_AREA."""
    if action_intent == "TURN_ON":
        return "Такой комнаты не вижу. Где включить свет?"
    if action_intent == "TURN_OFF":
        return "Такой комнаты не вижу. Где выключить свет?"
    return "Такой комнаты не вижу. Где выполнить команду?"


def too_many_actions_question(area_name: Optional[str]) -> str:
    """Build question for TOO_MANY_ACTIONS."""
    if area_name:
        return f"Что сделать в {area_to_prepositional(area_name)} сейчас?"
    return "Что сделать сейчас?"


def option_label_for_action(action_intent: str, params: Dict[str, Any]) -> str:
    """Human option label for a single action (for clarification UI)."""
    if action_intent == "TURN_OFF":
        return "Выключить свет"
    if action_intent == "TURN_ON":
        return "Включить свет"
    if action_intent == "ADJUST_BRIGHTNESS":
        delta = params.get("brightness_delta")
        if isinstance(delta, (int, float)) and delta < 0:
            return "Сделать потише"
        return "Сделать ярче"
    if action_intent == "SET_BRIGHTNESS":
        b = params.get("brightness")
        if b == 100:
            return "Сделать максимум"
        if b == 1:
            return "Сделать почти выключенным"
        if isinstance(b, (int, float)):
            return f"Поставить {int(b)}%"
        return "Поставить яркость"
    if action_intent == "ADJUST_COLOR_TEMP":
        delta = params.get("color_temp_delta_k")
        if isinstance(delta, (int, float)) and delta < 0:
            return "Сделать теплее"
        return "Сделать белее"
    if action_intent == "SET_COLOR_TEMP":
        kelvin = params.get("color_temp_kelvin")
        if isinstance(kelvin, (int, float)) and kelvin <= 3000:
            return "Сделать тёплый"
        if isinstance(kelvin, (int, float)) and kelvin >= 5500:
            return "Сделать холодный"
        return "Сделать белый"
    if action_intent == "SET_COLOR":
        # Params contain a structured color object: {"rgb":[r,g,b], ...}
        c = params.get("color") or {}
        rgb = c.get("rgb")
        if rgb == [0, 80, 255]:
            return "Поставить синий"
        if rgb == [255, 0, 0]:
            return "Поставить красный"
        if rgb == [0, 200, 80]:
            return "Поставить зелёный"
        if rgb == [160, 60, 255]:
            return "Поставить фиолетовый"
        if rgb == [255, 80, 180]:
            return "Поставить розовый"
        if rgb == [0, 160, 255]:
            return "Поставить голубой"
        return "Поставить цвет"
    return "Выполнить действие"
