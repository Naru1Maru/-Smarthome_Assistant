# Android-приложение SmartHome Assistant

Android-клиент для локального управления устройствами и сценариями.

## Функциональность
- вкладка `Управление`:
  - голосовая команда (push-to-talk);
  - текстовая команда;
  - быстрые действия для выбранной цели (комната/тип устройства/устройство);
- вкладка `Сценарии`:
  - построение сценария через LLM;
  - сохранение в Home Assistant;
  - список сохранённых сценариев;
  - ручное редактирование JSON automation и удаление;
- вкладка `Разработчик`:
  - диагностика сети/gateway;
  - parser mode, dry-run, технические детали;
  - доступ можно скрыть переключателем `Режим разработчика`.

## Требования
- Android Studio (AGP 9+), Java 17.
- `minSdk = 26`.
- Доступ к локальному gateway по LAN.

## Локальные ASR-ресурсы (в git не хранятся)

### Vosk
```text
app/src/main/assets/models/vosk-model-small-ru-0.22/
```

### Sherpa-ONNX
```text
app/src/main/assets/models/sherpa-onnx-small-zipformer-ru-2024-09-18/
```

Нужны файлы:
- `encoder.int8.onnx`
- `decoder.onnx`
- `joiner.int8.onnx`
- `tokens.txt`

### Sherpa AAR
```text
app/libs/sherpa-onnx-1.12.34.aar
```

## Сборка
```powershell
cd android_app
.\gradlew.bat :app:assembleDebug
```

APK:
```text
app/build/outputs/apk/debug/app-debug.apk
```

## Первый запуск
1. Установить APK.
2. Открыть `Разработчик`.
3. Указать `Gateway URL` и `X-API-Key`.
4. Проверить соединение.
5. При необходимости выбрать `parser mode`.

## Диагностические файлы
Во внутреннем хранилище приложения:
- `last_voice_clip.wav`
- `last_voice_clip.json`
- `voice_eval_history.jsonl`
- `voice_eval_history.csv`

