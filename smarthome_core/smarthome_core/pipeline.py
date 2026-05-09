"""High-level pipeline API (text -> parsed -> validated).

This is the intended integration point for the mobile app / ASR output.
The core module remains UI/framework-agnostic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, Union

from .assets import AssetPaths
from .io import load_json
from .parse_dispatch import parse_light_command_v1_dispatch
from .validator import validate_parsed_command


@dataclass(frozen=True)
class PipelineResult:
    """Wrapper result for app-friendly integration."""

    stage: str  # "PARSED_CLARIFICATION" | "VALIDATED"
    parsed: Dict[str, Any]
    validated: Optional[Dict[str, Any]]


def run_light_pipeline_v1(
    text: str,
    *,
    context: Optional[Dict[str, Any]] = None,
    root_dir: Optional[Union[str, Path]] = None,
    device_registry: Optional[Dict[str, Any]] = None,
    area_synonyms: Optional[Dict[str, Any]] = None,
    colors: Optional[Dict[str, Any]] = None,
    modifiers: Optional[Dict[str, Any]] = None,
    scene_aliases: Optional[Dict[str, Any]] = None,
    parser_mode: str = "rules",
    llm_client: Optional[Any] = None,
    parsed_schema: Optional[Dict[str, Any]] = None,
) -> PipelineResult:
    """Run the v1 pipeline for light commands.

    parser_mode:
      - "rules" (baseline robust rules)
      - "llm_safe" (rules first, then LLM only when rules are insufficient)
      - "llm" (LLM only, useful for evaluation)

    Args:
        text: user utterance (text, typically from ASR)
        context: e.g. {"selected_area_name": "кухня", "last_area_name": "кухня"}
        root_dir: project root if assets should be loaded from disk
        device_registry/area_synonyms/colors/modifiers: preloaded assets
        llm_client: LLM client implementation (required for llm_* modes)
        parsed_schema: ParsedCommand schema dict (required for llm_* modes if you want in-parser validation)

    Returns:
        PipelineResult(stage, parsed, validated|None)
    """
    ctx = context or {"selected_area_name": None, "last_area_name": None}

    if (
        device_registry is None
        or area_synonyms is None
        or colors is None
        or modifiers is None
        or scene_aliases is None
    ):
        paths = AssetPaths(Path(root_dir) if root_dir is not None else Path(__file__).resolve().parents[1])
        device_registry = device_registry or load_json(paths.device_registry)
        area_synonyms = area_synonyms or load_json(paths.area_synonyms)
        colors = colors or load_json(paths.colors)
        modifiers = modifiers or load_json(paths.modifiers)
        scene_aliases = scene_aliases or load_json(paths.scene_aliases)

        # Parsed schema is needed only for llm_* modes; load lazily.
        if parsed_schema is None and parser_mode.strip().lower() in {"llm_safe", "llm"}:
            from .schema_utils import load_schema
            parsed_schema = load_schema(paths.parsed_schema)

    parsed = parse_light_command_v1_dispatch(
        text,
        parser_mode=parser_mode,
        context=ctx,
        device_registry=device_registry,
        area_synonyms=area_synonyms,
        colors=colors,
        modifiers=modifiers,
        scene_aliases=scene_aliases,
        parsed_schema=parsed_schema,
        llm_client=llm_client,
    )

    if parsed.get("clarification") is not None:
        return PipelineResult(stage="PARSED_CLARIFICATION", parsed=parsed, validated=None)

    validated = validate_parsed_command(
        parsed,
        context=ctx,
        device_registry=device_registry,
        area_synonyms=area_synonyms,
    )
    return PipelineResult(stage="VALIDATED", parsed=parsed, validated=validated)
