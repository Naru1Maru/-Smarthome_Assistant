from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json, write_jsonl
from smarthome_core.schema_utils import load_schema, validate_with_schema
from smarthome_core.validator import validate_parsed_command


AREAS = ["Спальня", "Кухня", "Гостиная", "Коридор", "Ванная"]
AREA_LOC = {
    "Спальня": "в спальне",
    "Кухня": "на кухне",
    "Гостиная": "в гостиной",
    "Коридор": "в коридоре",
    "Ванная": "в ванной",
}

COLORS = {
    "красным": [255, 0, 0],
    "синим": [0, 80, 255],
    "зеленым": [0, 200, 80],
    "фиолетовым": [160, 60, 255],
    "оранжевым": [255, 120, 0],
}

TEMP_ALIASES = {
    "тёплым белым": 2700,
    "нейтральным белым": 4000,
    "дневным белым": 5000,
    "холодным белым": 6000,
    "ламповым": 2700,
}


def _params(
    *,
    transition_s: float,
    brightness: int | None = None,
    brightness_delta: int | None = None,
    color_rgb: list[int] | None = None,
    color_temp_kelvin: int | None = None,
    color_temp_delta_k: int | None = None,
) -> dict[str, Any]:
    color = None
    if color_rgb is not None:
        color = {"mode": "rgb", "name": None, "rgb": color_rgb}
    return {
        "brightness": brightness,
        "brightness_delta": brightness_delta,
        "color": color,
        "color_temp_kelvin": color_temp_kelvin,
        "color_temp_delta_k": color_temp_delta_k,
        "transition_s": transition_s,
    }


def _action(
    *,
    intent: str,
    area_name: str,
    params: dict[str, Any],
) -> dict[str, Any]:
    return {
        "domain": "light",
        "intent": intent,
        "target": {
            "scope": "AREA",
            "area_name": area_name,
            "entity_ids": [],
        },
        "params": params,
    }


def _record(
    *,
    rec_id: str,
    text: str,
    area_name: str,
    category: str,
    style: str,
    action: dict[str, Any],
    device_registry: dict[str, Any],
    area_synonyms: dict[str, Any],
    parsed_schema: dict[str, Any],
    validated_schema: dict[str, Any],
) -> dict[str, Any]:
    context = {"last_area_name": None}
    expected_parsed = {"schema_version": "1.0", "actions": [action]}
    validate_with_schema(expected_parsed, parsed_schema)
    expected_validated = validate_parsed_command(
        expected_parsed,
        context=context,
        device_registry=device_registry,
        area_synonyms=area_synonyms,
    )
    validate_with_schema(expected_validated, validated_schema)
    return {
        "id": rec_id,
        "text": text,
        "context": context,
        "tags": [
            f"style:{style}",
            f"category:{category}",
            f"room:{area_name}",
            f"intent:{action['intent']}",
        ],
        "expected_parsed": expected_parsed,
        "expected_validated": expected_validated,
    }


