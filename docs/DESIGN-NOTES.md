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

| skill | dev gain | 24-probe gain |
|---|---|---|
| `word_freq` | +1 | +11 |
| `merge_intervals` | +1 | +3 |

Gated stack: dev **18/20 → 20/20**, expanded probes **10/24 → 24/24**, holdout
**8/10 → 8/10**, base checksum unchanged, non-routed outputs identical. The
original 12-probe subset is 12/12.

The first expanded run was 23/24 because `probe_mi_2`'s prompt never named
`merge_overlapping`; the model guessed a training name, and the verifier
reported an import error. `tasks/lint_tasks.py` caught the under-specified
prompt. After the fix, the corrected run is 24/24. That failure was a
benchmark bug, not a model-capability result.

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

## 7. Composition is a generation gap

Five compound tasks require both `word_freq` and `merge_intervals` in one
solution. The parts are 3 word probes and 3 merge probes.

| config | parts word | parts merge | whole |
|---|---|---|---|
| base | 0/3 | 2/3 | 0/5 |
| word gate | 3/3 | 1/3 | 1/5 |
| merge gate | 0/3 | 3/3 | 0/5 |
| dual full (Σ=2) | 3/3 | 3/3 | 0/5 |
| dual half (Σ=1) | 3/3 | 3/3 | 0/5 |

The single gates pass their own parts and fail the whole. Both dual adapters
preserve both parts, so two deltas coexist without interference when the task
asks for one skill. But neither dual adapter solves the whole: the model does
not emit both functions in one response. That is a composition failure at
generation time, not the paper's Σ=2 weight-magnitude collapse. The deployed
router stays at Σ≤1 and claims no composition.

## 8. Round 2 on a private holdout

Ten tasks were withheld from the public repository: 4 word-frequency variants,
4 interval variants, 2 unrelated controls. Round 1 and round 2 both went from
**5/10 base to 10/10 gated**; the private delta was **0**. Public dev and the
24-probe set also tied (20/20 and 23/24), and the zero-forgetting checks held.

The promotion rule kept round 1. A tie is not a promotion; the extra 20 rows
and 40 iterations did not buy a blind gain. The `merge_overlapping`
name-collision in the 24-probe set persisted in both rounds, so more of the
same corpus did not fix it. That is the next corpus-design problem, not a
reason to promote.

## 9. What is still open

- A private holdout. The 10 holdout tasks are public in this repository, so a
  future blind claim needs a fresh, frozen holdout.
- Composition. The paper reports that two full-scale gates can collapse
  compound performance; this implementation enforces `Σ≤1` and does not claim
  composition.
- A learned router. The deployed router is deterministic keyword matching;
  oracle routing is an upper bound.
- More skills and a larger probe set. Two skills and 24 probes are enough to
  demonstrate the mechanism and expose a benchmark prompt bug, not to estimate
  a general skill-acquisition rate.
