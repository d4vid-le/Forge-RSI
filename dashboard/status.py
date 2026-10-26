"""Read-only status collection for the SkillForge ops dashboard.

Everything here is derived from files on disk: the skill registries, gated
evaluation reports, RSI iteration logs, the composition matrix, and the
sanitized markdown reports. No model calls. No writes.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path


def _load(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _rel(path: str | Path | None, root: Path) -> str | None:
    if not path:
        return None
    p = Path(path)
    try:
        return str(p.resolve().relative_to(root.resolve()))
    except Exception:
        return str(p)


def _task_lint(tasks_root: Path) -> dict:
    failures = []
    total = 0
    for split in ("dev", "holdout", "skills", "composition", "private_holdout"):
        d = tasks_root / split
        if not d.exists():
            continue
        for p in sorted(d.glob("*.json")):
            total += 1
            task = _load(p, {})
            chunks = re.findall(r"from solution import ([A-Za-z0-9_, ]+)",
                                task.get("tests", ""))
            wanted = [n.strip() for c in chunks for n in c.split(",") if n.strip()]
            missing = [n for n in wanted
                       if not re.search(rf"\b{re.escape(n)}\b", task.get("prompt", ""))]
            if not wanted or missing:
                failures.append({"split": split, "id": task.get("id"),
                                 "missing": missing})
    return {"ok": not failures, "n": total, "failures": failures}


def _registries(cfg: dict, root: Path) -> list[dict]:
    out = []
    roots = [
        ("round 1", Path(cfg["paths"]["adapters"]) / "skills" / "registry.json"),
        ("round 2", Path(cfg["paths"]["adapters"]) / "skills" / "r2" / "registry.json"),
    ]
    for label, path in roots:
        reg = _load(path, {})
        for name, e in (reg or {}).items():
            tr = e.get("training") or {}
            loss = tr.get("loss") or {}
            data = e.get("data") or {}
            adapter = Path(e["adapter"]) if e.get("adapter") else None
            out.append({
                "round": label,
                "skill": name,
                "status": e.get("status", "unknown"),
                "adapter": _rel(e.get("adapter"), root),
                "adapter_exists": bool(adapter and
                                       (adapter / "adapters.safetensors").exists()),
                "rows": data.get("rows"),
                "iters": tr.get("iters"),
                "train_loss": loss.get("train_loss_last"),
                "val_loss": loss.get("val_loss_last"),
                "base_unchanged": e.get("base_unchanged"),
                "decision": e.get("decision") or {},
            })
    return out


def _evaluations(cfg: dict, root: Path) -> list[dict]:
    runs = Path(cfg["paths"]["runs"])
    out = []
    for p in sorted(runs.glob("*_gated_report.json")):
        r = _load(p)
        if not r:
            continue
        b = r.get("base_summary") or {}
        g = r.get("gated_summary") or {}
        out.append({
            "run": p.name[: -len("_gated_report.json")],
            "split": r.get("split"),
            "base": b,
            "gated": g,
            "delta": r.get("delta_score"),
            "routed": len(r.get("routed_tasks") or []),
            "non_routed_identical": r.get("non_routed_identical"),
            "base_unchanged": r.get("base_unchanged"),
        })
    out.sort(key=lambda x: (str(x.get("split")), str(x.get("run"))))
    return out


def _rsi(cfg: dict) -> tuple[list[dict], list[dict]]:
    runs = Path(cfg["paths"]["runs"])
    iters, holds = [], []
    for p in sorted(runs.glob("iterations_*.jsonl")):
        round_name = p.stem.replace("iterations_", "")
        try:
            lines = p.read_text().splitlines()
        except Exception:
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if "iteration" in r:
                iters.append({
                    "round": round_name,
                    "iteration": r.get("iteration"),
                    "candidate": r.get("candidate"),
                    "wins": r.get("wins"),
                    "losses": r.get("losses"),
                    "ties": r.get("ties"),
                    "candidate_score": r.get("candidate_score"),
                    "delta": r.get("delta"),
                    "accepted": r.get("accepted"),
                    "reason": r.get("reason"),
                    "candidate_cost": r.get("candidate_cost"),
                })
            elif r.get("kind") == "holdout":
                holds.append({
                    "round": round_name,
                    "baseline_score": r.get("baseline_score"),
                    "final_score": r.get("final_score"),
                    "delta": r.get("delta"),
                    "not_worse": r.get("not_worse"),
                    "winner_harness": r.get("winner_harness"),
                })
    return iters, holds


def _reports(cfg: dict) -> list[dict]:
    reports = Path(cfg["paths"]["reports"])
    out = []
    for p in sorted(reports.glob("*.md")):
        try:
            stat = p.stat()
        except OSError:
            continue
        out.append({"name": p.name, "bytes": stat.st_size,
                    "modified": time.strftime("%Y-%m-%dT%H:%M:%S",
                                              time.localtime(stat.st_mtime))})
    return out


def collect(cfg: dict) -> dict:
    root = Path(cfg["paths"]["project"])
    base = Path(cfg["paths"]["agent"])
    tasks_root = Path(cfg["paths"]["tasks"])
    runs = Path(cfg["paths"]["runs"])

    skills = _registries(cfg, root)
    evals = _evaluations(cfg, root)
    iters, holds = _rsi(cfg)
    task_counts = {
        split: len(list((tasks_root / split).glob("*.json")))
        for split in ("dev", "holdout", "skills", "composition", "private_holdout")
        if (tasks_root / split).exists()
    }
    lint = _task_lint(tasks_root)
    checksums = sorted({s.get("base_unchanged") for s in skills
                        if s.get("base_unchanged") is not None})
    return {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "project": str(root),
        "base": {
            "path": str(base),
            "exists": base.exists(),
            "checksums_ok": all(checksums) if checksums else None,
        },
        "tasks": {"counts": task_counts, "lint": lint},
        "skills": skills,
        "evaluations": evals,
        "rsi": {"iterations": iters, "holdout": holds},
        "composition": _load(runs / "composition_matrix.json", {}),
        "private_decision": _load(runs / "private_round2_decision.json", {}),
        "reports": _reports(cfg),
    }
