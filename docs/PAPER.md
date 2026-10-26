# Parameter-space orthogonality is not composability

### Gated skill isolation on a shared backbone, and composition as the dominant failure axis

*A reproduction-lab report spanning two rigs: a 0.5B six-skill regime map and a 14B two-dialect isolation test.*

---

## Abstract

We ask whether independently trained low-rank skill deltas can be composed at inference on a frozen shared
backbone through hard 0/1 gates without interfering with one another, and we report four results.

**1. In the 0.5B regime, parameter-space orthogonality is real but does not buy functional independence.**
Cosine similarity between the effective weight deltas of six independently trained math skills averages
**0.0099** (max 0.0163) against a random-delta floor of **0.000689** — 14.4× the noise, so the deltas are
nearly orthogonal *and* not random. Nevertheless, opening two gates at full scale (Σ=2) collapses compound
performance to **0/60** samples, while a magnitude-matched control (both gates at 0.5, so Σ=1) recovers to
**18/60**, statistically indistinguishable from the best single gate (14/60, p=0.54). The failure is
**magnitude, not cross-skill interference**. The frozen Σ≤1 invariant is therefore empirically load-bearing
as a *scale* constraint, not as a routing constraint.

**2. On the 14B, isolation reproduces against the frozen comparator.** A domain-separated stack (two
specialist adapters plus a router) reaches **65/70 (92.9%)** first-call selection on hermes against a base
floor of **44/70 (62.9%)** (Fisher one-sided p=1.4e-05), and beats the frozen monolithic comparator by
**+13 robust problems of 32** — the pre-registered gate-2 threshold being +4. Every arm passed the
safety monitors, and the base model was byte-identical at every boundary.

**3. The composition-negative result: specialization buys no accuracy over a balanced monolithic mixture.**
A monolithic adapter trained on the same two dialects at a 2:1 harness-to-hermes ratio **collapses**
(25.7% hermes, 4.3% harness; both significantly below base). A volume-matched control at a 1:1 ratio does
**not** (90.0% hermes, 32.9% harness). Against the *balanced* control the separated stack gains **+2.9 pt**
on hermes and **loses 10.0 pt** on harness. Mixing is not destructive; *imbalance* is. And dedicated
serving is not better than a balanced mixture.

**4. The axis is composition, not scale and not capacity.** A capacity control with **identical training
draws** (same seed, same 1200 sampled rows, replay-verified) and **exactly double** the adapter parameters
reproduces the collapse unchanged — so the failure is neither a parameter budget nor a sampling accident,
but a property of the training composition. A second instance of the same axis appears *inside* a single
dialect: the harness-only specialist improves the dialect it was never trained on (hermes, 56/70 vs base
44/70, p=0.019) while showing no measurable gain on its own dialect.

We close with the one anomaly worth a follow-up probe, and we declare the agent-loop scaffold work that
this paper deliberately does **not** cover.

---

## 1. Question and framing

The `le-gates` composition rule keeps a frozen base model and adds, per skill, a low-rank delta injected at
a fixed set of projection sites, gated by a hard 0/1 scalar:

```
y = base(x) + Σ_k  gate_k · scale_k · (x @ A_k) @ B_k        gate_k ∈ {0,1},  Σ_k gate_k ≤ 1
```

The design hypothesis is that skills trained *independently* — each on its own corpus, never co-trained —
can be slotted into one backbone and switched at inference, giving per-skill lifecycle control (quarantine,
promote, hot-swap) without retraining anything else. That hypothesis has two halves, and they must be
tested separately:

- **Parameter-space claim:** the deltas do not occupy the same directions, so they can coexist.
- **Functional claim:** opening gate *k* delivers skill *k* and does not degrade the base's other
  competences.

This report tests both halves on two rigs at very different scales, and reports a third effect that turned
out to dominate: **the composition of the training corpus** — both between dialects and within one.

---

## 2. Method

### 2.1 Rigs and recipe

| | 0.5B rig | 14B rig |
|---|---|---|
| model | `Qwen2.5-Coder-0.5B-Instruct-bf16` | `Qwen2.5-Coder-14B-Instruct-bf16` |
| skills | 6 math domains (arith·ops, arith·percent, compound, algebra, combinatorics, geometry) | 2 tool-calling dialects (hermes, harness) |
| adapter | rank 8, α 16 → scale 2.0, last 6 layers, 7 projections | identical |
| optimizer | AdamW, lr 1e-4, grad-accum 4, clip 1.0, 300 iters, bf16, seed 0 | identical |
| fresh from base | yes (no warm start, no co-training) | yes |

