"""Core engine (parser-agnostic) for Smart Home NLU.

This package provides:
- JSON schema validation helpers (Draft 2020-12)
- Deterministic validator: ParsedCommand -> ValidatedCommand
- Execution plan builder for Home Assistant (dry-run)
"""

from .assets import AssetPaths
from .io import load_json, load_jsonl
from .schema_utils import validate_with_schema
from .validator import validate_parsed_command
from .privacy import redact_text
from .parser import parse_light_command_v1
from .pipeline import run_light_pipeline_v1, PipelineResult

__all__ = [
    "AssetPaths",
    "load_json",
    "load_jsonl",
    "validate_with_schema",
    "validate_parsed_command",
    "parse_light_command_v1",
    "run_light_pipeline_v1",
    "PipelineResult",
    "redact_text",
]

from .executor_ha import execute_validated_on_ha, build_service_calls_from_validated, ExecutionConfig, ExecutionResult
from .ha_client import HomeAssistantClient, HomeAssistantError
