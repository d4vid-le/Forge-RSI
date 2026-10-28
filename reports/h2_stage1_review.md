# H2.1 Stage 1: pre-registered negative on a 20-task hard split — composer collapse and an invalid compute control

- pre-registration v2: `56c3855cbac08f9e99672a102145cf63847c7bbd7d1c3ae30d0d6d407fa7a4df`
- frozen split: `dev_hard`, 20 tasks, combined sha256 `08798fc29ef0bbec230fa5de4440948f55b3bf3dd9e3d614419fe81034c1a4d8`
- decision: **KILL: primary +3 failed (B-A=+1); diversity/cue entropy below floor; composer selected a candidate instead of synthesizing; E control invalid/truncated**

## What this establishes

On this 20-task hard split, at this compute, H2.1's parallel propose–probe–compose loop **failed to meet the pre-registered +3 floor**. The composer reduced to selection, the cue table had zero routing entropy, and the diversity gate failed. These are measured facts.

## What this does not establish

- **Not “no effect.”** B−A = +1 with a 95% CI of [-0.10, +0.20]. The CI includes zero *and* +3. With n=20 this is underpowered for an equivalence claim. The honest wording is “failed to meet the floor.”
- **Not “B beat compute-matched greedy.”** E stopped after 2/5 iterations on the duplicate rule. The E control is invalid, not just incomplete; no compute claim is made.
- **Not a composition result.** The composer adopted `h2a_inv1` wholesale. It did not merge INV/DOM edits. The experiment tested selection, not composition.

## A / B / E

| arm | passed | score | Δ vs A | wins | losses | McNemar p | 95% CI |
|---|---:|---:|---:|---:|---:|---:|---|
| A r1b | 16/20 | 0.80 | — | — | — | — | — |
| B H2.1 real | 17/20 | 0.85 | +0.05 | 2 | 1 | 1.0000 | [-0.10, +0.20] |
| E incumbent | 15/20 | 0.75 | -0.05 | 0 | 1 | 1.0000 | [-0.15, +0.00] |

**The +1 is a trade, not a strict improvement.** B won `['hard_010', 'hard_019']` and lost `['hard_012']`. A is Pareto-better on the regression task; B is not a free upgrade.

## Per-task A/B/E

| task | A | B | E | A error | B error | E error |
|---|---|---|---|---|---|---|
| `hard_001` | PASS | PASS | PASS | none | none | none |
| `hard_002` | PASS | PASS | PASS | none | none | none |
| `hard_003` | PASS | PASS | PASS | none | none | none |
| `hard_004` | fail | fail | fail | assertion | assertion | assertion |
| `hard_005` | PASS | PASS | PASS | none | none | none |
| `hard_006` | PASS | PASS | fail | none | none | assertion |
| `hard_007` | PASS | PASS | PASS | none | none | none |
| `hard_008` | PASS | PASS | PASS | none | none | none |
| `hard_009` | PASS | PASS | PASS | none | none | none |
| `hard_010` | **fail** | **PASS** | fail | runtime | none | runtime |
| `hard_011` | PASS | PASS | PASS | none | none | none |
| `hard_012` | **PASS** | **fail** | PASS | none | assertion | none |
| `hard_013` | PASS | PASS | PASS | none | none | none |
| `hard_014` | PASS | PASS | PASS | none | none | none |
| `hard_015` | PASS | PASS | PASS | none | none | none |
| `hard_016` | PASS | PASS | PASS | none | none | none |
| `hard_017` | PASS | PASS | PASS | none | none | none |
| `hard_018` | fail | fail | fail | assertion | assertion | assertion |
| `hard_019` | **fail** | **PASS** | fail | assertion | none | assertion |
| `hard_020` | PASS | PASS | PASS | none | none | none |

## Composer

Mode: **selected** · selected `h2a_inv1`

The exact system + mission the composer saw is in [`h2_composer_prompt.md`](h2_composer_prompt.md); the real contrast table is [`h2_contrast_table.md`](h2_contrast_table.md). Verbatim selection was valid under the frozen prompt; a synthesis constraint would be a new experiment.

### Cue → harness table

