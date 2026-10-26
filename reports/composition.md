# Composition experiment — two skills, one compound task

Each compound task requires `word_freq` and `merge_intervals` in one
solution. `dual_full` is gate 1.0 + 1.0 (Σ=2); `dual_half` is 0.5 + 0.5
(Σ=1). The deployed router is also Σ≤1.

Parts subset: probe_wf_1, probe_wf_7, probe_wf_12, probe_mi_1, probe_mi_7, probe_mi_12

| config | parts word | parts merge | whole | word fn ok | merge fn ok |
|---|---|---|---|---|---|
| `base` | 0/3 | 2/3 | **0/5** | 1/5 | 4/5 |
| `word` | 3/3 | 1/3 | **1/5** | 5/5 | 1/5 |
| `merge` | 0/3 | 3/3 | **0/5** | 4/5 | 1/5 |
| `dual_full` | 3/3 | 3/3 | **0/5** | 4/5 | 1/5 |
| `dual_half` | 3/3 | 3/3 | **0/5** | 5/5 | 0/5 |

Reading: a single gate can pass its own part and still fail the whole.
The paper's 0.5B result predicts that two full gates can collapse; this
matrix reports what actually happened on this rig, not a forced result.
