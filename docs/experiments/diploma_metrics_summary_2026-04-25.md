# Сводка метрик для дипломной работы

## 1. Качество LLM-парсинга обычных команд

| Модель | Prompt | Weighted F1 | Macro F1 | Exact action | Clarification F1 | Repeat stable | Avg latency |
|---|---|---:|---:|---:|---:|---:|---:|
| qwen3:8b | universal | 83.7% | 84.5% | 73.0% | 66.7% | 100.0% | 1.61 c |
| gemma3:12b | universal | 78.8% | 80.4% | 66.0% | 100.0% | 100.0% | 3.03 c |
| qwen25-7b-local | baseline | 75.4% | 79.0% | 64.0% | 75.0% | 91.7% | 2.39 c |
| qwen3:4b-instruct | universal | 69.0% | 70.1% | 42.0% | 33.3% | 91.7% | 1.05 c |
| mistral-nemo:12b | universal | 65.4% | 64.7% | 52.0% | 18.2% | 100.0% | 4.51 c |
| llama3.1:8b | universal | 60.4% | 60.7% | 47.0% | 33.3% | 83.3% | 2.43 c |
| gemma3:4b | baseline | 59.2% | 60.8% | 34.0% | 100.0% | 83.3% | 2.39 c |
| qwen2.5:3b | universal | 40.9% | 45.2% | 24.0% | 0.0% | 83.3% | 2.72 c |

## 2. Производительность команд (LLM-only, dry-run)

Набор: 20 команд, 3 повтора на команду.

| Модель | Prompt | E2E p50 | E2E p95 | E2E p99 | E2E std | Parse p95 | Validate p95 | Execute p95 | LLM p95 | Execution Error Rate |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| qwen3:4b-instruct | universal | 918 ms | 1050 ms | 3530 ms | 337.3 ms | 1049 ms | 0 ms | 0 ms | 1048 ms | 0.0% |
| qwen3:8b | universal | 1359 ms | 1548 ms | 4528 ms | 408.2 ms | 1548 ms | 0 ms | 0 ms | 1546 ms | 0.0% |
| llama3.1:8b | universal | 2278 ms | 2497 ms | 5207 ms | 434.1 ms | 2497 ms | 0 ms | 0 ms | 2495 ms | 0.0% |
| qwen25-7b-local | baseline | 2134 ms | 2608 ms | 3970 ms | 318.6 ms | 2608 ms | 0 ms | 0 ms | 2606 ms | 0.0% |
| gemma3:4b | baseline | 2436 ms | 2641 ms | 5502 ms | 419.7 ms | 2641 ms | 0 ms | 0 ms | 2639 ms | 13.3% |
| qwen2.5:3b | universal | 2669 ms | 2822 ms | 4268 ms | 373.5 ms | 2822 ms | 0 ms | 0 ms | 2820 ms | 0.0% |
| gemma3:12b | universal | 2845 ms | 2977 ms | 7555 ms | 603.7 ms | 2977 ms | 0 ms | 0 ms | 2975 ms | 0.0% |
| mistral-nemo:12b | universal | 3614 ms | 4845 ms | 7056 ms | 825.1 ms | 4844 ms | 0 ms | 0 ms | 4843 ms | 0.0% |

## 3. Стабильность задержек

| Модель | Prompt | Avg std-dev per request | p95 std-dev per request |
|---|---|---:|---:|
| qwen3:4b-instruct | universal | 111.91 ms | 69 ms |
| qwen3:8b | universal | 152.22 ms | 107 ms |
| llama3.1:8b | universal | 150.41 ms | 261 ms |
| qwen25-7b-local | baseline | 94.55 ms | 89 ms |
| gemma3:4b | baseline | 117.28 ms | 105 ms |
| qwen2.5:3b | universal | 130.40 ms | 457 ms |
| gemma3:12b | universal | 123.71 ms | 24 ms |
| mistral-nemo:12b | universal | 336.88 ms | 832 ms |

## 4. Надёжность

| Метрика | Значение | Комментарий |
|---|---:|---|
| Execution Error Rate | 0.0% в большинстве моделей | Исключение: gemma3:4b дала 13.3% ошибок на dry-run sample. |
| Retry Recovery Rate | 0.0% | Retry пока не реализован в executor после HA-ошибки. |
| 24h soak success rate | не измерено | Нужен отдельный долгий прогон против реального HA. |

## 5. Сценарии (authoring pipeline)

### 5.1 Базовый замер до доработки prompt

| Модель | Scenario Preview Ready Rate | Valid JSON/Schema Rate | HA Save Active Rate | Manual Edit Success Rate | Delete Consistency Rate | Preview p95 | LLM p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| qwen3:8b | 16.7% | 16.7% | 100.0% | 100.0% | 100.0% | 4286 ms | 4283 ms |

### 5.2 Контрольный прогон после улучшения сценарного prompt и нормализации

Набор: 6 сценарных фраз (тот же контрольный набор из `operational_metrics.py`).

| Модель | Preview Ready | Комментарий |
|---|---:|---|
| qwen3:8b | 100.0% (6/6) | Все фразы собраны в валидный `ScenarioBundle`, без `NEEDS_CLARIFICATION`. |
| qwen25-7b-local:latest | 100.0% (6/6) | Убраны проблемы `TOO_MANY_ACTIONS`, дубли и неверные target-комбинации. |

## 6. UX-метрики (пока не закрыты)

| Метрика | Статус | Что требуется |
|---|---|---|
| Task Completion Rate | не измерено | 8-10 пользовательских задач с фиксацией успешности. |
| Task Time | не измерено | Замер медианного времени выполнения задач. |
| SUS / Likert | не измерено | Короткий опрос после тестирования. |

# Что означает каждая метрика

- **Weighted F1**: качество распознавания с учётом частоты классов.
- **Macro F1**: среднее качество по всем классам без учёта частоты.
- **Exact action**: доля запросов, где intent и параметры совпали полностью.
- **Clarification F1**: качество определения случаев, когда нужно уточнение.
- **Repeat stable**: повторяемость ответа при одинаковом запросе.
- **E2E latency p50/p95/p99**: время обработки запроса по квантилям.
- **Parse / Validate / Execute / LLM**: разбиение задержки по стадиям.
- **E2E std-dev**: разброс задержек между прогонами.
- **Execution Error Rate**: доля команд с ошибкой выполнения.
- **Retry Recovery Rate**: доля восстановлений после временной ошибки.
- **24h soak success rate**: доля успешных команд на длинном прогоне.
- **Scenario Preview Ready Rate**: доля сценариев, которые прошли до стадии preview.
- **Valid JSON/Schema Rate**: доля ответов LLM, которые дают валидный `ScenarioBundle`.
- **HA Save Active Rate**: доля сценариев, успешно сохранённых и активированных в HA.
- **Manual Edit Success Rate**: успешность upsert после ручной правки сценария.
- **Delete Consistency Rate**: консистентность удаления из storage и project-file.

# Итоговый вывод

Для обычных команд лучший баланс качества и скорости показывает `qwen3:8b` с `universal prompt`.  
Для сценариев после доработки prompt и нормализации pipeline достиг 6/6 на контрольном наборе как для `qwen3:8b`, так и для `qwen25-7b-local`.

Следующие обязательные шаги для диплома: провести UX-измерения и выполнить длительный 24h soak-тест на реальном контуре Home Assistant.
