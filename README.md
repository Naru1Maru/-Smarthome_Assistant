# SmartHome Assistant

Локальный ассистент для управления умным домом без облачных сервисов.

## Состав проекта
- `android_app/` — Android-клиент (Jetpack Compose).
- `smarthome_core/` — парсер, валидация, сценарии и HTTP gateway.
- `ha_addon_dist/` — готовая сборка Home Assistant add-on.
- `screenshots/` — скриншоты интерфейса.

## Как работает система
```text
Android-приложение -> SmartHome Gateway -> Home Assistant -> устройства
                    -> локальная LLM (llm/llm_safe/authoring)
```

## Что реализовано сейчас
- три parser-режима: `rules`, `llm_safe`, `llm`;
- быстрые действия с выбором цели: комната -> тип устройства -> конкретное устройство/профиль;
- отдельная вкладка сценариев:
  - LLM-preview (`/v1/scenario/preview`);
  - сохранение в HA (`/v1/scenario/save`);
  - загрузка списка (`/v1/scenario/list`);
  - ручное редактирование (`/v1/scenario/upsert`);
  - удаление (`/v1/scenario/delete`);
- пользовательский UI и скрываемая вкладка разработчика (включается переключателем);
- локальный офлайн ASR на Android: `Vosk` и `Sherpa-ONNX`.

## Быстрый запуск
1. Поднять gateway по [smarthome_core/README_GATEWAY.md](smarthome_core/README_GATEWAY.md).
2. Открыть `android_app/` в Android Studio и собрать APK.
3. В приложении задать `Gateway URL` и `X-API-Key`.
4. Выбрать parser-режим и проверить соединение.

## Сценарии и Home Assistant
- Gateway сохраняет рабочий YAML сценариев в `/config/smarthome_gateway_automations.yaml` (в add-on режиме).
- Для HA Projects экспортируются файлы в `/config/blueprints/automation/homeassistant/`.
- В интерфейсе HA сценарии из Projects подтверждаются через кнопку `Сохранить`.

## Важное по чистоте репозитория
- локальные модели ASR/LLM не хранятся в Git;
- временные каталоги и тестовые артефакты добавлены в `.gitignore`.

