# Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│  ui/ — React + Vite + Tailwind workbench                            │
│  Overview · Data · Train · Jobs · Skills · RSI · Playground         │
│  Telemetry                                                          │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ same-origin /api
┌───────────────────────────────▼─────────────────────────────────────┐
│  pipeline/api.py — local HTTP API + static product build           │
│  sessions · rows · import/export · forge · playground · ops        │
└───────┬──────────────────┬──────────────────┬───────────────────────┘
        │                  │                  │
┌───────▼──────┐   ┌───────▼──────┐   ┌───────▼──────────┐
│ pipeline/    │   │ forge_rsi/   │   │ dashboard/       │
│ curation,    │   │ RSI, Le-Gates│   │ read-only Ops    │
│ forge, play  │   │ Dream, bridge│   │ collector        │
└───────┬──────┘   └───────┬──────┘   └───────┬──────────┘
        │                  │                  │
        └──────────────────┴──────────────────┘
                           │
              tasks/ · harness/ · reports/ · runs/ · adapters/
```

## UI layer

- One shell: left rail (Workbench / Intelligence / Observability), compact top
  bar, full-height work area.
- Views fetch real APIs and render explicit loading/error/empty states.
- No mock fallback. If a server or model is missing, the panel says so.
- The prebuilt build is in `ui/dist`; `pipeline/api.py` serves it at `/`.
  The classic single-file UI is still at `/classic`.

## API layer

`pipeline/api.py` is a stdlib `ThreadingHTTPServer` with:

- Data: `/api/sessions`, `/api/session`, `/api/rows`, `/api/decide`,
  `/api/bulk`, `/api/edit`, `/api/import`, `/api/export`, `/api/quarantine`.
- Forge: `/api/forge/status`, `/api/forge/base-lock`, `/api/forge/prepare`,
  `/api/forge/train`, `/api/forge/stop`, `/api/forge/run`.
- Playground: `/api/playground/status`, `/api/playground/chat`,
  `/api/playground/probe`, `/api/playground/server/*`.
- Jobs: `/api/jobs`, `/api/jobs/log`, `/api/jobs/approve`, `/api/jobs/cancel`.
- Ops: `/api/ops/status`, `/api/ops/report`.
- Static: `/`, `/assets/*` from `ui/dist`, `/classic` for the old page.

The API binds to `127.0.0.1` by default. It has no authentication; do not expose
it. Training is refused if `mlx_lm.lora`, the model, or prepared data is missing.

## Engine modules

| module | owns |
|---|---|
| `pipeline/ingest.py` | load JSON/JSONL/OpenAI/chatml shapes, provenance |
| `pipeline/clean.py` | dedupe, normalize, tool-call repair, secret/host-path flags |
| `pipeline/store.py` | SQLite sessions, rows, decisions, quarantine |
| `pipeline/export.py` | hard gates, manifest, rejected bundle |
| `pipeline/forge.py` | dataset prep, `mlx_lm.lora` wrapper, run telemetry |
| `pipeline/playground.py` | endpoint discovery, real chat, robustness probe, server control |
| `pipeline/jobs.py` | allowlisted job chains, base-lock guard, human gate, sequential runner |
| `forge_rsi/agent.py` | MLX generation, code extraction, tool feedback |
| `forge_rsi/verifier.py` | deterministic temp-dir unittest runner |
| `forge_rsi/harness.py` | harness schema / validation / rendering |
| `forge_rsi/optimizer.py` | teacher proposal + JSON mode |
| `forge_rsi/legates.py` | skill corpora, router, training, gated eval, results |
| `forge_rsi/gaps.py` | failing-cluster detection + re-verified corpus mining |
| `forge_rsi/holdout.py` | private-holdout generation, verification, archive, rotation |
| `forge_rsi/composition.py` | dual-gate composition experiment |
| `forge_rsi/dream.py` | offline selection-policy replay + report |
| `forge_rsi/bridge.py` | traces → SkillForge rows (success + repair) |
| `forge_rsi/trainer.py` | `mlx_lm.lora` adapter training |
| `dashboard/status.py` | read-only artifact collector (shared by the Ops tab) |

## Data flow

```
raw JSONL ──ingest──▶ records ──clean──▶ rows ──review──▶ decisions
                                                   │
                                                   ▼
                                          export (hard gates)
                                                   │
                                                   ▼
                                       train/valid JSONL
                                                   │
                                                   ▼
                                          mlx_lm.lora adapter
                                                   │
                                                   ▼
                                  gated dev / holdout / probes
                                                   │
                                                   ▼
                                  promote or quarantine (gate 0)

measured run ──gaps──▶ failing clusters ──mine──▶ re-verified raw corpus
cached K samples ──dream──▶ selection policy ──▶ reports/dream.md
private holdout ──rotate──▶ archive old set ──▶ fresh blind set (local-only)
```

## Invariants

1. **Base lock.** The base is checksum-verified before/after training and never
   written by the trainer.
2. **Hard data gates.** No secrets, host paths, invalid tool JSON, orphan
   observations, or oversize rows reach training.
3. **Σ gate ≤ 1.** At most one skill adapter is active per task.
4. **Zero forgetting by construction.** Non-routed tasks use the base run
   verbatim.
5. **Holdout is a guard.** It is not used to choose a harness or adapter.
6. **Ties keep the incumbent.** A candidate must win.
7. **Quarantine, don't delete.** A failed adapter is gated to 0 and retained.
8. **No invented numbers.** Every displayed metric is read from a run artifact.
9. **Allowlisted jobs only.** The queue builds argv from validated parameters;
   there is no shell, no free-form command, and one job runs at a time.
10. **Human promotion gate.** A measured job stops at `awaiting_approval`; a
    rejection records no promotion and leaves the artifacts on disk.
11. **Gap mining excludes holdouts.** Only dev, skills, and composition runs are
    read; every mined row is re-verified with hidden tests before writing.
12. **Rotation is archival.** The private holdout is copied to
    `tasks/private_holdout_archive/` before replacement; only counts/hashes are
    published.
