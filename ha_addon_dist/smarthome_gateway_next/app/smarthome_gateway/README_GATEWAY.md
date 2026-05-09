# SmartHome Gateway (документация для add-on пакета)

Этот файл дублирует основную инструкцию запуска gateway и оставлен в составе add-on для удобства.

## Основные API
- `/v1/command`
- `/v1/quick-action`
- `/v1/scenario/preview`
- `/v1/scenario/save`
- `/v1/scenario/list`
- `/v1/scenario/upsert`
- `/v1/scenario/delete`

## Локальная проверка
```powershell
Invoke-RestMethod -Method Post `
  -Uri "http://127.0.0.1:8099/v1/command" `
  -Headers @{"X-API-Key"="change-me"} `
  -ContentType "application/json" `
  -Body '{"text":"в спальне сделай свет потише","parser_mode":"rules","dry_run":false}'
```

## LLM-переменные
- `LLM_BASE_URL`
- `LLM_MODEL`
- `LLM_API_KEY` (опционально)
