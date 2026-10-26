# Security and data handling

SkillForge is local-first. This repository is the **code and the synthetic
benchmark**, not a dump of a working machine.

## What is published

- Source code in `forge_rsi/` and `pipeline/`.
- The synthetic task suite in `tasks/` (prompts, tests, references).
- Harness JSON documents.
- Documentation and sanitized summary reports.
- A portable `config.example.toml` with relative paths.

## What is not published

- Model weights, LoRA adapter weights, and any `.safetensors` files.
- Generated training corpora (`curriculum/01_raw`, `02_curated`,
  `03_ready-for-training`), raw traces (`runs/`), exports, and the SQLite
  session database (`data/skillforge.db`).
- Legacy lab telemetry and machine-specific workspace dumps.
- API keys, tokens, credentials, personal paths, or usernames.

## Benchmark disclosure

The 20 dev and 10 holdout tasks are public. The holdout is therefore a **public
regression set**. Do not present a future score on it as a blind holdout result;
generate and freeze a new private holdout first.

## If you find a leak

Open a private security advisory or contact the maintainer through the
repository. Do not open a public issue containing the sensitive value.

## Model licensing

The code is MIT. Base models and adapters have their own licenses. This
repository does not redistribute model weights; check the license of any model
you use locally.
