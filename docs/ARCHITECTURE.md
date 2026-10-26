# Architecture

Three layers, one frozen base.

```
Layer 1  live RSI       MiMo 9B runs frozen coding tasks; a 35B teacher
                        rewrites the harness; wins are kept, regressions revert
Layer 2  Dream replay   cached K-sample candidates are re-ranked offline under
                        different selection policies (zero model calls)
Layer 3  SkillForge     passing traces + repairs -> curated SFT data -> LoRA
                        adapter -> dev/holdout re-measure -> promote/quarantine
Layer 4  Le-Gates       per-skill LoRA adapters on the frozen base, selected by
                        a hard 0/1 router with Σ gate ≤ 1
```

## Layer 1 — harness search

The harness is a JSON document:

```json
{
  "version": "h0",
  "role": "...",
  "contract": {"output": "...", "must": [], "must_not": []},
  "hops": [{"name": "implement", "instruction": "..."}],
  "tools": [],
  "selection": {"policy": "first", "k": 1},
  "budget": {"max_turns": 1, "max_output_tokens": 900}
}
```

It is the only object the loop may mutate. A candidate is accepted only if:

- `wins > losses` on the same dev tasks,
- score is not more than `0.05` below the incumbent,
- cost per solved task is at most `1.5×` the incumbent,
- the anti-leak validator passes.

Ties keep the incumbent. The holdout is evaluated once per round as a regression
guard, never used to choose a harness.

## Layer 2 — Dream replay

Selection policies (`first`, `longest`, `majority`, `test_gated`,
`best_of_k_oracle`) re-rank candidates that were already generated. No model
calls. `best_of_k_oracle` is an upper bound and is never deployed.

## Layer 3 — SkillForge

Passing traces and failure→fix pairs become messages-format SFT rows. The data
pipeline enforces hard gates (secrets, host paths, invalid tool JSON, orphan
observations, size). Training is real `mlx_lm.lora`; the base is frozen.

## Layer 4 — Le-Gates

```
y = base(x) + gate_k * scale_k * (x @ A_k) @ B_k
gate_k in {0,1},  Σ gate_k <= 1
```

One rank-8 adapter per skill, trained fresh from the base on a pure corpus
(`num_layers=6`, `scale=2.0`, `lr=1e-4`, masked loss). A deterministic keyword
router opens at most one gate. Non-routed tasks are copied verbatim from the
base run, so their outputs are identical by construction.

A skill is promoted only if it gains on dev **and** on held-out skill probes,
with no non-routed change and no holdout regression. Otherwise it is quarantined
(gated to 0), never deleted.

## Why the base checksum matters

`mlx_lm.lora` writes only adapter files. The base model directory is hashed
before and after training. A mismatch fails the run. This is the R1 rule from
the Le-Gates protocol and the reason the forgetting claim is structural rather
than statistical.

## Legacy UI snapshot

`workspace.tar` is the earlier frontend prototype. Its `backend/train_lora.py`
contains **simulated** training loops and mock inference; do not use it for
training or evaluation claims. The real path is:

- `forge_rsi/trainer.py` — `mlx_lm.lora` wrapper used by the skill adapters.
- `pipeline/forge.py` — the SkillForge Forge stage, also real `mlx_lm.lora`.

## What is not claimed

- Composition of two full-scale skills. `Σ≤1` is enforced as a magnitude
  constraint; `docs/PAPER.md` reports the composition failure measured on the
  0.5B rig.
- A learned router. The deployed router is deterministic keyword matching;
  oracle routing is an upper bound.
- General intelligence or cross-model transfer.
