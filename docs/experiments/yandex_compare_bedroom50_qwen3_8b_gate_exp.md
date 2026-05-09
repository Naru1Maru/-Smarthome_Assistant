# Hybrid Gate Experiment: Bedroom Creative 50

- dataset: `c:\Users\narumaru\workspace\Diplom\smarthome_core\data\light_yandex_compare_bedroom_creative50_ru_v1.jsonl`
- model: `qwen3:8b`
- base_url: `http://127.0.0.1:8000`
- rows: 50
- experimental mode: `llm_safe_gate_exp`

## Summary

| System / Metric | Overall | Explicit room | Implicit room |
|---|---:|---:|---:|
| Yandex `ok` | 35/50 (70.0%) | 13/25 (52.0%) | 22/25 (88.0%) |
| App `llm` strong semantic match | 36/50 (72.0%) | 18/25 (72.0%) | 18/25 (72.0%) |
| App `llm_safe` strong semantic match | 28/50 (56.0%) | 15/25 (60.0%) | 13/25 (52.0%) |
| App `llm_safe_gate_exp` strong semantic match | 38/50 (76.0%) | 20/25 (80.0%) | 18/25 (72.0%) |
| App `llm_safe_gate_exp` usable semantic match | 41/50 (82.0%) | - | - |

## Gate Routing

| Route | Count |
|---|---:|
| rules accepted | 26 |
| sent to LLM | 24 |

## Notes

- The production `llm_safe` mode was not changed.
- The experimental gate rejects rules results for soft-off phrases, dimming phrases without brightness parameters, brighten phrases without brightness parameters, and mood/scene phrases without at least two semantic dimensions.
- Full per-phrase comparison is stored in `c:\Users\narumaru\workspace\Diplom\smarthome_core\reports\yandex_compare_bedroom50_qwen3_8b_gate_exp.csv`.
