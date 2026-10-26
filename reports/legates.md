# Le-Gates — gated skill isolation

Frozen base + independent rank-8 skill deltas + a hard 0/1 router.
At most one gate opens per task (`Σ gate ≤ 1`), so the base is never
composed with two deltas. Non-routed tasks run on the untouched base.

## Base lock (R1)

- base model: `<models>/MiMo-v2.6-distill-qwen-9b-mlx`
- current sha256: `291bdfce569b42f2543ec9c80e13b07c02bd7dbf00c4a4999dc988f3a6688335`

| skill | adapter | status | base checksum matches |
|---|---|---|---|
| `word_freq` | `<repo>/adapters/skills/word_freq` | promoted | True |
| `merge_intervals` | `<repo>/adapters/skills/merge_intervals` | promoted | True |
| `rle` | `<repo>/adapters/skills/rle` | untrained | None |
| `second_largest` | `<repo>/adapters/skills/second_largest` | untrained | None |

## Adapters

| skill | rows | iters | train loss | val loss | rc | base unchanged |
|---|---|---|---|---|---|---|
| `word_freq` | 40 | 120 | 0.033 | 0.058 | 0 | True |
| `merge_intervals` | 40 | 120 | 0.015 | 0.043 | 0 | True |
| `rle` | — | — | — | — | — | — |
| `second_largest` | — | — | — | — | — | — |

## Round 2 adapters

| skill | rows | iters | train loss | val loss | base unchanged |
|---|---|---|---|---|---|
| `word_freq` | — | 160 | 0.032 | 0.029 | True |
| `merge_intervals` | — | 160 | 0.018 | 0.052 | True |

Round 2 decision: **False** — private holdout tie; keep round 1


## Lifecycle decisions

| skill | status | dev gain | probe gain | non-routed identical | reason |
|---|---|---|---|---|---|
| `word_freq` | **promoted** | 1 | 4 | True | dev +1, probe +4, no forgetting |
| `merge_intervals` | **promoted** | 1 | 3 | True | dev +1, probe +3, no forgetting |
| `rle` | **untrained** | — | — | — | — |
| `second_largest` | **untrained** | — | — | — | — |


## Gated evaluation — `dev` (run `legates_candidates_dev_gated`, keyword router)

- base: **18/20** (0.90)
- gated: **20/20** (1.00)
- delta: **+0.10**
- routed tasks: dev_012, dev_020
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

| task | skill | base | gated | delta |
|---|---|---|---|---|
| `dev_020` | `merge_intervals` | False | True | +1 |
| `dev_012` | `word_freq` | False | True | +1 |


## Gated evaluation — `holdout` (run `legates_candidates_holdout_gated`, keyword router)

- base: **8/10** (0.80)
- gated: **8/10** (0.80)
- delta: **+0.00**
- routed tasks: none
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

No holdout task matched a skill trigger, so the gated stack
is exactly the base stack on the holdout. That is the R1 /
zero-forgetting evidence, not a claim of holdout skill transfer.


## Gated evaluation — `skills` (run `legates_candidates_skills_gated`, keyword router)

- base: **5/12** (0.42)
- gated: **12/12** (1.00)
- delta: **+0.58**
- routed tasks: probe_mi_1, probe_mi_2, probe_mi_3, probe_mi_4, probe_mi_5, probe_mi_6, probe_wf_1, probe_wf_2, probe_wf_3, probe_wf_4, probe_wf_5, probe_wf_6
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

| task | skill | base | gated | delta |
|---|---|---|---|---|
| `probe_mi_1` | `merge_intervals` | True | True | +0 |
| `probe_mi_2` | `merge_intervals` | False | True | +1 |
| `probe_mi_3` | `merge_intervals` | False | True | +1 |
| `probe_mi_4` | `merge_intervals` | True | True | +0 |
| `probe_mi_5` | `merge_intervals` | False | True | +1 |
| `probe_mi_6` | `merge_intervals` | True | True | +0 |
| `probe_wf_1` | `word_freq` | False | True | +1 |
| `probe_wf_2` | `word_freq` | False | True | +1 |
| `probe_wf_3` | `word_freq` | True | True | +0 |
| `probe_wf_4` | `word_freq` | False | True | +1 |
| `probe_wf_5` | `word_freq` | False | True | +1 |
| `probe_wf_6` | `word_freq` | True | True | +0 |