Two protocol facts matter for reading every number that follows. First, **every arm in this report saw
exactly 1200 training examples** (300 steps × grad-accum 4, batch 1) — that is **0.14–0.42 of a single
epoch** against these corpora. No arm completed one pass. Second, the 14B has **4,300,800 trainable
parameters (0.029% of the model)**; the capacity control uses exactly twice that.

The training loss is masked cross-entropy, `l = Σ(ce · m) / max(Σ m, 1)` with the mask shifted one token
against the labels, so mask values *are* per-token weights:

```
l = mx.sum(ce * m) / mx.maximum(mx.sum(m), 1)        m = mask[:, 1:]
```

### 2.2 Corpora

The 14B corpora are constructed so that the design is exact rather than approximate: **the skewed monolithic
corpus is literally the concatenation of the two specialist corpora.**

| corpus | rows | harness | hermes | harness share | md5 |
|---|---|---|---|---|---|
| `hermes_train_v1.jsonl` | 2,837 | 0 | 2,837 | 0.0% | redacted |
| `harness_train_v1.jsonl` | 5,672 | 5,672 | 0 | 100.0% | redacted |
| `m1_merged_tool_v1.jsonl` | 8,509 | 5,672 | 2,837 | 66.7% | redacted |
| `m1_matched_tool_v1.jsonl` | 5,672 | 2,836 | 2,836 | 50.0% | redacted |

Note the pairing: `m1_merged` = `harness_train_v1` + `hermes_train_v1` exactly. The balanced control holds
the *hermes* count essentially equal (2,836 vs 2,837) and differs by 2,836 extra **harness** rows. So the
two monolithic arms are the same two corpora combined at two ratios, with hermes held constant.

The harness corpus is itself source-balanced — 2,836 rows from one agent harness and 2,836 from another —
and the harness evaluation set is split 35/35 across those same two sources, so no source-level imbalance
exists to confound the dialect-level result.

### 2.3 What each arm actually saw (replay-verified)

The sampler is uniform random with replacement over the corpus, `j = rng.randrange(n)`, seeded at 0, called
once per micro-batch — 1200 draws per arm, and **the generator is called nowhere else in the training
loop**. That makes the exact multiset of training rows for every arm *reproducible after the fact*. We
replayed it:

| arm | draws (harness / hermes) | share | **distinct** harness / hermes rows | corpus touched |
|---|---|---|---|---|
| S1 (hermes only) | 0 / 1200 | 0% / 100% | 0 / 976 † | 34.4% † |
| S2 (harness only) | 1200 / 0 | 100% / 0% | 1076 / 0 | 19.0% |
| M1-full (skewed) | 811 / 389 | 67.6% / 32.4% | 758 / 364 | 13.2% |
| M1-matched (balanced) | 612 / 588 | 51.0% / 49.0% | 541 / 535 | 19.0% |
| CAP (capacity control) | **811 / 389 — identical to M1-full** | 67.6% / 32.4% | 758 / 364 | 13.2% |

† S1 trained on a **2,872-row** version of the hermes corpus (`config.json` records `rows: 2872`); the
corpus was later trimmed to the 2,837 rows frozen for the M1 arms, so S1's distinct-row figures are replayed
against the current file and are indicative only. Its *composition* — 100% hermes — is unaffected, and no
claim in this paper depends on S1's row count.

Two consequences are used later. The capacity control CAP drew **byte-identical training rows to M1-full**
(same seed, same corpus, same length) and differs *only* in adapter rank — a stronger control than
"equal corpus" alone. And the skewed arm's distinct-hermes exposure (364 rows) is materially lower than the
balanced arm's (535), a confound we disclose in §6.2 and test against in §6.4.

### 2.4 Metrics: claim and discipline

Tool-calling is graded at two tiers, and the distinction is load-bearing throughout:

- **NATIVE** — the model emits exactly one `<tool_call>` block the base dialect defines.
- **TOLERANT** — any call-shaped JSON is parsed.

Under those tiers we report two different quantities:

- **CLAIM — `first_call_selection`:** the first call parses *and* its name matches the reference. This is the
  pre-registered skill metric; it asks only whether the model leads with the right tool.
- **DISCIPLINE — exactly-one-call:** the stricter view in which the model emits exactly one call and then
  stops. This is a **diagnostic, not a gate**. It scores a silent model and a rambling model identically.

