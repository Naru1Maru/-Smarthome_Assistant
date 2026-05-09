# Eval100 Extended Metrics

- dataset: `data/light_gold_eval100_ru_v1.jsonl`
- prompt profile: best known profile per model

## Summary
| rank | model | prompt | weighted F1 | macro F1 | primary action exact | clar F1 | repeat stable | repeat stable+correct | avg ms | errors |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | qwen3:8b | universal | 83.7% | 84.5% | 73.0% | 66.7% | 100.0% | 91.7% | 1612 | 0 |
| 2 | gemma3:12b | universal | 78.8% | 80.4% | 66.0% | 100.0% | 100.0% | 66.7% | 3027 | 0 |
| 3 | qwen25-7b-local:latest | baseline | 75.4% | 79.0% | 64.0% | 75.0% | 91.7% | 58.3% | 2387 | 0 |
| 4 | qwen3:4b-instruct | universal | 69.0% | 70.1% | 42.0% | 33.3% | 91.7% | 0.0% | 1052 | 0 |
| 5 | mistral-nemo:12b | universal | 65.4% | 64.7% | 52.0% | 18.2% | 100.0% | 83.3% | 4508 | 0 |
| 6 | llama3.1:8b | universal | 60.4% | 60.7% | 47.0% | 33.3% | 83.3% | 0.0% | 2433 | 0 |
| 7 | gemma3:4b | baseline | 59.2% | 60.8% | 34.0% | 100.0% | 83.3% | 0.0% | 2390 | 0 |
| 8 | qwen2.5:3b | universal | 40.9% | 45.2% | 24.0% | 0.0% | 83.3% | 0.0% | 2716 | 0 |

## Per-Intent F1
### qwen3:8b (universal)
| intent | support | precision | recall | F1 |
|---|---:|---:|---:|---:|
| ADJUST_BRIGHTNESS | 12 | 91.7% | 91.7% | 91.7% |
| ADJUST_COLOR_TEMP | 8 | 100.0% | 62.5% | 76.9% |
| SET_BRIGHTNESS | 12 | 57.1% | 100.0% | 72.7% |
| SET_COLOR | 22 | 100.0% | 81.8% | 90.0% |
| SET_COLOR_TEMP | 22 | 73.7% | 63.6% | 68.3% |
| TURN_OFF | 12 | 100.0% | 91.7% | 95.7% |
| TURN_ON | 12 | 92.3% | 100.0% | 96.0% |

### gemma3:12b (universal)
| intent | support | precision | recall | F1 |
|---|---:|---:|---:|---:|
| ADJUST_BRIGHTNESS | 12 | 80.0% | 100.0% | 88.9% |
| ADJUST_COLOR_TEMP | 8 | 100.0% | 50.0% | 66.7% |
| SET_BRIGHTNESS | 12 | 80.0% | 100.0% | 88.9% |
| SET_COLOR | 22 | 69.6% | 72.7% | 71.1% |
| SET_COLOR_TEMP | 22 | 73.7% | 63.6% | 68.3% |
| TURN_OFF | 12 | 100.0% | 91.7% | 95.7% |
| TURN_ON | 12 | 83.3% | 83.3% | 83.3% |

### qwen25-7b-local:latest (baseline)
| intent | support | precision | recall | F1 |
|---|---:|---:|---:|---:|
| ADJUST_BRIGHTNESS | 12 | 100.0% | 91.7% | 95.7% |
| ADJUST_COLOR_TEMP | 8 | 100.0% | 50.0% | 66.7% |
| SET_BRIGHTNESS | 12 | 70.6% | 100.0% | 82.8% |
| SET_COLOR | 22 | 62.5% | 90.9% | 74.1% |
| SET_COLOR_TEMP | 22 | 63.6% | 31.8% | 42.4% |
| TURN_OFF | 12 | 100.0% | 100.0% | 100.0% |
| TURN_ON | 12 | 91.7% | 91.7% | 91.7% |