def _build_semantics() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []

    # 1) TURN_ON (6)
    turn_on_creative = [
        "В спальне темновато, добавь там света.",
        "На кухне мрачновато, давай посветлее.",
        "Хочу, чтобы в гостиной стало светло.",
        "В коридоре ничего не видно, подсвети его.",
        "Сделай в ванной наконец-то светло.",
        "Верни свет в спальню, пожалуйста.",
    ]
    for i, area in enumerate(["Спальня", "Кухня", "Гостиная", "Коридор", "Ванная", "Спальня"], start=1):
        loc = AREA_LOC[area]
        rows.append(
            {
                "category": "turn_on_simple",
                "area": area,
                "action": _action(intent="TURN_ON", area_name=area, params=_params(transition_s=0.5)),
                "direct": f"Включи свет {loc}",
                "creative": turn_on_creative[i - 1],
            }
        )

    # 2) TURN_OFF (6)
    turn_off_creative = [
        "В гостиной уже хватит света, затемни её.",
        "На кухне можно выключаться, погаси там свет.",
        "В спальне пора в темноту, убери освещение.",
        "В коридоре свет не нужен, пусть будет темно.",
        "В ванной свет лишний, вырубай.",
        "В гостиной давай без освещения.",
    ]
    for i, area in enumerate(["Гостиная", "Кухня", "Спальня", "Коридор", "Ванная", "Гостиная"], start=1):
        loc = AREA_LOC[area]
        rows.append(
            {
                "category": "turn_off_simple",
                "area": area,
                "action": _action(intent="TURN_OFF", area_name=area, params=_params(transition_s=0.2)),
                "direct": f"Выключи свет {loc}",
                "creative": turn_off_creative[i - 1],
            }
        )

    # 3) SET_BRIGHTNESS (6)
    set_brightness_creative = [
        "В спальне сделай спокойные 20% яркости.",
        "На кухне поставь свет примерно на 35%.",
        "В гостиной оставь средний свет, около 50%.",
        "В коридоре подними яркость до 65%.",
        "В ванной сделай поярче, около 80%.",
        "В спальне нужен умеренный свет: примерно 45%.",
    ]
    for i, (area, value) in enumerate(
        zip(["Спальня", "Кухня", "Гостиная", "Коридор", "Ванная", "Спальня"], [20, 35, 50, 65, 80, 45]),
        start=1,
    ):
        loc = AREA_LOC[area]
        rows.append(
            {
                "category": "set_brightness_abs",
                "area": area,
                "action": _action(
                    intent="SET_BRIGHTNESS",
                    area_name=area,
                    params=_params(transition_s=0.7, brightness=value),
                ),
                "direct": f"Поставь яркость {loc} на {value}%",
                "creative": set_brightness_creative[i - 1],
            }
        )

    # 4) ADJUST_BRIGHTNESS (6)
    adjust_brightness_creative = [
        "На кухне добавь света чуть-чуть, процентов на 15.",
        "В спальне сделай заметно ярче, примерно на 25%.",
        "В гостиной приглуши свет где-то на 20%.",
        "В коридоре убавь яркость примерно на 30%.",
        "В ванной добавь немного света, около 10%.",
        "На кухне сделай на 15% тусклее.",
    ]
    for i, (area, delta) in enumerate(
        zip(["Кухня", "Спальня", "Гостиная", "Коридор", "Ванная", "Кухня"], [15, 25, -20, -30, 10, -15]),
        start=1,
    ):
        loc = AREA_LOC[area]
        if delta > 0:
            direct = f"Сделай свет {loc} ярче на {delta}%"
        else:
            direct = f"Сделай свет {loc} тусклее на {abs(delta)}%"
        rows.append(
            {
                "category": "adjust_brightness_delta",
                "area": area,
                "action": _action(
                    intent="ADJUST_BRIGHTNESS",
                    area_name=area,
                    params=_params(transition_s=0.7, brightness_delta=delta),
                ),
                "direct": direct,
                "creative": adjust_brightness_creative[i - 1],
            }
        )

    # 5) SET_COLOR (5)
    set_color_creative = [
        "Хочу в гостиной красный акцент в освещении.",
        "Сделай в спальне мягкий синий свет.",
        "На кухне нужен зеленоватый оттенок света.",
        "В ванной сделай свет фиолетовым, понастроению.",
        "В коридоре добавь оранжевый оттенок.",
    ]
    for i, (area, color_name) in enumerate(
        zip(["Гостиная", "Спальня", "Кухня", "Ванная", "Коридор"], list(COLORS.keys())),
        start=1,
    ):
        loc = AREA_LOC[area]
        rgb = COLORS[color_name]
        rows.append(
            {
                "category": "set_color_rgb",
                "area": area,
                "action": _action(
                    intent="SET_COLOR",
                    area_name=area,
                    params=_params(transition_s=0.6, color_rgb=rgb),
                ),
                "direct": f"Сделай свет {loc} {color_name}",
                "creative": set_color_creative[i - 1],
            }
        )

    # 6) SET_COLOR_TEMP (5)
    set_temp_creative = [
        "В спальне сделай свет теплым, как лампа накаливания.",
        "На кухне поставь нейтральный белый без желтизны.",
        "В гостиной включи дневной рабочий оттенок света.",
        "В ванной нужен холодный белый.",
        "В коридоре сделай ламповый уютный свет.",
    ]
    for i, (area, temp_name) in enumerate(
        zip(["Спальня", "Кухня", "Гостиная", "Ванная", "Коридор"], list(TEMP_ALIASES.keys())),
        start=1,
    ):
        loc = AREA_LOC[area]
        kelvin = TEMP_ALIASES[temp_name]
        rows.append(
            {
                "category": "set_color_temp_abs",
                "area": area,
                "action": _action(
                    intent="SET_COLOR_TEMP",
                    area_name=area,
                    params=_params(transition_s=0.8, color_temp_kelvin=kelvin),
                ),
                "direct": f"Сделай свет {loc} {temp_name}",
                "creative": set_temp_creative[i - 1],
            }
        )

    # 7) ADJUST_COLOR_TEMP (4)
    adjust_temp_creative = [
        "На кухне сдвинь оттенок света чуть теплее.",
        "В спальне сделай свет немного холоднее.",
        "В гостиной уведи свет в более мягкий теплый тон.",
        "В ванной сделай оттенок белее и прохладнее.",
    ]
    for i, (area, delta, phrase) in enumerate(
        [
        ("Кухня", -800, "теплее"),
        ("Спальня", 800, "холоднее"),
        ("Гостиная", -800, "помягче"),
        ("Ванная", 800, "побелее"),
        ],
        start=1,
    ):
        loc = AREA_LOC[area]
        rows.append(
            {
                "category": "adjust_color_temp_delta",
                "area": area,
                "action": _action(
                    intent="ADJUST_COLOR_TEMP",
                    area_name=area,
                    params=_params(transition_s=0.8, color_temp_delta_k=delta),
                ),
                "direct": f"Сделай свет {loc} {phrase}",
                "creative": adjust_temp_creative[i - 1],
            }
        )

    # 8) COMBINED TURN_ON + BRIGHTNESS + COLOR (6)
    combo_color = [
        ("Спальня", "фиолетовым", 35),
        ("Кухня", "оранжевым", 45),
        ("Гостиная", "синим", 40),
        ("Коридор", "зеленым", 30),
        ("Ванная", "красным", 25),
        ("Спальня", "оранжевым", 50),
    ]
    combo_color_creative = [
        "В спальне сделай фиолетовую подсветку и приглуши до 35%.",
        "На кухне хочу оранжевый свет, яркость около 45%.",
        "В гостиной дай синий оттенок и держи яркость на 40%.",
        "В коридоре сделай зелёный свет и примерно 30% яркости.",
        "В ванной нужен красный, но очень мягкий свет: 25%.",
        "В спальне оставь оранжевый оттенок и около 50% яркости.",
    ]
    for i, (area, color_name, brightness) in enumerate(combo_color, start=1):
        loc = AREA_LOC[area]
        rows.append(
            {
                "category": "combined_turn_on_color_brightness",
                "area": area,
                "action": _action(
                    intent="TURN_ON",
                    area_name=area,
                    params=_params(
                        transition_s=1.0,
                        brightness=brightness,
                        color_rgb=COLORS[color_name],
                    ),
                ),
                "direct": f"Включи свет {loc} на {brightness}% и сделай его {color_name}",
                "creative": combo_color_creative[i - 1],
            }
        )

    # 9) COMBINED TURN_ON + BRIGHTNESS + COLOR_TEMP (6)
    combo_temp = [
        ("Кухня", "тёплым белым", 55),
        ("Спальня", "холодным белым", 60),
        ("Гостиная", "нейтральным белым", 45),
        ("Коридор", "дневным белым", 50),
        ("Ванная", "тёплым белым", 35),
        ("Гостиная", "ламповым", 40),
    ]
    combo_temp_creative = [
        "На кухне хочу теплый мягкий свет около 55% яркости.",
        "В спальне сделай прохладный свет и яркость примерно 60%.",
        "В гостиной нужен нейтральный свет, где-то 45%.",
        "В коридоре поставь дневной белый и около 50% яркости.",
        "В ванной сделай уютный теплый свет на уровне 35%.",
        "В гостиной пусть будет ламповый тон и около 40% яркости.",
    ]
    for i, (area, temp_name, brightness) in enumerate(combo_temp, start=1):
        loc = AREA_LOC[area]
        rows.append(
            {
                "category": "combined_turn_on_temp_brightness",
                "area": area,
                "action": _action(
                    intent="TURN_ON",
                    area_name=area,
                    params=_params(
                        transition_s=1.0,
                        brightness=brightness,
                        color_temp_kelvin=TEMP_ALIASES[temp_name],
                    ),
                ),
                "direct": f"Включи свет {loc} на {brightness}% и сделай его {temp_name}",
                "creative": combo_temp_creative[i - 1],
            }
        )

    if len(rows) != 50:
        raise RuntimeError(f"Expected 50 semantic rows, got {len(rows)}")
    return rows


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    paths = AssetPaths(root)

    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    parsed_schema = load_schema(paths.parsed_schema)
    validated_schema = load_schema(paths.validated_schema)

    semantics = _build_semantics()
    records_all: list[dict[str, Any]] = []
    records_direct: list[dict[str, Any]] = []
    records_creative: list[dict[str, Any]] = []

    for idx, row in enumerate(semantics, start=1):
        direct = _record(
            rec_id=f"D{idx:03d}",
            text=row["direct"],
            area_name=row["area"],
            category=row["category"],
            style="direct",
            action=row["action"],
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            parsed_schema=parsed_schema,
            validated_schema=validated_schema,
        )
        creative = _record(
            rec_id=f"C{idx:03d}",
            text=row["creative"],
            area_name=row["area"],
            category=row["category"],
            style="creative",
            action=row["action"],
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            parsed_schema=parsed_schema,
            validated_schema=validated_schema,
        )
        records_direct.append(direct)
        records_creative.append(creative)
        records_all.extend([direct, creative])

    out_all = root / "data" / "light_gold_eval100_ru_v1.jsonl"
    out_direct = root / "data" / "light_gold_eval100_ru_v1_direct.jsonl"
    out_creative = root / "data" / "light_gold_eval100_ru_v1_creative.jsonl"

    write_jsonl(out_all, records_all)
    write_jsonl(out_direct, records_direct)
    write_jsonl(out_creative, records_creative)

    summary = {
        "dataset": str(out_all),
        "total": len(records_all),
        "direct": len(records_direct),
        "creative": len(records_creative),
    }
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
