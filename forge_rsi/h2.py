"""H2.1 Stage 1 orchestration and evidence artifacts.

This is the staged experiment, not the whole search tree:

  A  r1b baseline
  B  H2.1 k=2, real contrast table
  E  greedy with the same rollout/teacher budget as B

If B does not beat A by +3 or does not beat E by at least 2, the run stops and
the negative result is reported. Replication and the sealed private comparison
happen only after B wins.
"""
from __future__ import annotations

import gc
import json
import os
import shutil
import time
from pathlib import Path

from . import evaluator, harness as harness_mod, optimizer, ppc, prereg
from .ledger import Ledger

PREREG_DOC = "docs/H2-PREREG-v2.md"


def _eval(cfg: dict, harness_path: str | Path, split: str, run_id: str) -> dict:
    h = harness_mod.load(harness_path)
    run = evaluator.evaluate(cfg, h, split, run_id)
    gc.collect()
    try:
        import mlx.core as mx
        mx.clear_cache()
    except Exception:
        pass
    return run


def _failures(cfg: dict, run: dict, split: str) -> list[dict]:
    try:
        tasks = {t["id"]: t for t in evaluator.load_tasks(cfg, split)}
    except (FileNotFoundError, ValueError):
        tasks = {}
    out = []
    for trace in run.get("tasks", []):
        if trace.get("passed"):
            continue
        task = tasks.get(trace["task_id"], {})
        out.append({
            "task_id": trace["task_id"],
            "title": task.get("title") or trace["task_id"],
            "prompt": task.get("prompt", "")[:600],
            "error_class": trace.get("error_class"),
            "code": (trace.get("code") or "")[:700],
        })
    return out


def _write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def _jaccard(a: dict, b: dict) -> float:
    sa = {ln.strip() for ln in harness_mod.render(a).splitlines() if ln.strip()}
    sb = {ln.strip() for ln in harness_mod.render(b).splitlines() if ln.strip()}
    return len(sa & sb) / len(sa | sb) if (sa | sb) else 1.0


def greedy_same_budget(cfg: dict, round_name: str, *, split: str = "dev_hard",
                       iterations: int = 5, seed: int = 0,
                       reuse: bool = True) -> dict:
    """Greedy RSI with the same rollout/teacher budget as Stage-1 B."""
    runs_dir = Path(cfg["paths"]["runs"])
    harness_dir = Path(cfg["paths"]["harness"])
    base_path = harness_dir / "h0_baseline.json"
    base = harness_mod.load(base_path)
    ledger = Ledger(f"h2.1-E:{round_name}")
    h0_id = f"{round_name}_h0"
    h0_path = runs_dir / f"{h0_id}.json"
    if h0_path.exists():
        incumbent_run = json.loads(h0_path.read_text())
    else:
        incumbent_run = _eval(cfg, base_path, split, h0_id)
    ledger.add_run("base", incumbent_run)
    incumbent = base
    incumbent_path = base_path
    history, rows = [], []
    prev_cand = None
    killed_duplicate = False
    for i in range(1, iterations + 1):
        label = f"{round_name}_E_h{i}"
        cp = harness_dir / f"{label}.json"
        run_path = runs_dir / f"{label}.json"
        if reuse and cp.exists() and run_path.exists():
            cand = harness_mod.load(cp)
            cand_run = json.loads(run_path.read_text())
            meta = {"cached": True}
        else:
            fails = _failures(cfg, incumbent_run, split)
            t0 = time.time()
            cand, raw, errs = optimizer.propose(
                cfg, incumbent, history, fails, version=label)
            meta = {"calls": 1, "wall_s": round(time.time() - t0, 3),
                    "tokens_out": len(raw or ""), "error": "; ".join(errs or [])[:300]}
            if cand is None:
                rows.append({"iteration": i, "candidate": label, "accepted": False,
                             "reason": "proposal invalid"})
                history.append({"iteration": i, "accepted": False,
                                "candidate": label, "reason": "proposal invalid"})
                continue
            cand["version"] = label
            ok, verrs = harness_mod.validate(cand, incumbent=incumbent, cfg=cfg)
            if not ok:
                rows.append({"iteration": i, "candidate": label, "accepted": False,
                             "reason": "validation: " + "; ".join(verrs)[:200]})
                history.append({"iteration": i, "accepted": False,
                                "candidate": label, "reason": "invalid"})
                continue
            harness_mod.save(cand, cp)
            cand_run = _eval(cfg, cp, split, label)
            ledger.add("proposal", label, calls=1,
                       wall_s=meta["wall_s"], tokens_out=meta["tokens_out"],
                       error=meta["error"])
        if prev_cand is not None and _jaccard(prev_cand, cand) >= 0.95:
            killed_duplicate = True
            rows.append({"iteration": i, "candidate": label, "accepted": False,
                         "reason": "pre-registered duplicate kill"})
            history.append({"iteration": i, "accepted": False,
                            "candidate": label, "reason": "duplicate"})
            print(f"[h2 E] duplicate proposal at iteration {i}; stopping", flush=True)
            break
        prev_cand = cand
        ledger.add_run(label, cand_run, kind="rollout_cached" if meta.get("cached") else "rollout")
        cmp = evaluator.compare(incumbent_run, cand_run)
        accepted, reason = evaluator.acceptance(cmp, cand_run, incumbent_run, cfg)
        row = {
            "iteration": i, "candidate": label,
            "wins": cmp["win_count"], "losses": cmp["loss_count"],
            "candidate_score": cmp["candidate_score"],
            "incumbent_score": cmp["incumbent_score"],
            "delta": cmp["delta"], "accepted": accepted, "reason": reason,
            "candidate_run": label, "incumbent_run": incumbent_run.get("run_id"),
        }
        rows.append(row)
        history.append(row)
        if accepted:
            incumbent, incumbent_run, incumbent_path = cand, cand_run, cp
        print(f"[h2 E] iter {i}: wins={cmp['win_count']} losses={cmp['loss_count']} "
              f"delta={cmp['delta']:+.2f} accepted={accepted}", flush=True)
    result = {
        "arm": "E", "round": round_name, "split": split,
        "iterations": rows, "killed_duplicate": killed_duplicate,
        "winner_harness": str(incumbent_path),
        "winner_run": incumbent_run.get("run_id"),
        "summary": incumbent_run.get("summary"),
        "ledger": ledger.to_dict(),
    }
    _write_json(runs_dir / f"{round_name}_E.json", result)
    return result