The **parse-stop scaffold** — a wrapper that parses the first call and stops generation — is the instrument
that makes the claim measurable at all; `wf_scaffold` is well-formedness *under that scaffold*, and the
native tier's well-formedness (`wf_raw`) is carried alongside as a diagnostic on every row.

Robust bands run n=6 samples at temperature 0.3 over a declared fixed subset of 16 states per dialect;
a state is ROBUST at k≥5 of 6. Greedy evaluation is deterministic (it was re-measured and reproduced
exactly on all ten metrics, which is how we know the instruments are stable).

**Power.** Greedy comparisons are n=70 per dialect and robust bands are 16 states. That is enough to resolve
the large effects (specialist gains, the skew collapse: p from 1e-05 to 1e-17) and *not* enough to resolve
gaps of ~7 states, which we therefore report as directional but not significant (§7).

### 2.5 Doctrine applied to every number below

A few rules governed the run and should be read as part of the method:

- **Frozen gates, declared deviations.** Every gate threshold was fixed before the gated stack was measured.
  Deviations are recorded in the artifact itself (the capacity control's `config.json` carries
  `declared_deviation: "cap_matched_parameter"` and the protocol constants it departs from).
- **R1 — base byte-identity.** The base model's checksum is verified at every arm boundary. It held at the
  end of the run: 12 base files unchanged.
- **R10 — absence is never a pass.** A safety monitor with no data fails closed rather than reading clean.
  Three separate fail-open defects were found and fixed under this rule during the run; two measurements
  that the frozen protocol had omitted were then taken and are labelled **additions** wherever they appear.
- **Named degradations.** Any monitor miss is reported as *which item*, not as a count.

---

## 3. Result 1 — the 0.5B regime diagram

The 0.5B lab is the only rig holding six independently trained skills, so it is where the composition
question can be asked at all. All numbers below are from the 0.5B rig; the compound suite is 10 items, each
requiring **two** domains, with every answer verified by sympy at authoring time.

### 3.1 Orthogonality in parameter space is real

Cosine similarity of the effective weight deltas ΔW = a·b across the 42 wrapped (layer, container, target)
sites:

| | arith_ops | arith_per | compound | algebra | combinatorics | geometry |
|---|---|---|---|---|---|---|
| **arith_ops** | 1.000 | 0.008 | 0.004 | 0.006 | 0.015 | 0.011 |
| **arith_percent** | 0.008 | 1.000 | 0.010 | 0.007 | 0.008 | 0.008 |
| **compound** | 0.004 | 0.010 | 1.000 | 0.013 | 0.009 | 0.015 |
| **algebra** | 0.006 | 0.007 | 0.013 | 1.000 | 0.009 | 0.010 |
| **combinatorics** | 0.015 | 0.008 | 0.009 | 0.009 | 1.000 | 0.016 |
| **geometry** | 0.011 | 0.008 | 0.015 | 0.010 | 0.016 | 1.000 |

Mean **0.0099**, max 0.0163, min 0.0044. A random control of independent rank-8 deltas of the same shapes
(20 reps) gives mean 0.00000 with |max| **0.000689**, so the observed similarity is **14.4× the noise floor**.

The honest reading is two-sided: the six skills are nearly orthogonal — **and not random**. There is a
small, statistically resolvable shared component of roughly 1% of the vector norms. Parameter-space
orthogonality is therefore real; it is simply not the thing that determines whether composition works.

### 3.2 …but it does not deliver functional independence

| arm | greedy | robust (n=6) | items with any hit | Σ gate |
|---|---|---|---|---|
| **base (no adapters)** | **5/10** | **37/60 (62%)** | 9/10 | 0 |
| Arm 1: single gate, primary domain | 2/10 | 14/60 (23%) | 5/10 | 1 |
| Arm 1b: single gate, secondary domain | 3/10 | 14/60 (23%) | 5/10 | 1 |
| **Arm 2: dual gate, both domains** | **0/10** | **0/60 (0%)** | **0/10** | 2 |
| Arm 2h: dual gate, both at 0.5 (Σ=1) | 4/10 | 18/60 (30%) | 5/10 | 2×0.5 |

| comparison | p (one-sided Fisher) |
|---|---|
| base 37/60 vs Arm 1 14/60 | **3.9e-05** |
| Arm 1 14/60 vs Arm 2 (Σ=2) 0/60 | **5.2e-05** |
| Arm 1 14/60 vs Arm 2h (Σ=1) 18/60 | 0.54 (**not significant**) |
| base 37/60 vs Arm 2h 18/60 | **8.9e-04** |
| component stack 34/60 vs compound Arm 1 14/60 | **3.5e-04** |

