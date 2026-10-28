# H2 pre-registration v1 → v2

- v1 hash: `5a5f3f16e5052183302dec2bdd94c8e7aa978f5328c1c5784ee8c58b86bada75`
- v2 hash: `56c3855cbac08f9e99672a102145cf63847c7bbd7d1c3ae30d0d6d407fa7a4df`
- v1 frozen: commit `95aa968` (2026-10-28)
- v2 frozen: commit `9e57806` (2026-10-28), before the first H2 model call

## Why v2

v1 listed the private holdout baseline as 10/10 without labelling it. That number is the gated Le-Gates r1 result, not the r1b harness. v2 keeps the private set sealed and compares B vs A only at finalization; it also aligns E with B's 6 rollouts / 5 teacher calls. The primary endpoint is unchanged.

## Diff

```diff
--- docs/H2-PREREG.md (v1, commit 95aa968)
+++ docs/H2-PREREG-v2.md (v2, commit 9e57806)
@@ -1,13 +1,29 @@
-# H2 Pre-registration v1
+# H2 Pre-registration v2
 
-**Status:** FROZEN before the first H2.1 model call.
+**Status:** FROZEN before the first H2.1 model call. Supersedes v1.
 **Experiment:** H2.1 parallel Propose–Probe–Compose, then H2.2 experience library, then H2.3 plan composition.
 **Models:** frozen MiMo-v2.6-distill-qwen-9b-mlx (agent) and Qwen3.6-35B-A3B-MLX-8bit (teacher).
 **Task split:** `tasks/dev_hard` (20 tasks, `tasks/HARD_FREEZE.json`).
 **Code:** the H2 layer in `forge_rsi/` at the commit that introduces this file.
 
-This file is hashed to `docs/H2-PREREG.sha256`; the hash is copied to
+This file is hashed to `docs/H2-PREREG-v2.sha256`; the hash is copied to
 `runs/h2/prereg.sha256` before the first run. No endpoint moves after that.
+
+## Why v2
+
+v1 listed the private holdout baseline as 10/10 without labelling it. That number
+is the **gated Le-Gates r1** result, not the r1b harness. Measuring the r1b
+harness on the private set before B is frozen would open the seal early.
+
+v2 fixes only that guard and aligns the Stage-1 compute budget:
+
+- the private comparison is **B vs A measured once at finalization**, after B's
+  harness hash is frozen; no private baseline is measured beforehand;
+- Stage 1 B uses 1 base + 4 candidate + 1 real-composer rollouts = **6 dev_hard
+  rollouts and 5 teacher calls**; E uses the same 6 rollouts / 5 calls.
+
+The primary endpoint, task split, replication set, diversity floors, and stop
+rules are unchanged from v1.
 
 ## Why a hard split
 
@@ -15,12 +31,12 @@
 mathematically impossible there. The hard split was built and frozen first, then
 r1b was measured once:
 
-| Split | r1b baseline | Headroom |
+| Split | A = r1b baseline | Headroom |
 |---|---:|---:|
 | `dev_hard` (20) | **16/20** | 4 tasks |
 | `skills` probes (24) | **13/24** | 11 tasks |
 | public `holdout` (10) | 8/10 | 2 tasks |
-| private `private_holdout` (10) | 10/10 | 0 (guard only) |
+| private `private_holdout` (10) | not measured before seal | guard only |
 
 The public dev suite remains a **ceiling guard**, not the primary.
 
@@ -43,7 +59,8 @@
 1. **Primary:** B ≥ A + 3 on `dev_hard`.
 2. **Replication:** B ≥ 16/24 on the 24 public skill probes (A = 13/24).
 3. **Public holdout:** B ≥ 8/10 (no regression).
-4. **Private holdout:** B ≥ 10/10 (no regression), **sealed** until B is frozen.
+4. **Private holdout:** B ≥ A on the private set, where A is measured once at
+   finalization after B is frozen; the private set stays sealed until then.
 5. **Cost:** B's total search cost and deployment cost are reported against E
    and A. If B only wins at >1.5× E's total compute, the result is labelled
    cost-dependent, not a clean efficiency win.
@@ -59,7 +76,7 @@
 |---|---|
 | **A** | r1b harness: 16/20 on `dev_hard` |
 | **B** | H2.1 k=2, INV + DOM candidates, **real** contrast table |
-| **E** | greedy RSI with the **same total compute** as B: 1 base + 7 sequential proposal/eval rollouts, 7 teacher calls |
+| **E** | greedy RSI with the **same total compute** as B: 1 base + 5 sequential proposal/eval rollouts, 5 teacher calls |
 
 **Stop rule:** if **B ≤ A** or **B − E ≤ 1 task**, stop. Report the tie or the
 compute explanation. Do **not** run Stage 2.
@@ -91,7 +108,7 @@
 | Primary effect floor | **+3 tasks / 20** |
 | Replication floor | **+3 tasks / 24 probes** |
 | Public holdout | **no loss** (≥8/10) |
-| Private holdout | **no loss** (10/10) |
+| Private holdout | **no loss vs A at finalization** |
 | Diversity floor | ≥3 distinct candidate harnesses, mean line Jaccard ≤0.85, ≥2 unique tool sequences |
 | Cue entropy floor | ≥0.5 bits over cue→harness assignments |
 | Duplicate kill | two consecutive near-duplicate proposals (Jaccard ≥0.95) |

```
