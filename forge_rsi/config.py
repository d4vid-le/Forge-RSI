"""Configuration loading for Forge-RSI."""
from __future__ import annotations

import tomllib
from pathlib import Path


def load(path: str | Path | None = None) -> dict:
    p = Path(path) if path else Path(__file__).resolve().parent.parent / "config.toml"
    with open(p, "rb") as f:
        cfg = tomllib.load(f)
    # Resolve relative paths against the config file's directory, so a checked-in
    # `config.example.toml` works from any cwd after `cp` to `config.toml`.
    base = p.resolve().parent
    normalised = {}
    for k, v in cfg["paths"].items():
        vp = Path(v).expanduser()
        if not vp.is_absolute():
            vp = (base / vp).resolve()
        normalised[k] = str(vp)
    cfg["paths"] = normalised
    cfg["_config_path"] = str(p)
    return cfg


def ensure_dirs(cfg: dict) -> None:
    for key in ("harness", "runs", "reports", "adapters"):
        Path(cfg["paths"][key]).mkdir(parents=True, exist_ok=True)
    Path(cfg["paths"]["curriculum"], "01_raw").mkdir(parents=True, exist_ok=True)
    Path(cfg["paths"]["curriculum"], "03_ready-for-training").mkdir(parents=True, exist_ok=True)
