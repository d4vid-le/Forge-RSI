# Forge-RSI — final report

All scores below are measured on frozen tasks with hidden `unittest` tests.
The holdout is a fixed public regression set, used only as a guard, never to choose a harness.

## Frozen inputs

- tasks: **20 dev + 10 holdout**
- combined sha256: `84a7a0e5b1d60116605d522614c92754d0c23f20c04fdc0a1bf713f7ad73dadb`
- frozen at: 2026-10-25T11:55:33

## Round `r1`

**Start harness:** `h0`  
**Dev:** 18/20 (0.90) · **cost/solved:** 59.9 tokens  
**Holdout:** 8/10 (0.80)  

| # | candidate | wins | losses | dev | delta | accepted | reason |
|---|---|---|---|---|---|---|---|
| 1 | `r1_h1` | 0 | 0 | 0.90 | +0.00 | False | wins 0 <= losses 0 |
| 2 | `r1_h2` | 0 | 0 | 0.90 | +0.00 | False | wins 0 <= losses 0 |

**Holdout after round:** 0.80 (baseline 0.80, delta +0.00) — not worse: **True**  
**Winner harness:** `h0`  

## Round `r1b`

**Start harness:** `h0`  
**Dev:** 18/20 (0.90) · **cost/solved:** 59.9 tokens  
**Holdout:** 8/10 (0.80)  

| # | candidate | wins | losses | dev | delta | accepted | reason |
|---|---|---|---|---|---|---|---|
| 1 | `r1b_h1` | 2 | 0 | 1.00 | +0.10 | True | accepted |

**Holdout after round:** 0.80 (baseline 0.80, delta +0.00) — not worse: **True**  
**Winner harness:** `r1b_h1`  

## Harness probes (pre-loop engineering evidence)

| probe | dev | cost/solved | note |
|---|---|---|---|
| `h0_baseline_v2` | 18/20 | 59.9 |  |
| `probe_nonstub` | 20/20 | 56.2 | generic anti-stub retry; sole multi-turn task was the stub failure |
| `probe_plan` | 19/20 | 179.0 | fixes the stubborn stub but costs 2.4x tokens and introduces dev_018 failure |

## Le-Gates skill isolation (frozen base + gated adapters)

| skill | status | dev gain | probe gain | reason |
|---|---|---|---|---|
| `word_freq` | **promoted** | 1 | 4 | dev +1, probe +4, no forgetting |
| `merge_intervals` | **promoted** | 1 | 3 | dev +1, probe +3, no forgetting |
| `rle` | **untrained** | — | — | — |
| `second_largest` | **untrained** | — | — | — |

| run | split | base | gated | delta | non-routed identical | base unchanged |
|---|---|---|---|---|---|---|
| `legates_candidates_dev` | `dev` | 18/20 (0.90) | 20/20 (1.00) | +0.10 | True | True |
| `legates_candidates_holdout` | `holdout` | 8/10 (0.80) | 8/10 (0.80) | +0.00 | True | True |
| `legates_candidates_skills` | `skills` | 5/12 (0.42) | 12/12 (1.00) | +0.58 | True | True |
| `legates_final_dev` | `dev` | 18/20 (0.90) | 20/20 (1.00) | +0.10 | True | True |
| `legates_final_holdout` | `holdout` | 8/10 (0.80) | 8/10 (0.80) | +0.00 | True | True |
| `legates_final_skills` | `skills` | 5/12 (0.42) | 12/12 (1.00) | +0.58 | True | True |

## SkillForge data (Layer 3)

These are plumbing smoke-test rows, not a capability claim.

| file | rows | success | repair | tasks covered | runs |
|---|---|---|---|---|---|
| `20261025-121419-rsi-bridge_smoke-raw.jsonl` | 18 | 18 | 0 | 18 | r1_h0 |

## Limitations (read this before quoting a number)

- The suite is 30 small Python tasks. It measures code correctness under a
  deterministic verifier, not general intelligence.
- The teacher sees failure *symptoms* (error class, task prompt, model code),
  never test source or holdout items.
- Dream replay re-ranks cached samples; it does not evaluate new prompts.
- A single round on 20 dev tasks has a granularity of 0.05. Deltas smaller
  than that are noise unless the cost also moves.
- Adapters are candidates, not automatic improvements; the promotion rule
  requires a holdout non-regression and a dev gain (or, at the dev ceiling,
  a holdout gain with no dev regression).