| cue | harness | confidence | support | base passes | candidate passes |
|---|---|---|---|---|---|
| `unclassified/runtime` | `h2a_inv1` | 0.207 | 1 | 0 | 1 |
| `unclassified/assertion` | `h2a_inv1` | 0.095 | 2 | 0 | 1 |
| `word_freq/assertion` | `h2a_inv1` | 0.095 | 2 | 0 | 1 |

## Diversity

| metric | value | floor |
|---|---:|---:|
| distinct candidates | 4 | ≥3 |
| mean line Jaccard | 0.6923 | ≤0.85 |
| unique tool sequences | 1 | ≥2 |
| cue entropy | 0.0 | ≥0.5 |
| disagreement rate | 0.2 | report |

All cue groups mapped to `h2a_inv1`; the router signal is empty.

## E control

E was stopped by the duplicate rule after two byte-identical proposals (Jaccard 1.0). It ran **2/5** iterations. This is an invalid compute control, not a completed arm.

| iteration | candidate | passed | wins | losses | accepted | reason |
|---|---|---|---|---|---|---|
| 1 | `h2a_E_h1` | 14/20 | 0 | 1 | False | wins 0 <= losses 1 |
| 2 | `h2a_E_h2` | 14/20 | — | — | False | pre-registered duplicate kill |

## Cost

| arm | deployment passed | tokens in | tokens out | wall s | cost/solved | search calls | search tokens | search wall s |
|---|---|---|---|---|---|---|---|---|
| A r1b | 16/20 | 6041 | 2327 | 142.2 | 145.4 | — | — | — |
| B H2.1 | 17/20 | 6458 | 2675 | 199.48 | 157.4 | — | — | — |
| E incumbent | 15/20 | 5542 | 2219 | 134.12 | 147.9 | — | — | — |
| B search | — | — | — | — | — | 120 | 54288 | 1016.11 |
| E search | — | — | — | — | — | 40 | 19446 | 346.14 |

B's deployment cost per solved task is **157.4** vs A's **145.4**; B is not cheaper. The +1 gain per 1k search tokens is **0.0184** and per search minute **0.0590**; with the invalid E arm this is descriptive only.

## What was not run

- Stage 2 (shuffled/no-table; library on/off/shuffled) — not run after the Stage 1 stop.
- Stage 3 full H2.3 matrix — not run after the Stage 1 stop.
- The private holdout — **never opened**. The seal is intact.

## H2.3 smoke (not the experiment)

A one-task pre-flight: single-pass 0/1; forward word→merge 1/1 with the intermediate function verified and preserved. This is a mechanism signal for a separate pre-registered H2.3 run, not a result.

## Infrastructure

The ledger, pre-registration/seal, library, parallel PPC, and plan executor are the contribution here. The +1 harness stays in the workbench as a candidate, not a capability claim.


---

## Candidate harnesses

| candidate | content hash | tools | policy | turns | passed | role (short) |
|---|---|---|---|---|---|---|
| `inv1` | `a46c49470c53` | `[]` | `first` | 1 | 17/20 | You are a Python engineer. You write correct, self-contained functions |
| `inv2` | `84f9cbf9931d` | `[]` | `first` | 1 | 16/20 | You are a Python engineer. You write correct, self-contained functions |
| `dom1` | `00a0ca50ce91` | `[]` | `first` | 1 | 16/20 | You are a Python engineer. You write correct, self-contained functions |
| `dom2` | `30ece132a481` | `[]` | `first` | 1 | 16/20 | You are a Python engineer. You write correct, self-contained functions |
| `real` | `a46c49470c53` | `[]` | `first` | 1 | 17/20 | You are a Python engineer. You write correct, self-contained functions |
| `E h1` | `e4ec150beeae` | `['run_tests']` | `first` | 2 | 14/20 | You are a Python engineer. You write correct, self-contained functions |
| `E h2` | `e4ec150beeae` | `['run_tests']` | `first` | 2 | 14/20 | You are a Python engineer. You write correct, self-contained functions |

## Exact composer prompt

See `h2_composer_prompt.md`.


## Pre-registration diff

See `h2_prereg_diff.md`.


## H2.3 smoke

See `h2_plans_smoke.md`.
