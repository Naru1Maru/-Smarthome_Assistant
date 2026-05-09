# SmartHome Gateway (локальный запуск)

Документ синхронизирован с `smarthome_core/README_GATEWAY.md`.

## Запуск
```powershell
cd smarthome_core
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements_gateway.txt

$env:HA_URL = "http://homeassistant.local:8123"
$env:HA_TOKEN = "<LONG_LIVED_TOKEN>"
$env:GATEWAY_API_KEY = "change-me"
$env:SH_CORE_ROOT = "."

python -m uvicorn smarthome_gateway.main:app --host 0.0.0.0 --port 8099
```

## Проверка
```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8099/v1/command" `
  -Headers @{"X-API-Key"="change-me"} `
  -ContentType "application/json" `
  -Body '{"text":"в спальне сделай свет потише","parser_mode":"rules","dry_run":false}'
```

## Основные API
- `/v1/command`
- `/v1/quick-action`
- `/v1/scenario/preview`
- `/v1/scenario/save`
- `/v1/scenario/list`
- `/v1/scenario/upsert`
- `/v1/scenario/delete`

## LLM-переменные
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_API_KEY` (опционально)
