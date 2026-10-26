"""Gap detection and verified corpus mining.

Given a measured run, find failing task clusters, then mine *verified* passing
traces for those tasks into a SkillForge raw corpus. Two rules are absolute:

* the public holdout and the private holdout are never read for gap mining;
* a row is written only after its code passes the task's hidden tests again.

No teacher call is made here. A gap with no verified pass is reported as a
missing reference, not filled with invented code.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import evaluator
from . import harness as harness_mod
from . import verifier

ALLOWED_SPLITS = ("dev", "skills", "composition")
KNOWN_SKILLS = ("word_freq", "merge_intervals", "rle", "second_largest",
                "sum_even", "capitalize_words", "rle_encode")


class GapError(RuntimeError):
    """Gap detection or mining refused."""


def _load(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "run"


def _runs(cfg: dict) -> list[dict]:
    out = []
    for p in sorted(Path(cfg["paths"]["runs"]).glob("*.json")):
        d = _load(p)
        if not isinstance(d, dict):
            continue
        if d.get("split") not in ALLOWED_SPLITS or not d.get("tasks"):
            continue
        d["_file"] = p.name
        out.append(d)
    out.sort(key=lambda d: (str(d.get("started_at") or ""), d["_file"]))
    return out


def resolve_run(cfg: dict, run_id: str | None = None) -> dict:
    if run_id and run_id not in ("latest", "auto"):
        run = evaluator.load_run(cfg, run_id)
        if run.get("split") not in ALLOWED_SPLITS:
            raise GapError(
                f"gap mining refuses split {run.get('split')!r}; allowed: "
                + ", ".join(ALLOWED_SPLITS))
        return run
    candidates = _runs(cfg)
    if not candidates:
        raise GapError("no measured dev/skills/composition runs found")
    failing = [r for r in candidates
               if any(not t.get("passed") for t in r.get("tasks", []))]
    return (failing or candidates)[-1]


def _task_index(cfg: dict, split: str) -> dict[str, dict]:
    try:
        return {t["id"]: t for t in evaluator.load_tasks(cfg, split)}
    except (FileNotFoundError, ValueError):
        return {}


def _skill(task: dict | None, trace: dict) -> str:
    task = task or {}
    tags = [t for t in (task.get("tags") or []) if t in KNOWN_SKILLS]
    if len(tags) > 1:
        return "+".join(sorted(tags))
    if tags:
        return tags[0]
    text = f"{task.get('title', '')} {task.get('prompt', '')}".lower()
    if any(k in text for k in ("word", "frequency", "token count", "count_words")):
        return "word_freq"
    if any(k in text for k in ("interval", "merge", "span")):
        return "merge_intervals"
    if "run-length" in text or "rle" in text:
        return "rle"
    if "second-largest" in text or "second largest" in text:
        return "second_largest"
    if trace.get("gate"):
        return f"gate:{trace['gate']}"
    return "unclassified"


def detect(cfg: dict, run_id: str | None = None) -> dict:
    run = resolve_run(cfg, run_id)
    split = run["split"]
    tasks = _task_index(cfg, split)
    clusters: dict[str, dict] = {}
    for trace in run.get("tasks", []):
        key = _skill(tasks.get(trace.get("task_id")), trace)
        c = clusters.setdefault(key, {
            "key": key, "failed": 0, "total": 0,
            "by_error": {}, "tasks": [], "verified_rows": 0, "missing": [],
        })
        c["total"] += 1
        if not trace.get("passed"):
            c["failed"] += 1
            err = trace.get("error_class") or "unknown"
            c["by_error"][err] = c["by_error"].get(err, 0) + 1
            meta = tasks.get(trace.get("task_id"), {})
            c["tasks"].append({
                "id": trace.get("task_id"),
                "title": meta.get("title") or trace.get("task_id"),
                "error_class": err,
            })
    ordered = sorted(clusters.values(),
                     key=lambda c: (-c["failed"], c["key"]))
    summary = run.get("summary") or {}
    report = {
        "run_id": run.get("run_id") or run_id,
        "split": split,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "model": run.get("model"),
        "harness": run.get("harness", {}).get("version"),
        "summary": summary,
        "clusters": ordered,
        "excluded_splits": ["holdout", "private_holdout"],
        "policy": ("holdout and private slices are guards, never a source of "
                   "training data; a row requires a re-verified passing trace"),
        "corpus": None,
    }
    report["json"] = str(_write_json(cfg, report))
    report["report"] = str(write_report(cfg, report))
    return report


def _write_json(cfg: dict, report: dict) -> Path:
    p = Path(cfg["paths"]["runs"]) / f"gaps_{_safe(report['run_id'])}.json"
    p.write_text(json.dumps(report, indent=2) + "\n")
    return p


def _layout(report: dict) -> list[str]:
    s = report.get("summary") or {}
    lines = [
        f"# Skill gaps — `{report['run_id']}`",
        "",
        f"- split: **{report['split']}**",
        f"- measured: **{s.get('passed', '—')}/{s.get('n', '—')}**",
        f"- model: `{Path(report['model']).name if report.get('model') else '—'}`",
        f"- generated: {report['generated_at']}",
        "- policy: the public and private holdouts are excluded from gap mining",
        "",
        "## Clusters",
        "",
        "| skill | failed | total | errors | verified rows | missing |",
        "|---|---|---|---|---|---|",
    ]
    for c in report.get("clusters", []):
        errors = ", ".join(f"{k} {v}" for k, v in sorted(c.get("by_error", {}).items())) or "—"
        lines.append(
            f"| `{c['key']}` | {c['failed']} | {c['total']} | {errors} | "
            f"{c.get('verified_rows', 0)} | {len(c.get('missing') or [])} |")
    if not report.get("clusters"):
        lines.append("| — | 0 | 0 | — | 0 | 0 |")
    corpus = report.get("corpus")
    lines += ["", "## Corpus", ""]
    if corpus:
        lines += [
            f"- file: `{Path(corpus['file']).name}`",
            f"- rows: **{corpus['rows']}** (verified: {corpus.get('verified', 0)})",
            f"- by kind: `{json.dumps(corpus.get('by_kind', {}))}`",
            f"- missing references: {len(corpus.get('missing') or [])}",
            "- next: import the raw file, review it, and export through the hard gates",
        ]
    else:
        lines.append("Not built yet. Run `gaps-mine` on this run to mine verified traces.")
    lines += [
        "",
        "A missing reference is shown as missing on purpose. This report never",
        "contains hidden tests, holdout prompts, or invented solutions.",
        "",
    ]
    return lines


def write_report(cfg: dict, report: dict) -> Path:
    reports = Path(cfg["paths"]["reports"])
    reports.mkdir(parents=True, exist_ok=True)
    p = reports / "gaps.md"
    p.write_text("\n".join(_layout(report)))
    return p


def _verified(task: dict | None, code: str) -> bool:
    if not task or not code:
        return False
    try:
        return bool(verifier.verify(code, task).get("passed"))
    except Exception:
        return False


def mine(cfg: dict, run_id: str | None = None, min_rows: int = 1) -> dict:
    """Mine verified passing traces for the detected gap tasks."""
    report = detect(cfg, run_id)
    split = report["split"]
    tasks = _task_index(cfg, split)
    gap_ids = {t["id"] for c in report["clusters"] for t in c["tasks"]}
    runs = _runs(cfg)
    rows: list[dict] = []
    seen: set[tuple[str, str, str]] = set()
    used_runs: set[str] = set()
    verified_by_skill: dict[str, int] = {}
    missing: list[dict] = []
    global_h0 = _load(Path(cfg["paths"]["harness"]) / "h0_baseline.json", {})

    for tid in sorted(gap_ids):
        task = tasks.get(tid)
        if not task:
            missing.append({"id": tid, "reason": "task metadata not found"})
            continue
        skill = _skill(task, {})
        traces = [(run, next(t for t in run["tasks"] if t.get("task_id") == tid))
                  for run in runs
                  if any(t.get("task_id") == tid for t in run["tasks"])]
        if not traces:
            missing.append({"id": tid, "reason": "no measured trace"})
            continue
        pass_run, pass_trace = next(
            ((r, t) for r, t in reversed(traces) if t.get("passed")), (None, None))
        if not pass_trace or not _verified(task, pass_trace.get("code", "")):
            missing.append({"id": tid, "reason": "no re-verified passing trace"})
            continue
        sys_prompt = harness_mod.render(pass_run.get("harness") or global_h0)
        code = pass_trace.get("code", "").strip()
        key = (tid, "success", code)
        if key not in seen:
            seen.add(key)
            rows.append({
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user", "content": task["prompt"]},
                    {"role": "assistant", "content": code},
                ],
                "meta": {"source": "forge-rsi-gap", "run_id": pass_run.get("run_id"),
                         "task_id": tid, "skill": skill, "kind": "success",
                         "passed": True, "verified": True},
            })
            verified_by_skill[skill] = verified_by_skill.get(skill, 0) + 1
            used_runs.add(str(pass_run.get("run_id")))

        earlier_fail = next(
            ((r, t) for r, t in traces if not t.get("passed")), None)
        if earlier_fail:
            fail_trace = earlier_fail[1]
            err = fail_trace.get("error_class") or "unknown"
            key = (tid, "repair", code)
            if key not in seen:
                seen.add(key)
                rows.append({
                    "messages": [
                        {"role": "system", "content": sys_prompt},
                        {"role": "user", "content": task["prompt"]},
                        {"role": "assistant", "content": (
                            f"The previous attempt failed with a {err} error.\n\n"
                            f"Corrected solution:\n{code}")},
                    ],
                    "meta": {"source": "forge-rsi-gap", "run_id": pass_run.get("run_id"),
                             "task_id": tid, "skill": skill, "kind": "repair",
                             "passed": True, "verified": True},
                })
                verified_by_skill[skill] = verified_by_skill.get(skill, 0) + 1
                used_runs.add(str(pass_run.get("run_id")))

    by_kind: dict[str, int] = {}
    for row in rows:
        kind = row["meta"]["kind"]
        by_kind[kind] = by_kind.get(kind, 0) + 1

    stamp = time.strftime("%Y%m%d-%H%M%S")
    raw_dir = Path(cfg["paths"]["curriculum"]) / "01_raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{stamp}-gap-{_safe(report['run_id'])}-raw.jsonl"
    with open(path, "w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    manifest = {
        "file": str(path),
        "rows": len(rows),
        "verified": len(rows),
        "by_kind": by_kind,
        "by_skill": verified_by_skill,
        "tasks_covered": len({r["meta"]["task_id"] for r in rows}),
        "runs": sorted(used_runs),
        "missing": missing,
        "created_at": stamp,
        "note": ("holdout and private slices excluded; every row re-verified "
                 "with the task's hidden tests before writing"),
    }
    (raw_dir / f"{stamp}-gap-{_safe(report['run_id'])}-raw.manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n")

    # attach per-cluster counts and the corpus to the report
    by_skill = verified_by_skill
    for c in report["clusters"]:
        c["verified_rows"] = by_skill.get(c["key"], 0)
        c["missing"] = [m for m in missing
                        if m["id"] in {t["id"] for t in c["tasks"]}]
    report["corpus"] = manifest
    _write_json(cfg, report)
    write_report(cfg, report)
    if len(rows) < min_rows:
        raise GapError(
            f"mined {len(rows)} verified rows, below --min-rows {min_rows}")
    return report


def format_report(report: dict) -> str:
    return "\n".join(_layout(report))
