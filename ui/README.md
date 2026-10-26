# SkillForge product UI

The React workbench served by the pipeline at `http://127.0.0.1:8010`.

## Views

- **Overview** — base lock, skill registry, gated evaluations, RSI, composition, reports.
- **Data** — sessions, import, review queue, row detail, accept/reject/edit, export.
- **Train** — environment, model + base lock, dataset, LoRA config, command preview, live run.
- **Skills** — Le-Gates registry, zero-forgetting checks, composition.
- **RSI** — proposals, pairwise outcomes, holdout guards, decision.
- **Playground** — real local chat, robustness probe, `mlx_lm.server` control.
- **Telemetry** — runs, evaluation matrix, base lock, generated reports.

Every panel calls the real pipeline API. There is no mock fallback: missing
servers, models, or runs render as missing.

## Development

```bash
cd ui
npm install
npm run dev      # http://127.0.0.1:5173
```

`vite.config.js` proxies `/api` to `http://127.0.0.1:8010`, so run the pipeline
server in another terminal:

```bash
./sf serve
```

Build for the product server:

```bash
npm run build    # writes ui/dist; ./sf serve serves it at /
```

The prebuilt `ui/dist` is included so end users do not need Node.

## API contract

| panel | endpoints |
|---|---|
| Overview / Skills / RSI / Telemetry | `/api/ops/status`, `/api/ops/report?name=` |
| Data | `/api/sessions`, `/api/session`, `/api/rows`, `/api/decide`, `/api/bulk`, `/api/edit`, `/api/import`, `/api/export`, `/api/quarantine` |
| Train | `/api/forge/status`, `/api/forge/base-lock`, `/api/forge/prepare`, `/api/forge/train`, `/api/forge/stop`, `/api/forge/run` |
| Playground | `/api/playground/status`, `/api/playground/chat`, `/api/playground/probe`, `/api/playground/server/*` |

`/api/ops/status` returns `{ok: true, status: {...}}`; the other endpoints return
their payload with `ok` at the top level. The client is in `src/api.ts`.

## Design

The shell is a persistent left rail (Workbench / Intelligence / Observability)
with a compact top bar and full-height work areas. The palette is intentionally
low-contrast dark; numbers are tabular; tables use sticky headers. No external
fonts or CDNs are required.