### qwen3:4b-instruct (universal)
| intent | support | precision | recall | F1 |
|---|---:|---:|---:|---:|
| ADJUST_BRIGHTNESS | 12 | 70.6% | 100.0% | 82.8% |
| ADJUST_COLOR_TEMP | 8 | 100.0% | 50.0% | 66.7% |
| SET_BRIGHTNESS | 12 | 50.0% | 83.3% | 62.5% |
| SET_COLOR | 22 | 77.8% | 63.6% | 70.0% |
| SET_COLOR_TEMP | 22 | 56.5% | 59.1% | 57.8% |
| TURN_OFF | 12 | 100.0% | 91.7% | 95.7% |
| TURN_ON | 12 | 83.3% | 41.7% | 55.6% |

### mistral-nemo:12b (universal)
| intent | support | precision | recall | F1 |
|---|---:|---:|---:|---:|
| ADJUST_BRIGHTNESS | 12 | 75.0% | 25.0% | 37.5% |
| ADJUST_COLOR_TEMP | 8 | 100.0% | 25.0% | 40.0% |
| SET_BRIGHTNESS | 12 | 44.4% | 100.0% | 61.5% |
| SET_COLOR | 22 | 73.9% | 77.3% | 75.6% |
| SET_COLOR_TEMP | 22 | 52.4% | 50.0% | 51.2% |
| TURN_OFF | 12 | 100.0% | 91.7% | 95.7% |
| TURN_ON | 12 | 91.7% | 91.7% | 91.7% |

### llama3.1:8b (universal)
| intent | support | precision | recall | F1 |
|---|---:|---:|---:|---:|
| ADJUST_BRIGHTNESS | 12 | 77.8% | 58.3% | 66.7% |
| ADJUST_COLOR_TEMP | 8 | 100.0% | 37.5% | 54.5% |
| SET_BRIGHTNESS | 12 | 60.0% | 100.0% | 75.0% |
| SET_COLOR | 22 | 67.9% | 86.4% | 76.0% |
| SET_COLOR_TEMP | 22 | 39.1% | 40.9% | 40.0% |
| TURN_OFF | 12 | 100.0% | 100.0% | 100.0% |
| TURN_ON | 12 | 25.0% | 8.3% | 12.5% |

### gemma3:4b (baseline)
| intent | support | precision | recall | F1 |
|---|---:|---:|---:|---:|
| ADJUST_BRIGHTNESS | 12 | 44.4% | 100.0% | 61.5% |
| ADJUST_COLOR_TEMP | 8 | 100.0% | 62.5% | 76.9% |
| SET_BRIGHTNESS | 12 | 25.0% | 8.3% | 12.5% |
| SET_COLOR | 22 | 68.4% | 59.1% | 63.4% |
| SET_COLOR_TEMP | 22 | 52.6% | 45.5% | 48.8% |
| TURN_OFF | 12 | 100.0% | 91.7% | 95.7% |
| TURN_ON | 12 | 100.0% | 50.0% | 66.7% |

### qwen2.5:3b (universal)
| intent | support | precision | recall | F1 |
|---|---:|---:|---:|---:|
| ADJUST_BRIGHTNESS | 12 | 100.0% | 41.7% | 58.8% |
| ADJUST_COLOR_TEMP | 8 | 100.0% | 25.0% | 40.0% |
| SET_BRIGHTNESS | 12 | 73.3% | 91.7% | 81.5% |
| SET_COLOR | 22 | 0.0% | 0.0% | 0.0% |
| SET_COLOR_TEMP | 22 | 30.3% | 90.9% | 45.5% |
| TURN_OFF | 12 | 100.0% | 83.3% | 90.9% |
| TURN_ON | 12 | 0.0% | 0.0% | 0.0% |

## Limits
- HA real execution success was not measured in this run.
- CPU/RAM/VRAM telemetry was not measured in this run.