**The dual gate collapses — 0 of 60 samples, on every one of ten two-domain items.** That is not a marginal
loss; the model never produces a correct answer. But the magnitude control is the informative arm: two
orthogonal skills at half scale each recover to 18/60, indistinguishable from the best single gate (p=0.54).
The collapse is therefore **not** directional interference between orthogonal deltas. It is scale: doubling
the injected delta at all 42 sites pushes the residual stream out of the model's working range.

> **Σ≤1 is load-bearing as a magnitude constraint, not as a routing constraint.**

### 3.3 Opening a specialist gate overrides broader competence

The untrained base scores **37/60** on these two-domain items. **Every adapter configuration is
significantly worse** (Arm 1 14/60, p=3.9e-05; Arm 2h 18/60, p=8.9e-04; Arm 2 0/60). A near-orthogonal
single-domain delta, once its gate is open, **commands the layer output** and steers the model into the
single-domain pattern — discarding the base's broader competence in the process.

This is the functional half of the isolation hypothesis failing in the cleanest possible way: orthogonality
of the deltas is irrelevant to it.

### 3.4 A genuine composition gap, separable from the floor

On the *components* of the same compound items, the separated stack succeeds on **34/60 (57%)**, while the
same stack on the compounds scores **14/60 (23%)** — a significant gap (p=3.5e-04). **The parts work; the
whole does not.** That is a composition gap, not merely a low floor, and it is the 0.5B version of the
effect that the 14B composition axis (§5–6) makes quantitative.

### 3.5 The regime diagram

| property | status in the 0.5B regime |
|---|---|
| parameter-space orthogonality of independent skill deltas | **holds** (0.0099 vs 0.000689 floor) |
| deltas are noise-like / interchangeable | **no** — a real ~1% shared component exists |
| two skills at full scale compose | **fails catastrophically** (0/60) |
| two skills at matched Σ=1 compose | **works, no better than one** (18 vs 14, p=0.54) |
| opening a specialist gate preserves base competence | **fails** (every arm < base, p≤8.9e-04) |
| parts compose into wholes | **fails** (57% parts vs 23% compounds, p=3.5e-04) |

The regime, stated plainly: **these deltas are orthogonal but not harmless.** They are near-orthogonal
directions that nonetheless each dominate the layer output when switched on, and their composition is
governed by magnitude rather than by interference.

**Caveats (0.5B).** Suite size is 10 items, so item-level counts are coarse — the robust protocol (60
samples/arm) carries the statistics, and the decisive gaps are far outside noise. Both single-gate arms use
the **oracle** domain assignment, the best case for any router, so the measured penalty is a lower bound on
what a real router would incur. And these arms ran while the 14B queue was training, which inflates that
rig's logged step times across the overlap window (~30.6 → ~31.8 s/step) without endangering memory
(≈1 GB against 29.5 GB); no run crashed and no 0.5B number is affected.

---

## 4. Result 2 — the 14B isolation proof

The 14B rig tests the same hypothesis with two *tool-calling dialects* instead of six math domains, at a
scale where a 0/60-style collapse would be unmissable.

### 4.1 A specialist trained independently works

| arm | corpus | hermes first-call | harness first-call |
|---|---|---|---|
| base (floor) | — | 44/70 (62.9%) | 18/70 (25.7%) |
| **S1 = hermes only** | hermes only (2,872 rows at training time) | **65/70 (92.9%)** | 22/70 (31.4%) |
| S2 = harness only | 5,672 harness | 56/70 (80.0%) | 16/70 (22.9%) |

S1 gains **+30.0 pt** on its dialect (65 vs 44; one-sided Fisher **p=1.4e-05**). Trained from a fresh
adapter on one dialect's corpus, never co-trained, it moves the model from "usually does not lead with the
right tool" to "usually does".

### 4.2 Isolation reproduces against the frozen comparator

The gated stack routes between the two specialists. Against the frozen gate-2 comparator — the monolithic
adapter trained on the same two corpora at the skewed ratio — on the pre-registered CLAIM metric (robust
first-call problems, k≥5 of 6 over 16 states per dialect, 32 total):

| stack | robust claim (of 32) | greedy first-call hermes | harness |
|---|---|---|---|
| gated (separated + router) | **16** | 65/70 (92.9%) | 16/70 (22.9%) |
| M1-full (skewed monolithic) | **3** | 18/70 (25.7%) | 3/70 (4.3%) |
| base | 13 | 44/70 | 18/70 |

