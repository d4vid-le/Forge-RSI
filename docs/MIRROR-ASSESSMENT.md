# Mirror assessment — adopt, borrow, or ignore?

**Repo:** https://github.com/reflection-oss/mirror (Apache-2.0)
**Date:** 2026-10-25
**Decision:** **Do not replace Forge-RSI with Mirror.** Borrow the headless
prompt→trace pattern and, if needed later, use Mirror as an external executor
for a bounded A/B — not as the optimizer.

## What Mirror is

A production terminal coding-agent runtime:

- `mirror-agent` — Rust agent loop, providers, tools, compaction, store, HTTP +
  AgentRPC interfaces.
- `mirror-cli` — Python terminal client, workspaces, sessions, extensions, MCP.
- `mirror-sandbox` / `mirror-sandboxd` — sandboxed tool execution.
- Apache-2.0; source build needs Rust, `protoc`, `ripgrep`; wheels ship the
  native agent.

It supports `--api openai-chat-completions --base-url ... --model ...`, so a
local `mlx_lm.server` endpoint is possible in principle.

## What its "built-in eval" actually is

Mirror does not ship a task suite, grader, holdout, or optimizer. Its eval
support is **headless execution**:

```bash
mirror-agent serve --api openai-chat-completions \
  --base-url http://127.0.0.1:8000/v1 --model mimo \
  --workspace /path/to/workspace --output ./mirror.jsonl
curl -X POST http://127.0.0.1:4097/message --data-binary 'solve task ...'
```

It writes committed conversation records (`mirror.jsonl`) and model-call traces
(`mirror.model-calls.jsonl`). The caller supplies tasks and scoring. That is a
useful *executor* contract, not an eval framework.

## Fit matrix

| Requirement | Mirror | Verdict |
|---|---|---|
| RSI harness proposal / pairwise accept / revert | absent | ✗ |
| Le-Gates adapters, router, quarantine | absent | ✗ |
| Frozen task suite + deterministic verifier | absent | ✗ |
| Dream replay / selection-policy search | absent | ✗ |
| Production tool loop, sandbox, worktrees | strong | ✓ |
| Local MLX model | via OpenAI-compatible endpoint | risky |
| Small auditable Python harness | large Rust+Python system | ✗ |

## Why not rip it out

1. **Orthogonal problem.** Mirror is the executor. Forge-RSI is the optimizer
   (tasks, scoring, acceptance, harness search, skill isolation). Replacing the
   executor would not improve the RSI mechanism.
2. **Tool-call dependency.** Mirror relies on tool calls for file/shell work.
   The baby MiMo model's tool-call reliability is the weakest measured link;
   integration debugging would confound model capability with harness plumbing.
3. **Heavy rewrite.** Rust/`protoc` build, provider auth, sandbox, worktrees,
   session store. We already have a working, measured pipeline.
4. **New project.** Just released; API churn is likely. Forking now is a
   maintenance liability.
5. **No scoring discipline.** It has no holdout freeze, pairwise acceptance,
   anti-leak validator, or adapter promotion rules. Those are the parts that
   make our claims honest.

## What to borrow

- **Headless contract:** one prompt in, one machine-readable trace out.
- **Workspace isolation:** run agent edits in a throwaway worktree/copy.
- **Explicit tool approval / sandbox boundary:** useful if we later let the
  agent execute arbitrary shell commands.
- **OpenAI-compatible provider adapter:** if we want an external-agent baseline.

## Revisit conditions

Adopt Mirror (or parts of it) only if:

1. We need a production-grade multi-tool coding loop with sandboxing, and the
   local model proves reliable at the required tool-call protocol.
2. A bounded side-by-side on the same 5–10 tasks shows Mirror's executor beats
   our simple runner on pass rate or cost, with the same verifier.
3. We can pin a release and vendor the needed components under Apache-2.0 with
   attribution.

Until then: **keep Forge-RSI; do not fork Mirror.**
