# Private holdout + round 2

10 synthetic tasks, withheld from the public repository: 4 word-frequency
variants, 4 interval variants, 2 unrelated controls. The function names
and test data are new; the adapters never saw them.

| run | base | gated | delta | routed | non-routed identical | base unchanged |
|---|---|---|---|---|---|---|
| round 1 | 5/10 (0.50) | 10/10 (1.00) | +0.50 | 8 | True | True |
| round 2 | 5/10 (0.50) | 10/10 (1.00) | +0.50 | 8 | True | True |

| task | skill | round 1 | round 2 | delta |
|---|---|---|---|---|
| `priv_mi_1` | `merge_intervals` | True | True | 0 |
| `priv_mi_2` | `merge_intervals` | True | True | 0 |
| `priv_mi_3` | `merge_intervals` | True | True | 0 |
| `priv_mi_4` | `merge_intervals` | True | True | 0 |
| `priv_wf_1` | `word_freq` | True | True | 0 |
| `priv_wf_2` | `word_freq` | True | True | 0 |
| `priv_wf_3` | `word_freq` | True | True | 0 |
| `priv_wf_4` | `word_freq` | True | True | 0 |

## Decision

- private holdout delta: **+0.00**
- public dev delta: +0.00
- public 24-probe delta: +0.00
- zero-forgetting checks: True
- **promote round 2: False**
- reason: private holdout tie; keep round 1

The task definitions are withheld; only aggregate and per-task-id outcomes
are reported. A future blind claim needs a fresh private holdout again.

