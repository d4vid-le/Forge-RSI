# Forge-RSI — the continual-learning loop

Forge-RSI is one project, not a pile of experiments. **SkillForge** is the
workbench that drives the loop. The loop is:

```
                    ┌──────────────────────────────────────────┐
                    │  frozen base model (checksum-verified)  │
                    └──────────────────────────────────────────┘
                                     │
   ┌───────────────┬─────────────────┼─────────────────┬────────────────┐
   │               │                 │                 │                │
 Data            Train            Skills            RSI             Playground
 curation        adapters         Le-Gates           harness          eval
   │               │                 │                 │                │
   └───────────────┴─────────────────┴─────────────────┴────────────────┘
                                     │
                                 Telemetry
                          runs · evals · reports · base lock
                                     │
                              improvement plan
                                     │
                          automation (job queue + human gate)
```

## Stage 0 — freeze

- Hash the base model, task suite, verifier, and config.
- Nothing downstream may mutate the base. Training writes adapter files only.
- The base checksum is compared before and after every training run.

## Stage 1 — data curation

- Import raw rows in any reasonable shape.
- Clean: normalize, dedupe, repair tool-call JSON, mask secrets, flag host paths,
  drop oversize rows.
- Review: accept / reject / edit with a real diff.
- Export through hard gates. A failed gate blocks training.
- Every artifact is append-only and traceable to its source.

## Stage 2 — training

- Prepare train/valid from **reviewed** rows.
- Preview the exact `mlx_lm.lora` argv and YAML before running.
- LoRA recipe: rank 8, α 16, scale 2.0, last 6 layers, masked loss.
- The adapter is a **candidate**. It is promoted only by the evaluation rule,
  never by the training loss.

## Stage 3 — skill isolation (Le-Gates)

```
y = W_base(x) + Σ gate_k · scale_k · (B_k A_k) x
gate_k ∈ {0,1},  Σ gate_k ≤ 1
```

- One adapter per skill, trained fresh from the base on a pure corpus.
- A deterministic router opens at most one gate.
- Non-routed tasks run on the untouched base: forgetting is zero by construction.
- The measured limits are explicit: parts work, compound wholes do not; the
  router does not compose two skills.

## Stage 4 — RSI harness search

A harness is a JSON prompt object. The loop:

1. evaluates the incumbent on the dev tasks;
2. asks the teacher for one bounded edit (≤2 fields);
3. evaluates the candidate on the same tasks;
4. compares task-by-task and on cost;
5. keeps the candidate only if `wins > losses`, the score is within 0.05, cost is
   within 1.5×, and the anti-leak validator passes; otherwise it reverts.

The holdout is a regression guard, never an optimization signal. Ties keep the
incumbent.

## Stage 5 — telemetry

- Per-run JSON, append-only `runs.jsonl`.
- Per-evaluation base/gated summaries and per-task traces.
- Per-adapter train/val loss, base-lock status, promotion/quarantine decision.
- Markdown reports generated from the artifacts, not typed by hand.

## Stage 6 — improvement plan

- Failed skills → gap detection → new pure corpora → adapters → gated evaluation.
- Gap mining groups measured failures by skill and writes only traces that pass
  the hidden tests **again**. Holdout and private slices are excluded.
- Rejected harness proposals → a diversity rule and measured probes.
- Dream replay searches selection policies offline over cached K samples; the
  oracle is an upper bound, never deployed.
- A private holdout for the promotion decision (withheld from the public repo).
- Rotation generates a fresh, verified private set, archives the old one, and
  records only counts and hashes.

## Stage 7 — automation

The queue is the first automation layer. It ships with explicit human gates:

- **Guarded jobs** — allowlisted chains for a skill round (corpora → train →
  gated eval → gate → decision → reports), a gap round (detect → mine verified
  traces), an RSI round (loop → gate → reports), a Dream round (K-sample dev run
  → offline replay → report), and holdout rotation (status → gate → rotate).
  Parameters are validated; there is no shell or free-form argv.
- **Base-lock guard** — training steps refuse to start when the base is missing
  or its recorded lock no longer matches.
- **One at a time** — a single worker preserves CPU/memory and makes the order
  auditable. Training steps also refuse to start while another Forge run is
  active. Output goes to `runs/jobs/<id>.log`; state to `data/jobs.json`.
- **Human promotion gate** — a measured job stops at `awaiting_approval`.
  Approving resumes the decision/report steps; rejecting records no promotion
  and leaves the adapters on disk. Rotation also stops at a gate before the
  current private set is replaced.
- **Gap detection and mining** — failure clusters are grouped by skill, then
  verified passing traces become a raw corpus for review.
- **Private-holdout rotation** — deterministic templates are verified against
  their own hidden tests; the old set is archived, not deleted.
- **Dream policy** — live K-sample collection followed by offline policy replay.
  No model calls happen in the replay itself.

Still ahead:

- automatic triggers and scheduling for the four chains;
- teacher-authored repairs for gaps with no verified pass (currently reported as
  missing, never invented);
- a router that can be deployed after offline Dream validation.

The queue is sequential on purpose. Promotion always requires the documented
rule **and** a human approval.

## What is not claimed

- General intelligence or cross-model transfer.
- Composition of two skills under one gate.
- Any blind-holdout result from the public 10-task set.
- An adapter gain without a measured private-holdout decision.
