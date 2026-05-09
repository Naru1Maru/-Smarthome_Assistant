# Operational Metrics

- command sample size: `1`
- command repeats: `1`
- command mode: LLM, dry-run execution

## Command Performance
| model | prompt | e2e p50 | e2e p95 | e2e p99 | e2e std | parse p95 | validate p95 | execute p95 | llm p95 | exec error |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| qwen25-7b-local:latest | baseline | 5734 | 5734 | 5734 | 0.0 | 5733 | 1 | 0 | 5731 | 0.0% |

## Command Stability
| model | prompt | per-request std avg | per-request std p95 |
|---|---|---:|---:|
| qwen25-7b-local:latest | baseline | 0.0 | 0 |

## Reliability
| metric | value | note |
|---|---:|---|
| Retry Recovery Rate | 0.0% | executor currently stops after first HA error; retry is not implemented |
| 24h soak success rate | not measured | requires real 24-hour run against HA |

## Scenario Quality
- scenario sample size: `24`
- scenario source: `data/scenario_eval24_ru_v1.jsonl`
| model | Preview Ready | Valid JSON/Schema | HA Save Active | Manual Edit Success | Delete Consistency | preview p95 | llm p95 |
|---|---:|---:|---:|---:|---:|---:|---:|
| qwen25-7b-local:latest | 95.8% | 95.8% | 100.0% | 100.0% | 100.0% | 17963 | 17959 |

## UX Metrics
| metric | status |
|---|---|
| Task Completion Rate | not measured; requires 8-10 task user study |
| Task Time median | not measured; requires recorded user sessions |
| SUS / Likert survey | not measured; requires respondent answers |
