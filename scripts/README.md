# Scripts

- `run_all.sh` — the round-1 runbook as one script (freeze → RSI loop → skill
  corpora/training → gated eval → reports). Set `PYTHON` to the MLX
  interpreter if it is not `python`.
- `train_round2.py` — trains a second round of Le-Gates adapters on a fresh
  corpus (seed 1, 60 rows, 160 iters). It writes to `adapters/skills/r2/` and
  does not touch the round-1 adapters or the base model.
- `eval_round2.py` — evaluates round 1 vs round 2 on the public dev/probe splits
  and on a private holdout. The private holdout tasks are **not** included in
  this repository; generate your own under `tasks/private_holdout/` (10 tasks:
  8 skill variants + 2 unrelated controls) and keep their definitions out of
  the public tree.

```bash
python scripts/train_round2.py
python scripts/eval_round2.py
```