def _copy_candidates(out: Path, cfg: dict, round_name: str) -> None:
    cdir = out / "candidates"
    cdir.mkdir(parents=True, exist_ok=True)
    hdir = Path(cfg["paths"]["harness"])
    for p in sorted(hdir.glob(f"{round_name}_*.json")):
        shutil.copy2(p, cdir / p.name)


def _ledger_rows(arm: str, run: dict) -> list[dict]:
    rows = []
    for t in run.get("tasks", []):
        rows.append({"kind": "outcome", "arm": arm, "task_id": t.get("task_id"),
                     "passed": bool(t.get("passed")),
                     "error_class": t.get("error_class"),
                     "tokens_out": int(t.get("tokens_out") or 0),
                     "turns": int(t.get("turns") or 0),
                     "wall_s": float(t.get("wall_s") or 0)})
    return rows


def _task_diff(a: dict, b: dict) -> list[dict]:
    amap = {t["task_id"]: t for t in a.get("tasks", [])}
    bmap = {t["task_id"]: t for t in b.get("tasks", [])}
    out = []
    for tid in sorted(set(amap) & set(bmap)):
        av, bv = bool(amap[tid].get("passed")), bool(bmap[tid].get("passed"))
        if av != bv:
            out.append({"task_id": tid, "A": av, "B": bv,
                        "A_error": amap[tid].get("error_class"),
                        "B_error": bmap[tid].get("error_class")})
    return out


def _cost_summary(ledgers: dict[str, dict], a_run: dict) -> dict:
    out = {}
    for name, led in ledgers.items():
        out[name] = led
    s = a_run.get("summary") or {}
    out["A"] = {"deployment_tokens_out": s.get("tokens_out"),
                "cost_per_solved": s.get("cost_per_solved"),
                "wall_s": s.get("wall_s"), "passed": s.get("passed"),
                "n": s.get("n")}
    return out


