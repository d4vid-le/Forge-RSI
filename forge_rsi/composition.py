"""Composition experiment: two skill deltas, one compound task.

The Le-Gates rule opens at most one gate at inference (Σ≤1). This module
builds the two-gate controls from the paper:

  * full  = gate_word(1.0) + gate_merge(1.0), Σ = 2
  * half  = gate_word(0.5) + gate_merge(0.5), Σ = 1

It merges two rank-8 adapters into one rank-16 adapter by concatenating
`lora_a` along the rank axis and `lora_b` along the rank axis, with the gate
coefficients applied to `lora_b`. The merged adapter is a genuine two-delta
forward pass, not a prompt trick.

No fabricated numbers: every configuration is evaluated by the same verifier
on the same tasks, and the per-function pass/fail is parsed from the verifier
output.
"""
from __future__ import annotations

import gc
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import mlx.core as mx

from . import config, evaluator, legates


# ───────────────────────────── adapter merge ────────────────────────────

def merge_adapters(cfg: dict, a_dir: str | Path, b_dir: str | Path,
                   out_dir: str | Path, coeff_a: float = 1.0,
                   coeff_b: float = 1.0) -> dict:
    """Merge two rank-r LoRA adapters into one rank-2r adapter."""
    a_dir = Path(a_dir)
    b_dir = Path(b_dir)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wa = mx.load(str(a_dir / "adapters.safetensors"))
    wb = mx.load(str(b_dir / "adapters.safetensors"))
    if set(wa) != set(wb):
        raise ValueError("adapter key sets differ; cannot merge")
    merged = {}
    for k in wa:
        if k.endswith("lora_a"):
            merged[k] = mx.concatenate([wa[k], wb[k]], axis=1)
        elif k.endswith("lora_b"):
            merged[k] = mx.concatenate([coeff_a * wa[k], coeff_b * wb[k]], axis=0)
        else:
            if wa[k].shape != wb[k].shape:
                raise ValueError(f"non-LoRA key shape mismatch: {k}")
            merged[k] = wa[k]
    mx.save_safetensors(str(out_dir / "adapters.safetensors"), merged)

    cfg_a = json.loads((a_dir / "adapter_config.json").read_text())
    rank = int(cfg_a["lora_parameters"]["rank"]) * 2
    cfg_a["lora_parameters"] = {
        "rank": rank,
        "scale": cfg_a["lora_parameters"]["scale"],
        "dropout": 0.0,
    }
    cfg_a["adapter_path"] = str(out_dir)
    cfg_a["config"] = str(out_dir / "adapter_config.json")
    cfg_a["model"] = cfg["paths"]["agent"]
    cfg_a["num_layers"] = int(cfg_a.get("num_layers", 6))
    (out_dir / "adapter_config.json").write_text(json.dumps(cfg_a, indent=2) + "\n")
    return {
        "dir": str(out_dir),
        "rank": rank,
        "scale": cfg_a["lora_parameters"]["scale"],
        "coeff_a": coeff_a,
        "coeff_b": coeff_b,
        "sum_gate": coeff_a + coeff_b,
    }


def build_composition_adapters(cfg: dict) -> dict:
    root = Path(cfg["paths"]["adapters"]) / "skills"
    a = root / "word_freq"
    b = root / "merge_intervals"
    full = merge_adapters(cfg, a, b, root / "_composition" / "full", 1.0, 1.0)
    half = merge_adapters(cfg, a, b, root / "_composition" / "half", 0.5, 0.5)
    return {"full": full, "half": half}


def verify_load(cfg: dict, adapter_dir: str | Path) -> dict:
    """Load the merged adapter once and generate a few tokens."""
    from mlx_lm import generate, load
    model, tok = load(cfg["paths"]["agent"], adapter_path=str(adapter_dir))
    messages = [
        {"role": "system", "content": "You are a Python engineer."},
        {"role": "user", "content": "Write `add(a, b)` returning a + b."},
    ]
    prompt = tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
    out = generate(model, tok, prompt=prompt, max_tokens=24, verbose=False)
    del model
    gc.collect()
    mx.clear_cache()
    return {"adapter": str(adapter_dir), "output": out[:200]}


# ───────────────────────────── evaluation ───────────────────────────────

