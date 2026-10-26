# Tasks

The benchmark is synthetic Python coding tasks with hidden `unittest` tests.

| split | count | purpose |
|---|---|---|
| `dev` | 20 | harness and adapter development |
| `holdout` | 10 | public regression guard |
| `skills` | 24 | held-out skill probes (not in any adapter corpus) |
| `composition` | 5 | two-skill compound tasks (`word_freq` + `merge_intervals`) |

Each task JSON contains the prompt, the hidden tests, the entry filename, a
timeout, and tags. Reference solutions live in `build_tasks.py` and are proven
to pass their own tests before a task is written.

```bash
python3 tasks/build_tasks.py   # verifies references and rewrites the JSONs
```

## Prompt lint

A task must tell the model which function name to define. If the hidden tests
import a name that never appears in the prompt, the task is under-specified and
a failure is a benchmark bug, not a model failure.

```bash
python3 tasks/lint_tasks.py
```

This caught `probe_mi_2`, whose prompt originally omitted `merge_overlapping`.
The corrected prompt names the function; the first 23/24 run is superseded by
the corrected **24/24** run in `reports/`.

## Public benchmark disclosure

The 10 holdout tasks are in this repository. That makes them a **public
regression set**, not a blind holdout. For a future claim that depends on a
blind evaluation, generate a fresh holdout with the same builder, freeze its
hashes, and do not inspect it before the final run.

## Skill probes

`tasks/skills/` contains 24 probes across two skills (`word_freq`,
`merge_intervals`; 12 each) with function names and test cases that are **not**
in the training corpora. They are the generalization check for the Le-Gates
adapters. The original 12-probe subset is 12/12; the corrected expanded set is
**24/24**. The first run was 23/24 because one prompt omitted the function name;
the linter caught it.