## Gated evaluation — `dev` (run `legates_final_dev_gated`, keyword router)

- base: **18/20** (0.90)
- gated: **20/20** (1.00)
- delta: **+0.10**
- routed tasks: dev_012, dev_020
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

| task | skill | base | gated | delta |
|---|---|---|---|---|
| `dev_020` | `merge_intervals` | False | True | +1 |
| `dev_012` | `word_freq` | False | True | +1 |


## Gated evaluation — `holdout` (run `legates_final_holdout_gated`, keyword router)

- base: **8/10** (0.80)
- gated: **8/10** (0.80)
- delta: **+0.00**
- routed tasks: none
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

No holdout task matched a skill trigger, so the gated stack
is exactly the base stack on the holdout. That is the R1 /
zero-forgetting evidence, not a claim of holdout skill transfer.


## Gated evaluation — `skills` (run `legates_final_skills_gated`, keyword router)

- base: **5/12** (0.42)
- gated: **12/12** (1.00)
- delta: **+0.58**
- routed tasks: probe_mi_1, probe_mi_2, probe_mi_3, probe_mi_4, probe_mi_5, probe_mi_6, probe_wf_1, probe_wf_2, probe_wf_3, probe_wf_4, probe_wf_5, probe_wf_6
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

| task | skill | base | gated | delta |
|---|---|---|---|---|
| `probe_mi_1` | `merge_intervals` | True | True | +0 |
| `probe_mi_2` | `merge_intervals` | False | True | +1 |
| `probe_mi_3` | `merge_intervals` | False | True | +1 |
| `probe_mi_4` | `merge_intervals` | True | True | +0 |
| `probe_mi_5` | `merge_intervals` | False | True | +1 |
| `probe_mi_6` | `merge_intervals` | True | True | +0 |
| `probe_wf_1` | `word_freq` | False | True | +1 |
| `probe_wf_2` | `word_freq` | False | True | +1 |
| `probe_wf_3` | `word_freq` | True | True | +0 |
| `probe_wf_4` | `word_freq` | False | True | +1 |
| `probe_wf_5` | `word_freq` | False | True | +1 |
| `probe_wf_6` | `word_freq` | True | True | +0 |


## Gated evaluation — `private_holdout` (run `private_r1_private_holdout_gated`, keyword router)

- base: **5/10** (0.50)
- gated: **10/10** (1.00)
- delta: **+0.50**
- routed tasks: priv_mi_1, priv_mi_2, priv_mi_3, priv_mi_4, priv_wf_1, priv_wf_2, priv_wf_3, priv_wf_4
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

| task | skill | base | gated | delta |
|---|---|---|---|---|
| `priv_mi_1` | `merge_intervals` | True | True | +0 |
| `priv_mi_2` | `merge_intervals` | False | True | +1 |
| `priv_mi_3` | `merge_intervals` | True | True | +0 |
| `priv_mi_4` | `merge_intervals` | True | True | +0 |
| `priv_wf_1` | `word_freq` | False | True | +1 |
| `priv_wf_2` | `word_freq` | False | True | +1 |
| `priv_wf_3` | `word_freq` | False | True | +1 |
| `priv_wf_4` | `word_freq` | False | True | +1 |


## Gated evaluation — `private_holdout` (run `private_r2_private_holdout_gated`, keyword router)

- base: **5/10** (0.50)
- gated: **10/10** (1.00)
- delta: **+0.50**
- routed tasks: priv_mi_1, priv_mi_2, priv_mi_3, priv_mi_4, priv_wf_1, priv_wf_2, priv_wf_3, priv_wf_4
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

