# Forge-RSI runbook

Forge-RSI is the engine; **SkillForge** is the local workbench UI and data
pipeline that drives it. One loop: curate data, train isolated skills, measure,
search the harness, replay policies, and keep the base frozen.

## 0. Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dashboard]'

cp config.example.toml config.toml
mkdir -p models
ln -s /absolute/path/to/MiMo-v2.6-distill-qwen-9b-mlx  models/MiMo-v2.6-distill-qwen-9b-mlx
ln -s /absolute/path/to/Qwen3.6-35B-A3B-MLX-8bit       models/Qwen3.6-35B-A3B-MLX-8bit
```

The UI is prebuilt in `ui/dist`. Rebuild only when editing it:

```bash
npm --prefix ui install
npm --prefix ui run build
```

## 1. Run the workbench

```bash
PYTHON=/path/to/mlx-env/bin/python \
PATH=/path/to/mlx-env/bin:$PATH \
FORGE_RSI_LABS=/absolute/path/to/MiMo-v2.6-distill-qwen-9b-mlx \
./sf serve
# http://127.0.0.1:8010
```

`PYTHON` selects the interpreter. `PATH` makes `mlx_lm.lora` and
`mlx_lm.server` discoverable. `FORGE_RSI_LABS` adds model directories outside
the Hugging Face cache. Without the MLX bin on `PATH`, the Train view disables
training and says why; it never simulates.

The classic single-file UI is at `/classic`. The standalone read-only Ops
dashboard is `python -m forge_rsi dashboard` on `:8765`.

## 2. Curate data

In the **Data** view: pick a session, import paths/globs, review rows, accept or
reject, edit, then export. Or use the CLI:

```bash
./sf import curriculum/01_raw/my-run.jsonl --session-name "my run"
./sf accept <session> --all-clean --yes
./sf export <session> \
  --out curriculum/03_ready-for-training \
  --format messages --sort domain
# must print: hard gates: PASSED
```

The export gate refuses secrets, host paths, invalid tool JSON, orphan
observations, and oversize rows. A failed gate blocks training.

## 3. Train a skill adapter

In the **Train** view: select the session, prepare train/valid, preview the
exact `mlx_lm.lora` command, then start. The base lock is checked before
training; the base remains frozen and the adapter is a candidate.

Or use the CLI:

```bash
python -m forge_rsi skills-build \
  --skills word_freq,merge_intervals --rows 40
python -m forge_rsi skills-train \
  --skills word_freq,merge_intervals --iters 120
```

## 4. Evaluate and promote (Le-Gates)

```bash
python -m forge_rsi skills-eval \
  --splits dev,holdout,skills --run-id legates_candidates
python -m forge_rsi skills-decide --run-prefix legates_candidates
python -m forge_rsi skills-eval \
  --splits dev,holdout,skills --run-id legates_final
python -m forge_rsi skills-report
```

A skill is promoted only if it gains on dev **and** on held-out probes, with no
non-routed change and no holdout regression. Otherwise it is quarantined
(gated to 0), never deleted.

## 5. Guarded jobs

The **Jobs** view queues an explicit chain and stops at a human gate:

- **Skill round** — build corpora → train adapters → gated evaluation →
  **human gate** → promotion decision → reports.
- **Gap round** — detect failing skill clusters → mine re-verified traces into a
  raw corpus. Holdouts are excluded.
- **RSI round** — harness loop → **human gate** → round report → final report.
- **Dream round** — K-sample dev run → offline policy replay → Dream report.
- **Rotate holdout** — review the current set → **human gate** → generate,
  verify, and archive a fresh private holdout.
- **Reports only** — regenerate the measured reports from disk.

The API accepts only allowlisted parameters; there is no shell and no free-form
argv. Each step's command is recorded and its output streamed to
`runs/jobs/<job>.log`. Jobs run one at a time. Training steps check the base
lock first and fail before touching weights on a mismatch; they also refuse to
start while another Forge training run is active. Rejecting a job leaves the
adapters on disk but records no promotion.

## 6. Gaps, Dream, and holdout rotation

Gap detection groups measured failures by skill. Mining writes only traces that
pass the task's hidden tests again; the public and private holdouts are never
read.

```bash
python -m forge_rsi gaps-detect --run latest
python -m forge_rsi gaps-mine --run latest --min-rows 1
# writes curriculum/01_raw/<stamp>-gap-<run>-raw.jsonl + a manifest
```

Dream needs a run with more than one candidate per task. Collect them live,
then replay the policies offline (no model calls in the replay):

```bash
python -m forge_rsi eval --harness harness/h0_baseline.json \
  --split skills --run-id dream_k3 --samples 3 --limit 12
python -m forge_rsi dream --run dream_k3
python -m forge_rsi dream-report --run dream_k3
```

Rotate the private holdout when a new blind claim is needed. The old set is
archived under `tasks/private_holdout_archive/`; prompts and tests stay local
and only counts/hashes reach `reports/holdout_rotation.md`.

```bash
python -m forge_rsi holdout-status
python -m forge_rsi holdout-rotate --count 10 --seed 42 --force
```

The public 10-task holdout remains a regression set. Do not treat a score on it
as a blind result.

## 7. RSI harness round

```bash
python -m forge_rsi loop --round r1 --iterations 5
```

A candidate is kept only if:

- `wins > losses` task-by-task,
- the score is not more than `0.05` below the incumbent,
- cost per solved task is at most `1.5×` the incumbent,
- the anti-leak validator passes.

Ties keep the incumbent. The holdout is a regression guard, never an
optimization signal.

## 8. Reports and telemetry

The **Telemetry** view and `reports/` are generated from disk:

```bash
python -m forge_rsi final-report
```

```
reports/final.md          combined evidence
reports/legates.md        skill registry + gated evaluations
reports/composition.md    two-skill composition matrix
reports/gaps.md           measured skill gaps + mined corpus
reports/dream.md          offline selection-policy replay
reports/private_holdout.md  private holdout + round-2 decision
reports/holdout_rotation.md  latest rotation (counts/hashes only)
runs/                     per-run JSON + append-only iteration logs
adapters/                 candidate adapters (never auto-promoted)
```

## 9. Round 2 / private holdout

```bash
python scripts/train_round2.py
python scripts/eval_round2.py
```

Round 2 is evaluated on a **private holdout** that is not in the public repo.
The promotion rule is stricter: private-holdout gain, no public dev/probe
regression, and no forgetting. A tie keeps the incumbent.

## 10. Tests and full reproducibility

The Forge log parser has deterministic stdlib tests (no model, no network):

```bash
python -m unittest discover -s tests
```

Full reproducibility:

```bash
./scripts/run_all.sh
```

## Gates that must never be skipped

- Base byte-identity (checksum before/after training).
- Non-routed tasks identical to the base run.
- Holdout not worse.
- Anti-leak harness validation.
- Task prompts linted (the function name the tests import must appear).
- Adapter promotion only through the documented rule; ties keep the incumbent.
