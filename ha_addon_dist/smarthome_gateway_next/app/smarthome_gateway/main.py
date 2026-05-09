from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Literal

from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse


class UTF8JSONResponse(JSONResponse):
    media_type = "application/json; charset=utf-8"
from pydantic import BaseModel, ConfigDict, Field

# Ensure project root is on sys.path so `import smarthome_core` works
_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from smarthome_core.assets import AssetPaths
from smarthome_core.io import load_json
from smarthome_core.pipeline import run_light_pipeline_v1
from smarthome_core.privacy import redact_text, should_log_raw_text, get_redaction_mode
from smarthome_core.ha_client import HomeAssistantClient
from smarthome_core.executor_ha import execute_validated_on_ha, ExecutionConfig, build_service_calls_from_validated
from smarthome_core.llm_client import LLMCallInfo, OpenAICompatibleClient
from smarthome_core.scenario_llm import run_scenario_authoring_pipeline_v1


ParserMode = Literal["rules", "llm_safe", "llm"]


class CommandContext(BaseModel):
    selected_area_name: Optional[str] = None
    last_area_name: Optional[str] = None
    last_entity_ids: list[str] = Field(default_factory=list)
    last_color_name: Optional[str] = None
    last_brightness: Optional[int] = Field(default=None, ge=0, le=100)
    last_color_temp_kelvin: Optional[int] = Field(default=None, ge=1500, le=6500)
    pending_clarification_slot: Optional[str] = None


class CommandRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    parser_mode: ParserMode = "rules"
    dry_run: bool = False
    context: Optional[CommandContext] = None
    request_id: Optional[str] = None


class QuickActionTargetRequest(BaseModel):
    area_name: Optional[str] = None
    device_type: str = Field(..., min_length=1, max_length=64)
    device_id: Optional[str] = None


class QuickActionRequest(BaseModel):
    action_id: str = Field(..., min_length=1, max_length=64)
    dry_run: bool = False
    target: QuickActionTargetRequest
    request_id: Optional[str] = None


class ScenarioPreviewRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=1000)
    context: Optional[CommandContext] = None
    request_id: Optional[str] = None


class ScenarioSaveRequest(BaseModel):
    validated_bundle: Optional[Dict[str, Any]] = None
    automations: list[Dict[str, Any]] = Field(default_factory=list)
    auto_activate: bool = True
    request_id: Optional[str] = None


class ScenarioUpsertRequest(BaseModel):
    automation: Dict[str, Any]
    auto_activate: bool = True
    request_id: Optional[str] = None


class ScenarioDeleteRequest(BaseModel):
    automation_id: str = Field(..., min_length=1, max_length=128)
    auto_activate: bool = True
    request_id: Optional[str] = None


class TimingMs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    parse: int
    validate_ms: int = Field(..., alias="validate", serialization_alias="validate")
    execute: int
    llm: Optional["LLMTimingMs"] = None


class LLMTimingMs(BaseModel):
    duration_ms: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    model: Optional[str] = None


class CommandResponse(BaseModel):
    ok: bool
    status: Literal["EXECUTED", "DRY_RUN", "NEEDS_CLARIFICATION", "ERROR"]
    request_id: str
    say_text: str
    parser_mode_used: ParserMode
    parsed_command: Dict[str, Any]
    validated_command: Optional[Dict[str, Any]] = None
    calls: list[Dict[str, Any]] = []
    errors: list[Dict[str, Any]] = []
    clarification: Optional[Dict[str, Any]] = None
    timing_ms: TimingMs