**Δ = +13 robust problems against a pre-registered threshold of +4 — gate 2 MET.** On greedy first-call the
separated stack beats the skewed monolith by **p=3.4e-17** on hermes and **p=1.1e-03** on harness. Robust
hermes also clears its gate: 15/16 vs base's 10/16, **p=0.041**.

Both halves of the claim metric move together: **+13.6 pt** on first-call selection and **+8.6 pt** on
`wf_scaffold`, against gate-1 thresholds of +10 and +5.

### 4.3 Safety holds

Every trained arm passed the E3 damage monitors (math greedy / math robust / chat, floors 20/20/10):

| arm | math greedy | math robust | chat |
|---|---|---|---|
| S1 | 20 | 19 | 10 |
| S2 | 20 | 19 | 10 |
| M1-full | 19 | 19 | 10 |
| M1-matched | 19 | 19 | 10 |
| CAP | 20 | 19 | 10 |
| gated stack | 20 | 20 | 10 |

The single -1 across all arms is **one named item**: index 14, combinatorics — *"Two fair six-sided dice are
rolled. What is the probability the sum is 7?"*, ground truth `1/6`. Two arms sampled `0.1667` and `1/6`,
both numerically correct — a grader/format ambiguity, not a capability loss. There were no NaN aborts, no
loss spikes, and the base remained byte-identical throughout.

### 4.4 Where isolation fails

The separated stack's harness score is **16/70 (22.9%) — below the base floor (25.7%)** and well below the
balanced monolithic control (32.9%). Its robust band on harness is 1/16 against base's 3/16. Gate 5
(per-dialect robust ≥ base +4) is **UNMET on harness** while met on hermes. The mechanism is visible in the
table above: the router faithfully routes harness inputs to S2, and **S2 is not better than base on
harness**. The harness deficit is therefore *inherited from the specialist*, not caused by routing — which
is exactly the anomaly §7 addresses.

One flag remains open rather than resolved: the frozen gate-1 text also requires native well-formedness
≥ base + 5 pt, and that half is **UNMET and unachievable by construction** — no stack in either rig emits a
native `<tool_call>` at all (base included: 0/70), so the metric's ceiling is zero. Gate 1 is judged on
`wf_scaffold` under the recorded ruling, both halves are printed by both of the run's independent gate
evaluators, and the flag is declared open rather than quietly dropped.

---

## 5. Result 3 — the composition-negative result

### 5.1 The skewed monolith collapses

M1-full, trained on the concatenated corpus at a 2:1 harness-to-hermes ratio, is **worse than the untouched
base on both dialects**:

| | hermes | harness |
|---|---|---|
| base | 44/70 (62.9%) | 18/70 (25.7%) |
| M1-full | 18/70 (25.7%) | 3/70 (4.3%) |
| p (base > M1-full) | **8.5e-06** | **3.0e-04** |

Its robust bands are 3/16 hermes and 0/16 harness. This is a decisive, reproducible collapse — and it is
also, notably, a *better fit to its own training data* than the balanced control: final loss **0.8859** vs
**1.0523**. The collapsed model optimizes its corpus more effectively. That is the signature of
over-following the dominant component rather than failing to learn.

### 5.2 The balanced mixture does not collapse — mixing is not the problem

M1-matched, volume-matched at 1:1, is strong on both dialects:

| arm | hermes | harness | corpus |
|---|---|---|---|
| M1-full (2:1) | 18/70 (25.7%) | 3/70 (4.3%) | 8,509 rows, 66.7% harness |
| **M1-matched (1:1)** | **63/70 (90.0%)** | **23/70 (32.9%)** | 5,672 rows, 50.0% harness |

M1-matched beats base significantly on hermes (63 vs 44, **p=1.3e-04**) and numerically on harness
(23 vs 18, p=0.23 — directional, not significant at n=70). It also edges the *hermes specialist* on hermes
nonsignificantly (63 vs 65, p=0.82) and is the best harness scorer of any arm.

**So mixing two dialects is not destructive.** The pre-registered wording this result licenses is exact:

> **Domain separation protects against composition skew and buys per-skill lifecycle control (quarantine /
> promote / hot-swap without retraining); against a balanced mixed corpus it shows +2.9 pt (92.9% vs 90.0%)
> on hermes and −10.0 pt (22.9% vs 32.9%) on harness.**

### 5.3 The negative: dedicated serving is not better than a balanced mixture

