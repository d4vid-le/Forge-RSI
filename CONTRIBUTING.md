# Contributing

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
cp config.example.toml config.toml
# edit config.toml and point the model paths at your local MLX models
```

## Checks before opening a PR

```bash
python3 tasks/build_tasks.py          # every reference must pass its own tests
python3 tasks/lint_tasks.py           # every prompt names the functions its tests import
python3 -m py_compile forge_rsi/*.py pipeline/*.py dashboard/*.py
python3 -m unittest discover -s tests
python3 -m pipeline --help
```

If you change the RSI loop, include the measured before/after table and the
exact command. A number without a receipt is not a result.

## Data policy

Do not commit:

- `config.toml` (local paths)
- `models/`, `adapters/`, `*.safetensors`
- `data/`, `runs/`, `exports/`
- generated corpora under `curriculum/01_raw`, `02_curated`,
  `03_ready-for-training`
- API keys, tokens, credentials, or personal paths

See [`SECURITY.md`](SECURITY.md) for the full policy.

## Claims

The 10 holdout tasks are public. Do not present a score on them as a blind
holdout result. If a claim needs a blind evaluation, generate and freeze a new
private holdout first.
