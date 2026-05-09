# SmartHome Assistant

SmartHome Assistant is a prototype system for controlling smart-home devices with natural-language commands. The project combines an Android application, a local gateway server, a rule-based command parser, an LLM-based interpreter, scenario generation, and integration with Home Assistant.

The system was developed as part of a master's thesis on local AI-assisted smart-home control. The main focus is not just sending commands to devices, but building a controlled processing pipeline where natural-language interpretation is separated from actual device execution.

## What The System Does

- Accepts text and voice commands from an Android application.
- Supports three command interpretation modes: `rules`, `llm`, and `llm_safe`.
- Converts user phrases into structured commands before execution.
- Validates commands before sending them to Home Assistant.
- Supports quick actions for common lighting controls.
- Generates automation scenarios from natural-language descriptions.
- Provides scenario preview, save, list, update, and delete operations.
- Can work with a local LLM through an OpenAI-compatible API.
- Keeps LLM output away from direct device execution.

The current implementation is focused primarily on lighting control because lighting is a clear and practical smart-home domain: it includes on/off actions, brightness, color, color temperature, presets, and scheduled automations.

## Architecture

```text
Android application
        |
        | HTTP + X-API-Key
        v
SmartHome Gateway
        |
        | rules / llm / llm_safe
        v
Command interpretation and validation
        |
        | validated actions
        v
Home Assistant
        |
        v
Smart-home devices

Optional:
SmartHome Gateway -> OpenAI-compatible local LLM bridge -> local LLM
```

The gateway is the central control point. The Android application does not execute smart-home actions directly. LLM output is also not sent directly to Home Assistant: it is parsed, normalized, validated, and only then converted into executable actions.

## Repository Structure

```text
.
├─ android_app/
│  └─ Android client application
├─ ha_addon_dist/
│  └─ Home Assistant add-on package for the gateway
├─ smarthome_core/
│  ├─ data/              Test datasets used in evaluation
│  ├─ lexicon/           Dictionaries for rule-based interpretation
│  ├─ registry/          Test device registry
│  ├─ schemas/           JSON Schemas for internal command formats
│  ├─ scripts/           Evaluation and benchmark scripts
│  ├─ smarthome_core/    Core parser, validator, LLM and scenario logic
│  ├─ smarthome_gateway/ Gateway HTTP API
│  └─ tests/             Automated tests
├─ docs/
│  ├─ experiments/       Experiment summaries
│  ├─ thesis_figures/    Architecture diagrams
│  └─ REPOSITORY_CONTENTS.md
├─ llama_openai_bridge.py
├─ ollama_openai_shim.py
├─ pyproject.toml
└─ requirements_gateway.txt
```

## Main Components

### Android Application

The Android app provides the user interface for:

- entering text commands;
- using push-to-talk voice input;
- selecting a room, target device, or control profile;
- sending quick actions;
- creating and managing automation scenarios;
- switching parser modes in developer mode.

The Android app is located in `android_app/`.

### SmartHome Gateway

The gateway is a Python HTTP service that coordinates command processing:

- receives requests from the Android app;
- selects the interpretation mode;
- calls the rule-based parser or the LLM interpreter;
- validates the structured result;
- optionally executes the action in Home Assistant;
- supports dry-run execution for safe testing;
- exposes scenario preview/save/list/upsert/delete operations.

The gateway code is located in `smarthome_core/smarthome_gateway/`.

### Rule-Based Interpreter

The rule-based module handles common and deterministic commands using dictionaries, normalization, patterns, and device/area mappings. It is fast and predictable, which makes it useful for direct commands such as turning lights on or changing brightness.

### LLM Interpreter

The LLM interpreter is used for less direct phrases, mood-like commands, and natural-language scenario descriptions. The gateway expects an OpenAI-compatible API, so different local LLM runtimes can be used behind the same interface.

### Home Assistant Integration

Home Assistant is used as the execution environment. The gateway sends only validated actions to Home Assistant and can be packaged as a Home Assistant add-on.

## Requirements

### Gateway

- Python 3.11 or newer.
- Home Assistant instance.
- Home Assistant Long-Lived Access Token or Supervisor token in add-on mode.
- Optional local LLM server with an OpenAI-compatible API.