Reading the two controls against the separated stack:

| control | what it isolates | dialect | gated (claim) | control | Δ |
|---|---|---|---|---|---|
| M1-full | skew-confounded (2:1) — the frozen gate-2 comparator | hermes | 92.9% | 25.7% | **+67.1 pt** |
| M1-full | " | harness | 22.9% | 4.3% | **+18.6 pt** |
| **M1-matched** | clean composition control (1:1) | hermes | 92.9% | 90.0% | **+2.9 pt** |
| **M1-matched** | " | harness | 22.9% | 32.9% | **−10.0 pt** |

Against the skew-confounded comparator, separation looks overwhelming. Against the **clean** control it is a
wash on hermes and a **loss** on harness. The honest summary is that the separated stack is at or above the
specialists in 3 of 4 arm-dialect cells on greedy first-call (tie with S1 on hermes) and in 4 of 4 on the
robust band — but that "at or above" includes a tie, and a tie is not a win. **On the evidence here,
separation's case rests on skew protection and lifecycle control, not on accuracy.**

### 5.4 The zero-hermes paradox in the same table

The harness-only specialist S2 saw **zero hermes tokens** — and is *significantly better than base* on
hermes: **56/70 vs 44/70 (p=0.019)**. Meanwhile it shows no measurable gain on its own dialect
(16/70 vs base's 18/70). Whatever these adapters learn, it is not a dialect-specific skill in the way the
design assumed: it behaves more like a **generic "lead with a well-formed call" policy**, which helps where
the base is weak (hermes) and is redundant where the base already emits calls but where the real difficulty
lies in the *arguments* (harness exact-argument match: 1/70 for base and for S2 alike).

---

## 6. Result 4 — the axis is composition, not scale, not capacity

### 6.1 The design

Holding hermes fixed (2,837 vs 2,836 rows) and varying the harness component gives a one-axis comparison:

| arm | harness share (drawn) | total rows drawn | hermes |
|---|---|---|---|
| S1 | 0% | 1,200 | 92.9% † |
| M1-matched | 51.0% | 1,200 | 90.0% |
| M1-full | 67.6% | 1,200 | **25.7%** |
| S2 | 100% | 1,200 | 80.0% |

The hermes response is **non-monotonic** in harness share: 0% → 92.9%, 51% → 90.0%, 67.6% → **25.7%**,
100% → 80.0%. Pure harness does *not* destroy hermes (S2, 80%, significantly above base). So the collapse
at 67.6% is not "harness rows are poison", and not a simple dose-response in the mixing ratio either.

### 6.2 A confound we must disclose

Because the 1200-draw budget is spread over a larger corpus in the skewed arm, the two monolithic arms
differ in *distinct* hermes rows seen: **364 for M1-full vs 535 for M1-matched**. Composition ratio and
distinct-hermes coverage are therefore **not separable in this design as run**.

This is exactly why the zero-hermes result matters. If the collapse were simply reduced hermes coverage,
then an arm with *zero* hermes coverage (S2) should be at least as bad — and it is not; it is significantly
*better* than base on hermes. Less hermes exposure in the intermediate range cannot explain a collapse that
full absence does not produce.

### 6.3 Capacity is ruled out by an identical-draws control

CAP is trained on the skewed corpus with **rank 16 / α 32 — exactly double the parameters** (8,601,600 vs
4,300,800, verified by counting the saved tensors) — and, because it shares the seed, the corpus and the
length, it drew **the identical 1200 training rows**: 811 harness / 389 hermes, 758/364 distinct. Same data,
same sequence, twice the capacity.

| arm | params | hermes | harness | robust (h / n) |
|---|---|---|---|---|
| M1-full | 4,300,800 | 18/70 (25.7%) | 3/70 (4.3%) | 3/16, 0/16 |
| CAP | **8,601,600** | 31/70 | 5/70 | 3/16, 0/16 |

CAP does not recover — it remains far below base on hermes (31 vs 44; p=0.017 two-sided against it) and its
robust bands are **identical** to M1-full's. Doubling capacity, on identical data, changes nothing
qualitatively. **The failure is a property of the training composition, not of the parameter budget and not
of the sampling.**

### 6.4 The reading: a gradient-magnitude mechanism

The two dialects carry very different loss scales. Trained alone, the hermes corpus reaches a final loss of
**0.4402**; the harness corpus reaches **1.3444** — roughly 3× the per-row loss, consistent with the harness
rows being long JSON-payload targets against a short name-and-arguments hermes target. At a 67.6% harness
draw rate, the optimization is therefore dominated by the harder, longer, higher-gradient component, and its
interleaving is what the two M1 arms differ in. This is consistent with everything measured: the collapse
reproduces under identical draws and doubled capacity; pure harness *does not* collapse hermes; and the
collapsed arm fits its own corpus *better* than the balanced arm fits its.

We state this as the best-supported mechanism rather than a proven one — §6.5 gives the test that would
settle it.

### 6.5 The unified axis, and the decisive test

Across both rigs the same quantity fails: **composition**. In the 0.5B it appears as cross-skill *magnitude*
(Σ=2 → 0/60) and as domain override; in the 14B as an interleaving/ratio effect that no amount of capacity
repairs. In S2 it appears a third time, *inside a single dialect*: an arm whose entire training signal is one
dialect's distribution improves the other dialect and does nothing measurable for its own.

The decisive experiment this report does **not** contain: hold **distinct hermes rows equal** (not just
drawn rows), hold epochs equal, and vary only the interleaving ratio — then the composition axis is
unconfounded from coverage. Its cheap version is specified as the 0.5B probe in §7.

---

## 7. The one anomaly worth a probe

**S2's harness behaviour is anomalous and we are not going to launder it into a finding.**

Stated precisely, with the power caveats attached:

- On its own dialect, the harness-only specialist shows **no measurable gain** over the untouched base:
  16/70 vs 18/70 (n.s.), robust 1/16 vs 3/16 (n.s.).
- On the dialect it **never trained on**, it shows a **significant** gain: 56/70 vs 44/70, p=0.019.
- At n=70 per dialect, an 18-vs-16 gap is well inside noise — so "the specialist hurts harness" is **not**
  established, and neither is "the mixture beats the specialist" (23 vs 16, p=0.13). What *is* established
  is that harness-only training produced **no detectable harness benefit while producing a detectable
  hermes benefit**.

**Candidate explanations, ordered by our prior.**

1. **Generic-call policy (H1).** The adapter learns "lead with a well-formed call" as a demeanour, not a
   dialect. Hermes rewards this strongly (base is weak there), harness less so because base already emits
   calls there and the difficulty is in the arguments.
2. **Argument-level difficulty (H2).** Harness exact-argument match is ~0 for every arm (1/70 for both base
   and S2). If harness competence is argument-bound, a name-level objective cannot express it.
3. **Name-prior dilution (H3).** Harness references are dominated by one tool (bash, 42.3% of eval
   references; 55% of corpus name mentions) while hermes references are flat (116 distinct names, top share
   6.1%). Training on a 13-name vocabulary may teach a prior that the eval's mixture dilutes.

**The designated probe (one 0.5B run, ~1 hour, one variable).** Train, at equal distinct-row counts and
equal epochs: (a) pure-dialect, (b) balanced mixture, (c) base, on a dialect where the base floor is low
(the 0.5B analogue of harness). Pre-register the prediction that H1 makes — the pure arm improves the *weak*
dialect no more than the balanced arm does, while (H3) predicts the pure arm's gain is concentrated on the
dominant tool name. Score names and arguments separately, and report the name-prior entropy of what each arm
actually emits. **Not a blocker:** no claim in this paper depends on which explanation holds; the composition
results of §5–6 stand regardless, and the separated stack's harness deficit stands as measured.

---

## 8. Out of scope — the scaffold is the next program, not the next experiment

The agent-loop (E2) evaluation returns **0/14 for the base scaffold and 0/14 for the gated stack**, with
`PARSEFAIL` on every episode. That is a statement about the **scaffold's ability to parse the model's output
in that environment**, not about adapter quality — the same stack scores 92.9% on hermes under the
parse-stop scaffold, and the two scaffolds are different instruments. Consequently:

- **This paper makes no claim about agentic tool use, episode success, or loop behaviour.** The pre-registered
  E2 gate is reported as **UNMET** in the run's gate table and is deliberately not minimized here.
- **The scaffold work is an engineering program with its own acceptance criteria**, not an experiment in this
  paper's design space. It needs its own rig, its own metrics, and its own pre-registration — a different
  grant. Folding it in as "one more arm" would import an infrastructure failure into a measurement result
  and corrupt both.
- The 0.5B composition findings (§3) and the 14B composition findings (§5–6) are untouched by it: none of
  them routes through the agent loop.

---

## 9. Limitations and threats to validity

1. **Power.** Greedy n=70/dialect, robust bands of 16 states. Large effects are decisive (p ≤ 1e-4); ~7-state
   gaps are directional only. We report them as such and never as established.
2. **One seed, one model per scale.** All arms ran seed 0. The 14B results are single-seed by design (the
   template is the isolation comparison, not a seed study). The 0.5B arms share their seed too; the
   orthogonality control has 20 reps but the capability arms do not.
3. **Sub-epoch training.** Every arm saw 1200 examples — 13–34% of its corpus. These are all
   partial-first-epoch results, and the ordering of what each arm sees is a real experimental factor rather
   than a nuisance.
4. **The coverage confound (§6.2).** Distinct-hermes rows differ between the two monolithic arms (364 vs
   535). We argue from the zero-hermes result that coverage alone cannot explain the collapse, but the
   design does not separate them directly.
5. **Frozen gate 1's literal half is unmet and unachievable** (native well-formedness is 0/70 for every
   stack). The flag is open in both the verdict and this paper.