class ScenarioTimingMs(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    parse: int
    validate_ms: int = Field(..., alias="validate", serialization_alias="validate")
    compile_ms: int = Field(..., alias="compile", serialization_alias="compile")
    llm: Optional["LLMTimingMs"] = None


class ScenarioPreviewResponse(BaseModel):
    ok: bool
    status: Literal["PREVIEW_READY", "NEEDS_CLARIFICATION", "ERROR"]
    request_id: str
    say_text: str
    parsed_bundle: Dict[str, Any]
    validated_bundle: Optional[Dict[str, Any]] = None
    automations: list[Dict[str, Any]] = []
    errors: list[Dict[str, Any]] = []
    clarification: Optional[Dict[str, Any]] = None
    timing_ms: ScenarioTimingMs


class ScenarioSaveResponse(BaseModel):
    ok: bool
    status: Literal["SAVED_ACTIVE", "SAVED_NEEDS_INCLUDE", "SAVED_RELOAD_FAILED", "ERROR"]
    request_id: str
    say_text: str
    saved_automation_count: int = 0
    file_automation_count: int = 0
    storage_file: Optional[str] = None
    include_detected: bool = False
    reloaded: bool = False
    include_hint: Optional[str] = None
    project_files: list[str] = []
    errors: list[Dict[str, Any]] = []


class ScenarioDeleteResponse(BaseModel):
    ok: bool
    status: Literal["DELETED_ACTIVE", "DELETED_PENDING_RELOAD", "NOT_FOUND", "ERROR"]
    request_id: str
    say_text: str
    deleted_automation_id: Optional[str] = None
    file_automation_count: int = 0
    storage_file: Optional[str] = None
    include_detected: bool = False
    reloaded: bool = False
    include_hint: Optional[str] = None
    project_files_removed: list[str] = []
    errors: list[Dict[str, Any]] = []


class ScenarioListItem(BaseModel):
    automation_id: str
    alias: str
    trigger_summary: str = ""
    action_summary: str = ""
    automation: Dict[str, Any]


class ScenarioListResponse(BaseModel):
    ok: bool = True
    storage_file: Optional[str] = None
    file_automation_count: int = 0
    items: list[ScenarioListItem] = []
    errors: list[Dict[str, Any]] = []


class CatalogCapabilities(BaseModel):
    on_off: bool = False
    brightness: bool = False
    rgb: bool = False
    color_temp: bool = False
    transition: bool = False


class CatalogDevice(BaseModel):
    device_id: str
    name: str
    device_type: str
    area_id: Optional[str] = None
    area_name: Optional[str] = None
    entity_id: Optional[str] = None
    control_profile: str = "power_only"
    supported_quick_actions: list[str] = Field(default_factory=list)
    capabilities: CatalogCapabilities = Field(default_factory=CatalogCapabilities)


class CatalogTargetProfile(BaseModel):
    device_type: str
    profile_id: str
    label: str
    supported_quick_actions: list[str] = Field(default_factory=list)
    device_ids: list[str] = Field(default_factory=list)


class CatalogArea(BaseModel):
    area_id: str
    name: str
    device_types: list[str] = Field(default_factory=list)
    device_ids: list[str] = Field(default_factory=list)
    target_profiles: list[CatalogTargetProfile] = Field(default_factory=list)


class CatalogResponse(BaseModel):
    ok: bool = True
    schema_version: str = "1.0"
    areas: list[CatalogArea] = Field(default_factory=list)
    devices: list[CatalogDevice] = Field(default_factory=list)


class ReadinessProbe(BaseModel):
    ok: bool
    configured: bool = True
    detail: Optional[str] = None


class ReadinessResponse(BaseModel):
    ok: bool = True
    time_utc: str
    version: str = "1.0"
    ready_for_live_commands: bool
    ready_for_llm_commands: bool
    gateway: ReadinessProbe
    home_assistant: ReadinessProbe
    llm: ReadinessProbe
    runtime_fingerprint: Dict[str, Any] = Field(default_factory=dict)


def _supported_quick_actions_for_capabilities(device_type: str, capabilities: Dict[str, Any]) -> list[str]:
    normalized_type = str(device_type or "").strip().lower()
    caps = capabilities if isinstance(capabilities, dict) else {}
    actions: list[str] = []

    if bool(caps.get("on_off")):
        actions.extend(["TURN_ON", "TURN_OFF"])
    if normalized_type == "light" and bool(caps.get("brightness")):
        actions.extend(["BRIGHTER", "DIMMER"])
    if normalized_type == "light" and bool(caps.get("color_temp")):
        actions.extend(["WARMER", "COOLER"])
    if normalized_type == "light" and any(bool(caps.get(k)) for k in ("brightness", "rgb", "color_temp")):
        actions.append("COZY")
    if normalized_type == "light" and bool(caps.get("brightness")) and any(bool(caps.get(k)) for k in ("rgb", "color_temp")):
        actions.append("MOVIE")

    return list(dict.fromkeys(actions))


def _control_profile_for_capabilities(device_type: str, capabilities: Dict[str, Any]) -> str:
    normalized_type = str(device_type or "").strip().lower()
    caps = capabilities if isinstance(capabilities, dict) else {}

    if normalized_type == "light":
        if bool(caps.get("rgb")):
            return "color_scene"
        if bool(caps.get("color_temp")):
            return "tunable_white"
        if bool(caps.get("brightness")):
            return "dimmable"
    if bool(caps.get("on_off")):
        return "power_only"
    return "basic"


def _control_profile_label(profile_id: str) -> str:
    normalized = str(profile_id or "").strip().lower()
    return {
        "color_scene": "Цвет и сцены",
        "tunable_white": "Белый свет",
        "dimmable": "Яркость",
        "power_only": "Питание",
        "basic": "Базовое",
    }.get(normalized, "Управление")


def _env(name: str, default: Optional[str] = None) -> Optional[str]:
    v = os.getenv(name)
    if v is None or str(v).strip() == "":
        return default
    return str(v)


def _env_flag(name: str, default: bool = False) -> bool:
    raw = _env(name)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _short_sha256(path: Path) -> Optional[str]:
    try:
        data = path.read_bytes()
    except Exception:
        return None
    return hashlib.sha256(data).hexdigest()[:12]


def _file_contains(path: Path, needle: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return False
    return needle in text


def _resolve_runtime_file(root_dir: Path, *relative_parts: str) -> Path:
    direct = root_dir.joinpath(*relative_parts)
    if direct.exists():
        return direct
    fallback = _PROJECT_ROOT.joinpath(*relative_parts)
    if fallback.exists():
        return fallback
    return direct


def _build_runtime_fingerprint(root_dir: Path) -> Dict[str, Any]:
    parser_llm_path = _resolve_runtime_file(root_dir, "smarthome_core", "parser_llm.py")
    gateway_main_path = _resolve_runtime_file(root_dir, "smarthome_gateway", "main.py")
    pipeline_path = _resolve_runtime_file(root_dir, "smarthome_core", "pipeline.py")

    return {
        "root_dir": str(root_dir),
        "parser_llm_sha256_12": _short_sha256(parser_llm_path),
        "gateway_main_sha256_12": _short_sha256(gateway_main_path),
        "pipeline_sha256_12": _short_sha256(pipeline_path),
        "features": {
            "selected_area_context": _file_contains(parser_llm_path, "selected_area_name"),
            "explicit_switch_recovery": _file_contains(parser_llm_path, "_recover_explicit_switch_command"),
            "prompt_prefers_selected_area": _file_contains(
                parser_llm_path,
                "prefer context.selected_area_name, then context.last_area_name",
            ),
            "pipeline_selected_area_default": _file_contains(
                pipeline_path,
                '{"selected_area_name": None, "last_area_name": None}',
            ),
        },
    }


def _require_api_key(x_api_key: Optional[str]) -> None:
    configured_key = _env("GATEWAY_API_KEY")
    if configured_key and x_api_key != configured_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def _append_jsonl(path: Path, obj: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _say_text_for(status: str, clarification: Optional[Dict[str, Any]], errors: list[Dict[str, Any]]) -> str:
    if status == "NEEDS_CLARIFICATION":
        q = (clarification or {}).get("question")
        return str(q) if q else "Уточните, пожалуйста."
    if status in {"EXECUTED", "DRY_RUN"}:
        return "Готово."
    if errors:
        code = errors[0].get("code") or "ERROR"
        return f"Не могу выполнить команду: {code}."
    return "Не могу выполнить команду."


def _say_text_for_scenario_preview(
    status: str,
    clarification: Optional[Dict[str, Any]],
    errors: list[Dict[str, Any]],
    *,
    automation_count: int = 0,
) -> str:
    if status == "NEEDS_CLARIFICATION":
        question = str((clarification or {}).get("question") or "").strip()
        return question or "Нужно уточнение для создания сценария."
    if status == "ERROR":
        if errors:
            return f"Не удалось подготовить сценарий: {errors[0].get('message') or errors[0].get('code')}"
        return "Не удалось подготовить сценарий."
    if automation_count == 1:
        return "Сценарий подготовлен."
    return f"Подготовлено сценариев: {automation_count}."


def _say_text_for_scenario_save(
    status: str,
    *,
    saved_count: int,
    include_hint: Optional[str],
    errors: list[Dict[str, Any]],
) -> str:
    if status == "SAVED_ACTIVE":
        if saved_count == 1:
            return "Сценарий сохранён и активирован в Home Assistant."
        return f"Сценарии сохранены и активированы: {saved_count}."
    if status == "SAVED_NEEDS_INCLUDE":
        hint = include_hint or "Подключите generated файл автоматизаций в configuration.yaml."
        return f"Сценарий сохранён, но ещё не активирован. {hint}"
    if status == "SAVED_RELOAD_FAILED":
        if errors:
            return f"Сценарий сохранён, но automation.reload не выполнился: {errors[0].get('message') or errors[0].get('code')}"
        return "Сценарий сохранён, но automation.reload не выполнился."
    if errors:
        return f"Не удалось сохранить сценарий: {errors[0].get('message') or errors[0].get('code')}"
    return "Не удалось сохранить сценарий."


def _say_text_for_scenario_delete(
    status: str,
    *,
    automation_id: Optional[str],
    include_hint: Optional[str],
    errors: list[Dict[str, Any]],
) -> str:
    if status == "DELETED_ACTIVE":
        return f"Сценарий удалён и изменения применены: {automation_id or 'unknown'}."
    if status == "DELETED_PENDING_RELOAD":
        if include_hint:
            return f"Сценарий удалён, но автоматизации не были перезагружены. {include_hint}"
        return "Сценарий удалён. Для применения изменений перезагрузите automation в Home Assistant."
    if status == "NOT_FOUND":
        return f"Сценарий не найден: {automation_id or 'unknown'}."
    if errors:
        return f"Не удалось удалить сценарий: {errors[0].get('message') or errors[0].get('code')}"
    return "Не удалось удалить сценарий."


def _scenario_config_dir(root_dir: Path) -> Path:
    ha_config_dir = Path("/config")
    if ha_config_dir.exists():
        return ha_config_dir
    return root_dir / "gateway_scenarios"


def _running_in_ha_addon() -> bool:
    if Path("/data/options.json").exists():
        return True
    token = _env("SUPERVISOR_TOKEN")
    return bool(token and str(token).strip())


def _ha_config_mount_available() -> bool:
    return Path("/config").exists()


def _scenario_automations_file(root_dir: Path) -> Path:
    return _scenario_config_dir(root_dir) / "smarthome_gateway_automations.yaml"


def _scenario_configuration_file(root_dir: Path) -> Path:
    return _scenario_config_dir(root_dir) / "configuration.yaml"


def _scenario_include_hint(file_name: str) -> str:
    return f"Добавьте в configuration.yaml строку automation: !include {file_name}"


_AUTOMATION_INCLUDE_RE = re.compile(r"(?im)^\s*automation\s*:\s*!include\s+([^\s#]+)\s*$")
_AUTOMATION_KEY_RE = re.compile(r"(?im)^\s*automation\s*:")
_LIST_INCLUDE_RE = re.compile(r"(?im)^\s*-\s*!include\s+([^\s#]+)\s*$")
_AUTOMATION_DIR_INCLUDE_RE = re.compile(r"(?im)^\s*automation\s*:\s*!include_dir(?:_merge)?_list\s+([^\s#]+)\s*$")


def _read_text_if_exists(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def _find_simple_automation_include(config_path: Path) -> Optional[str]:
    text = _read_text_if_exists(config_path)
    match = _AUTOMATION_INCLUDE_RE.search(text)
    if not match:
        return None
    include_path = str(match.group(1) or "").strip()
    return include_path or None


def _has_automation_key(config_path: Path) -> bool:
    text = _read_text_if_exists(config_path)
    return bool(_AUTOMATION_KEY_RE.search(text))


def _find_automation_dir_include(config_path: Path) -> Optional[str]:
    text = _read_text_if_exists(config_path)
    match = _AUTOMATION_DIR_INCLUDE_RE.search(text)
    if not match:
        return None
    include_dir = str(match.group(1) or "").strip().strip("'\"")
    return include_dir or None


def _resolve_scenario_automations_file(root_dir: Path, config_path: Path) -> Path:
    include_dir = _find_automation_dir_include(config_path)
    if include_dir:
        return _scenario_config_dir(root_dir) / include_dir / "smarthome_gateway_automations.yaml"
    return _scenario_automations_file(root_dir)


def _append_gateway_include_to_configuration(config_path: Path, include_file_name: str) -> bool:
    text = _read_text_if_exists(config_path)
    include_line = f"automation: !include {include_file_name}"
    if include_line in text:
        return False
    if text and not text.endswith("\n"):
        text += "\n"
    text += include_line + "\n"
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(text, encoding="utf-8")
    return True


def _upgrade_simple_automation_include_to_list(config_path: Path, include_file_name: str) -> bool:
    text = _read_text_if_exists(config_path)
    match = _AUTOMATION_INCLUDE_RE.search(text)
    if not match:
        return False
    existing_include = str(match.group(1) or "").strip()
    if not existing_include:
        return False
    if existing_include == include_file_name:
        return False

    replacement = (
        "automation:\n"
        f"  - !include {existing_include}\n"
        f"  - !include {include_file_name}"
    )
    updated = text[:match.start()] + replacement + text[match.end():]
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(updated, encoding="utf-8")
    return True


def _reload_automation_service(errors: list[Dict[str, Any]]) -> tuple[str, bool]:
    try:
        _make_ha_client().call_service("automation.reload", {})
        return "SAVED_ACTIVE", True
    except Exception as e:
        errors.append({"code": "AUTOMATION_RELOAD_ERROR", "message": str(e)})
        return "SAVED_RELOAD_FAILED", False


def _load_generated_automations(path: Path) -> list[Dict[str, Any]]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return []
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _merge_generated_automations(
    existing: list[Dict[str, Any]],
    incoming: list[Dict[str, Any]],
) -> list[Dict[str, Any]]:
    merged: list[Dict[str, Any]] = []
    by_id: Dict[str, Dict[str, Any]] = {}

    for item in existing:
        automation_id = str(item.get("id") or "").strip()
        if automation_id:
            by_id[automation_id] = item
        else:
            merged.append(item)

    for item in incoming:
        automation_id = str(item.get("id") or "").strip()
        if automation_id:
            by_id[automation_id] = item
        else:
            merged.append(item)

    stable_ids = sorted(by_id.keys())
    merged.extend(by_id[automation_id] for automation_id in stable_ids)
    return merged


def _write_generated_automations(path: Path, automations: list[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(automations, ensure_ascii=False, indent=2), encoding="utf-8")


def _scenario_project_automation_dir(root_dir: Path) -> Path:
    return _scenario_config_dir(root_dir) / "blueprints" / "automation" / "homeassistant"


def _slug_filename(value: str) -> str:
    slug = re.sub(r"[^a-z0-9._-]+", "_", str(value or "").strip().lower())
    return slug.strip("_.-") or "scenario"


def _automation_to_project_blueprint(automation: Dict[str, Any]) -> Dict[str, Any]:
    alias = str(automation.get("alias") or automation.get("id") or "SmartHome Scenario").strip() or "SmartHome Scenario"
    out: Dict[str, Any] = {
        "blueprint": {
            "name": alias,
            "description": "Generated by SmartHome Gateway scenario authoring",
            "domain": "automation",
            "input": {},
        },
        "trigger": list(automation.get("trigger") or []),
        "action": list(automation.get("action") or []),
        "mode": str(automation.get("mode") or "single"),
    }
    conditions = automation.get("condition")
    if isinstance(conditions, list) and conditions:
        out["condition"] = conditions
    return out


def _export_project_blueprints(root_dir: Path, automations: list[Dict[str, Any]]) -> list[str]:
    project_dir = _scenario_project_automation_dir(root_dir)
    project_dir.mkdir(parents=True, exist_ok=True)
    exported: list[str] = []
    for item in automations:
        automation_id = str(item.get("id") or "").strip()
        alias = str(item.get("alias") or "").strip()
        token = _slug_filename(automation_id or alias)
        file_path = project_dir / f"smarthome_gateway_{token}.yaml"
        blueprint = _automation_to_project_blueprint(item)
        file_path.write_text(json.dumps(blueprint, ensure_ascii=False, indent=2), encoding="utf-8")
        exported.append(str(file_path))
    return exported


def _scenario_project_automation_file(root_dir: Path, automation: Dict[str, Any]) -> Path:
    automation_id = str(automation.get("id") or "").strip()
    alias = str(automation.get("alias") or "").strip()
    token = _slug_filename(automation_id or alias)
    return _scenario_project_automation_dir(root_dir) / f"smarthome_gateway_{token}.yaml"


def _remove_project_blueprint_for_automation(root_dir: Path, automation: Dict[str, Any]) -> Optional[str]:
    file_path = _scenario_project_automation_file(root_dir, automation)
    if not file_path.exists():
        return None
    file_path.unlink()
    return str(file_path)


def _scenario_trigger_summary(automation: Dict[str, Any]) -> str:
    trigger = None
    triggers = automation.get("trigger")
    if isinstance(triggers, list) and triggers:
        first = triggers[0]
        if isinstance(first, dict):
            trigger = first
    if trigger is None:
        return "no trigger"

    trigger_type = str(trigger.get("trigger") or trigger.get("platform") or "").strip().lower()
    if trigger_type == "time":
        at = str(trigger.get("at") or "").strip()
        if at:
            return f"time {at}"
    if trigger_type:
        return trigger_type
    return "trigger"


def _scenario_action_summary(automation: Dict[str, Any]) -> str:
    actions = automation.get("action")
    if not isinstance(actions, list) or not actions:
        return "no actions"
    first = actions[0] if isinstance(actions[0], dict) else None
    if first is None:
        return "action"
    service = str(first.get("action") or first.get("service") or "").strip()
    if service:
        return service
    return "action"


def _configuration_includes_generated_automations(config_path: Path, include_file_name: str) -> bool:
    text = _read_text_if_exists(config_path)
    if not text.strip():
        return False

    def _matches_include_path(raw: str) -> bool:
        candidate = str(raw or "").strip().strip("'\"")
        if not candidate:
            return False
        if candidate == include_file_name:
            return True
        normalized = candidate.replace("\\", "/")
        return normalized.endswith("/" + include_file_name)

    simple_include = _find_simple_automation_include(config_path)
    if simple_include and _matches_include_path(simple_include):
        return True

    include_dir = _find_automation_dir_include(config_path)
    if include_dir:
        normalized = str(include_dir).replace("\\", "/").strip().strip("/")
        if normalized:
            generated_path = normalized + "/" + include_file_name
            if _matches_include_path(generated_path):
                return True

    for match in _LIST_INCLUDE_RE.finditer(text):
        include_path = str(match.group(1) or "").strip()
        if _matches_include_path(include_path):
            return True
    return False


def _validate_save_automations(automations: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    if not automations:
        raise ValueError("No automations to save")
    normalized: list[Dict[str, Any]] = []
    for idx, item in enumerate(automations):
        if not isinstance(item, dict):
            raise ValueError(f"automation[{idx}] is not an object")
        automation_id = str(item.get("id") or "").strip()
        actions = item.get("action")
        triggers = item.get("trigger")
        if not automation_id:
            raise ValueError(f"automation[{idx}] has no id")
        if not isinstance(actions, list) or not actions:
            raise ValueError(f"automation[{idx}] has no actions")
        if not isinstance(triggers, list) or not triggers:
            raise ValueError(f"automation[{idx}] has no triggers")
        normalized.append(item)
    return normalized


def _load_assets(root_dir: Path) -> Dict[str, Any]:
    paths = AssetPaths(root_dir)
    assets = {
        "paths": paths,
        "device_registry": load_json(paths.device_registry),
        "area_synonyms": load_json(paths.area_synonyms),
        "colors": load_json(paths.colors),
        "modifiers": load_json(paths.modifiers),
        "scene_aliases": load_json(paths.scene_aliases),
        "parsed_schema": None,
        "scenario_schema": None,
    }
    try:
        from smarthome_core.schema_utils import load_schema

        assets["parsed_schema"] = load_schema(paths.parsed_schema)
    except Exception:
        assets["parsed_schema"] = None
    try:
        from smarthome_core.schema_utils import load_schema

        assets["scenario_schema"] = load_schema(paths.scenario_bundle_schema)
    except Exception:
        assets["scenario_schema"] = None
    return assets


def _make_llm_client() -> Optional[Any]:
    base_url = _env("LLM_BASE_URL")
    if not base_url:
        return None
    model = _env("LLM_MODEL", "local-model")
    api_key = _env("LLM_API_KEY")
    return OpenAICompatibleClient(base_url=base_url, api_key=api_key, model=model)


def _resolve_ha_token(ha_url: str) -> tuple[Optional[str], Optional[str]]:
    token = _env("HA_TOKEN")
    if token:
        return token, "HA_TOKEN"

    use_supervisor = _env_flag("USE_SUPERVISOR_TOKEN", default=False)
    if "supervisor/core" in str(ha_url or "") or use_supervisor:
        supervisor_token = _env("SUPERVISOR_TOKEN")
        if supervisor_token:
            return supervisor_token, "SUPERVISOR_TOKEN"

    return None, None


def _ha_missing_token_detail(ha_url: str) -> str:
    if "supervisor/core" in str(ha_url or "") or _env_flag("USE_SUPERVISOR_TOKEN", default=False):
        return "Neither HA_TOKEN nor SUPERVISOR_TOKEN is set"
    return "HA_TOKEN is not set"


def _make_ha_client() -> HomeAssistantClient:
    ha_url = _env("HA_URL", "http://homeassistant.local:8123")
    token, _token_source = _resolve_ha_token(ha_url)
    if not token:
        raise RuntimeError(_ha_missing_token_detail(ha_url))

    verify_tls = _env("HA_VERIFY_TLS", "1") != "0"
    timeout_s = float(_env("HA_TIMEOUT_S", "10"))
    return HomeAssistantClient(base_url=ha_url, token=token, timeout_s=timeout_s, verify_tls=verify_tls)


def _probe_home_assistant() -> ReadinessProbe:
    ha_url = _env("HA_URL", "http://homeassistant.local:8123")
    token, token_source = _resolve_ha_token(ha_url)
    if not token:
        return ReadinessProbe(ok=False, configured=False, detail=_ha_missing_token_detail(ha_url))

    try:
        ha_client = _make_ha_client()
        response = ha_client._request("GET", "/api/")
        if response:
            source = token_source or "token"
            return ReadinessProbe(ok=True, configured=True, detail=f"reachable via {source}")
        return ReadinessProbe(ok=False, configured=True, detail="empty response from /api/")
    except Exception as e:
        return ReadinessProbe(ok=False, configured=True, detail=str(e))


def _probe_llm() -> ReadinessProbe:
    base_url = _env("LLM_BASE_URL")
    if not base_url:
        return ReadinessProbe(ok=False, configured=False, detail="LLM_BASE_URL is not set")
    model = _env("LLM_MODEL", "local-model")
    return ReadinessProbe(ok=True, configured=True, detail=f"configured (model={model})")


def _reset_llm_call_info(client: Optional[Any]) -> None:
    if client is None:
        return
    clear_fn = getattr(client, "clear_last_call_info", None)
    if callable(clear_fn):
        clear_fn()


def _collect_llm_timing(client: Optional[Any]) -> Optional[LLMTimingMs]:
    if client is None:
        return None
    get_fn = getattr(client, "get_last_call_info", None)
    if not callable(get_fn):
        return None
    info = get_fn()
    if not isinstance(info, LLMCallInfo):
        return None
    return LLMTimingMs(
        duration_ms=int(info.duration_ms),
        prompt_tokens=int(info.prompt_tokens),
        completion_tokens=int(info.completion_tokens),
        total_tokens=int(info.total_tokens),
        model=info.model or None,
    )


def _build_catalog(device_registry: Dict[str, Any]) -> CatalogResponse:
    areas_raw = device_registry.get("areas") if isinstance(device_registry, dict) else None
    devices_raw = device_registry.get("devices") if isinstance(device_registry, dict) else None

    areas_raw = areas_raw if isinstance(areas_raw, list) else []
    devices_raw = devices_raw if isinstance(devices_raw, list) else []

    area_meta: dict[str, dict[str, Any]] = {}
    device_to_area: dict[str, str] = {}
    area_device_types: dict[str, list[str]] = {}
    area_target_profiles: dict[str, dict[tuple[str, str], Dict[str, Any]]] = {}

    for area in areas_raw:
        if not isinstance(area, dict):
            continue
        area_id = str(area.get("area_id") or "").strip()
        area_name = str(area.get("name") or "").strip()
        if not area_id or not area_name:
            continue
        device_ids = [str(v).strip() for v in (area.get("devices") or []) if str(v).strip()]
        area_meta[area_id] = {"name": area_name, "device_ids": device_ids}
        area_device_types[area_id] = []
        area_target_profiles[area_id] = {}
        for device_id in device_ids:
            device_to_area[device_id] = area_id

    devices: list[CatalogDevice] = []
    for raw in devices_raw:
        if not isinstance(raw, dict):
            continue
        device_id = str(raw.get("device_id") or "").strip()
        if not device_id:
            continue
        device_type = str(raw.get("device_type") or "").strip() or "unknown"
        area_id_raw = str(raw.get("area_id") or "").strip()
        area_id = area_id_raw or device_to_area.get(device_id)
        area_name = area_meta.get(area_id, {}).get("name") if area_id else None
        if area_id and device_type not in area_device_types.get(area_id, []):
            area_device_types.setdefault(area_id, []).append(device_type)

        capabilities = raw.get("capabilities") if isinstance(raw.get("capabilities"), dict) else {}
        ha = raw.get("home_assistant") if isinstance(raw.get("home_assistant"), dict) else {}
        control_profile = _control_profile_for_capabilities(device_type, capabilities)
        supported_quick_actions = _supported_quick_actions_for_capabilities(device_type, capabilities)
        if area_id:
            key = (device_type, control_profile)
            bucket = area_target_profiles.setdefault(area_id, {}).setdefault(
                key,
                {
                    "device_type": device_type,
                    "profile_id": control_profile,
                    "label": _control_profile_label(control_profile),
                    "supported_quick_actions": list(supported_quick_actions),
                    "device_ids": [],
                },
            )
            bucket["device_ids"].append(device_id)
            bucket["supported_quick_actions"] = list(
                dict.fromkeys(list(bucket.get("supported_quick_actions") or []) + list(supported_quick_actions))
            )
        devices.append(
            CatalogDevice(
                device_id=device_id,
                name=str(raw.get("name") or "").strip() or device_id,
                device_type=device_type,
                area_id=area_id or None,
                area_name=str(area_name).strip() if area_name else None,
                entity_id=str(ha.get("entity_id") or "").strip() or None,
                control_profile=control_profile,
                supported_quick_actions=supported_quick_actions,
                capabilities=CatalogCapabilities(
                    on_off=bool(capabilities.get("on_off")),
                    brightness=bool(capabilities.get("brightness")),
                    rgb=bool(capabilities.get("rgb")),
                    color_temp=bool(capabilities.get("color_temp")),
                    transition=bool(capabilities.get("transition")),
                ),
            )
        )

    areas: list[CatalogArea] = []
    for area in areas_raw:
        if not isinstance(area, dict):
            continue
        area_id = str(area.get("area_id") or "").strip()
        area_name = str(area.get("name") or "").strip()
        if not area_id or not area_name:
            continue
        device_ids = area_meta.get(area_id, {}).get("device_ids", [])
        device_types = area_device_types.get(area_id, [])
        target_profiles = [
            CatalogTargetProfile(
                device_type=str(profile.get("device_type") or ""),
                profile_id=str(profile.get("profile_id") or ""),
                label=str(profile.get("label") or ""),
                supported_quick_actions=list(profile.get("supported_quick_actions") or []),
                device_ids=list(profile.get("device_ids") or []),
            )
            for _, profile in sorted(
                area_target_profiles.get(area_id, {}).items(),
                key=lambda item: (str(item[1].get("device_type") or ""), str(item[1].get("profile_id") or "")),
            )
        ]
        areas.append(
            CatalogArea(
                area_id=area_id,
                name=area_name,
                device_types=list(dict.fromkeys(device_types)),
                device_ids=device_ids,
                target_profiles=target_profiles,
            )
        )

    return CatalogResponse(
        schema_version=str(device_registry.get("schema_version") or "1.0"),
        areas=areas,
        devices=devices,
    )


def _resolve_quick_action_target(
    device_registry: Dict[str, Any],
    *,
    area_name: Optional[str],
    device_type: str,
    device_id: Optional[str],
) -> tuple[Optional[Dict[str, Any]], list[str], Optional[str], Optional[Dict[str, str]]]:
    catalog = _build_catalog(device_registry)
    normalized_type = str(device_type or "").strip().lower()
    area_name = str(area_name or "").strip() or None
    device_id = str(device_id or "").strip() or None

    if device_id:
        device = next((d for d in catalog.devices if d.device_id == device_id), None)
        if device is None:
            return None, [], area_name, {"code": "UNKNOWN_DEVICE", "message": f"Unknown device_id={device_id}"}
        if normalized_type and device.device_type != normalized_type:
            return None, [], area_name, {"code": "DEVICE_TYPE_MISMATCH", "message": "device_id does not match device_type"}
        if not device.entity_id:
            return None, [], area_name, {"code": "NO_ENTITY", "message": f"device_id={device_id} has no entity_id"}
        return (
            {"scope": "ENTITY", "area_name": None, "entity_ids": [device.entity_id]},
            [device.entity_id],
            device.area_name or area_name,
            None,
        )

    if not area_name:
        return None, [], None, {"code": "MISSING_TARGET", "message": "area_name is required for device_type targets"}

    devices = [
        d for d in catalog.devices
        if d.area_name == area_name and d.device_type == normalized_type and d.entity_id
    ]
    if not devices:
        return None, [], area_name, {"code": "NO_TARGET", "message": f"No devices for {normalized_type} in {area_name}"}

    entity_ids = [str(d.entity_id) for d in devices if d.entity_id]
    return (
        {"scope": "AREA", "area_name": area_name, "entity_ids": []},
        entity_ids,
        area_name,
        None,
    )


def _resolve_catalog_target_devices(
    catalog: CatalogResponse,
    *,
    area_name: Optional[str],
    device_type: str,
    device_id: Optional[str],
) -> list[CatalogDevice]:
    normalized_type = str(device_type or "").strip().lower()
    normalized_area = str(area_name or "").strip() or None
    normalized_device_id = str(device_id or "").strip() or None

    if normalized_device_id:
        device = next((d for d in catalog.devices if d.device_id == normalized_device_id), None)
        return [device] if device is not None else []

    if not normalized_area:
        return []
    return [
        d for d in catalog.devices
        if d.area_name == normalized_area and d.device_type == normalized_type
    ]


def _intersect_supported_quick_actions(devices: list[CatalogDevice]) -> list[str]:
    if not devices:
        return []
    shared = set(devices[0].supported_quick_actions)
    for device in devices[1:]:
        shared &= set(device.supported_quick_actions)
    return [action for action in devices[0].supported_quick_actions if action in shared]


def _light_validated_quick_action(
    *,
    action_id: str,
    target: Dict[str, Any],
    entity_ids: list[str],
    area_name: Optional[str],
) -> Optional[Dict[str, Any]]:
    aid = str(action_id or "").strip().upper()
    intent = None
    parsed_params: Dict[str, Any] = {
        "brightness": None,
        "brightness_delta": None,
        "color": None,
        "color_temp_kelvin": None,
        "color_temp_delta_k": None,
        "transition_s": 0.6,
    }
    normalized_params: Dict[str, Any] = {
        "brightness_pct": None,
        "brightness_delta_pct": None,
        "rgb_color": None,
        "color_temp_kelvin": None,
        "color_temp_delta_k": None,
        "transition_s": 0.6,
    }
    service = "light.turn_on"
    step_data: Dict[str, Any] = {
        "brightness_pct": None,
        "brightness_step_pct": None,
        "rgb_color": None,
        "color_temp_kelvin": None,
        "transition": 0.6,
    }

    if aid == "TURN_ON":
        intent = "TURN_ON"
    elif aid == "TURN_OFF":
        intent = "TURN_OFF"
        service = "light.turn_off"
        parsed_params["transition_s"] = 0.4
        normalized_params["transition_s"] = 0.4
        step_data["transition"] = 0.4
    elif aid == "BRIGHTER":
        intent = "ADJUST_BRIGHTNESS"
        parsed_params["brightness_delta"] = 15
        normalized_params["brightness_delta_pct"] = 15
        step_data["brightness_step_pct"] = 15
    elif aid == "DIMMER":
        intent = "ADJUST_BRIGHTNESS"
        parsed_params["brightness_delta"] = -15
        normalized_params["brightness_delta_pct"] = -15
        step_data["brightness_step_pct"] = -15
    elif aid == "WARMER":
        intent = "ADJUST_COLOR_TEMP"
        parsed_params["color_temp_delta_k"] = -700
        normalized_params["color_temp_delta_k"] = -700
    elif aid == "COOLER":
        intent = "ADJUST_COLOR_TEMP"
        parsed_params["color_temp_delta_k"] = 700
        normalized_params["color_temp_delta_k"] = 700
    elif aid == "COZY":
        intent = "TURN_ON"
        parsed_params["brightness"] = 35
        parsed_params["color_temp_kelvin"] = 2700
        normalized_params["brightness_pct"] = 35
        normalized_params["color_temp_kelvin"] = 2700
        step_data["brightness_pct"] = 35
        step_data["color_temp_kelvin"] = 2700
    elif aid == "MOVIE":
        intent = "TURN_ON"
        parsed_params["brightness"] = 18
        parsed_params["color_temp_kelvin"] = 2400
        normalized_params["brightness_pct"] = 18
        normalized_params["color_temp_kelvin"] = 2400
        step_data["brightness_pct"] = 18
        step_data["color_temp_kelvin"] = 2400
    else:
        return None

    context_last_entities = entity_ids if target.get("scope") == "ENTITY" else []
    return {
        "schema_version": "1.0",
        "status": "EXECUTABLE",
        "reason_code": "OK",
        "warnings": [],
        "normalized": {
            "actions": [
                {
                    "domain": "light",
                    "intent": intent,
                    "target": target,
                    "params": normalized_params,
                }
            ],
            "context_updates": {
                "last_area_name": area_name,
                "last_entity_ids": context_last_entities,
            },
        },
        "execution_plan": [
            {
                "executor": "HOME_ASSISTANT",
                "service": service,
                "target": {"entity_id": entity_ids, "area_name": target.get("area_name")},
                "data": step_data,
            }
        ],
        "clarification": {"needed": False, "question": None, "options": []},
        "_parsed_command": {
            "schema_version": "1.0",
            "actions": [
                {
                    "domain": "light",
                    "intent": intent,
                    "target": target,
                    "params": parsed_params,
                }
            ],
        },
    }


def _switch_quick_action_payload(
    *,
    action_id: str,
    target: Dict[str, Any],
    entity_ids: list[str],
    area_name: Optional[str],
) -> Optional[Dict[str, Any]]:
    aid = str(action_id or "").strip().upper()
    if aid == "TURN_ON":
        service = "switch.turn_on"
        intent = "TURN_ON"
    elif aid == "TURN_OFF":
        service = "switch.turn_off"
        intent = "TURN_OFF"
    else:
        return None

    payload = {"entity_id": entity_ids if len(entity_ids) > 1 else entity_ids[0]}
    return {
        "calls": [{"service": service, "payload": payload}],
        "parsed_command": {
            "schema_version": "1.0",
            "actions": [
                {
                    "domain": "switch",
                    "intent": intent,
                    "target": target,
                    "params": {},
                }
            ],
        },
        "validated_command": {
            "schema_version": "1.0",
            "status": "EXECUTABLE",
            "reason_code": "OK",
            "warnings": [],
            "normalized": {
                "actions": [
                    {
                        "domain": "switch",
                        "intent": intent,
                        "target": target,
                        "params": {},
                    }
                ],
                "context_updates": {
                    "last_area_name": area_name,
                    "last_entity_ids": entity_ids if target.get("scope") == "ENTITY" else [],
                },
            },
            "execution_plan": [
                {
                    "executor": "HOME_ASSISTANT",
                    "service": service,
                    "target": {"entity_id": entity_ids, "area_name": target.get("area_name")},
                    "data": {},
                }
            ],
        },
    }


def _execute_calls(
    *,
    calls: list[Dict[str, Any]],
    dry_run: bool,
) -> tuple[bool, list[Dict[str, Any]], list[Dict[str, Any]]]:
    if dry_run:
        return True, calls, []

    try:
        ha_client = _make_ha_client()
    except Exception as e:
        return False, [], [{"code": "EXEC_ERROR", "message": str(e)}]

    executed: list[Dict[str, Any]] = []
    for call in calls:
        service = str(call.get("service") or "").strip()
        payload = dict(call.get("payload") or {})
        try:
            ha_client.call_service(service, payload)
            executed.append(call)
        except Exception as e:
            return False, executed, [{"code": "HA_ERROR", "message": str(e), "service": service}]
    return True, executed, []


@asynccontextmanager
async def lifespan(app: FastAPI):
    root_dir = Path(_env("SH_CORE_ROOT", str(_PROJECT_ROOT))).resolve()
    app.state.root_dir = root_dir
    app.state.assets = _load_assets(root_dir)
    app.state.llm_client = _make_llm_client()

    log_dir = Path(_env("GATEWAY_LOG_DIR", str(root_dir / "gateway_logs"))).resolve()
    app.state.log_path = log_dir / "commands.jsonl"
    yield


app = FastAPI(
    title="SmartHome Gateway",
    version="1.0",
    default_response_class=UTF8JSONResponse,
    lifespan=lifespan,
)


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"ok": True, "time_utc": _now_iso(), "version": "1.0"}


@app.get("/v1/readiness", response_model=ReadinessResponse)
def readiness(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> ReadinessResponse:
    _require_api_key(x_api_key)

    ha_probe = _probe_home_assistant()
    llm_probe = _probe_llm()
    gateway_probe = ReadinessProbe(ok=True, configured=True, detail="reachable")
    root_dir = getattr(app.state, "root_dir", Path(_env("SH_CORE_ROOT", str(_PROJECT_ROOT))).resolve())

    return ReadinessResponse(
        time_utc=_now_iso(),
        ready_for_live_commands=ha_probe.ok,
        ready_for_llm_commands=llm_probe.ok,
        gateway=gateway_probe,
        home_assistant=ha_probe,
        llm=llm_probe,
        runtime_fingerprint=_build_runtime_fingerprint(root_dir),
    )


@app.get("/v1/catalog", response_model=CatalogResponse)
def catalog(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> CatalogResponse:
    _require_api_key(x_api_key)
    device_registry = app.state.assets.get("device_registry") or {}
    return _build_catalog(device_registry)


@app.post("/v1/scenario/preview", response_model=ScenarioPreviewResponse)
def scenario_preview(
    req: ScenarioPreviewRequest,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> ScenarioPreviewResponse:
    _require_api_key(x_api_key)

    llm_client = app.state.llm_client
    if llm_client is None:
        raise HTTPException(status_code=400, detail="LLM is not configured (set LLM_BASE_URL)")

    request_id = req.request_id or str(uuid.uuid4())
    ctx = (req.context.model_dump() if req.context is not None else {})
    ctx.setdefault("last_area_name", None)
    ctx.setdefault("last_entity_ids", [])
    ctx.setdefault("selected_area_name", None)
    ctx.setdefault("last_color_name", None)
    ctx.setdefault("last_brightness", None)
    ctx.setdefault("last_color_temp_kelvin", None)
    ctx.setdefault("pending_clarification_slot", None)

    _reset_llm_call_info(llm_client)
    t_parse0 = time.perf_counter()
    try:
        pipeline_res = run_scenario_authoring_pipeline_v1(
            req.text,
            llm_client=llm_client,
            context=ctx,
            root_dir=app.state.root_dir,
            device_registry=app.state.assets["device_registry"],
            area_synonyms=app.state.assets["area_synonyms"],
            scene_aliases=app.state.assets.get("scene_aliases", {}),
            scenario_schema=app.state.assets.get("scenario_schema"),
        )
    except Exception as e:
        t_parse1 = time.perf_counter()
        llm_timing = _collect_llm_timing(llm_client)
        timing = ScenarioTimingMs(
            parse=int((t_parse1 - t_parse0) * 1000),
            validate_ms=0,
            compile_ms=0,
            llm=llm_timing,
        )
        errors = [{"code": "SCENARIO_PREVIEW_ERROR", "message": str(e)}]
        say_text = _say_text_for_scenario_preview("ERROR", None, errors)
        return ScenarioPreviewResponse(
            ok=False,
            status="ERROR",
            request_id=request_id,
            say_text=say_text,
            parsed_bundle={},
            validated_bundle=None,
            automations=[],
            errors=errors,
            clarification=None,
            timing_ms=timing,
        )
    t_parse1 = time.perf_counter()
    llm_timing = _collect_llm_timing(llm_client)

    parsed = pipeline_res.parsed
    validated = pipeline_res.validated
    automations = pipeline_res.automations or []
    clarification = (validated or {}).get("clarification") if isinstance(validated, dict) else None

    if pipeline_res.stage == "CLARIFICATION":
        timing = ScenarioTimingMs(
            parse=int((t_parse1 - t_parse0) * 1000),
            validate_ms=0,
            compile_ms=0,
            llm=llm_timing,
        )
        say_text = _say_text_for_scenario_preview("NEEDS_CLARIFICATION", clarification, [])
        return ScenarioPreviewResponse(
            ok=True,
            status="NEEDS_CLARIFICATION",
            request_id=request_id,
            say_text=say_text,
            parsed_bundle=parsed,
            validated_bundle=validated,
            automations=[],
            errors=[],
            clarification=clarification,
            timing_ms=timing,
        )

    timing = ScenarioTimingMs(
        parse=int((t_parse1 - t_parse0) * 1000),
        validate_ms=0,
        compile_ms=0,
        llm=llm_timing,
    )
    say_text = _say_text_for_scenario_preview(
        "PREVIEW_READY",
        clarification,
        [],
        automation_count=len(automations),
    )
    return ScenarioPreviewResponse(
        ok=True,
        status="PREVIEW_READY",
        request_id=request_id,
        say_text=say_text,
        parsed_bundle=parsed,
        validated_bundle=validated,
        automations=automations,
        errors=[],
        clarification=None,
        timing_ms=timing,
    )


@app.post("/v1/scenario/save", response_model=ScenarioSaveResponse)
def scenario_save(
    req: ScenarioSaveRequest,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> ScenarioSaveResponse:
    _require_api_key(x_api_key)

    request_id = req.request_id or str(uuid.uuid4())
    errors: list[Dict[str, Any]] = []
    try:
        automations = _validate_save_automations(list(req.automations or []))
        auto_activate = bool(req.auto_activate)
        root_dir = getattr(app.state, "root_dir", _PROJECT_ROOT)
        config_file = _scenario_configuration_file(root_dir)
        automations_file = _resolve_scenario_automations_file(root_dir, config_file)
        existing = _load_generated_automations(automations_file)
        merged = _merge_generated_automations(existing, automations)
        _write_generated_automations(automations_file, merged)
        project_files: list[str] = []
        try:
            project_files = _export_project_blueprints(root_dir, automations)
        except Exception as e:
            errors.append({"code": "PROJECT_EXPORT_ERROR", "message": str(e)})

        include_hint = _scenario_include_hint(automations_file.name)
        include_detected = _configuration_includes_generated_automations(config_file, automations_file.name)
        status = "SAVED_NEEDS_INCLUDE"
        reloaded = False

        if auto_activate and _running_in_ha_addon() and not _ha_config_mount_available():
            errors.append(
                {
                    "code": "CONFIG_MOUNT_MISSING",
                    "message": "Add-on has no /config mount. Add `map: [config:rw]`, restart add-on and save again.",
                }
            )
            status = "SAVED_NEEDS_INCLUDE"
            include_detected = False
            include_hint = (
                "В add-on не смонтирован /config. Добавьте `map: [config:rw]` в config.yaml, "
                "перезапустите add-on и повторите сохранение."
            )
        elif auto_activate and include_detected:
            status, reloaded = _reload_automation_service(errors)
        elif auto_activate:
            activated = False

            upgraded = _upgrade_simple_automation_include_to_list(config_file, automations_file.name)
            if upgraded:
                activated = True
                include_detected = True
            elif not _has_automation_key(config_file):
                _append_gateway_include_to_configuration(config_file, automations_file.name)
                activated = True
                include_detected = True

            if activated:
                status, reloaded = _reload_automation_service(errors)
            else:
                status = "SAVED_NEEDS_INCLUDE"

        return ScenarioSaveResponse(
            ok=status != "ERROR",
            status=status,
            request_id=request_id,
            say_text=_say_text_for_scenario_save(
                status,
                saved_count=len(automations),
                include_hint=None if include_detected else include_hint,
                errors=errors,
            ),
            saved_automation_count=len(automations),
            file_automation_count=len(merged),
            storage_file=str(automations_file),
            include_detected=include_detected,
            reloaded=reloaded,
            include_hint=None if include_detected else include_hint,
            project_files=project_files,
            errors=errors,
        )
    except Exception as e:
        errors.append({"code": "SCENARIO_SAVE_ERROR", "message": str(e)})
        return ScenarioSaveResponse(
            ok=False,
            status="ERROR",
            request_id=request_id,
            say_text=_say_text_for_scenario_save(
                "ERROR",
                saved_count=0,
                include_hint=None,
                errors=errors,
            ),
            saved_automation_count=0,
            file_automation_count=0,
            storage_file=None,
            include_detected=False,
            reloaded=False,
            include_hint=None,
            project_files=[],
            errors=errors,
        )


@app.get("/v1/scenario/list", response_model=ScenarioListResponse)
def scenario_list(
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> ScenarioListResponse:
    _require_api_key(x_api_key)

    errors: list[Dict[str, Any]] = []
    try:
        root_dir = getattr(app.state, "root_dir", _PROJECT_ROOT)
        config_file = _scenario_configuration_file(root_dir)
        automations_file = _resolve_scenario_automations_file(root_dir, config_file)
        automations = _load_generated_automations(automations_file)
        items: list[ScenarioListItem] = []

        for item in automations:
            automation_id = str(item.get("id") or "").strip()
            if not automation_id:
                continue
            alias = str(item.get("alias") or automation_id).strip() or automation_id
            items.append(
                ScenarioListItem(
                    automation_id=automation_id,
                    alias=alias,
                    trigger_summary=_scenario_trigger_summary(item),
                    action_summary=_scenario_action_summary(item),
                    automation=item,
                )
            )

        items.sort(key=lambda it: it.alias.lower())
        return ScenarioListResponse(
            ok=True,
            storage_file=str(automations_file),
            file_automation_count=len(automations),
            items=items,
            errors=errors,
        )
    except Exception as e:
        errors.append({"code": "SCENARIO_LIST_ERROR", "message": str(e)})
        return ScenarioListResponse(
            ok=False,
            storage_file=None,
            file_automation_count=0,
            items=[],
            errors=errors,
        )


@app.post("/v1/scenario/upsert", response_model=ScenarioSaveResponse)
def scenario_upsert(
    req: ScenarioUpsertRequest,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> ScenarioSaveResponse:
    _require_api_key(x_api_key)
    return scenario_save(
        ScenarioSaveRequest(
            validated_bundle=None,
            automations=[req.automation],
            auto_activate=req.auto_activate,
            request_id=req.request_id,
        ),
        x_api_key=x_api_key,
    )


@app.post("/v1/scenario/delete", response_model=ScenarioDeleteResponse)
def scenario_delete(
    req: ScenarioDeleteRequest,
    x_api_key: Optional[str] = Header(default=None, alias="X-API-Key"),
) -> ScenarioDeleteResponse:
    _require_api_key(x_api_key)

    request_id = req.request_id or str(uuid.uuid4())
    errors: list[Dict[str, Any]] = []

    try:
        automation_id = str(req.automation_id or "").strip()
        if not automation_id:
            raise ValueError("automation_id is required")

        auto_activate = bool(req.auto_activate)
        root_dir = getattr(app.state, "root_dir", _PROJECT_ROOT)
        config_file = _scenario_configuration_file(root_dir)
        automations_file = _resolve_scenario_automations_file(root_dir, config_file)

        existing = _load_generated_automations(automations_file)
        kept: list[Dict[str, Any]] = []
        removed: list[Dict[str, Any]] = []
        for item in existing:
            current_id = str(item.get("id") or "").strip()
            if current_id == automation_id:
                removed.append(item)
            else:
                kept.append(item)

        include_hint = _scenario_include_hint(automations_file.name)
        include_detected = _configuration_includes_generated_automations(config_file, automations_file.name)

        if not removed:
            status = "NOT_FOUND"
            return ScenarioDeleteResponse(
                ok=True,
                status=status,
                request_id=request_id,
                say_text=_say_text_for_scenario_delete(
                    status,
                    automation_id=automation_id,
                    include_hint=None,
                    errors=errors,
                ),
                deleted_automation_id=None,
                file_automation_count=len(existing),
                storage_file=str(automations_file),
                include_detected=include_detected,
                reloaded=False,
                include_hint=None if include_detected else include_hint,
                project_files_removed=[],
                errors=errors,
            )

        _write_generated_automations(automations_file, kept)
        removed_project_files: list[str] = []
        for item in removed:
            try:
                removed_file = _remove_project_blueprint_for_automation(root_dir, item)
                if removed_file:
                    removed_project_files.append(removed_file)
            except Exception as e:
                errors.append({"code": "PROJECT_DELETE_ERROR", "message": str(e)})

        status = "DELETED_PENDING_RELOAD"
        reloaded = False

        if auto_activate and include_detected:
            try:
                _make_ha_client().call_service("automation.reload", {})
                status = "DELETED_ACTIVE"
                reloaded = True
            except Exception as e:
                errors.append({"code": "AUTOMATION_RELOAD_ERROR", "message": str(e)})
                status = "DELETED_PENDING_RELOAD"

        return ScenarioDeleteResponse(
            ok=True,
            status=status,
            request_id=request_id,
            say_text=_say_text_for_scenario_delete(
                status,
                automation_id=automation_id,
                include_hint=None if include_detected else include_hint,
                errors=errors,
            ),
            deleted_automation_id=automation_id,
            file_automation_count=len(kept),
            storage_file=str(automations_file),
            include_detected=include_detected,
            reloaded=reloaded,
            include_hint=None if include_detected else include_hint,
            project_files_removed=removed_project_files,
            errors=errors,
        )
    except Exception as e:
        errors.append({"code": "SCENARIO_DELETE_ERROR", "message": str(e)})
        return ScenarioDeleteResponse(
            ok=False,
            status="ERROR",
            request_id=request_id,
            say_text=_say_text_for_scenario_delete(
                "ERROR",
                automation_id=req.automation_id,
                include_hint=None,
                errors=errors,
            ),
            deleted_automation_id=None,
            file_automation_count=0,
            storage_file=None,
            include_detected=False,
            reloaded=False,
            include_hint=None,
            project_files_removed=[],
            errors=errors,
        )


@app.post("/v1/quick-action", response_model=CommandResponse)
def quick_action(req: QuickActionRequest, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> CommandResponse:
    _require_api_key(x_api_key)

    request_id = req.request_id or str(uuid.uuid4())
    parser_mode_used: ParserMode = "rules"
    device_registry = app.state.assets.get("device_registry") or {}
    catalog = _build_catalog(device_registry)
    device_type = str(req.target.device_type or "").strip().lower()
    parsed_command: Dict[str, Any] = {"schema_version": "1.0", "actions": []}
    validated_command: Optional[Dict[str, Any]] = None
    clarification = None

    target, entity_ids, area_name, target_error = _resolve_quick_action_target(
        device_registry,
        area_name=req.target.area_name,
        device_type=device_type,
        device_id=req.target.device_id,
    )
    target_devices = _resolve_catalog_target_devices(
        catalog,
        area_name=area_name,
        device_type=device_type,
        device_id=req.target.device_id,
    )
    if target_error is not None or target is None or not entity_ids:
        errors = [target_error or {"code": "NO_TARGET", "message": "No entities resolved"}]
        timing = TimingMs(parse=0, validate_ms=0, execute=0, llm=None)
        status = "ERROR"
        say_text = _say_text_for(status, clarification, errors)
        log_text = f"[quick] {req.action_id} {device_type} {req.target.device_id or req.target.area_name or ''}".strip()
        _log(log_text, request_id, parser_mode_used, status, errors, [], timing)
        return CommandResponse(
            ok=False,
            status=status,
            request_id=request_id,
            say_text=say_text,
            parser_mode_used=parser_mode_used,
            parsed_command=parsed_command,
            validated_command=validated_command,
            calls=[],
            errors=errors,
            clarification=clarification,
            timing_ms=timing,
        )

    supported_actions = _intersect_supported_quick_actions(target_devices)
    normalized_action_id = str(req.action_id or "").strip().upper()
    if supported_actions and normalized_action_id not in supported_actions:
        errors = [{
            "code": "UNSUPPORTED_ACTION_FOR_TARGET",
            "message": f"action_id={normalized_action_id} is not supported for selected target",
        }]
        timing = TimingMs(parse=0, validate_ms=0, execute=0, llm=None)
        status = "ERROR"
        say_text = _say_text_for(status, clarification, errors)
        log_text = f"[quick] {req.action_id} {device_type} {req.target.device_id or req.target.area_name or ''}".strip()
        _log(log_text, request_id, parser_mode_used, status, errors, [], timing)
        return CommandResponse(
            ok=False,
            status=status,
            request_id=request_id,
            say_text=say_text,
            parser_mode_used=parser_mode_used,
            parsed_command=parsed_command,
            validated_command=validated_command,
            calls=[],
            errors=errors,
            clarification=clarification,
            timing_ms=timing,
        )

    t_ex0 = time.perf_counter()
    if device_type == "light":
        validated_command = _light_validated_quick_action(
            action_id=req.action_id,
            target=target,
            entity_ids=entity_ids,
            area_name=area_name,
        )
        if validated_command is None:
            errors = [{"code": "UNSUPPORTED_ACTION", "message": f"Unsupported light action_id={req.action_id}"}]
            calls = []
            ok = False
            status = "ERROR"
        elif req.dry_run:
            parsed_command = dict(validated_command.pop("_parsed_command", parsed_command))
            calls, errors = build_service_calls_from_validated(
                validated_command,
                device_registry=device_registry,
                client=None,
                cfg=ExecutionConfig(dry_run=True),
            )
            ok = len(errors) == 0
            status = "DRY_RUN" if ok else "ERROR"
        else:
            parsed_command = dict(validated_command.pop("_parsed_command", parsed_command))
            try:
                exec_res = execute_validated_on_ha(
                    validated_command,
                    device_registry=device_registry,
                    client=_make_ha_client(),
                    cfg=ExecutionConfig(dry_run=False),
                )
                calls = exec_res.calls
                errors = exec_res.errors
                ok = exec_res.ok
                status = "EXECUTED" if ok else "ERROR"
            except Exception as e:
                calls = []
                errors = [{"code": "EXEC_ERROR", "message": str(e)}]
                ok = False
                status = "ERROR"
    elif device_type == "switch":
        payload = _switch_quick_action_payload(
            action_id=req.action_id,
            target=target,
            entity_ids=entity_ids,
            area_name=area_name,
        )
        if payload is None:
            errors = [{"code": "UNSUPPORTED_ACTION", "message": f"Unsupported switch action_id={req.action_id}"}]
            calls = []
            ok = False
            status = "ERROR"
        else:
            parsed_command = payload["parsed_command"]
            validated_command = payload["validated_command"]
            ok, calls, errors = _execute_calls(calls=payload["calls"], dry_run=req.dry_run)
            status = "DRY_RUN" if req.dry_run and ok else "EXECUTED" if ok else "ERROR"
    else:
        errors = [{"code": "UNSUPPORTED_DEVICE_TYPE", "message": f"Unsupported device_type={device_type}"}]
        calls = []
        ok = False
        status = "ERROR"

    t_ex1 = time.perf_counter()
    timing = TimingMs(parse=0, validate_ms=0, execute=int((t_ex1 - t_ex0) * 1000), llm=None)
    say_text = _say_text_for(status, clarification, errors)
    log_text = f"[quick] {req.action_id} {device_type} {req.target.device_id or req.target.area_name or ''}".strip()
    _log(log_text, request_id, parser_mode_used, status, errors, calls, timing)

    return CommandResponse(
        ok=ok,
        status=status,
        request_id=request_id,
        say_text=say_text,
        parser_mode_used=parser_mode_used,
        parsed_command=parsed_command,
        validated_command=validated_command,
        calls=calls,
        errors=errors,
        clarification=clarification,
        timing_ms=timing,
    )


@app.post("/v1/command", response_model=CommandResponse)
def command(req: CommandRequest, x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> CommandResponse:
    _require_api_key(x_api_key)

    request_id = req.request_id or str(uuid.uuid4())

    # Context
    ctx = (req.context.model_dump() if req.context is not None else {})
    ctx.setdefault("last_area_name", None)
    ctx.setdefault("last_entity_ids", [])
    ctx.setdefault("selected_area_name", None)
    ctx.setdefault("last_color_name", None)
    ctx.setdefault("last_brightness", None)
    ctx.setdefault("last_color_temp_kelvin", None)
    ctx.setdefault("pending_clarification_slot", None)

    parser_mode = (req.parser_mode or "rules").strip().lower()
    llm_client = app.state.llm_client
    parsed_schema = app.state.assets.get("parsed_schema")

    # If llm requested but not configured:
    if parser_mode in {"llm_safe", "llm"} and llm_client is None:
        if parser_mode == "llm":
            raise HTTPException(status_code=400, detail="LLM is not configured (set LLM_BASE_URL)")
        parser_mode_used: ParserMode = "rules"
        llm_client_used = None
    else:
        parser_mode_used = parser_mode  # type: ignore
        llm_client_used = llm_client

    # Parse + validate via pipeline
    _reset_llm_call_info(llm_client_used)
    t_parse0 = time.perf_counter()
    pipeline_res = run_light_pipeline_v1(
        req.text,
        context=ctx,
        root_dir=app.state.root_dir,
        device_registry=app.state.assets["device_registry"],
        area_synonyms=app.state.assets["area_synonyms"],
        colors=app.state.assets["colors"],
        modifiers=app.state.assets["modifiers"],
        scene_aliases=app.state.assets.get("scene_aliases", {}),
        parser_mode=parser_mode_used,
        llm_client=llm_client_used,
        parsed_schema=parsed_schema,
    )
    t_parse1 = time.perf_counter()
    llm_timing = _collect_llm_timing(llm_client_used)

    parsed = pipeline_res.parsed
    validated = pipeline_res.validated

    # Parsed-stage clarification
    if pipeline_res.stage == "PARSED_CLARIFICATION":
        clarification = parsed.get("clarification")
        status = "NEEDS_CLARIFICATION"
        errors: list[Dict[str, Any]] = []
        calls: list[Dict[str, Any]] = []
        timing = TimingMs(parse=int((t_parse1 - t_parse0) * 1000), validate_ms=0, execute=0, llm=llm_timing)
        say_text = _say_text_for(status, clarification, errors)
        _log(req.text, request_id, parser_mode_used, status, errors, calls, timing)
        return CommandResponse(
            ok=True,
            status=status,
            request_id=request_id,
            say_text=say_text,
            parser_mode_used=parser_mode_used,
            parsed_command=parsed,
            validated_command=None,
            calls=calls,
            errors=errors,
            clarification=clarification,
            timing_ms=timing,
        )

    # Validated-stage clarification
    if isinstance(validated, dict) and validated.get("clarification"):
        if validated.get("status") in {"NEEDS_CLARIFICATION", "NOT_EXECUTABLE"}:
            clarification = validated.get("clarification")
            status = "NEEDS_CLARIFICATION"
            errors = []
            calls = []
            timing = TimingMs(parse=int((t_parse1 - t_parse0) * 1000), validate_ms=0, execute=0, llm=llm_timing)
            say_text = _say_text_for(status, clarification, errors)
            _log(req.text, request_id, parser_mode_used, status, errors, calls, timing)
            return CommandResponse(
                ok=True,
                status=status,
                request_id=request_id,
                say_text=say_text,
                parser_mode_used=parser_mode_used,
                parsed_command=parsed,
                validated_command=validated,
                calls=calls,
                errors=errors,
                clarification=clarification,
                timing_ms=timing,
            )

    # Execute
    t_ex0 = time.perf_counter()
    if not isinstance(validated, dict):
        errors = [{"code": "NO_VALIDATED", "message": "validated_command is missing"}]
        calls = []
        ok = False
        status = "ERROR"
        t_ex1 = time.perf_counter()
    elif req.dry_run:
        cfg = ExecutionConfig(dry_run=True)
        calls, errors = build_service_calls_from_validated(
            validated,
            device_registry=app.state.assets["device_registry"],
            client=None,
            cfg=cfg,
        )
        ok = len(errors) == 0
        status = "DRY_RUN" if ok else "ERROR"
        t_ex1 = time.perf_counter()
    else:
        try:
            ha_client = _make_ha_client()
            cfg = ExecutionConfig(dry_run=False)
            exec_res = execute_validated_on_ha(
                validated,
                device_registry=app.state.assets["device_registry"],
                client=ha_client,
                cfg=cfg,
            )
            calls = exec_res.calls
            errors = exec_res.errors
            ok = exec_res.ok
            status = "EXECUTED" if ok else "ERROR"
        except Exception as e:
            calls = []
            errors = [{"code": "EXEC_ERROR", "message": str(e)}]
            ok = False
            status = "ERROR"
        t_ex1 = time.perf_counter()

    timing = TimingMs(
        parse=int((t_parse1 - t_parse0) * 1000),
        validate_ms=0,
        execute=int((t_ex1 - t_ex0) * 1000),
        llm=llm_timing,
    )
    say_text = _say_text_for(status, None, errors)
    _log(req.text, request_id, parser_mode_used, status, errors, calls, timing)

    return CommandResponse(
        ok=ok,
        status=status,
        request_id=request_id,
        say_text=say_text,
        parser_mode_used=parser_mode_used,
        parsed_command=parsed,
        validated_command=validated,
        calls=calls,
        errors=errors,
        clarification=None,
        timing_ms=timing,
    )


def _log(
    raw_text: str,
    request_id: str,
    parser_mode_used: str,
    status: str,
    errors: list[Dict[str, Any]],
    calls: list[Dict[str, Any]],
    timing: TimingMs,
) -> None:
    device_registry = app.state.assets.get("device_registry") or {}
    allow_raw = should_log_raw_text(device_registry)
    redaction_mode = get_redaction_mode(device_registry)
    stored_text = raw_text if allow_raw else redact_text(raw_text, mode=redaction_mode)

    error_codes = [e.get("code") for e in errors][:3]
    services = []
    for c in calls[:5]:
        svc = c.get("service")
        if svc:
            services.append(svc)

    log_obj = {
        "time_utc": _now_iso(),
        "request_id": request_id,
        "text": stored_text,
        "parser_mode_used": parser_mode_used,
        "status": status,
        "ok": status in {"EXECUTED", "DRY_RUN", "NEEDS_CLARIFICATION"} and not errors,
        "errors": error_codes,
        "services": services,
        "timing_ms": timing.model_dump(by_alias=True),
    }

    try:
        _append_jsonl(app.state.log_path, log_obj)
    except Exception:
        # Logging must not break command execution.
        pass

