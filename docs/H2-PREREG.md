# H2 Pre-registration v1

**Status:** FROZEN before the first H2.1 model call.
**Experiment:** H2.1 parallel Propose–Probe–Compose, then H2.2 experience library, then H2.3 plan composition.
**Models:** frozen MiMo-v2.6-distill-qwen-9b-mlx (agent) and Qwen3.6-35B-A3B-MLX-8bit (teacher).
**Task split:** `tasks/dev_hard` (20 tasks, `tasks/HARD_FREEZE.json`).
**Code:** the H2 layer in `forge_rsi/` at the commit that introduces this file.

This file is hashed to `docs/H2-PREREG.sha256`; the hash is copied to
`runs/h2/prereg.sha256` before the first run. No endpoint moves after that.

## Why a hard split

The original dev suite is saturated by r1b: **20/20**. A +3 dev endpoint is
mathematically impossible there. The hard split was built and frozen first, then
r1b was measured once:

| Split | r1b baseline | Headroom |
|---|---:|---:|
| `dev_hard` (20) | **16/20** | 4 tasks |
| `skills` probes (24) | **13/24** | 11 tasks |
| public `holdout` (10) | 8/10 | 2 tasks |
| private `private_holdout` (10) | 10/10 | 0 (guard only) |

The public dev suite remains a **ceiling guard**, not the primary.

## Primary endpoint

**B beats A by at least 3 tasks on `dev_hard`.**

- **A** = r1b harness, measured 16/20.
- **B** = H2.1, k=2, real contrast table.
- Primary pass floor: **B ≥ 19/20**.
- Report the paired McNemar exact p and a deterministic 2,000-sample bootstrap
  95% CI over task-level outcomes. Because n=20, +3 is an effect floor, not a
  significance claim; the exact p is reported as measured.
- +1/+2 is a tie; +3 is the floor; +5 (20/20) is interesting.

## Replication and guards

Promotion requires all of:

1. **Primary:** B ≥ A + 3 on `dev_hard`.
2. **Replication:** B ≥ 16/24 on the 24 public skill probes (A = 13/24).
3. **Public holdout:** B ≥ 8/10 (no regression).
4. **Private holdout:** B ≥ 10/10 (no regression), **sealed** until B is frozen.
5. **Cost:** B's total search cost and deployment cost are reported against E
   and A. If B only wins at >1.5× E's total compute, the result is labelled
   cost-dependent, not a clean efficiency win.

The private holdout is opened only by `finalize` with B's harness hash. The
library may cite only `dev`/`dev_hard`/`skills` evidence.

## Arms and staging

### Stage 1 — the decision (run first)

| Arm | What it is |
|---|---|
| **A** | r1b harness: 16/20 on `dev_hard` |
| **B** | H2.1 k=2, INV + DOM candidates, **real** contrast table |
| **E** | greedy RSI with the **same total compute** as B: 1 base + 7 sequential proposal/eval rollouts, 7 teacher calls |

**Stop rule:** if **B ≤ A** or **B − E ≤ 1 task**, stop. Report the tie or the
compute explanation. Do **not** run Stage 2.

### Stage 2 — only if B wins Stage 1

| Arm | What it is |
|---|---|
| **C** | k=2, shuffled contrast table |
| **D** | k=2, no per-task table (aggregates only) |
| **F** | experience library **on** |
| **G** | library **off** |
| **H** | shuffled lessons |

The contrast test is **B > C > D**. If C or D matches B, the gain is compute,
not contrast. The library test is **F > G > H** at one retrieved lesson; 1 vs 2
vs all is reported as the text-side interference result.

### Stage 3 — only if Stage 1 replicates

**H2.3 composition:** forward (word→merge), reverse (merge→word), random order,
single-pass, monolithic dual. A two-pass arm must beat both one-pass arms and
preserve the first artifact in the second generation.

## Numeric thresholds set before the run

| Threshold | Value |
|---|---|
| Primary effect floor | **+3 tasks / 20** |
| Replication floor | **+3 tasks / 24 probes** |
| Public holdout | **no loss** (≥8/10) |
| Private holdout | **no loss** (10/10) |
| Diversity floor | ≥3 distinct candidate harnesses, mean line Jaccard ≤0.85, ≥2 unique tool sequences |
| Cue entropy floor | ≥0.5 bits over cue→harness assignments |
| Duplicate kill | two consecutive near-duplicate proposals (Jaccard ≥0.95) |
| Contrast gate | real > shuffled ≥ none |
| Library gate | with > shuffled and with > off at limit 1 |
| Composition gate | two-pass best > one-pass best, preservation ≥4/5 |
| Cost reporting | tokens, wall seconds, model calls, eval calls; gain per 1k tokens and per minute |

## Seeds and determinism

- Agent seed: `0` per task, evaluator uses `i * 101` as today.
- Teacher seed: `1` + fixed offsets by dimension/arm.
- Bootstrap seed: `0`; shuffle seed: `0`; random-order seed: `0`.
- Teacher temperature/top-p and agent temperature/top-p come from `config.toml`
  and are recorded in the manifest.
- No endpoint changes after this file is hashed.

## Artifacts per round

All raw, not aggregates:

```
runs/h2_<round>/
  manifest.json          # models, seeds, task/checkpoint hashes, arms, prereg hash
  ledger.jsonl           # one row per arm × task × candidate
  contrast_table_real.md
  contrast_table_shuffled.md
  contrast_table_none.md
  candidates/            # full harness JSON, one per candidate/arm
  diversity.json
  cost.json
  library/               # cue, lesson, evidence, confidence
  report.md              # pre-registered endpoint vs actual
```

Per-task pass/fail is required. A mean score without the diff is not a result.

## Decision rules

- **Promote** only if primary + replication + no public/private regression +
  acceptable cost.
- **Quarantine** on tie or regression; write the negative result.
- **Kill** the round if candidates are near-duplicates for two consecutive
  proposals.
- **Stop Stage 1** if B ≤ A or B − E ≤ 1.
- **Do not run Stage 2 or 3** after a failed Stage 1.
- A tie is a result and is reported with the same rigor as a gain.

## What is not claimed

- The public 10-task holdout is not a blind holdout.
- The 24 skill probes are public and were used in Le-Gates research.
- The private holdout is the only sealed set; it is a guard, not a search signal.
- No composition claim is made from a single-order success; intermediate-state
  preservation is required.
- No library claim is made from self-reported confidence; confidence is a Wilson
  lower bound over measured counts.
