# Eval100 Additional Metrics

Metrics were calculated from existing baseline and universal prompt reports. No additional LLM run was required.

## Metric Definitions
| metric | meaning |
|---|---|
| balanced_score | weighted score 0..100: semantic 45%, creative semantic 20%, status 20%, schema validity 10%, latency 5% |
| creative_gap_pp | gap between direct and creative phrases: direct semantic - creative semantic |
| exception_free_rate | share of requests without parse/validation exceptions |
| latency_score | normalized latency: 1.0 at 0 ms, 0.0 at 5000+ ms |
| semantic_per_second | semantic match adjusted by average latency; higher is better |
| semantic_per_1k_tokens | semantic match per 1000 tokens; rough token efficiency estimate |

## Best Prompt Per Model
| rank | model | prompt | balanced | semantic | creative | gap | status | schema | exception-free | avg ms | p95 ms | sem/sec | sem/1k tok |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | qwen3:8b | universal | 81.27 | 76.0% | 70.0% | +12.0 pp | 99.0% | 99.0% | 100.0% | 1631 | 1720 | 0.4660 | 0.5770 |
| 2 | gemma3:12b | universal | 77.43 | 71.0% | 72.0% | -2.0 pp | 99.0% | 93.0% | 100.0% | 3018 | 3235 | 0.2353 | 0.4889 |
| 3 | qwen25-7b-local:latest | baseline | 72.44 | 64.0% | 58.0% | +12.0 pp | 99.0% | 99.0% | 100.0% | 2658 | 3442 | 0.2408 | 1.0784 |
| 4 | qwen3:4b-instruct | universal | 72.19 | 61.0% | 56.0% | +10.0 pp | 99.0% | 98.0% | 100.0% | 1062 | 1170 | 0.5744 | 0.4655 |
| 5 | mistral-nemo:12b | universal | 69.17 | 61.0% | 58.0% | +6.0 pp | 99.0% | 97.0% | 100.0% | 4376 | 5245 | 0.1394 | 0.4214 |
| 6 | llama3.1:8b | universal | 67.37 | 55.0% | 58.0% | -6.0 pp | 99.0% | 87.0% | 100.0% | 2485 | 2783 | 0.2213 | 0.4359 |
| 7 | gemma3:4b | baseline | 62.20 | 51.0% | 52.0% | -2.0 pp | 89.0% | 87.0% | 100.0% | 2646 | 2768 | 0.1927 | 0.5858 |
| 8 | qwen2.5:3b | universal | 54.24 | 39.0% | 38.0% | +2.0 pp | 93.0% | 82.0% | 100.0% | 2712 | 3029 | 0.1438 | 0.2935 |

## All Model/Prompt Combinations
| rank | model | prompt | balanced | semantic | creative | status | avg ms | p95 ms | sem/sec | tokens avg |
|---:|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | qwen3:8b | universal | 81.27 | 76.0% | 70.0% | 99.0% | 1631 | 1720 | 0.4660 | 1317.1 |
| 2 | gemma3:12b | universal | 77.43 | 71.0% | 72.0% | 99.0% | 3018 | 3235 | 0.2353 | 1452.2 |
| 3 | gemma3:12b | baseline | 72.74 | 67.0% | 58.0% | 99.0% | 3306 | 3460 | 0.2027 | 841.0 |
| 4 | qwen25-7b-local:latest | baseline | 72.44 | 64.0% | 58.0% | 99.0% | 2658 | 3442 | 0.2408 | 593.5 |
| 5 | qwen3:4b-instruct | universal | 72.19 | 61.0% | 56.0% | 99.0% | 1062 | 1170 | 0.5744 | 1310.4 |
| 6 | mistral-nemo:12b | universal | 69.17 | 61.0% | 58.0% | 99.0% | 4376 | 5245 | 0.1394 | 1447.5 |
| 7 | qwen25-7b-local:latest | universal | 68.29 | 56.0% | 54.0% | 100.0% | 2712 | 2971 | 0.2065 | 1093.3 |
| 8 | llama3.1:8b | universal | 67.37 | 55.0% | 58.0% | 99.0% | 2485 | 2783 | 0.2213 | 1261.8 |
| 9 | llama3.1:8b | baseline | 66.64 | 57.0% | 60.0% | 96.0% | 3710 | 3955 | 0.1536 | 734.9 |
| 10 | mistral-nemo:12b | baseline | 64.61 | 53.0% | 56.0% | 99.0% | 4438 | 4640 | 0.1194 | 824.7 |
| 11 | gemma3:4b | baseline | 62.20 | 51.0% | 52.0% | 89.0% | 2646 | 2768 | 0.1927 | 870.6 |
| 12 | qwen3:8b | baseline | 60.91 | 46.0% | 44.0% | 97.0% | 2593 | 3119 | 0.1774 | 781.3 |
| 13 | gemma3:4b | universal | 59.57 | 45.0% | 36.0% | 98.0% | 1482 | 1589 | 0.3036 | 1453.0 |
| 14 | qwen2.5:3b | universal | 54.24 | 39.0% | 38.0% | 93.0% | 2712 | 3029 | 0.1438 | 1328.7 |
| 15 | qwen3:4b-instruct | baseline | 51.50 | 29.0% | 32.0% | 96.0% | 1252 | 1877 | 0.2316 | 730.9 |
| 16 | qwen2.5:3b | baseline | 44.89 | 37.0% | 34.0% | 64.0% | 2762 | 4026 | 0.1340 | 732.3 |

## Not Yet Measured
- Intent/category confusion matrix: requires per-record predictions.
- Precision/recall/F1 by command type: turn_on, turn_off, brightness, color, color_temp, combined.
- Clarification precision/recall on a special dataset with intentionally ambiguous commands.
- Repeatability: multiple runs of the same model/prompt to measure variance.
- Real Home Assistant execution success rate: requires end-to-end execution logs from HA.
- RAM/CPU/VRAM usage during inference: requires OS-level telemetry during benchmark.
