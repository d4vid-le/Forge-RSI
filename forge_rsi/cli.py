"""Forge-RSI command line.

Run with the MLX environment:
    /Users/dblab/mlx-env/bin/python -m forge_rsi <command> ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from . import (bridge, composition, config, dream, evaluator, final_report,
               harness as harness_mod, legates, optimizer, pipeline, report, trainer)


# ───────────────────────────── helpers ─────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _run_cli(args: list[str]) -> int:
    cmd = [sys.executable, "-m", "forge_rsi"] + args
    print("[run]", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


def _iter_file(cfg: dict, round_name: str) -> Path:
    return Path(cfg["paths"]["runs"]) / f"iterations_{round_name}.jsonl"


def _append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row) + "\n")


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


# ───────────────────────────── commands ────────────────────────────

def cmd_freeze(cfg: dict, a) -> int:
    tasks_root = Path(cfg["paths"]["tasks"])
    files = sorted((tasks_root / "dev").glob("*.json")) + sorted((tasks_root / "holdout").glob("*.json"))
    files += sorted(Path(__file__).resolve().parent.glob("*.py"))
    files += [Path(cfg["_config_path"])]
    entries = {str(p.relative_to(Path(cfg["paths"]["project"]))): _sha256(p) for p in files}
    combined = hashlib.sha256("".join(f"{k}:{v}" for k, v in sorted(entries.items())).encode()).hexdigest()
    payload = {
        "frozen_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "task_counts": {"dev": len(list((tasks_root / "dev").glob("*.json"))),
                         "holdout": len(list((tasks_root / "holdout").glob("*.json")))},
        "combined_sha256": combined,
        "files": entries,
    }
    out = tasks_root / "FREEZE.json"
    out.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"[freeze] {payload['task_counts']} combined={combined[:16]}… -> {out}")
    if payload["task_counts"] != {"dev": 20, "holdout": 10}:
        print("[freeze] HARD STOP: expected 20 dev + 10 holdout", file=sys.stderr)
        return 2
    return 0


def cmd_eval(cfg: dict, a) -> int:
    h = harness_mod.load(a.harness)
    task_ids = [x.strip() for x in a.task_ids.split(",") if x.strip()] if a.task_ids else None
    result = evaluator.evaluate(
        cfg, h, a.split, a.run_id, samples=a.samples,
        adapter_path=a.adapter, limit=a.limit, use_tools=not a.no_tools,
        temperature=a.temperature, task_ids=task_ids,
    )
    print(json.dumps(result["summary"], indent=2))
    return 0


def cmd_propose(cfg: dict, a) -> int:
    incumbent = harness_mod.load(a.harness)
    run = evaluator.load_run(cfg, a.run_id)
    history = [r for r in _read_jsonl(_iter_file(cfg, a.round_name))
               if "iteration" in r] if a.round_name else []
    failures = []
    tasks = evaluator.load_tasks(cfg, run["split"])
    tmap = {t["id"]: t for t in tasks}
    for t in run["tasks"]:
        if not t["passed"]:
            task = tmap.get(t["task_id"], {})
            failures.append({
                "task_id": t["task_id"], "title": task.get("title", ""),
                "prompt": task.get("prompt", ""), "error_class": t["error_class"],
                "feedback": t.get("feedback", ""), "code": t.get("code", ""),
            })
    version = Path(a.out).stem
    probes = []
    probe_path = Path(cfg["paths"]["runs"]) / "probes.json"
    if probe_path.exists():
        probes = json.loads(probe_path.read_text())
    candidate, raw, errors = optimizer.propose(cfg, incumbent, history, failures,
                                               version, probes=probes)
    if candidate is None:
        err_path = Path(cfg["paths"]["runs"]) / f"{version}_proposal_error.txt"
        err_path.write_text(raw + "\n\nERRORS:\n" + "\n".join(errors))
        print(f"[propose] REJECTED: {errors}\n  raw saved to {err_path}")
        return 3
    harness_mod.save(candidate, a.out)
    print(f"[propose] wrote {a.out} ({harness_mod.harness_hash(candidate)})")
    changed = [k for k in harness_mod.diff_fields(incumbent, candidate) if k != "version"]
    print(f"[propose] changed fields: {changed}")
    return 0


def cmd_compare(cfg: dict, a) -> int:
    inc = evaluator.load_run(cfg, a.incumbent)
    cand = evaluator.load_run(cfg, a.candidate)
    cmp = evaluator.compare(inc, cand)
    ok, reason = evaluator.acceptance(cmp, cand, inc, cfg)
    print(json.dumps({**cmp, "accepted": ok, "reason": reason}, indent=2))
    return 0 if ok else 4


def cmd_dream(cfg: dict, a) -> int:
    run = evaluator.load_run(cfg, a.run)
    result = dream.run_and_write(cfg, run)
    print(dream.format_table(result))
    return 0


def cmd_bridge(cfg: dict, a) -> int:
    runs = [evaluator.load_run(cfg, r) for r in a.run]
    path, manifest = bridge.write_raw(cfg, runs, a.tag)
    print(f"[bridge] {manifest['rows']} rows -> {path}")
    print(json.dumps(manifest, indent=2))
    return 0 if manifest["rows"] >= a.min_rows else 5


def cmd_train(cfg: dict, a) -> int:
    data = Path(a.data)
    if data.is_file():
        out = Path(a.workdir or (Path(cfg["paths"]["adapters"]) / f"{Path(a.adapter).name}_data"))
        info = trainer.prepare_data(data, out)
        print(f"[train] prepared {info}")
        data = out
    res = trainer.train(cfg, data, a.adapter, iters=a.iters)
    print(f"[train] rc={res['returncode']} adapter={res['adapter']}")
    print(res["tail"])
    return 0 if res["returncode"] == 0 else 6


def cmd_loop(cfg: dict, a) -> int:
    """Round loop: baseline -> propose/eval/compare xN -> holdout."""
    config.ensure_dirs(cfg)
    round_name = a.round
    start = a.start_harness or str(Path(cfg["paths"]["harness"]) / "h0_baseline.json")
    start_h = harness_mod.load(start)
    adapter = getattr(a, "adapter", None)
    extra = ["--adapter", adapter] if adapter else []

    if not (Path(cfg["paths"]["tasks"]) / "FREEZE.json").exists():
        rc = cmd_freeze(cfg, a)
        if rc:
            return rc

    prefix = f"{round_name}"
    baseline_id = f"{prefix}_h0"
    if not (Path(cfg["paths"]["runs"]) / f"{baseline_id}.json").exists():
        rc = _run_cli(["eval", "--harness", start, "--split", "dev", "--run-id", baseline_id] + extra)
        if rc:
            return rc
    incumbent_run = evaluator.load_run(cfg, baseline_id)
    incumbent_path = start

    # Baseline holdout (used only as a regression guard, never optimised).
    base_hold_id = f"{prefix}_baseline_holdout"
    if not (Path(cfg["paths"]["runs"]) / f"{base_hold_id}.json").exists():
        rc = _run_cli(["eval", "--harness", start, "--split", "holdout", "--run-id", base_hold_id] + extra)
        if rc:
            return rc
    base_hold = evaluator.load_run(cfg, base_hold_id)

    history = _read_jsonl(_iter_file(cfg, round_name))
    done = {r["iteration"]: r for r in history if "iteration" in r}

    # Resume: restore the incumbent from the last accepted iteration.
    for i in sorted(done):
        if done[i].get("accepted"):
            incumbent_run = evaluator.load_run(cfg, done[i]["candidate_run"])
            incumbent_path = str(Path(cfg["paths"]["harness"]) / f"{done[i]['candidate']}.json")

    reject_streak = 0
    for i in range(1, a.iterations + 1):
        if i in done:
            print(f"[loop] iter {i}: cached accepted={done[i].get('accepted')}", flush=True)
            continue

        candidate_id = f"{prefix}_h{i}"
        candidate_path = str(Path(cfg["paths"]["harness"]) / f"{candidate_id}.json")
        cached_run_path = Path(cfg["paths"]["runs"]) / f"{candidate_id}.json"

        if cached_run_path.exists():
            candidate_run = evaluator.load_run(cfg, candidate_id)
            harness_mod.save(candidate_run["harness"], candidate_path)
            print(f"[loop] iter {i}: reusing cached run {candidate_id}", flush=True)
        else:
            rc = _run_cli(["propose", "--harness", incumbent_path,
                           "--run-id", incumbent_run["run_id"],
                           "--out", candidate_path, "--round-name", round_name])
            if rc != 0:
                history.append({"iteration": i, "accepted": False,
                                "reason": "proposal invalid",
                                "candidate": f"{prefix}_h{i}"})
                _append_jsonl(_iter_file(cfg, round_name), history[-1])
                reject_streak += 1
                if reject_streak >= a.patience:
                    break
                continue

            rc = _run_cli(["eval", "--harness", candidate_path, "--split", "dev",
                           "--run-id", candidate_id, "--samples", str(a.samples)] + extra)
            if rc:
                return rc
            candidate_run = evaluator.load_run(cfg, candidate_id)
        cmp = evaluator.compare(incumbent_run, candidate_run)
        ok, reason = evaluator.acceptance(cmp, candidate_run, incumbent_run, cfg)
        row = {
            "round": round_name, "iteration": i,
            "incumbent": incumbent_run["harness"].get("version"),
            "candidate": candidate_run["harness"].get("version"),
            "wins": cmp["win_count"], "losses": cmp["loss_count"], "ties": cmp["tie_count"],
            "incumbent_score": cmp["incumbent_score"], "candidate_score": cmp["candidate_score"],
            "delta": cmp["delta"], "accepted": ok, "reason": reason,
            "candidate_run": candidate_id,
            "incumbent_run": incumbent_run["run_id"],
            "candidate_cost": candidate_run["summary"]["cost_per_solved"],
            "incumbent_cost": incumbent_run["summary"]["cost_per_solved"],
        }
        history.append(row)
        _append_jsonl(_iter_file(cfg, round_name), row)
        print(f"[loop] iter {i}: wins={cmp['win_count']} losses={cmp['loss_count']} "
              f"delta={cmp['delta']:+.2f} accepted={ok} ({reason})", flush=True)
        if ok:
            incumbent_run = candidate_run
            incumbent_path = candidate_path
            reject_streak = 0
        else:
            reject_streak += 1
            if reject_streak >= a.patience:
                print(f"[loop] stopping after {reject_streak} rejections", flush=True)
                break

    # Final holdout on the winner, exactly once.
    final_hold_id = f"{prefix}_final_holdout"
    if not (Path(cfg["paths"]["runs"]) / f"{final_hold_id}.json").exists():
        rc = _run_cli(["eval", "--harness", incumbent_path, "--split", "holdout",
                       "--run-id", final_hold_id] + extra)
        if rc:
            return rc
    final_hold = evaluator.load_run(cfg, final_hold_id)
    cmp = evaluator.compare(base_hold, final_hold)
    # The holdout is a regression guard, not a tournament: a tie is not worse.
    not_worse = (
        cmp["candidate_score"] >= cmp["incumbent_score"] - cfg["loop"]["score_tolerance"]
        and cmp["loss_count"] == 0
    )
    reason = "no regression" if not_worse else (
        f"{cmp['loss_count']} holdout regression(s), "
        f"delta {cmp['delta']:+.2f}"
    )
    hold_row = {
        "round": round_name, "kind": "holdout",
        "baseline": base_hold["run_id"], "final": final_hold["run_id"],
        "wins": cmp["win_count"], "losses": cmp["loss_count"],
        "baseline_score": cmp["incumbent_score"], "final_score": cmp["candidate_score"],
        "delta": cmp["delta"], "not_worse": not_worse, "reason": reason,
        "winner_harness": incumbent_run["harness"].get("version"),
    }
    _append_jsonl(_iter_file(cfg, round_name), hold_row)
    print(f"[loop] holdout: baseline={cmp['incumbent_score']:.2f} "
          f"final={cmp['candidate_score']:.2f} delta={cmp['delta']:+.2f} "
          f"not_worse={not_worse}")

    # Winner pointer for the next round.
    winner = Path(cfg["paths"]["harness"]) / f"{prefix}_winner.json"
    harness_mod.save(incumbent_run["harness"], winner)
    print(f"[loop] winner -> {winner}")
    report.write_round(cfg, round_name)
    return 0


def cmd_report(cfg: dict, a) -> int:
    path = report.write_round(cfg, a.round)
    print(f"[report] wrote {path}")
    return 0


def cmd_gaps_detect(cfg: dict, a) -> int:
    from . import gaps
    try:
        report = gaps.detect(cfg, a.run)
    except gaps.GapError as e:
        print(f"[gaps] {e}", file=sys.stderr)
        return 4
    print(gaps.format_report(report))
    return 0


def cmd_gaps_mine(cfg: dict, a) -> int:
    from . import gaps
    try:
        report = gaps.mine(cfg, a.run, min_rows=a.min_rows)
    except gaps.GapError as e:
        print(f"[gaps] {e}", file=sys.stderr)
        return 5
    print(gaps.format_report(report))
    print(json.dumps(report.get("corpus") or {}, indent=2))
    return 0


def cmd_holdout_status(cfg: dict, a) -> int:
    from . import holdout
    print(holdout.format_status(holdout.status(cfg)))
    return 0


def cmd_holdout_rotate(cfg: dict, a) -> int:
    from . import holdout
    try:
        result = holdout.rotate(cfg, count=a.count, seed=a.seed, force=a.force)
    except holdout.HoldoutError as e:
        print(f"[holdout] {e}", file=sys.stderr)
        return 4
    print(json.dumps(result, indent=2))
    return 0


def cmd_dream_report(cfg: dict, a) -> int:
    from . import dream
    try:
        path, result = dream.write_report(cfg, a.run)
    except FileNotFoundError as e:
        print(f"[dream] {e}", file=sys.stderr)
        return 4
    print(dream.format_table(result))
    print(f"[dream] report -> {path}")
    return 0


def cmd_final_report(cfg: dict, a) -> int:
    path = final_report.write(cfg)
    print(f"[final-report] wrote {path}")
    return 0


def cmd_dashboard(cfg: dict, a) -> int:
    try:
        import uvicorn
        from dashboard.app import app
    except ImportError:
        print("dashboard dependencies missing: pip install -e '.[dashboard]'",
              file=sys.stderr)
        return 10
    print(f"[dashboard] http://{a.host}:{a.port} (read-only)")
    uvicorn.run(app, host=a.host, port=a.port, log_level="info")
    return 0


def _skill_list(a) -> list[str]:
    return [x.strip() for x in a.skills.split(",") if x.strip()]


def cmd_skills_build(cfg: dict, a) -> int:
    probes = legates.build_probes(cfg)
    print(f"[skills] probes -> {probes['dir']} ({len(probes['tasks'])} tasks)")
    h = harness_mod.load(a.harness or str(Path(cfg["paths"]["harness"]) / "h0_baseline.json"))
    system = harness_mod.render(h)
    root = Path(cfg["paths"]["adapters"]) / "skills"
    reg = legates.load_registry(cfg)
    out = {}
    for skill in _skill_list(a):
        if skill not in legates.SKILLS:
            print(f"[skills] unknown skill: {skill}", file=sys.stderr)
            return 8
        corpus_dir = root / skill / "data"
        info = legates.build_corpus(cfg, skill, a.rows, corpus_dir, system, seed=a.seed)
        reg[skill]["data"] = info
        reg[skill]["system_prompt_sha"] = hashlib.sha256(system.encode()).hexdigest()[:16]
        reg[skill]["status"] = "candidate"
        reg[skill].pop("base_checksum", None)
        reg[skill].pop("decision", None)
        reg[skill].pop("training", None)
        out[skill] = info
        print(f"[skills] {skill}: {info['rows']} rows "
              f"(train={info['train']} valid={info['valid']} test={info['test']})")
    legates.save_registry(cfg, reg)
    print(json.dumps(out, indent=2))
    return 0


def cmd_skills_train(cfg: dict, a) -> int:
    root = Path(cfg["paths"]["adapters"]) / "skills"
    reg = legates.load_registry(cfg)
    results = {}
    for skill in _skill_list(a):
        corpus = root / skill / "data"
        adapter = root / skill
        if not (corpus / "train.jsonl").exists():
            print(f"[skills] no corpus for {skill}; run skills-build first", file=sys.stderr)
            return 8
        print(f"[skills] training {skill} -> {adapter}", flush=True)
        res = legates.train_skill(cfg, skill, corpus, adapter, iters=a.iters)
        res["loss"] = legates.summarize_train_log(res["log"])
        results[skill] = res
        reg[skill].update({
            "adapter": str(adapter),
            "status": "candidate",
            "base_checksum": res["base_checksum_after"],
            "base_unchanged": res["base_unchanged"],
            "training": {
                "iters": res["iters"],
                "returncode": res["returncode"],
                "log": res["log"],
                "loss": res["loss"],
            },
        })
        legates.save_registry(cfg, reg)
        print(f"[skills] {skill}: rc={res['returncode']} "
              f"loss={res['loss']} base_unchanged={res['base_unchanged']}")
    return 0 if all(r["returncode"] == 0 for r in results.values()) else 9


def cmd_skills_eval(cfg: dict, a) -> int:
    splits = [x.strip() for x in a.splits.split(",") if x.strip()]
    reports = {}
    harness_path = a.harness or str(Path(cfg["paths"]["harness"]) / "h0_baseline.json")
    for split in splits:
        report = legates.gated_eval(cfg, harness_path, split,
                                    f"{a.run_id}_{split}", router_mode=a.router,
                                    registry_path=a.registry)
        reports[split] = report
        print(legates.format_gated_report(report))
    return 0


def cmd_skills_decide(cfg: dict, a) -> int:
    decisions = legates.decide_skills(cfg, run_prefix=a.run_prefix,
                                      registry_path=a.registry)
    print(json.dumps(decisions, indent=2))
    return 0


def cmd_skills_report(cfg: dict, a) -> int:
    path = legates.write_report(cfg)
    print(f"[skills] report -> {path}")
    return 0


def cmd_composition_build(cfg: dict, a) -> int:
    result = composition.build_composition_adapters(cfg)
    print(json.dumps(result, indent=2))
    if not a.no_verify:
        print(json.dumps(composition.verify_load(cfg, result["full"]["dir"]), indent=2))
    return 0


def cmd_composition_eval(cfg: dict, a) -> int:
    result = composition.run_matrix(cfg, a.harness)
    print(composition.format_matrix(result))
    return 0


def cmd_pipeline(cfg: dict, a) -> int:
    result = pipeline.full_round(
        cfg, a.round, start_harness=a.start_harness, adapter=a.adapter,
        iterations=a.iterations, skip_train=a.skip_train,
        skip_loop=a.skip_loop, force_loop=a.force_loop,
    )
    return 0 if result.get("winner_run") else 7


# ───────────────────────────── parser ─────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="forge_rsi", description="Local RSI harness loop")
    p.add_argument("--config", default=None)
    sub = p.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("freeze", help="hash tasks + verifier + config")
    f.set_defaults(func=cmd_freeze)

    e = sub.add_parser("eval", help="evaluate a harness on a split")
    e.add_argument("--harness", required=True)
    e.add_argument("--split", choices=["dev", "holdout", "skills", "composition", "private_holdout"], default="dev")
    e.add_argument("--run-id", required=True)
    e.add_argument("--samples", type=int, default=1)
    e.add_argument("--limit", type=int, default=None)
    e.add_argument("--adapter", default=None)
    e.add_argument("--temperature", type=float, default=None)
    e.add_argument("--task-ids", default=None, help="comma-separated task ids")
    e.add_argument("--no-tools", action="store_true")
    e.set_defaults(func=cmd_eval)

    pr = sub.add_parser("propose", help="teacher proposes the next harness")
    pr.add_argument("--harness", required=True)
    pr.add_argument("--run-id", required=True)
    pr.add_argument("--out", required=True)
    pr.add_argument("--round-name", default=None)
    pr.set_defaults(func=cmd_propose)

    c = sub.add_parser("compare", help="compare two runs")
    c.add_argument("--incumbent", required=True)
    c.add_argument("--candidate", required=True)
    c.set_defaults(func=cmd_compare)

    d = sub.add_parser("dream", help="offline selection-policy search")
    d.add_argument("--run", required=True)
    d.set_defaults(func=cmd_dream)

    b = sub.add_parser("bridge", help="write SkillForge rows from runs")
    b.add_argument("--run", action="append", required=True)
    b.add_argument("--tag", default="round")
    b.add_argument("--min-rows", type=int, default=1)
    b.set_defaults(func=cmd_bridge)

    t = sub.add_parser("train", help="train a LoRA adapter")
    t.add_argument("--data", required=True)
    t.add_argument("--adapter", required=True)
    t.add_argument("--iters", type=int, default=None)
    t.add_argument("--workdir", default=None)
    t.set_defaults(func=cmd_train)

    lp = sub.add_parser("loop", help="run one full RSI round")
    lp.add_argument("--round", default="r1")
    lp.add_argument("--iterations", type=int, default=None)
    lp.add_argument("--patience", type=int, default=None)
    lp.add_argument("--samples", type=int, default=1)
    lp.add_argument("--start-harness", default=None)
    lp.add_argument("--adapter", default=None)
    lp.set_defaults(func=cmd_loop)

    r = sub.add_parser("report", help="write a markdown round report")
    r.add_argument("--round", default="r1")
    r.set_defaults(func=cmd_report)

    pl = sub.add_parser("pipeline", help="RSI round -> Dream -> SkillForge -> adapter")
    pl.add_argument("--round", default="r1")
    pl.add_argument("--start-harness", default=None)
    pl.add_argument("--adapter", default=None)
    pl.add_argument("--iterations", type=int, default=None)
    pl.add_argument("--skip-train", action="store_true")
    pl.add_argument("--skip-loop", action="store_true",
                    help="reuse harness/<round>_winner.json instead of re-running the loop")
    pl.add_argument("--force-loop", action="store_true")
    pl.set_defaults(func=cmd_pipeline)

    fr = sub.add_parser("final-report", help="generate reports/final.md from artifacts")
    fr.set_defaults(func=cmd_final_report)

    sb = sub.add_parser("skills-build", help="build Le-Gates probe tasks + skill corpora")
    sb.add_argument("--skills", default="word_freq,merge_intervals")
    sb.add_argument("--rows", type=int, default=40)
    sb.add_argument("--seed", type=int, default=0)
    sb.add_argument("--harness", default=None)
    sb.set_defaults(func=cmd_skills_build)

    st = sub.add_parser("skills-train", help="train one or more Le-Gates skill adapters")
    st.add_argument("--skills", default="word_freq,merge_intervals")
    st.add_argument("--iters", type=int, default=120)
    st.set_defaults(func=cmd_skills_train)

    se = sub.add_parser("skills-eval", help="gated base + skill evaluation")
    se.add_argument("--harness", default=None)
    se.add_argument("--splits", default="dev,holdout,skills")
    se.add_argument("--run-id", default="legates")
    se.add_argument("--router", choices=["keyword", "oracle"], default="keyword")
    se.add_argument("--registry", default=None)
    se.set_defaults(func=cmd_skills_eval)

    sd = sub.add_parser("skills-decide", help="quarantine/promote skill adapters")
    sd.add_argument("--run-prefix", default="legates")
    sd.add_argument("--registry", default=None)
    sd.set_defaults(func=cmd_skills_decide)

    sr = sub.add_parser("skills-report", help="write reports/legates.md")
    sr.set_defaults(func=cmd_skills_report)

    cb = sub.add_parser("composition-build", help="merge two skill adapters into dual-gate controls")
    cb.add_argument("--no-verify", action="store_true")
    cb.set_defaults(func=cmd_composition_build)

    ce = sub.add_parser("composition-eval", help="run the two-skill composition matrix")
    ce.add_argument("--harness", default=None)
    ce.set_defaults(func=cmd_composition_eval)

    gd = sub.add_parser("gaps-detect", help="find failing skill clusters in a measured run")
    gd.add_argument("--run", default="latest", help="run id/path, or latest")
    gd.set_defaults(func=cmd_gaps_detect)

    gm = sub.add_parser("gaps-mine", help="mine verified traces for detected gaps")
    gm.add_argument("--run", default="latest", help="run id/path, or latest")
    gm.add_argument("--min-rows", type=int, default=1)
    gm.set_defaults(func=cmd_gaps_mine)

    hs = sub.add_parser("holdout-status", help="report the private holdout state")
    hs.set_defaults(func=cmd_holdout_status)

    hr = sub.add_parser("holdout-rotate", help="generate and freeze a fresh private holdout")
    hr.add_argument("--count", type=int, default=10)
    hr.add_argument("--seed", type=int, default=None)
    hr.add_argument("--force", action="store_true",
                    help="archive the current private holdout and replace it")
    hr.set_defaults(func=cmd_holdout_rotate)

    dr = sub.add_parser("dream-report", help="write reports/dream.md from a replay")
    dr.add_argument("--run", default=None, help="run id (default: latest dream replay)")
    dr.set_defaults(func=cmd_dream_report)

    db = sub.add_parser("dashboard", help="read-only local ops dashboard")
    db.add_argument("--host", default="127.0.0.1")
    db.add_argument("--port", type=int, default=8765)
    db.set_defaults(func=cmd_dashboard)
    return p


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    cfg = config.load(a.config)
    if a.cmd == "loop":
        a.iterations = a.iterations or int(cfg["loop"]["iterations"])
        a.patience = a.patience or int(cfg["loop"]["patience"])
    return a.func(cfg, a)


if __name__ == "__main__":
    raise SystemExit(main())
