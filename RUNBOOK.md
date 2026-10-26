# SkillForge runbook

One local loop: a frozen base, a measured harness search, per-skill adapters,
and a read-only dashboard.

## 0. Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dashboard]'
cp config.example.toml config.toml
mkdir -p models
ln -s /path/to/MiMo-v2.6-distill-qwen-9b-mlx  models/MiMo-v2.6-distill-qwen-9b-mlx
ln -s /path/to/Qwen3.6-35B-A3B-MLX-8bit       models/Qwen3.6-35B-A3B-MLX-8bit
```

The base is frozen. Training writes adapter files only; the base checksum is
recorded before and after every run.

## 1. Freeze and baseline

```bash
python -m forge_rsi freeze
python -m forge_rsi lint-tasks 2>/dev/null || python tasks/lint_tasks.py
python3 tasks/build_tasks.py
python -m forge_rsi eval --harness harness/h0_baseline.json \
  --split dev --run-id baseline_dev
```

Gate: the task linter passes; every reference solution passes its own tests.

## 2. RSI harness round

```bash
python -m forge_rsi loop --round r1 --iterations 5
```

A candidate is kept only if:

- `wins > losses` task-by-task,
- score is not more than `0.05` below the incumbent,
- cost per solved task is at most `1.5x` the incumbent,
- the anti-leak validator passes.

Ties keep the incumbent. The holdout is a regression guard, not an
optimization signal.

## 3. Le-Gates skill adapters

```bash
python -m forge_rsi skills-build \
  --skills word_freq,merge_intervals --rows 40
python -m forge_rsi skills-train \
  --skills word_freq,merge_intervals --iters 120

python -m forge_rsi skills-eval \
  --splits dev,holdout,skills --run-id legates_candidates
python -m forge_rsi skills-decide --run-prefix legates_candidates
python -m forge_rsi skills-eval \
  --splits dev,holdout,skills --run-id legates_final
```

A skill is promoted only if it gains on dev **and** on held-out probes, with no
non-routed change and no holdout regression. Otherwise it is quarantined
(gated to 0), never deleted.

## 4. Reports

```bash
python -m forge_rsi skills-report
python -m forge_rsi final-report
```

Artifacts:

```
reports/final.md          combined evidence
reports/legates.md        skill registry + gated evaluations
reports/composition.md    two-skill composition matrix
reports/private_holdout.md  private-holdout + round-2 decision
harness/                  append-only harness versions
runs/                     per-run JSON + append-only iteration logs
adapters/                 candidate adapters (never auto-promoted)
```

## 5. Data curation + Forge training UI

```bash
PYTHON=/path/to/mlx-env/bin/python \
PATH=/path/to/mlx-env/bin:$PATH \
SKILLFORGE_LABS=/path/to/MiMo-model \
./sf serve
# http://127.0.0.1:8010
```

Tabs: **Ops** (read-only overview), **Data** (curation), **Forge** (real
`mlx_lm.lora` training), **Playground** (real local server). The Forge tab
refuses to train if `mlx_lm.lora`, the model, or the dataset is missing.

## 6. Ops dashboard

```bash
python -m forge_rsi dashboard
# http://127.0.0.1:8765
```

Read-only. No training or promotion from the UI.

## 7. Round 2 (optional)

```bash
python scripts/train_round2.py
python scripts/eval_round2.py
```

Round 2 is evaluated on a **private holdout** that is not in the public repo.
The promotion rule is stricter: private-holdout gain, no public dev/probe
regression, and no forgetting. A tie keeps the incumbent.

## Gates that must never be skipped

- Base byte-identity (checksum before/after training).
- Non-routed tasks identical to the base run.
- Holdout not worse.
- Anti-leak harness validation.
- Report names and task prompts linted.
