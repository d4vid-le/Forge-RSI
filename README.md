# SkillForge

**A local-first skill library OS for one frozen model.**

SkillForge is not just a trainer. It keeps the base model strictly frozen and
encapsulates specialized skills into independent, domain-pure LoRA adapters. At
inference, a bounded router opens **at most one** skill gate per request. A bad
skill is gated to `0`, never unlearned.

This repository contains two coupled systems:

1. **Forge-RSI** — a measured recursive self-improvement loop that searches the
   agent's *prompt-level harness* (role, contract, workflow, tools, budget)
   against a frozen Python task suite.
2. **Le-Gates** — per-skill LoRA adapters trained fresh from the frozen base,
   selected by a hard `0/1` router with `Σ gate ≤ 1`. Non-routed tasks run on
   the untouched base, so forgetting is zero **by construction**.

Both are local. Both are deterministic where it matters. Every reported number
comes from a reproducible run, not a simulated curve.

---

## The mechanism: Le-Gates

$$
y = W_{base}(x) + \sum_k \left(gate_k \cdot scale_k \cdot (B_k A_k)\,x\right)
$$

- `W_base` is frozen and checksum-verified (R1).
- `A_k`, `B_k` are rank-8 LoRA deltas for skill `k`.
- `gate_k ∈ {0,1}` and `Σ gate_k ≤ 1`. At most one skill is active.
- A bad adapter is **quarantined** (gate 0), not deleted.

Each adapter is trained from the base on a **pure** corpus for that skill:
`num_layers=6`, `rank=8`, `scale=2.0`, `lr=1e-4`, masked loss. No other skill's
data is mixed in.

---

## Measured results

Frozen suite: **20 dev + 10 holdout** Python tasks, hidden `unittest` tests,
reference solutions proven before the tasks enter the suite.

### Le-Gates skill isolation

| split | base | gated | delta | routed | non-routed identical | base checksum |
|---|---|---|---|---|---|---|
| dev (20) | 18/20 (0.90) | **20/20 (1.00)** | +0.10 | `dev_012`, `dev_020` | yes | unchanged |
| holdout (10) | 8/10 (0.80) | 8/10 (0.80) | 0.00 | none | yes | unchanged |
| skill probes (24) | 10/24 (0.42) | **24/24 (1.00)** | +0.58 | all 24 | yes | unchanged |

- `word_freq`: dev +1, 24-probe +11.
- `merge_intervals`: dev +1, 24-probe +3.
- Both adapters promoted; both base checksums unchanged.
- The original 12-probe subset is 12/12. The first expanded run was 23/24
  because `probe_mi_2`'s prompt omitted the function name; `tasks/lint_tasks.py`
  caught it. After fixing the prompt, the corrected run is **24/24** for both
  rounds. This was a benchmark spec bug, not a model failure.

### Composition test (two skills, one compound task)

Each compound task requires both `word_freq` and `merge_intervals` in one
solution. `dual_full` is gate 1.0 + 1.0 (Σ=2); `dual_half` is 0.5 + 0.5 (Σ=1).

| config | parts word | parts merge | whole |
|---|---|---|---|
| base | 0/3 | 2/3 | 0/5 |
| word gate | 3/3 | 1/3 | 1/5 |
| merge gate | 0/3 | 3/3 | 0/5 |
| dual full (Σ=2) | 3/3 | 3/3 | 0/5 |
| dual half (Σ=1) | 3/3 | 3/3 | 0/5 |

Single gates solve their own parts and fail the whole. Both dual adapters
preserve both parts (6/6), but neither solves the whole: the model does not
emit both functions in one response. This is a **generation/composition gap**,
not a weight-interference collapse. The deployed router stays at Σ≤1 and makes
no composition claim.

### Private holdout and round 2

10 tasks withheld from this repository: 4 word-frequency variants, 4 interval
variants, and 2 unrelated controls. Round 2 adapters were trained from the base
on a fresh corpus (seed 1, 60 rows, 160 iters) with the same rank-8 recipe.

| run | base | gated | delta |
|---|---|---|---|
| round 1 | 5/10 (0.50) | **10/10 (1.00)** | +0.50 |
| round 2 | 5/10 (0.50) | **10/10 (1.00)** | +0.50 |

Decision: **keep round 1**. Round 2 ties the blind holdout; the extra 20 rows
and 40 iters bought no blind gain. Public dev and the 24-probe set also tie
(20/20 and 24/24), so the promotion rule keeps the incumbent. The first
24-probe run's failure was a task-prompt bug; the corrected run is 24/24 in
both rounds. The private holdout tie remains.

### RSI harness search

The harness loop uses a 35B teacher to propose bounded edits, evaluates each
proposal on the same dev tasks, and keeps it only if:

1. `wins > losses` task-by-task,
2. the score is not more than `0.05` below the incumbent,
3. cost per solved task is at most `1.5×` the incumbent,
4. the proposal passes the anti-leak validator.

Ties keep the incumbent. The holdout is a **regression guard**, never an
optimization signal.

