# SkillForge Ops dashboard

A read-only local dashboard over the lab's measured artifacts:

- base model lock status;
- skill adapters (round 1 / round 2, status, losses, decisions);
- gated evaluations (dev, holdout, probes, private holdout);
- RSI rounds and holdout guards;
- composition matrix;
- round-2 decision;
- markdown reports.

It never calls a model, writes a file, or triggers training. It binds to
`127.0.0.1` by default.

## Run

```bash
pip install -e '.[dashboard]'
cp config.example.toml config.toml      # edit model paths
python -m forge_rsi dashboard
# open http://127.0.0.1:8765
```

Or directly:

```bash
uvicorn dashboard.app:app --host 127.0.0.1 --port 8765
```

## API

| route | purpose |
|---|---|
| `GET /api/health` | liveness + config loaded |
| `GET /api/status` | JSON summary used by the UI |
| `GET /api/report/{name}` | one markdown report (whitelisted) |
| `GET /` | the dashboard |

## Safety

- Read-only: no eval, train, promote, or write endpoints.
- Loopback only by default. There is no authentication; do not expose it.
- Report names are whitelisted to `[A-Za-z0-9_.-]+\.md` and resolved under
  `reports/`.
- The UI displays local paths only to the local operator; nothing is uploaded.
