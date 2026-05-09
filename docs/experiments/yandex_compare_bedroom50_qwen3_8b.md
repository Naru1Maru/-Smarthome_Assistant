# Yandex vs App Bedroom Creative 50

- dataset: `c:\Users\narumaru\workspace\Diplom\smarthome_core\data\light_yandex_compare_bedroom_creative50_ru_v1.jsonl`
- yandex manual csv: `c:\Users\narumaru\workspace\Diplom\light_yandex_test.csv`
- model: `qwen3:8b`
- base_url: `http://127.0.0.1:8000`
- rows: 50

## Summary

| System / Metric | Overall | Explicit room | Implicit room |
|---|---:|---:|---:|
| Yandex `ok` | 35/50 (70.0%) | 13/25 (52.0%) | 22/25 (88.0%) |
| App `llm` strong semantic match | 36/50 (72.0%) | 18/25 (72.0%) | 18/25 (72.0%) |
| App `llm` usable semantic match | 39/50 (78.0%) | - | - |
| App `llm_safe` strong semantic match | 28/50 (56.0%) | 15/25 (60.0%) | 13/25 (52.0%) |
| App `llm_safe` usable semantic match | 34/50 (68.0%) | - | - |

## Notes

- `strong semantic match` means score `2`: the result is executable and semantically close to the intended effect.
- `usable semantic match` means score `1` or `2`: the result is executable and at least partially matches the intended effect.
- Yandex results are taken from manual marking in the provided CSV; in the current file only the binary field `yandex_executed` is used for aggregation.
- Full per-phrase comparison is stored in `c:\Users\narumaru\workspace\Diplom\smarthome_core\reports\yandex_compare_bedroom50_qwen3_8b.csv`.
