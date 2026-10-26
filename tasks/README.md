# Tasks

The benchmark is synthetic Python coding tasks with hidden `unittest` tests.

| split | count | purpose |
|---|---|---|
| `dev` | 20 | harness and adapter development |
| `holdout` | 10 | public regression guard |
| `skills` | 12 | held-out skill probes (not in any adapter corpus) |

Each task JSON contains the prompt, the hidden tests, the entry filename, a
timeout, and tags. Reference solutions live in `build_tasks.py` and are proven
to pass their own tests before a task is written.

```bash
python3 tasks/build_tasks.py   # verifies references and rewrites the JSONs
```

## Public benchmark disclosure

The 10 holdout tasks are in this repository. That makes them a **public
regression set**, not a blind holdout. For a future claim that depends on a
blind evaluation, generate a fresh holdout with the same builder, freeze its
hashes, and do not inspect it before the final run.

## Skill probes

`tasks/skills/` contains 12 probes across two skills (`word_freq`,
`merge_intervals`) with function names that are **not** in the training corpora
(`token_frequency`, `merge_intervals_sorted`, `merge_closed_intervals`,
`range_merger`). They are the generalization check for the Le-Gates adapters.