6. **Two additions.** The balanced control's robust band and the gated stack's math-robust E3 monitor were
   measured *outside* the frozen protocol (the latter because the runner omitted it; its absence had been
   reading as "clean" under a fail-open defect). Both are labelled additions and change no frozen gate.
7. **Environment.** Logged step time drifted monotonically across the run for identical work (32.8 → 41.4 →
   47.9 s/step). We treat it as an observed environment effect, not a protocol deviation; no arm's
   comparison depends on wall time.
8. **Scale transfer.** The Σ=2 collapse is a 0.5B result. A larger model with a wider working range might
   tolerate it, and the 14B rig could not test that (one math adapter only). Conversely, the 14B composition
   effect might not appear at 0.5B. **Neither result is currently known to transfer across scale** — which
   is precisely why both rigs are reported side by side.

---

## 10. Reproducibility

| artifact | availability |
|---|---|
| 14B verdict (all tables, gate table, wording audit) | internal lab artifact (not included) |
| 0.5B findings (orthogonality, arms, Fisher tests) | internal lab artifact (not included) |
| 0.5B closed claim block | internal lab artifact (not included) |
| per-arm adapter configs (rank, α, seed, rows, loss, deviation declarations) | internal lab artifact (not included) |
| corpora | internal; md5s redacted above |