| task | skill | base | gated | delta |
|---|---|---|---|---|
| `priv_mi_1` | `merge_intervals` | True | True | +0 |
| `priv_mi_2` | `merge_intervals` | False | True | +1 |
| `priv_mi_3` | `merge_intervals` | True | True | +0 |
| `priv_mi_4` | `merge_intervals` | True | True | +0 |
| `priv_wf_1` | `word_freq` | False | True | +1 |
| `priv_wf_2` | `word_freq` | False | True | +1 |
| `priv_wf_3` | `word_freq` | False | True | +1 |
| `priv_wf_4` | `word_freq` | False | True | +1 |


## Gated evaluation — `dev` (run `r2_public_dev_gated`, keyword router)

- base: **18/20** (0.90)
- gated: **20/20** (1.00)
- delta: **+0.10**
- routed tasks: dev_012, dev_020
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

| task | skill | base | gated | delta |
|---|---|---|---|---|
| `dev_020` | `merge_intervals` | False | True | +1 |
| `dev_012` | `word_freq` | False | True | +1 |


## Gated evaluation — `skills` (run `r2_public_skills_gated`, keyword router)

- base: **9/24** (0.38)
- gated: **23/24** (0.96)
- delta: **+0.58**
- routed tasks: probe_mi_1, probe_mi_10, probe_mi_11, probe_mi_12, probe_mi_2, probe_mi_3, probe_mi_4, probe_mi_5, probe_mi_6, probe_mi_7, probe_mi_8, probe_mi_9, probe_wf_1, probe_wf_10, probe_wf_11, probe_wf_12, probe_wf_2, probe_wf_3, probe_wf_4, probe_wf_5, probe_wf_6, probe_wf_7, probe_wf_8, probe_wf_9
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

| task | skill | base | gated | delta |
|---|---|---|---|---|
| `probe_mi_1` | `merge_intervals` | True | True | +0 |
| `probe_mi_10` | `merge_intervals` | False | True | +1 |
| `probe_mi_11` | `merge_intervals` | True | True | +0 |
| `probe_mi_12` | `merge_intervals` | False | True | +1 |
| `probe_mi_2` | `merge_intervals` | False | False | +0 |
| `probe_mi_3` | `merge_intervals` | False | True | +1 |
| `probe_mi_4` | `merge_intervals` | True | True | +0 |
| `probe_mi_5` | `merge_intervals` | True | True | +0 |
| `probe_mi_6` | `merge_intervals` | True | True | +0 |
| `probe_mi_7` | `merge_intervals` | True | True | +0 |
| `probe_mi_8` | `merge_intervals` | True | True | +0 |
| `probe_mi_9` | `merge_intervals` | True | True | +0 |
| `probe_wf_1` | `word_freq` | False | True | +1 |
| `probe_wf_10` | `word_freq` | False | True | +1 |
| `probe_wf_11` | `word_freq` | False | True | +1 |
| `probe_wf_12` | `word_freq` | False | True | +1 |
| `probe_wf_2` | `word_freq` | False | True | +1 |
| `probe_wf_3` | `word_freq` | True | True | +0 |
| `probe_wf_4` | `word_freq` | False | True | +1 |
| `probe_wf_5` | `word_freq` | False | True | +1 |
| `probe_wf_6` | `word_freq` | False | True | +1 |
| `probe_wf_7` | `word_freq` | False | True | +1 |
| `probe_wf_8` | `word_freq` | False | True | +1 |
| `probe_wf_9` | `word_freq` | False | True | +1 |


## Gated evaluation — `skills` (run `skills24_fixed_r1_skills_gated`, keyword router)

- base: **10/24** (0.42)
- gated: **24/24** (1.00)
- delta: **+0.58**
- routed tasks: probe_mi_1, probe_mi_10, probe_mi_11, probe_mi_12, probe_mi_2, probe_mi_3, probe_mi_4, probe_mi_5, probe_mi_6, probe_mi_7, probe_mi_8, probe_mi_9, probe_wf_1, probe_wf_10, probe_wf_11, probe_wf_12, probe_wf_2, probe_wf_3, probe_wf_4, probe_wf_5, probe_wf_6, probe_wf_7, probe_wf_8, probe_wf_9
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