def run_stage1(cfg: dict, round_name: str = "h2a", *, k: int = 2,
               seed: int = 0, reuse: bool = True) -> dict:
    runs_dir = Path(cfg["paths"]["runs"])
    harness_dir = Path(cfg["paths"]["harness"])
    out = runs_dir / round_name
    out.mkdir(parents=True, exist_ok=True)

    doc = Path(cfg["paths"]["project"]) / PREREG_DOC
    prereg_sha = doc.with_suffix(".sha256").read_text().split()[0] if doc.with_suffix(
        ".sha256").exists() else ""
    record = prereg.create(cfg, round_name, k=k, arms=["real"], splits={
        "search": ["dev_hard"], "guards": ["holdout", "skills"],
        "sealed": ["private_holdout"]})
    record["prereg_doc"] = PREREG_DOC
    record["prereg_sha256"] = prereg_sha
    record["task_freeze"] = "tasks/HARD_FREEZE.json"
    prereg.save(cfg, round_name, record)

    # A: r1b harness on dev_hard
    a_path = runs_dir / "r1b_dev_hard.json"
    if not a_path.exists():
        _eval(cfg, harness_dir / "r1b_winner.json", "dev_hard", "r1b_dev_hard")
    a_run = json.loads(a_path.read_text())

    # B: H2.1 k=2 real table
    result = ppc.run(
        cfg, round_name, k=k, arms=["real"], split="dev_hard",
        propose_many=lambda *a, **kw: optimizer.propose_ppc_many(*a, **kw),
        eval_fn=lambda hp, split, rid: _eval(cfg, hp, split, rid),
        compose_many=lambda cfg_, base, cands, variant, arm, cues, **kw: (
            optimizer.compose_ppc_many(
                cfg_, base, cands, {arm: variant}, cues, **kw)[arm]),
        seed=seed, reuse=reuse)
    b_run = json.loads((runs_dir / f"{round_name}_real.json").read_text())
    b_stats = prereg.paired_stats(a_run, b_run, seed=seed)

    # E: greedy with the same budget (1 base + 5 iterations)
    e = greedy_same_budget(cfg, round_name, split="dev_hard", iterations=5, seed=seed, reuse=reuse)
    e_run = json.loads((runs_dir / f"{e['winner_run']}.json").read_text())
    e_stats = prereg.paired_stats(a_run, e_run, seed=seed)

    b_passed = int((b_run.get("summary") or {}).get("passed") or 0)
    a_passed = int((a_run.get("summary") or {}).get("passed") or 0)
    e_passed = int((e_run.get("summary") or {}).get("passed") or 0)
    primary = (b_passed - a_passed) >= 3
    beats_e = (b_passed - e_passed) >= 2
    div = result["contrast"]["diversity"]
    diversity_ok = (div.get("distinct_candidates", 0) >= 3
                    and div.get("mean_line_jaccard", 1.0) <= 0.85
                    and div.get("cue_entropy", 0.0) >= 0.5)
    stage1_pass = primary and beats_e and diversity_ok

    # Replication only when Stage 1 passes.
    final = {}
    if stage1_pass:
        winner_path = Path(result["winner_harness"])
        b_hash = result["winner_hash"]
        prereg.unseal(cfg, round_name, b_hash)
        for split, a_file, b_id in [
            ("skills", "r1b_skills_harness.json", f"{round_name}_skills"),
            ("holdout", "r1b_baseline_holdout.json", f"{round_name}_holdout"),
        ]:
            b_path = runs_dir / f"{b_id}.json"
            b = (json.loads(b_path.read_text()) if b_path.exists()
                 else _eval(cfg, winner_path, split, b_id))
            a = json.loads((runs_dir / a_file).read_text())
            final[split] = {"stats": prereg.paired_stats(a, b, seed=seed),
                            "A": a.get("summary"), "B": b.get("summary")}
        # Private: evaluate A and B after the seal is opened with B's hash.
        pa = runs_dir / f"{round_name}_private_A.json"
        pb = runs_dir / f"{round_name}_private_B.json"
        a_pr = (json.loads(pa.read_text()) if pa.exists()
                else _eval(cfg, harness_dir / "r1b_winner.json",
                           "private_holdout", f"{round_name}_private_A"))
        b_pr = (json.loads(pb.read_text()) if pb.exists()
                else _eval(cfg, winner_path, "private_holdout",
                           f"{round_name}_private_B"))
        final["private_holdout"] = {
            "stats": prereg.paired_stats(a_pr, b_pr, seed=seed),
            "A": a_pr.get("summary"), "B": b_pr.get("summary"),
        }

    replication = (final.get("skills", {}).get("stats", {}).get("candidate_score", -1)
                   >= final.get("skills", {}).get("stats", {}).get("base_score", 99) + 0.125
                   and final.get("skills", {}).get("stats", {}).get("delta", -99) >= 0.125)
    holdout_ok = (final.get("holdout", {}).get("stats", {}).get("losses", 99) == 0)
    private_ok = (final.get("private_holdout", {}).get("stats", {}).get("losses", 99) == 0)
    promoted = bool(stage1_pass and replication and holdout_ok and private_ok)

    if not diversity_ok:
        decision = "KILL: candidate diversity or cue entropy below the pre-registered floor"
    elif not stage1_pass:
        decision = "STOP: Stage 1 failed"
    elif not promoted:
        decision = "QUARANTINE: replication or guard failed"
    else:
        decision = "PROMOTE"
    manifest = {
        "experiment": "h2.1-stage1", "round": round_name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "prereg_doc": PREREG_DOC, "prereg_sha256": prereg_sha,
        "task_freeze": "tasks/HARD_FREEZE.json",
        "task_freeze_sha256": json.loads(
            (Path(cfg["paths"]["project"]) / "tasks" / "HARD_FREEZE.json").read_text()
        ).get("combined_sha256") if (Path(cfg["paths"]["project"]) /
                                     "tasks" / "HARD_FREEZE.json").exists() else None,
        "models": {"agent": cfg["paths"]["agent"], "teacher": cfg["paths"]["teacher"]},
        "seeds": {"agent": 0, "teacher": int(cfg["teacher"]["seed"]),
                  "bootstrap": seed, "shuffle": seed, "plan": seed},
        "k": k, "arms": ["A", "B", "E"], "split": "dev_hard",
        "cost_control": "E greedy same budget (1 base + 5 iterations)",
        "git_commit": os.environ.get("FORGE_RSI_COMMIT", "unknown"),
    }
    _write_json(out / "manifest.json", manifest)
    _write_json(out / "diversity.json", {
        "contrast": result["contrast"]["diversity"],
        "disagreement": result["contrast"]["disagreement"],
    })
    _write_json(out / "cost.json", _cost_summary(
        {"B": result["ledger"], "E": e["ledger"]}, a_run))
    (out / "contrast_table_real.md").write_text(
        ppc.render_table(result["contrast"]))
    for arm in ("shuffled", "none"):
        (out / f"contrast_table_{arm}.md").write_text(
            f"NOT RUN — Stage 1 uses the real table only.\n"
            f"Arm {arm} is Stage 2 and requires B to win Stage 1.\n")
    _copy_candidates(out, cfg, round_name)
    led_rows = []
    for arm, run in (("A", a_run), ("B", b_run), ("E", e_run)):
        led_rows += _ledger_rows(arm, run)
    with open(out / "ledger.jsonl", "w") as f:
        for row in led_rows:
            f.write(json.dumps(row) + "\n")
        for name, led in (("B", result["ledger"]), ("E", e["ledger"])):
            f.write(json.dumps({"kind": "cost", "arm": name, **led}) + "\n")
    if final:
        for split, data in final.items():
            _write_json(out / f"final_{split}.json", data)

    report = [
        f"# H2.1 Stage 1 — `{round_name}`",
        "",
        f"- pre-registration: `{prereg_sha[:16]}…` ({PREREG_DOC})",
        f"- task split: `dev_hard` (combined `{str(manifest.get('task_freeze_sha256'))[:16]}…`)",
        f"- decision: **{decision}**",
        "",
        "## Primary endpoint",
        "",
        "| arm | passed | score | delta vs A | wins | losses | sign p | CI95 |",
        "|---|---|---|---|---|---|---|---|",
        f"| A r1b | {a_passed}/20 | {a_run['summary']['score']:.2f} | — | — | — | — | — |",
        f"| B H2.1 real | {b_passed}/20 | {b_run['summary']['score']:.2f} | "
        f"{b_stats['delta']:+.2f} | {b_stats['wins']} | {b_stats['losses']} | "
        f"{b_stats['sign_test_p']:.4f} | [{b_stats['bootstrap_ci95'][0]:+.2f}, "
        f"{b_stats['bootstrap_ci95'][1]:+.2f}] |",
        f"| E greedy same budget | {e_passed}/20 | {e_run['summary']['score']:.2f} | "
        f"{e_stats['delta']:+.2f} | {e_stats['wins']} | {e_stats['losses']} | "
        f"{e_stats['sign_test_p']:.4f} | [{e_stats['bootstrap_ci95'][0]:+.2f}, "
        f"{e_stats['bootstrap_ci95'][1]:+.2f}] |",
        "",
        f"- primary floor +3: **{'PASS' if primary else 'FAIL'}** "
        f"(B−A = {b_passed - a_passed:+d})",
        f"- B beats E by ≥2: **{'PASS' if beats_e else 'FAIL'}** "
        f"(B−E = {b_passed - e_passed:+d})",
        f"- diversity floor: **{'PASS' if diversity_ok else 'FAIL'}** "
        f"(distinct {div.get('distinct_candidates')}, jaccard {div.get('mean_line_jaccard')}, "
        f"cue entropy {div.get('cue_entropy')})",
        f"- Stage 1: **{'PASS' if stage1_pass else 'STOP'}**",
        "",
        "## Per-task diff vs A",
        "",
        "| task | A | B | A error | B error |",
        "|---|---|---|---|---|",
    ]
    diff = _task_diff(a_run, b_run)
    for row in diff:
        report.append(f"| `{row['task_id']}` | {'PASS' if row['A'] else 'fail'} | "
                      f"{'PASS' if row['B'] else 'fail'} | {row['A_error']} | {row['B_error']} |")
    if not diff:
        report.append("| — | — | — | — | — |")
    report += ["", "## Diversity / surprise", "",
               f"- disagreement: {result['contrast']['disagreement']['rate']:.2%}",
               f"- distinct candidates: {result['contrast']['diversity']['distinct_candidates']}",
               f"- mean line Jaccard: {result['contrast']['diversity']['mean_line_jaccard']}",
               f"- unique tool sequences: {result['contrast']['diversity']['unique_tool_sequences']}",
               f"- cue entropy: {result['contrast']['diversity'].get('cue_entropy', 'n/a')}",
               "", "## Cost", "",
               f"- B ledger: {result['ledger']['calls']} calls, "
               f"{result['ledger']['tokens']:,} tokens, {result['ledger']['wall_s']:.1f}s",
               f"- E ledger: {e['ledger']['calls']} calls, "
               f"{e['ledger']['tokens']:,} tokens, {e['ledger']['wall_s']:.1f}s",
               "", "## Guard splits", ""]
    if final:
        report += ["| split | A | B | delta | losses |", "|---|---|---|---|---|"]
        for split, data in final.items():
            s = data["stats"]
            report.append(f"| {split} | {s['base_score']:.2f} | {s['candidate_score']:.2f} | "
                          f"{s['delta']:+.2f} | {s['losses']} |")
        report += ["", f"- replication (probes +3): **{'PASS' if replication else 'FAIL'}**",
                   f"- public holdout no regression: **{'PASS' if holdout_ok else 'FAIL'}**",
                   f"- private no regression: **{'PASS' if private_ok else 'FAIL'}**"]
    else:
        report.append("Not run. Stage 1 must pass before replication or the seal opens.")
    report += ["", "A tie or stop is the result. Do not run Stage 2 after this.", ""]
    (out / "report.md").write_text("\n".join(report))
    summary = {
        "round": round_name, "decision": decision,
        "stage1_pass": stage1_pass, "promoted": promoted,
        "A": {"passed": a_passed, "score": a_run["summary"]["score"]},
        "B": {"passed": b_passed, "score": b_run["summary"]["score"],
              "stats": b_stats, "harness": result["winner_hash"]},
        "E": {"passed": e_passed, "score": e_run["summary"]["score"],
              "stats": e_stats},
        "primary": primary, "beats_e": beats_e, "diversity_ok": diversity_ok,
        "replication": replication, "holdout_ok": holdout_ok,
        "private_ok": private_ok, "final": final,
        "artifacts": str(out),
        "prereg_sha256": prereg_sha,
    }
    _write_json(out / "summary.json", summary)
    return summary