The training-sample composition in §2.3 was reproduced from the per-arm configs plus `random.Random(0)` and
the corpus order. The corpora themselves are not included in this repository. All measurements, including
every adverse one — the E2 failure, the unmet gates, the capacity control's non-recovery, and the
measurements taken outside the frozen protocol — are retained in the verdict rather than filtered out of it.

---

## 11. Conclusion

On two rigs, at two vocabularies — six math domains at 0.5B, two tool dialects at 14B — the isolation
hypothesis splits exactly along the line we proposed at the start.

**In parameter space it holds.** Independently trained deltas are nearly orthogonal (mean cosine 0.0099
against a 0.000689 random floor). In the 14B the resulting isolation is real and reproducible: separation
beats the frozen comparator by +13 robust problems of 32, and its specialist moves hermes from 62.9% to
92.9%. Isolation as a *construction* works, and the safety story around it holds — the base byte-identical
throughout, every damage monitor clean, every miss named.

**Functionally it does not.** In the 0.5B, orthogonal skills compose catastrophically (0/60) and the failure
is magnitude rather than interference — a finding that demotes Σ≤1 from a routing rule to a scale
constraint. Every adapter configuration scores below the bare base because an open specialist gate overrides
broader competence. Parts succeed (57%) while wholes fail (23%).

**And the dominant axis turned out to be composition, not composition-of-skills but composition-of-data.**
A monolithic adapter trained on the two dialects at 2:1 collapses below base on both; the same corpora
balanced at 1:1 produce a strong model that matches the specialist on hermes and beats every arm on harness.
Against that clean control, the separated stack gains 2.9 pt on one dialect and loses 10.0 on the other —
**so dedicated serving buys lifecycle control and skew robustness, not accuracy.** The collapse is not
capacity: a control with identical training draws and exactly double the parameters reproduces it unchanged.

The practical statement is narrower than the design hoped and stronger than a null result. Gated skill
isolation is a real construction whose value is operational — per-skill quarantine, promotion and hot-swap
on a frozen backbone — and whose costs and benefits are governed by the *composition of the training
corpus*, at every level at which composition can be skewed.

*The agent-loop scaffold is the next program. The harness anomaly is one probe away from an explanation and
blocks nothing here.*