| task | skill | base | gated | delta |
|---|---|---|---|---|
| `probe_mi_1` | `merge_intervals` | True | True | +0 |
| `probe_mi_10` | `merge_intervals` | False | True | +1 |
| `probe_mi_11` | `merge_intervals` | True | True | +0 |
| `probe_mi_12` | `merge_intervals` | False | True | +1 |
| `probe_mi_2` | `merge_intervals` | True | True | +0 |
| `probe_mi_3` | `merge_intervals` | False | True | +1 |
| `probe_mi_4` | `merge_intervals` | True | True | +0 |
| `probe_mi_5` | `merge_intervals` | True | True | +0 |
| `probe_mi_6` | `merge_intervals` | True | True | +0 |
| `probe_mi_7` | `merge_intervals` | True | True | +0 |
| `probe_mi_8` | `merge_intervals` | True | True | +0 |
| `probe_mi_9` | `merge_intervals` | True | True | +0 |
| `probe_wf_1` | `word_freq` | False | True | +1 |
| `probe_wf_10` | `word_freq` | False | True | +1 |
| `probe_wf_11` | `word_freq` | False | True | +1 |
| `probe_wf_12` | `word_freq` | False | True | +1 |
| `probe_wf_2` | `word_freq` | False | True | +1 |
| `probe_wf_3` | `word_freq` | True | True | +0 |
| `probe_wf_4` | `word_freq` | False | True | +1 |
| `probe_wf_5` | `word_freq` | False | True | +1 |
| `probe_wf_6` | `word_freq` | False | True | +1 |
| `probe_wf_7` | `word_freq` | False | True | +1 |
| `probe_wf_8` | `word_freq` | False | True | +1 |
| `probe_wf_9` | `word_freq` | False | True | +1 |


## Gated evaluation — `skills` (run `skills24_fixed_r2_skills_gated`, keyword router)

- base: **10/24** (0.42)
- gated: **24/24** (1.00)
- delta: **+0.58**
- routed tasks: probe_mi_1, probe_mi_10, probe_mi_11, probe_mi_12, probe_mi_2, probe_mi_3, probe_mi_4, probe_mi_5, probe_mi_6, probe_mi_7, probe_mi_8, probe_mi_9, probe_wf_1, probe_wf_10, probe_wf_11, probe_wf_12, probe_wf_2, probe_wf_3, probe_wf_4, probe_wf_5, probe_wf_6, probe_wf_7, probe_wf_8, probe_wf_9
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

| task | skill | base | gated | delta |
|---|---|---|---|---|
| `probe_mi_1` | `merge_intervals` | True | True | +0 |
| `probe_mi_10` | `merge_intervals` | False | True | +1 |
| `probe_mi_11` | `merge_intervals` | True | True | +0 |
| `probe_mi_12` | `merge_intervals` | False | True | +1 |
| `probe_mi_2` | `merge_intervals` | True | True | +0 |
| `probe_mi_3` | `merge_intervals` | False | True | +1 |
| `probe_mi_4` | `merge_intervals` | True | True | +0 |
| `probe_mi_5` | `merge_intervals` | True | True | +0 |
| `probe_mi_6` | `merge_intervals` | True | True | +0 |
| `probe_mi_7` | `merge_intervals` | True | True | +0 |
| `probe_mi_8` | `merge_intervals` | True | True | +0 |
| `probe_mi_9` | `merge_intervals` | True | True | +0 |
| `probe_wf_1` | `word_freq` | False | True | +1 |
| `probe_wf_10` | `word_freq` | False | True | +1 |
| `probe_wf_11` | `word_freq` | False | True | +1 |
| `probe_wf_12` | `word_freq` | False | True | +1 |
| `probe_wf_2` | `word_freq` | False | True | +1 |
| `probe_wf_3` | `word_freq` | True | True | +0 |
| `probe_wf_4` | `word_freq` | False | True | +1 |
| `probe_wf_5` | `word_freq` | False | True | +1 |
| `probe_wf_6` | `word_freq` | False | True | +1 |
| `probe_wf_7` | `word_freq` | False | True | +1 |
| `probe_wf_8` | `word_freq` | False | True | +1 |
| `probe_wf_9` | `word_freq` | False | True | +1 |


