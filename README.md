# SkillForge

**A local continual-learning workbench for a frozen model.**

One product, one loop: curate real data, train isolated skills, measure them,
search the agent harness, replay policies offline, and keep a frozen base
byte-identical the whole time.

![SkillForge workbench](docs/screenshot-overview.png)

## What is here

| View | What it does |
|---|---|
| **Overview** | Base lock, skill registry, gated evaluations, RSI rounds, composition, reports |
| **Data** | Import → clean → review → accept/reject/edit → export through hard gates |
| **Train** | Real `mlx_lm.lora` training: dataset prep, LoRA config, exact command preview, live loss/log |
| **Jobs** | Guarded queue: allowlisted data → train → eval → report chains with a human promotion gate |
| **Skills** | Le-Gates adapters: rank-8 deltas on the frozen base, one gate at a time, quarantine-first |
| **RSI** | Harness proposals, pairwise accept/reject, holdout guards, cost-aware acceptance |
| **Playground** | Real local chat and robustness probe against `mlx_lm.server` or Ollama |
| **Telemetry** | Runs, evaluations, base-lock state, and generated reports |

Nothing here is a mock. If a server or model is missing, the UI says so instead of
inventing a token, a loss, or a score.

## Quick start

Requirements: macOS on Apple Silicon, Python 3.11+, MLX, and a local model.
The UI is prebuilt in `ui/dist`; Node is only needed to edit it.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dashboard]'

cp config.example.toml config.toml
mkdir -p models
ln -s /absolute/path/to/MiMo-v2.6-distill-qwen-9b-mlx  models/MiMo-v2.6-distill-qwen-9b-mlx
ln -s /absolute/path/to/Qwen3.6-35B-A3B-MLX-8bit       models/Qwen3.6-35B-A3B-MLX-8bit
```

Run the workbench under the MLX environment. `PYTHON` selects the interpreter,
`PATH` makes `mlx_lm.lora` / `mlx_lm.server` discoverable, and
`SKILLFORGE_LABS` adds model directories outside the Hugging Face cache:

```bash
PYTHON=/path/to/mlx-env/bin/python \
PATH=/path/to/mlx-env/bin:$PATH \
SKILLFORGE_LABS=/absolute/path/to/MiMo-v2.6-distill-qwen-9b-mlx \
./sf serve
# http://127.0.0.1:8010
```

The React UI is served at `/`; the classic single-file UI remains at `/classic`.
The standalone read-only Ops dashboard is still available:

```bash
python -m forge_rsi dashboard
# http://127.0.0.1:8765
```

### Edit the UI

```bash
npm --prefix ui install
npm --prefix ui run dev      # http://127.0.0.1:5173, /api proxied to :8010
npm --prefix ui run build    # writes ui/dist, served by ./sf serve
```

### Tests

Deterministic stdlib checks for the Forge log parser and the guarded queue
(no model, no network):

```bash
python -m unittest discover -s tests
```

## The loop

```
Data → Train → Skills → RSI → Playground → Telemetry
                    Jobs orchestrates and gates the long chains
```

- **Data**: import raw JSON/JSONL, clean, review, export. The export gate refuses
  secrets, host paths, invalid tool JSON, orphan observations, and oversize rows.
- **Train**: prepare train/valid, preview the exact `mlx_lm.lora` argv, run it,
  poll real loss/log. The base is frozen; the adapter is a candidate.
- **Skills (Le-Gates)**: one rank-8 adapter per skill, trained fresh from the
  base on a pure corpus, selected by a hard 0/1 router with `Σ gate ≤ 1`.
  A bad skill is quarantined (gate 0), never deleted.
- **RSI**: the teacher proposes a harness, the loop runs the frozen tasks,
  compares task-by-task, and keeps the candidate only if it wins, stays near the
  cost ceiling, and passes the anti-leak validator. Ties keep the incumbent.
- **Jobs**: queue an explicit chain (skill round or RSI round). The API accepts
  only allowlisted parameters, records the exact argv, streams the child's output,
  and stops at a human gate before promotion. Training steps check the base lock
  first; a mismatch fails the job before any weights are touched.
- **Playground**: chat and probe a real local server; no server, no reply.
- **Telemetry**: every run, evaluation, and report is read from disk.

The remaining automation work is gap detection, automatic curation suggestions,
and private-holdout rotation. The queue is intentionally sequential and still
requires a human at the promotion gate.

## Measured state

| | Result |
|---|---|
| Dev | 20/20 gated (base 18/20) |
| Holdout | 8/10 (unchanged, public regression guard) |
| 24 held-out skill probes | 24/24 gated (base 10/24) |
| Private holdout | 10/10 gated (base 5/10), withheld |
| Round 2 | tied the blind holdout; kept round 1 |
| RSI | r1 rejected repeated `run_tests`; r1b accepted `nonstub_retry` |
| Composition | parts work; the compound whole does not |

Full evidence is in [`reports/`](reports/): `final.md`, `legates.md`,
`composition.md`, `private_holdout.md`, `r1.md`, `r1b.md`.

## Architecture

```
ui/                 React + Vite + Tailwind product UI (prebuilt in ui/dist)
pipeline/           data curation, Forge (mlx_lm.lora), Playground, jobs, local API
forge_rsi/          RSI loop, Le-Gates, Dream replay, SkillForge bridge, trainer
dashboard/          standalone read-only Ops collector
tasks/              20 dev + 10 holdout + 24 skill probes + composition
harness/            append-only harness versions
reports/            measured, generated reports
scripts/            run-all + round-2 helpers
legacy/             preserved prototypes and old lab artifacts (local only)
```

See [Architecture](docs/ARCHITECTURE.md) for the data flow and gates,
[Product](docs/PRODUCT.md) for the continual-learning roadmap,
[Design notes](docs/DESIGN-NOTES.md) for the findings, and
[the paper](docs/PAPER.md) for the Le-Gates mechanism.

## Safety and data

- The base model is frozen and checksum-verified; training writes adapter files only.
- Non-routed tasks are copied from the base run, so forgetting is zero by construction.
- The export gate is fail-closed. Adapters are quarantine-first.
- Model weights, generated corpora, raw runs, session DBs, and personal paths are
  not committed.
- The 10 holdout tasks are public. They are a regression set, not a blind holdout;
  generate and freeze a new private holdout for a future blind claim.
- The local UI displays local paths only to the local operator; it binds to
  `127.0.0.1` and has no authentication. Do not expose it.

## License

MIT. See [`LICENSE`](LICENSE).
