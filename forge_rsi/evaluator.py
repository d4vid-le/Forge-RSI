"""Evaluation and pairwise comparison."""
from __future__ import annotations

import json
import time
from pathlib import Path

from . import agent
from . import harness as harness_mod

SPLITS = {"dev": "dev", "dev_hard": "dev_hard", "holdout": "holdout",
          "skills": "skills", "composition": "composition",
          "private_holdout": "private_holdout"}


def tasks_dir(cfg: dict, split: str) -> Path:
    return Path(cfg["paths"]["tasks"]) / split


def load_tasks(cfg: dict, split: str) -> list[dict]:
    d = tasks_dir(cfg, split)
    if not d.exists():
        raise FileNotFoundError(f"no task split at {d}")
    tasks = []
    for p in sorted(d.glob("*.json")):
        tasks.append(json.loads(p.read_text()))
    if not tasks:
        raise ValueError(f"empty task split at {d}")
    return tasks


def summarize(traces: list[dict]) -> dict:
    n = len(traces)
    passed = sum(1 for t in traces if t["passed"])
    by_error: dict[str, int] = {}
    by_tag: dict[str, dict[str, int]] = {}
    tag_map = {}
    for t in traces:
        by_error[t["error_class"]] = by_error.get(t["error_class"], 0) + 1
    return {
        "n": n,
        "passed": passed,
        "score": round(passed / n, 4) if n else 0.0,
        "tokens_in": sum(t["tokens_in"] for t in traces),
        "tokens_out": sum(t["tokens_out"] for t in traces),
        "turns": sum(t["turns"] for t in traces),
        "wall_s": round(sum(t["wall_s"] for t in traces), 2),
        "by_error": by_error,
        "cost_per_solved": round(
            (sum(t["tokens_out"] for t in traces) / passed) if passed else float("inf"), 1),
    }


def evaluate(cfg: dict, h: dict, split: str, run_id: str,
             samples: int = 1, adapter_path: str | None = None,
             limit: int | None = None, use_tools: bool = True,
             temperature: float | None = None,
             task_ids: list[str] | None = None) -> dict:
    tasks = load_tasks(cfg, split)
    if task_ids:
        wanted = set(task_ids)
        tasks = [t for t in tasks if t["id"] in wanted]
        missing = wanted - {t["id"] for t in tasks}
        if missing:
            raise ValueError(f"task ids not in split {split}: {sorted(missing)}")
    if limit:
        tasks = tasks[:limit]
    model, tok = agent.load_model(cfg["paths"]["agent"], adapter_path=adapter_path)
    traces = []
    t0 = time.time()
    for i, task in enumerate(tasks, 1):
        trace = agent.run_task(model, tok, h, task, cfg, seed=i * 101,
                               samples=samples, use_tools=use_tools,
                               temperature=temperature)
        traces.append(trace)
        print(f"[eval {run_id}] {i:02d}/{len(tasks)} {task['id']:9} "
              f"{'PASS' if trace['passed'] else 'fail':4} "
              f"{trace['tokens_out']:5d} tok  {trace['wall_s']:6.1f}s", flush=True)

    result = {
        "run_id": run_id,
        "split": split,
        "model": cfg["paths"]["agent"],
        "adapter": adapter_path,
        "samples": samples,
        "use_tools": use_tools,
        "task_ids": [t["id"] for t in tasks],
        "harness": h,
        "harness_hash": harness_mod.harness_hash(h),
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "wall_s": round(time.time() - t0, 2),
        "summary": summarize(traces),
        "tasks": traces,
    }
    runs = Path(cfg["paths"]["runs"])
    runs.mkdir(parents=True, exist_ok=True)
    (runs / f"{run_id}.json").write_text(json.dumps(result, indent=2) + "\n")
    with open(runs / "runs.jsonl", "a") as f:
        f.write(json.dumps({
            "run_id": run_id, "split": split, "harness_hash": result["harness_hash"],
            "summary": result["summary"], "at": result["started_at"],
        }) + "\n")
    print(f"[eval {run_id}] score {result['summary']['score']:.2f} "
          f"({result['summary']['passed']}/{result['summary']['n']}) "
          f"in {result['wall_s']/60:.1f} min", flush=True)
    return result


def load_run(cfg: dict, run_id_or_path: str) -> dict:
    p = Path(run_id_or_path)
    if not p.exists():
        p = Path(cfg["paths"]["runs"]) / f"{run_id_or_path}.json"
    if not p.exists():
        raise FileNotFoundError(f"no run at {run_id_or_path}")
    return json.loads(p.read_text())


def compare(a: dict, b: dict) -> dict:
    """Compare run b (candidate) against run a (incumbent) task-by-task."""
    amap = {t["task_id"]: t for t in a["tasks"]}
    bmap = {t["task_id"]: t for t in b["tasks"]}
    ids = sorted(set(amap) & set(bmap))
    wins, losses, ties = [], [], []
    for tid in ids:
        ap, bp = amap[tid]["passed"], bmap[tid]["passed"]
        if bp and not ap:
            wins.append(tid)
        elif ap and not bp:
            losses.append(tid)
        else:
            ties.append(tid)
    n = len(ids) or 1
    return {
        "n": len(ids),
        "wins": wins,
        "losses": losses,
        "ties": ties,
        "win_count": len(wins),
        "loss_count": len(losses),
        "tie_count": len(ties),
        "candidate_score": b["summary"]["score"],
        "incumbent_score": a["summary"]["score"],
        "delta": round(b["summary"]["score"] - a["summary"]["score"], 4),
        "accept": len(wins) > len(losses),
    }


def acceptance(cmp: dict, candidate: dict, incumbent: dict, cfg: dict) -> tuple[bool, str]:
    """Apply the full acceptance rule, not just wins > losses."""
    loop = cfg["loop"]
    if not cmp["accept"]:
        return False, f"wins {cmp['win_count']} <= losses {cmp['loss_count']}"
    if cmp["candidate_score"] < cmp["incumbent_score"] - loop["score_tolerance"]:
        return False, (f"score {cmp['candidate_score']:.2f} trails "
                       f"{cmp['incumbent_score']:.2f}")
    base_cost = incumbent["summary"]["cost_per_solved"]
    new_cost = candidate["summary"]["cost_per_solved"]
    if base_cost and new_cost and new_cost > base_cost * loop["cost_ceiling"]:
        return False, f"cost {new_cost:.0f} > {loop['cost_ceiling']}x {base_cost:.0f}"
    return True, "accepted"