| round | proposal | result | decision |
|---|---|---|---|
| `r1` | `run_tests` (twice) | 18/20, 0 wins / 0 losses vs h0 | rejected (tie) |
| `r1b` | `nonstub_retry` | **20/20**, 2 wins / 0 losses | **accepted** |

The first teacher proposals repeated the same `run_tests` harness and were
rejected. After adding a diversity rule — *do not repeat a rejected harness; if
a measured probe is better and cheaper, prefer it* — the teacher proposed
`nonstub_retry`. The loop accepted it: dev **18/20 → 20/20**, cost/solved
**59.9 → 56.2**, holdout unchanged at **8/10**.

See [`reports/`](reports/) for the full round tables, including the rejected
proposals.

---

## Quick start

Requirements: macOS on Apple Silicon, Python 3.11+, and MLX.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

cp config.example.toml config.toml
mkdir -p models
# Point these at your local MLX model copies:
ln -s /absolute/path/to/MiMo-v2.6-distill-qwen-9b-mlx  models/MiMo-v2.6-distill-qwen-9b-mlx
ln -s /absolute/path/to/Qwen3.6-35B-A3B-MLX-8bit       models/Qwen3.6-35B-A3B-MLX-8bit
```

### 1. Freeze and baseline

```bash
python -m forge_rsi freeze
python -m forge_rsi eval \
  --harness harness/h0_baseline.json \
  --split dev --run-id baseline_dev
```

### 2. Run one RSI round

```bash
python -m forge_rsi loop --round r1 --iterations 5
```

This proposes, evaluates, compares, keeps or reverts, then evaluates the winner
on the holdout once.

### 3. Le-Gates skill adapters

```bash
# Build pure skill corpora + held-out skill probes
python -m forge_rsi skills-build \
  --skills word_freq,merge_intervals --rows 40

# Train one rank-8 adapter per skill
python -m forge_rsi skills-train \
  --skills word_freq,merge_intervals --iters 120

# Gate the base + adapters on dev, holdout, and the skill probes
python -m forge_rsi skills-eval \
  --splits dev,holdout,skills --run-id legates_candidates

# Quarantine-first decision from dev + probe evidence
python -m forge_rsi skills-decide --run-prefix legates_candidates
python -m forge_rsi skills-report
```

### 4. SkillForge data pipeline (optional)

```bash
./sf import path/to/raw.jsonl --session-name "my run"
./sf accept <session> --all-clean --yes
./sf export <session> \
  --out curriculum/03_ready-for-training \
  --format messages --sort domain
# must print: hard gates: PASSED
```

The export gate refuses secrets, host paths, invalid tool calls, orphan
observations, and oversize rows. Training the resulting adapter uses the same
`mlx_lm.lora` recipe as the skill adapters.

---

## Repository layout

```
forge_rsi/                 RSI loop + Le-Gates implementation
  harness.py               load / validate / render / diff the harness
  agent.py                 MLX generation, code extraction, tool feedback
  verifier.py              temp-dir unittest runner (hidden tests)
  evaluator.py             scoring, pairwise comparison, acceptance
  optimizer.py             teacher proposal + JSON mode + validation
  dream.py                 offline selection-policy replay
  legates.py               skill corpora, router, training, gated eval
  bridge.py                traces -> SkillForge rows
  trainer.py               mlx_lm.lora wrapper
  pipeline.py              RSI -> Dream -> SkillForge -> adapter
  report.py / final_report.py
  cli.py                   python -m forge_rsi ...
pipeline/                  SkillForge data curation/export pipeline
tasks/dev, tasks/holdout   frozen benchmark tasks
tasks/skills               held-out skill probes
harness/                   harness versions and probes
docs/                      architecture, design notes, paper, Mirror assessment
reports/                   sanitized measured reports
config.example.toml        portable example config
workspace.tar              legacy frontend snapshot (simulated backend; UI reference only)
```

---

## What is deliberately not in this repository

- **No model weights and no adapter weights.** The base model and its
  derivatives have their own licenses; train your own adapters locally.
- **No generated training corpora, raw run traces, SQLite session DBs, or
  exports.** Those can contain prompts, tool output, and host paths. The code
  and the synthetic benchmark are enough to reproduce the mechanism.
- **No API keys, credentials, or personal paths.** All examples use
  `<repo>`, `<models>`, or relative paths.

The benchmark tasks **are** published. That makes the 10-task holdout a public
regression set, not a blind holdout. If you want a blind evaluation for a future
claim, generate a fresh private holdout with the same builder and freeze it
before you look at it.

See [`SECURITY.md`](SECURITY.md) for the data-handling policy.

---

## Status

Early-stage research code. The mechanism works and is measured; the production
harness and training UI are the next program, not a current claim.

- Harness search: measured, with accepted/rejected proposals logged.
- Le-Gates: measured on dev + 24 held-out probes, with a zero-forgetting check.
- SkillForge curation: real import/accept/export with hard gates.
- Training: real `mlx_lm.lora`, no simulated loss.

## License

MIT. See [`LICENSE`](LICENSE).
