"""Adapter training and data preparation for the SkillForge half."""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path


def prepare_data(rows_path: str | Path, out_dir: str | Path,
                 train_frac: float = 0.8) -> dict:
    rows = []
    with open(rows_path) as f:
        for line in f:
            if line.strip():
                rows.append(json.loads(line))
    if not rows:
        raise ValueError(f"no rows in {rows_path}")
    random.Random(0).shuffle(rows)
    n = len(rows)
    n_train = max(1, int(n * train_frac))
    n_valid = max(1, int((n - n_train) / 2)) if n - n_train >= 2 else 1
    train = rows[:n_train]
    valid = rows[n_train:n_train + n_valid]
    test = rows[n_train + n_valid:]
    if not valid:
        valid = train[:1]
    if not test:
        test = valid[:1]
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    for name, subset in (("train", train), ("valid", valid), ("test", test)):
        with open(out / f"{name}.jsonl", "w") as f:
            for r in subset:
                f.write(json.dumps({"messages": r["messages"]}) + "\n")
    return {"rows": n, "train": len(train), "valid": len(valid), "test": len(test),
            "dir": str(out)}


def _lora_exe() -> str:
    cand = Path(sys.executable).parent / "mlx_lm.lora"
    return str(cand) if cand.exists() else "mlx_lm.lora"


def train(cfg: dict, data_dir: str | Path, adapter_dir: str | Path,
          iters: int | None = None, recipe: dict | None = None) -> dict:
    tcfg = dict(cfg["train"])
    if recipe:
        tcfg.update(recipe)
    data_dir = Path(data_dir).resolve()
    adapter_dir = Path(adapter_dir).resolve()
    adapter_dir.mkdir(parents=True, exist_ok=True)
    iters = iters or int(tcfg["iters"])
    yaml_path = adapter_dir / "train_config.yaml"
    yaml = f"""model: "{cfg['paths']['agent']}"
train: true
fine_tune_type: lora
optimizer: adamw
data: "{data_dir}"
seed: 0
num_layers: {tcfg['num_layers']}
batch_size: {tcfg['batch_size']}
iters: {iters}
learning_rate: {tcfg['learning_rate']}
val_batches: {tcfg.get('val_batches', 5)}
steps_per_report: {tcfg.get('steps_per_report', 10)}
steps_per_eval: {tcfg.get('steps_per_eval', 100)}
grad_accumulation_steps: {tcfg.get('grad_accumulation_steps', 1)}
max_seq_length: {tcfg['max_seq_length']}
grad_checkpoint: {str(tcfg.get('grad_checkpoint', False)).lower()}
adapter_path: "{adapter_dir}"
save_every: {tcfg.get('save_every', 100)}
test: false
test_batches: 5
mask_prompt: {str(tcfg.get('mask_prompt', False)).lower()}
lora_parameters:
  rank: {tcfg['rank']}
  scale: {tcfg['scale']}
  dropout: {tcfg.get('dropout', 0.0)}
"""
    yaml_path.write_text(yaml)
    cmd = [_lora_exe(), "-c", str(yaml_path)]
    print("[train]", " ".join(cmd), flush=True)
    p = subprocess.run(cmd, capture_output=True, text=True)
    log = adapter_dir / "train.log"
    log.write_text((p.stdout or "") + "\n" + (p.stderr or ""))
    tail = "\n".join(log.read_text().splitlines()[-20:])
    return {
        "returncode": p.returncode,
        "adapter": str(adapter_dir),
        "iters": iters,
        "config": str(yaml_path),
        "log": str(log),
        "tail": tail,
    }


def adapter_ready(adapter_dir: str | Path) -> bool:
    d = Path(adapter_dir)
    return (d / "adapters.safetensors").exists()