### Android Application

- Android Studio.
- Java 17.
- Android device or emulator.
- Network access from the phone to the gateway.

### Optional Voice Input Assets

Local ASR assets are not committed to this repository because of their size. If voice input is required, place the models manually:

```text
android_app/app/src/main/assets/models/vosk-model-small-ru-0.22/
android_app/app/src/main/assets/models/sherpa-onnx-small-zipformer-ru-2024-09-18/
android_app/app/libs/sherpa-onnx-1.12.34.aar
```

The Android application can still be inspected and built after adding the required local ASR resources.

## Running The Gateway Locally

From the repository root:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements_gateway.txt
```

Set the required environment variables:

```powershell
$env:HA_URL = "http://homeassistant.local:8123"
$env:HA_TOKEN = "<HOME_ASSISTANT_LONG_LIVED_TOKEN>"
$env:GATEWAY_API_KEY = "change-me"
$env:SH_CORE_ROOT = "."
```

If a local LLM bridge is used:

```powershell
$env:LLM_BASE_URL = "http://127.0.0.1:8080/v1"
$env:LLM_MODEL = "qwen3:8b"
```

Run the gateway:

```powershell
python -m uvicorn smarthome_gateway.main:app --host 0.0.0.0 --port 8099
```

Example dry-run request:

```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8099/v1/command" `
  -Headers @{"X-API-Key"="change-me"} `
  -ContentType "application/json" `
  -Body '{"text":"в спальне сделай свет теплее","parser_mode":"llm_safe","dry_run":true}'
```

## Running As Home Assistant Add-On

The add-on package is located in:

```text
ha_addon_dist/smarthome_gateway_next/
```

The add-on configuration includes:

- `gateway_api_key`;
- `ha_url`;
- `ha_token` or Supervisor token mode;
- `llm_base_url`;
- `llm_model`;
- logging and timeout settings.

The default `config.yaml` contains example values only. Replace them with your local configuration before deployment.

## Android Setup

1. Open `android_app/` in Android Studio.
2. Add ASR assets if local voice input is required.
3. Build and install the APK.
4. Open the app settings.
5. Set the gateway URL, for example:

```text
http://<gateway-host>:8099
```

6. Set the same API key as configured in the gateway.
7. Select the parser mode:

```text
rules
llm
llm_safe
```

For normal use, `llm_safe` is the recommended mode: rules handle clear commands, while more complex phrases can be passed to the LLM path.

## LLM Bridge Options

The gateway expects an OpenAI-compatible chat completion API. Two helper scripts are included:

- `ollama_openai_shim.py` for adapting Ollama-style local models;
- `llama_openai_bridge.py` for llama.cpp-style local inference.

You can also use any other local server that exposes an OpenAI-compatible `/chat/completions` endpoint.

## Test And Evaluation Data

Selected datasets and experiment scripts are included for reproducibility:

```text
smarthome_core/data/
smarthome_core/scripts/
docs/experiments/
```

The datasets include:

- 100 Russian lighting commands for command interpretation evaluation;
- direct and creative command subsets;
- 24 automation scenario prompts;
- 50 creative bedroom-light commands used for comparison with Yandex Alice.

## Running Tests

Python tests:

```powershell
cd smarthome_core
python -m pytest tests
```

Android unit tests can be run from Android Studio or Gradle after the Android project is configured.

## Security Notes

- Do not commit real Home Assistant tokens.
- Do not commit real gateway API keys.
- Do not expose the gateway outside a trusted network without additional authentication and transport security.
- Keep LLM execution local if privacy is a requirement.
- Use dry-run mode when testing new parser or prompt changes.

## What Is Not Included

The repository does not include:

- local ASR models;
- local LLM model weights;
- APK build artifacts;
- Home Assistant secrets;
- runtime logs;
- full thesis text.

Only source code, selected reproducible datasets, experiment summaries, schemas, and diagrams are included.

## Documentation

Additional documentation is available in:

```text
docs/REPOSITORY_CONTENTS.md
docs/appendices.md
docs/experiments/
docs/thesis_figures/
```

The `docs/` directory is included to connect the implementation with the evaluation materials used in the thesis.
