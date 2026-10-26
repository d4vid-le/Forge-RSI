"""Layer 3 bridge: turn run traces into SkillForge-importable rows.

Only passing trajectories become SFT positives. A failed attempt followed by a
passing retry on the same task becomes a repair pair. Nothing from the holdout
is ever exported.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from . import harness as harness_mod


def _load_tasks(cfg: dict) -> dict[str, dict]:
    out = {}
    for split in ("dev", "holdout"):
        d = Path(cfg["paths"]["tasks"]) / split
        for p in sorted(d.glob("*.json")):
            t = json.loads(p.read_text())
            t["_split"] = split
            out[t["id"]] = t
    return out


def _code_key(code: str) -> str:
    return hashlib.sha256((code or "").strip().encode()).hexdigest()[:16]


def build_rows(cfg: dict, runs: list[dict]) -> list[dict]:
    """Runs must be chronological. Returns deduped SkillForge rows."""
    tasks = _load_tasks(cfg)
    rows: list[dict] = []
    seen: set[str] = set()
    last_fail: dict[str, dict] = {}

    for run in runs:
        h = run.get("harness", {})
        system = harness_mod.render(h)
        for t in run["tasks"]:
            if t.get("task_id", "").startswith("hold_"):
                continue
            task = tasks.get(t["task_id"])
            if not task:
                continue
            key = f"{t['task_id']}:{_code_key(t.get('code', ''))}"
            if t["passed"]:
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": task["prompt"]},
                        {"role": "assistant", "content": t["code"]},
                    ],
                    "meta": {
                        "source": "forge-rsi",
                        "run_id": run["run_id"],
                        "task_id": t["task_id"],
                        "harness": h.get("version"),
                        "kind": "success",
                        "passed": True,
                    },
                })
                last_fail.pop(t["task_id"], None)
            else:
                last_fail[t["task_id"]] = t

        # Repair pairs: a task that failed in an earlier run and passes in this one.
        for tid, fail in list(last_fail.items()):
            cur = next((x for x in run["tasks"] if x["task_id"] == tid and x["passed"]), None)
            if not cur:
                continue
            task = tasks[tid]
            key = f"{tid}:repair:{_code_key(cur.get('code', ''))}"
            if key in seen:
                continue
            seen.add(key)
            # Never copy verifier output into training data: it contains test
            # names, assertions, and absolute temp paths. Keep only the error
            # class, which is a harmless signal.
            rows.append({
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": task["prompt"]},
                    {"role": "assistant", "content": (
                        f"The previous attempt failed with a {fail.get('error_class', 'unknown')} error.\n\n"
                        f"Corrected solution:\n{cur['code']}"
                    )},
                ],
                "meta": {
                    "source": "forge-rsi",
                    "run_id": run["run_id"],
                    "task_id": tid,
                    "harness": h.get("version"),
                    "kind": "repair",
                    "passed": True,
                },
            })
            last_fail.pop(tid, None)
    return rows


def write_raw(cfg: dict, runs: list[dict], tag: str) -> tuple[Path, dict]:
    rows = build_rows(cfg, runs)
    raw_dir = Path(cfg["paths"]["curriculum"]) / "01_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    path = raw_dir / f"{stamp}-rsi-{tag}-raw.jsonl"
    with open(path, "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    by_kind: dict[str, int] = {}
    by_task: dict[str, int] = {}
    for r in rows:
        by_kind[r["meta"]["kind"]] = by_kind.get(r["meta"]["kind"], 0) + 1
        by_task[r["meta"]["task_id"]] = by_task.get(r["meta"]["task_id"], 0) + 1
    manifest = {
        "file": str(path),
        "rows": len(rows),
        "by_kind": by_kind,
        "tasks_covered": len(by_task),
        "runs": [r["run_id"] for r in runs],
        "created_at": stamp,
        "note": "holdout never included; messages contain no task ids",
    }
    (raw_dir / f"{stamp}-rsi-{tag}-raw.manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return path, manifest
