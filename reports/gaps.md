# Skill gaps — `skills24_fixed_r2_skills_base`

- split: **skills**
- measured: **10/24**
- model: `MiMo-v2.6-distill-qwen-9b-mlx`
- generated: 2026-10-26T01:08:05
- policy: the public and private holdouts are excluded from gap mining

## Clusters

| skill | failed | total | errors | verified rows | missing |
|---|---|---|---|---|---|
| `word_freq` | 11 | 12 | assertion 10, runtime 1 | 22 | 0 |
| `merge_intervals` | 3 | 12 | assertion 3 | 6 | 0 |

## Corpus

- file: `20261026-010806-gap-skills24_fixed_r2_skills_base-raw.jsonl`
- rows: **28** (verified: 28)
- by kind: `{"success": 14, "repair": 14}`
- missing references: 0
- next: import the raw file, review it, and export through the hard gates

A missing reference is shown as missing on purpose. This report never
contains hidden tests, holdout prompts, or invented solutions.