def _run_cli(args: list[str]) -> int:
    cmd = [sys.executable, "-m", "forge_rsi"] + args
    print("[composition]", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


PARTS = [
    "probe_wf_1", "probe_wf_7", "probe_wf_12",
    "probe_mi_1", "probe_mi_7", "probe_mi_12",
]


def parse_trace(trace: dict) -> dict:
    """Per-function view of a compound task trace."""
    code = trace.get("code") or ""
    feedback = trace.get("feedback") or ""
    word_defined = bool(re.search(r"^\s*def\s+word_freq\s*\(", code, re.M))
    merge_defined = bool(re.search(r"^\s*def\s+merge_intervals\s*\(", code, re.M))
    word_fail = bool(re.search(r"(FAIL|ERROR): test_word_", feedback))
    merge_fail = bool(re.search(r"(FAIL|ERROR): test_merge_", feedback))
    syntax = bool(re.search(r"SyntaxError|IndentationError", feedback))
    if trace.get("passed"):
        return {"whole": True, "word": True, "merge": True,
                "word_defined": word_defined, "merge_defined": merge_defined}
    return {
        "whole": False,
        "word": word_defined and not word_fail and not syntax,
        "merge": merge_defined and not merge_fail and not syntax,
        "word_defined": word_defined,
        "merge_defined": merge_defined,
    }


def _load_run(cfg: dict, run_id: str) -> dict:
    return evaluator.load_run(cfg, run_id)


def run_config(cfg: dict, harness_path: str, name: str,
               adapter: str | None, split: str, task_ids: list[str] | None,
               run_id: str) -> dict:
    args = ["eval", "--harness", harness_path, "--split", split,
            "--run-id", run_id]
    if adapter:
        args += ["--adapter", adapter]
    if task_ids:
        args += ["--task-ids", ",".join(task_ids)]
    rc = _run_cli(args)
    if rc:
        raise RuntimeError(f"eval failed for {name} (rc={rc})")
    return _load_run(cfg, run_id)


def summarize(cfg: dict, whole_run: dict, parts_run: dict | None) -> dict:
    whole = [parse_trace(t) for t in whole_run["tasks"]]
    n = len(whole)
    row = {
        "whole_pass": sum(1 for x in whole if x["whole"]),
        "whole_n": n,
        "word_ok": sum(1 for x in whole if x["word"]),
        "merge_ok": sum(1 for x in whole if x["merge"]),
        "word_defined": sum(1 for x in whole if x["word_defined"]),
        "merge_defined": sum(1 for x in whole if x["merge_defined"]),
        "whole_tasks": {t["task_id"]: parse_trace(t) for t in whole_run["tasks"]},
    }
    if parts_run:
        parts = {t["task_id"]: t for t in parts_run["tasks"]}
        row["parts_word"] = sum(1 for tid in PARTS if tid.startswith("probe_wf")
                                and parts.get(tid, {}).get("passed"))
        row["parts_merge"] = sum(1 for tid in PARTS if tid.startswith("probe_mi")
                                 and parts.get(tid, {}).get("passed"))
        row["parts_word_n"] = sum(1 for tid in PARTS if tid.startswith("probe_wf"))
        row["parts_merge_n"] = sum(1 for tid in PARTS if tid.startswith("probe_mi"))
    return row


def run_matrix(cfg: dict, harness_path: str | None = None) -> dict:
    harness_path = harness_path or str(Path(cfg["paths"]["harness"]) / "h0_baseline.json")
    root = Path(cfg["paths"]["adapters"]) / "skills"
    merged = build_composition_adapters(cfg)
    # Verify the merged adapter loads before spending a full matrix.
    verify = verify_load(cfg, merged["full"]["dir"])

    configs = {
        "base": None,
        "word": str(root / "word_freq"),
        "merge": str(root / "merge_intervals"),
        "dual_full": merged["full"]["dir"],
        "dual_half": merged["half"]["dir"],
    }
    rows = {}
    for name, adapter in configs.items():
        whole_id = f"comp_{name}_whole"
        parts_id = f"comp_{name}_parts"
        whole = run_config(cfg, harness_path, name, adapter, "composition",
                           None, whole_id)
        parts = run_config(cfg, harness_path, name, adapter, "skills",
                           PARTS, parts_id)
        rows[name] = summarize(cfg, whole, parts)

    result = {
        "harness": Path(harness_path).stem,
        "parts_tasks": PARTS,
        "composition_tasks": [f"comp_0{i}" for i in range(1, 6)],
        "adapters": merged,
        "verify_load": verify,
        "configs": rows,
    }
    out = Path(cfg["paths"]["runs"]) / "composition_matrix.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    (Path(cfg["paths"]["reports"]) / "composition.md").write_text(
        format_matrix(result) + "\n")
    return result


def format_matrix(result: dict) -> str:
    lines = [
        "# Composition experiment — two skills, one compound task",
        "",
        "Each compound task requires `word_freq` and `merge_intervals` in one",
        "solution. `dual_full` is gate 1.0 + 1.0 (Σ=2); `dual_half` is 0.5 + 0.5",
        "(Σ=1). The deployed router is also Σ≤1.",
        "",
        f"Parts subset: {', '.join(result['parts_tasks'])}",
        "",
        "| config | parts word | parts merge | whole | word fn ok | merge fn ok |",
        "|---|---|---|---|---|---|",
    ]
    for name, r in result["configs"].items():
        lines.append(
            f"| `{name}` | {r.get('parts_word', '—')}/{r.get('parts_word_n', '—')} | "
            f"{r.get('parts_merge', '—')}/{r.get('parts_merge_n', '—')} | "
            f"**{r['whole_pass']}/{r['whole_n']}** | {r['word_ok']}/{r['whole_n']} | "
            f"{r['merge_ok']}/{r['whole_n']} |"
        )
    lines += [
        "",
        "Reading: a single gate can pass its own part and still fail the whole.",
        "The paper's 0.5B result predicts that two full gates can collapse; this",
        "matrix reports what actually happened on this rig, not a forced result.",
    ]
    return "\n".join(lines)
