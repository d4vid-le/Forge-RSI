#!/usr/bin/env python3
"""Train the round-2 Le-Gates adapters on a fresh corpus (seed 1, 60 rows).

Writes adapters/skills/r2/<skill>/ and adapters/skills/r2/registry.json.
Does not touch the round-1 adapters or the base model.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forge_rsi import config, harness, legates


def main() -> int:
    cfg = config.load()
    h = harness.load("harness/h0_baseline.json")
    system = harness.render(h)
    root = Path(cfg["paths"]["adapters"]) / "skills" / "r2"
    reg = legates.default_registry(cfg)
    summary = {}
    for skill in ("word_freq", "merge_intervals"):
        corpus = root / skill / "data"
        if not (corpus / "train.jsonl").exists():
            info = legates.build_corpus(cfg, skill, 60, corpus, system, seed=1)
        else:
            info = {"dir": str(corpus)}
        print(f"[r2] training {skill} -> {root / skill}", flush=True)
        res = legates.train_skill(cfg, skill, corpus, root / skill, iters=160)
        loss = legates.summarize_train_log(res["log"])
        reg[skill].update({
            "adapter": str(root / skill),
            "status": "candidate",
            "round": 2,
            "base_checksum": res["base_checksum_after"],
            "base_unchanged": res["base_unchanged"],
            "training": {
                "iters": res["iters"],
                "returncode": res["returncode"],
                "log": res["log"],
                "loss": loss,
            },
            "data": info,
        })
        summary[skill] = {"rc": res["returncode"], "loss": loss,
                          "base_unchanged": res["base_unchanged"],
                          "adapter": str(root / skill)}
        print(f"[r2] {skill}: rc={res['returncode']} loss={loss} "
              f"base_unchanged={res['base_unchanged']}", flush=True)
    path = legates.save_registry(cfg, reg, root / "registry.json")
    (root / "train_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"[r2] registry -> {path}")
    return 0 if all(v["rc"] == 0 for v in summary.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
