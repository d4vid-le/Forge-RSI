# H2.1 Stage 1 — `h2a`

- pre-registration: `56c3855cbac08f9e…` (docs/H2-PREREG-v2.md)
- task split: `dev_hard` (combined `08798fc29ef0bbec…`)
- decision: **KILL: candidate diversity or cue entropy below the pre-registered floor**

## Primary endpoint

| arm | passed | score | delta vs A | wins | losses | sign p | CI95 |
|---|---|---|---|---|---|---|---|
| A r1b | 16/20 | 0.80 | — | — | — | — | — |
| B H2.1 real | 17/20 | 0.85 | +0.05 | 2 | 1 | 1.0000 | [-0.10, +0.20] |
| E greedy same budget | 15/20 | 0.75 | -0.05 | 0 | 1 | 1.0000 | [-0.15, +0.00] |

- primary floor +3: **FAIL** (B−A = +1)
- B vs E incumbent by ≥2: **PASS** (B−E = +2; E stopped after 2/5 iterations, control incomplete)
- diversity floor: **FAIL** (distinct 4, jaccard 0.6923, cue entropy 0.0)
- Stage 1: **STOP**

## Per-task diff vs A

| task | A | B | A error | B error |
|---|---|---|---|---|
| `hard_010` | fail | PASS | runtime | none |
| `hard_012` | PASS | fail | none | assertion |
| `hard_019` | fail | PASS | assertion | none |

## Diversity / surprise

- disagreement: 20.00%
- distinct candidates: 4
- mean line Jaccard: 0.6923
- unique tool sequences: 1
- cue entropy: 0.0

## Cost

- B ledger: 120 calls, 54,288 tokens, 1016.1s
- E ledger: 40 calls, 19,446 tokens, 346.1s
- E stopped on duplicate proposals: **yes** (2/5 iterations recorded)

## Guard splits

Not run. Stage 1 must pass before replication or the seal opens.

A tie or stop is the result. Do not run Stage 2 after this.
