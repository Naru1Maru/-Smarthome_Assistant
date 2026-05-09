# SmartHome Gateway Next (Home Assistant add-on)

Версия: `1.2.12`.

Add-on запускает SmartHome Gateway внутри Home Assistant и поддерживает:
- `rules`, `llm_safe`, `llm`;
- быстрые действия (`/v1/quick-action`);
- полный цикл сценариев:
  - preview;
  - save;
  - list;
  - upsert (ручное редактирование);
  - delete.

## Ключевые изменения в 1.2.12
- API управления сценариями (`list/upsert/delete`);
- удаление проектного файла при удалении сценария;
- короткие summary полей trigger/action для UI;
- стабилизированная логика сохранения/активации сценариев в HA.

## Рекомендуемые опции add-on
- `ha_url: http://supervisor/core`
- `use_supervisor_token: true`
- `ha_token: ""`
- `map: [config:rw]` (обязательно для сохранения в `/config`)
- порт: `8109 -> 8099`

## Переустановка
1. Остановить старый add-on.
2. Обновить папку `smarthome_gateway_next` в `addons/local`.
3. Обновить список add-on и перезапустить Home Assistant.
4. Запустить add-on и проверить лог `Uvicorn running on http://0.0.0.0:8099`.

## Проверка сохранения сценария
При успешном `save` в ответе:
- `storage_file` должен быть в `/config/...`;
- статус `SAVED_ACTIVE` означает, что `automation.reload` выполнен;
- `project_files` указывает файлы в `/config/blueprints/automation/homeassistant/`.

Сценарии из project-файлов видны в разделе HA `Проекты`; для применения подтверждаются кнопкой `Сохранить`.

