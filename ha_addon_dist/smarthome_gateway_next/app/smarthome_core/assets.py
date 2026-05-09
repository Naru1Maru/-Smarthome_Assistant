"""Asset paths for the project structure.

The core engine is app-agnostic, but it needs access to:
- Schemas (ParsedCommand, ValidatedCommand)
- Device registry (areas, HA config, policies)
- Lexicon (area synonyms, colors, modifiers)
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AssetPaths:
    """Convenience paths for this repo layout.

    You can override these in your app / scripts as needed.
    """

    root: Path

    @property
    def schemas_dir(self) -> Path:
        return self.root / "schemas"

    @property
    def lexicon_dir(self) -> Path:
        return self.root / "lexicon"

    @property
    def registry_dir(self) -> Path:
        return self.root / "registry"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def parsed_schema(self) -> Path:
        return self.schemas_dir / "parsed_command_v1.schema.json"

    @property
    def validated_schema(self) -> Path:
        return self.schemas_dir / "validated_command_v1.schema.json"

    @property
    def scenario_bundle_schema(self) -> Path:
        return self.schemas_dir / "scenario_bundle_v1.schema.json"

    @property
    def device_registry(self) -> Path:
        return self.registry_dir / "device_registry_v1.json"

    @property
    def area_synonyms(self) -> Path:
        return self.lexicon_dir / "area_synonyms_v1.json"

    @property
    def colors(self) -> Path:
        return self.lexicon_dir / "colors_v1.json"

    @property
    def modifiers(self) -> Path:
        return self.lexicon_dir / "modifiers_v1.json"

    @property
    def scene_aliases(self) -> Path:
        return self.lexicon_dir / "scene_aliases_v1.json"

    @property
    def gold_dataset(self) -> Path:
        return self.data_dir / "light_gold_dual_v1.jsonl"