## Gated evaluation — `skills` (run `skills24_r1_skills_gated`, keyword router)

- base: **9/24** (0.38)
- gated: **23/24** (0.96)
- delta: **+0.58**
- routed tasks: probe_mi_1, probe_mi_10, probe_mi_11, probe_mi_12, probe_mi_2, probe_mi_3, probe_mi_4, probe_mi_5, probe_mi_6, probe_mi_7, probe_mi_8, probe_mi_9, probe_wf_1, probe_wf_10, probe_wf_11, probe_wf_12, probe_wf_2, probe_wf_3, probe_wf_4, probe_wf_5, probe_wf_6, probe_wf_7, probe_wf_8, probe_wf_9
- non-routed tasks byte-identical: **True**
- base checksum match: **True**

| task | skill | base | gated | delta |
|---|---|---|---|---|
| `probe_mi_1` | `merge_intervals` | True | True | +0 |
| `probe_mi_10` | `merge_intervals` | False | True | +1 |
| `probe_mi_11` | `merge_intervals` | True | True | +0 |
| `probe_mi_12` | `merge_intervals` | False | True | +1 |
| `probe_mi_2` | `merge_intervals` | False | False | +0 |
| `probe_mi_3` | `merge_intervals` | False | True | +1 |
| `probe_mi_4` | `merge_intervals` | True | True | +0 |
| `probe_mi_5` | `merge_intervals` | True | True | +0 |
| `probe_mi_6` | `merge_intervals` | True | True | +0 |
| `probe_mi_7` | `merge_intervals` | True | True | +0 |
| `probe_mi_8` | `merge_intervals` | True | True | +0 |
| `probe_mi_9` | `merge_intervals` | True | True | +0 |
| `probe_wf_1` | `word_freq` | False | True | +1 |
| `probe_wf_10` | `word_freq` | False | True | +1 |
| `probe_wf_11` | `word_freq` | False | True | +1 |
| `probe_wf_12` | `word_freq` | False | True | +1 |
| `probe_wf_2` | `word_freq` | False | True | +1 |
| `probe_wf_3` | `word_freq` | True | True | +0 |
| `probe_wf_4` | `word_freq` | False | True | +1 |
| `probe_wf_5` | `word_freq` | False | True | +1 |
| `probe_wf_6` | `word_freq` | False | True | +1 |
| `probe_wf_7` | `word_freq` | False | True | +1 |
| `probe_wf_8` | `word_freq` | False | True | +1 |
| `probe_wf_9` | `word_freq` | False | True | +1 |

Note: the first 24-probe run predates the `probe_mi_2` prompt-lint
fix (the prompt omitted the function name). Use the
`skills24_fixed_*` rows for the corrected 24/24 result.

## What this proves

- Each skill adapter is trained from the frozen base on a **pure** corpus
  for that skill; no other skill's data is mixed in.
- The router opens at most one gate. Tasks that do not route are copied
  verbatim from the base run, so their outputs are identical by
  construction — not by a statistical argument.
- The base model checksum is recorded before and after training and must
  match; `mlx_lm.lora` writes only adapter files.

## What this does not prove

- **Composition.** `PAPER.md` shows that two full-scale gates (Σ=2) can
  collapse compound performance; the fix is the Σ≤1 magnitude constraint,
  not a claim that skills compose. This implementation enforces Σ≤1.
- **A learned router.** The deployed router is deterministic keyword
  matching. `oracle` routing is an upper bound, not a deployable result.
- **General intelligence.** The probes are small Python tasks. A skill
  adapter that fixes word-frequency probes is not a general coding gain.

