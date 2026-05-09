import random
import string
from pathlib import Path

import pytest

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json
from smarthome_core.parser import parse_light_command_v1
from smarthome_core.schema_utils import load_schema, validate_with_schema


@pytest.fixture(scope="session")
def paths() -> AssetPaths:
    return AssetPaths(Path(__file__).resolve().parents[1])


def _rand_text(rng: random.Random, n: int) -> str:
    alphabet = string.ascii_letters + string.digits + " абвгдеёжзийклмнопрстуфхцчшщъыьэюя!?.,;:-_%/()"
    return "".join(rng.choice(alphabet) for _ in range(n))


def test_parser_never_crashes_and_respects_invariants(paths: AssetPaths) -> None:
    rng = random.Random(0)

    device_registry = load_json(paths.device_registry)
    area_synonyms = load_json(paths.area_synonyms)
    colors = load_json(paths.colors)
    modifiers = load_json(paths.modifiers)
    parsed_schema = load_schema(paths.parsed_schema)

    max_actions = int(device_registry.get("limits", {}).get("max_actions_per_utterance", 5))

    for _ in range(300):
        text = _rand_text(rng, rng.randint(0, 200)).strip()
        out = parse_light_command_v1(
            text,
            context={"last_area_name": None},
            device_registry=device_registry,
            area_synonyms=area_synonyms,
            colors=colors,
            modifiers=modifiers,
        )
        # Must be schema-valid
        validate_with_schema(out, parsed_schema)
        # Must not exceed limits
        assert len(out.get("actions", [])) <= max_actions
