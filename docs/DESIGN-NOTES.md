# Design notes — what we measured and what changed

These are the engineering findings behind the code. They are deliberately
narrow: they describe this frozen 9B model, this 30-task suite, and these
adapters. They are not claims about general intelligence.

## 1. The baby model's failure was a memorized stub, not a reasoning gap

On the word-frequency task, the agent consistently emitted:

```python
def word_freq(text: str) -> dict:
    return {}
```

It could solve the same problem when the function name or prompt changed. That
is a strong, reproducible prior, not random sampling noise. The verifier made it
visible; the harness loop made it actionable.

## 2. Verbose test feedback made the small model worse

Returning the full assertion traceback caused the model to try to reverse-engineer
the hidden tests. On one interval task it emitted a traceback fragment instead of
code. The fix was to return **pass/fail plus the error class only** — no test
names, assertions, or expected values.

## 3. The cheapest effective harness lever was a generic anti-stub retry

`nonstub_retry` detects a function whose body is a single constant/empty return
and asks for a real implementation. It fixed the word-frequency stub for ~49
extra output tokens.

`plan_then_code` also fixed it, but used ~2.4× the tokens and introduced a new
failure on another task. The acceptance rule rejected it on cost. This is the
loop doing its job: a plausible prompt idea is not automatically an improvement.

## 4. Per-skill Le-Gates adapters generalize beyond the training prompts

Two rank-8 adapters were trained from the frozen base on pure synthetic corpora:

| skill | dev gain | held-out probe gain |
|---|---|---|
| `word_freq` | +1 | +4 |
| `merge_intervals` | +1 | +3 |

Gated stack: dev **18/20 → 20/20**, probes **5/12 → 12/12**, holdout **8/10 →
8/10**, base checksum unchanged, non-routed outputs identical.

The probes include function names that were **not** in the training corpus
(`token_frequency`, `merge_intervals_sorted`, `merge_closed_intervals`,
`range_merger`), so this is transfer, not only prompt memorization.

## 5. The teacher needed a diversity rule

In the first harness round, the teacher proposed the same `run_tests` harness
twice. Both tied the incumbent (18/20, zero wins, zero losses) and were rejected.
The probes already showed that `nonstub_retry` solved 20/20 at lower cost.

After adding a rule — *do not repeat a rejected harness; if a probe has a better
dev score at lower cost, prefer it* — the teacher proposed `nonstub_retry` and
the loop accepted it. The lesson is that the optimizer needs both a memory of
rejections and a cost-aware prior over measured probes, not just a general
"improve the prompt" instruction.

## 6. Zero forgetting is a construction, not a statistic

The base model is frozen and checksum-verified. Each skill adapter is trained
with `mlx_lm.lora`, which writes only adapter files. At inference, the router
opens at most one gate (`Σ gate ≤ 1`). Non-routed tasks are copied verbatim from
the base run.

That is why the holdout score does not move: no holdout task matched a skill
trigger, so the gated stack *is* the base stack on those tasks. A future round
with a different router must re-prove that, not assume it.

## 7. What is still open

- A private holdout. The 10 holdout tasks are public in this repository, so a
  future blind claim needs a fresh, frozen holdout.
- Composition. The paper reports that two full-scale gates can collapse
  compound performance; this implementation enforces `Σ≤1` and does not claim
  composition.
- A learned router. The deployed router is deterministic keyword matching;
  oracle routing is an upper bound.
- More skills and a larger probe set. Two skills and 12 probes are enough to
  demonstrate the mechanism, not to estimate a general skill-acquisition rate.
