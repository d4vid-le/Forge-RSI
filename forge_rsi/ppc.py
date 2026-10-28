"""H2.1 — parallel Propose–Probe–Compose with verifiable rewards.

This is the upstream half of the loop: candidate harnesses are proposed on two
dimensions (invariant and domain), probed on the same dev tasks, and composed
from a quantitative contrast table. The composer's measured cue→harness output
is the router's training signal.

The private holdout is not read here. ``finalize`` unseals it only with a frozen
winner hash, per the pre-registration.
"""
from __future__ import annotations

import copy
import json
import math
import random
import re
import time
from pathlib import Path

from . import evaluator, harness as harness_mod, prereg
from .ledger import Ledger
from .library import Library, Lesson, wilson_lower


class PPCError(RuntimeError):
    pass


def _skill(task: dict, trace: dict | None = None) -> str:
    tags = [t for t in (task.get("tags") or [])
            if t in ("word_freq", "merge_intervals", "rle", "second_largest",
                     "sum_even", "capitalize_words")]
    if len(tags) > 1:
        return "+".join(sorted(tags))
    if tags:
        return tags[0]
    text = f"{task.get('title', '')} {task.get('prompt', '')}".lower()
    if "word" in text or "frequency" in text or "token" in text:
        return "word_freq"
    if "interval" in text or "merge" in text or "span" in text:
        return "merge_intervals"
    if trace and trace.get("gate"):
        return f"gate:{trace['gate']}"
    return "unclassified"


def _task_index(cfg: dict, split: str) -> dict[str, dict]:
    try:
        return {t["id"]: t for t in evaluator.load_tasks(cfg, split)}
    except (FileNotFoundError, ValueError):
        return {}


def _outcome(trace: dict | None) -> dict:
    if not trace:
        return {"passed": False, "error_class": "missing", "tokens_out": 0}
    return {"passed": bool(trace.get("passed")),
            "error_class": trace.get("error_class") or "unknown",
            "tokens_out": int(trace.get("tokens_out") or 0)}


def _line_set(h: dict) -> set[str]:
    return {ln.strip() for ln in harness_mod.render(h).splitlines() if ln.strip()}


def mean_line_jaccard(harnesses: dict[str, dict]) -> float:
    names = sorted(harnesses)
    if len(names) < 2:
        return 1.0
    sets = {n: _line_set(harnesses[n]) for n in names}
    sims = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            u = sets[a] | sets[b]
            sims.append(len(sets[a] & sets[b]) / len(u) if u else 1.0)
    return round(sum(sims) / len(sims), 4)


def _cue_entropy(cues: list[dict]) -> float:
    counts: dict[str, int] = {}
    for c in cues:
        name = str(c.get("harness") or "none")
        counts[name] = counts.get(name, 0) + 1
    n = sum(counts.values())
    if not n:
        return 0.0
    total = 0.0
    for v in counts.values():
        p = v / n
        total -= p * math.log2(p)
    return round(total, 4)


def diversity(base_h: dict, candidates: dict[str, dict], cues: list[dict]) -> dict:
    hashes = {n: harness_mod.harness_hash(h) for n, h in candidates.items()}
    seqs = {
        n: (tuple(h.get("tools") or []),
            tuple(x.get("name") for x in (h.get("hops") or [])),
            (h.get("selection") or {}).get("policy"))
        for n, h in candidates.items()
    }
    return {
        "candidates": len(candidates),
        "distinct_candidates": len(set(hashes.values())),
        "mean_line_jaccard": mean_line_jaccard({"base": base_h, **candidates}),
        "unique_tool_sequences": len(set(seqs.values())),
        "unique_cues": len({json.dumps(c.get("cue"), sort_keys=True) for c in cues}),
        "cue_entropy": _cue_entropy(cues),
        "hashes": hashes,
    }


def contrast(base_run: dict, candidate_runs: dict[str, dict],
             tasks: dict[str, dict], cue_min_support: int = 1) -> dict:
    """Build the per-task contrast, aggregate scores, disagreement, and cue table."""
    bmap = {t["task_id"]: t for t in base_run.get("tasks", [])}
    cmaps = {n: {t["task_id"]: t for t in r.get("tasks", [])}
             for n, r in candidate_runs.items()}
    ids = sorted(set(bmap) & {i for m in cmaps.values() for i in m})
    rows = []
    for tid in ids:
        task = tasks.get(tid, {})
        rows.append({
            "task_id": tid,
            "title": task.get("title") or tid,
            "skill": _skill(task, bmap.get(tid)),
            "base": _outcome(bmap.get(tid)),
            "candidates": {n: _outcome(cmaps[n].get(tid)) for n in cmaps},
        })

    aggregates = {}
    for n, run in candidate_runs.items():
        s = run.get("summary") or {}
        aggregates[n] = {
            "score": s.get("score"),
            "passed": s.get("passed"),
            "n": s.get("n"),
            "cost_per_solved": s.get("cost_per_solved"),
            "tokens_out": s.get("tokens_out"),
            "wall_s": s.get("wall_s"),
            "delta_vs_base": round((s.get("score") or 0)
                                   - (base_run.get("summary", {}).get("score") or 0), 4),
        }

    # Disagreement: candidate outcome vectors that are not all identical.
    changed = 0
    disagreed = 0
    for row in rows:
        vals = [row["candidates"][n]["passed"] for n in cmaps]
        base_v = row["base"]["passed"]
        changed += int(any(v != base_v for v in vals))
        disagreed += int(len(set(vals)) > 1)
    n = max(1, len(rows))

    # Cue table: group by (skill, base error class), pick the candidate with the
    # highest verified pass rate, and calibrate confidence from counts.
    groups: dict[tuple[str, str], list[dict]] = {}
    for row in rows:
        groups.setdefault((row["skill"], row["base"]["error_class"]), []).append(row)
    cues = []
    for (skill, err), group in sorted(groups.items()):
        if len(group) < cue_min_support:
            continue
        base_pass = sum(1 for r in group if r["base"]["passed"])
        best = None
        for name in cmaps:
            passes = sum(1 for r in group if r["candidates"][name]["passed"])
            if best is None or passes > best[1]:
                best = (name, passes)
        if not best or best[1] <= base_pass:
            continue
        name, passes = best
        cues.append({
            "cue": {"skill": skill, "error_class": err},
            "harness": name,
            "confidence": wilson_lower(passes, len(group)),
            "evidence": {
                "n": len(group),
                "base_passes": base_pass,
                "candidate_passes": passes,
                "task_ids": [r["task_id"] for r in group],
            },
            "lesson": (f"when the failure cue is {skill}/{err}, "
                       f"prefer harness {name}"),
        })
    cues.sort(key=lambda c: (-c["confidence"], c["cue"]["skill"], c["cue"]["error_class"]))

    return {
        "base": base_run.get("run_id"),
        "split": base_run.get("split"),
        "rows": rows,
        "aggregates": aggregates,
        "disagreement": {
            "tasks": len(rows),
            "tasks_changed_by_any_candidate": changed,
            "tasks_with_candidate_disagreement": disagreed,
            "rate": round(disagreed / n, 4),
            "surprise": "candidate disagreement is the I-don't-know signal",
        },
        "diversity": diversity(base_run.get("harness") or {}, {
            n: r.get("harness") or {} for n, r in candidate_runs.items()
        }, cues),
        "cue_table": cues,
    }


def table_variant(con: dict, arm: str, seed: int = 0) -> dict:
    """Return a copy of the contrast with the requested ablation applied.

    - real: task-aligned outcomes
    - shuffled: each candidate's outcomes permuted independently (aggregates kept)
    - none: no per-task table
    """
    if arm == "real":
        return con
    if arm == "none":
        out = copy.deepcopy(con)
        out["rows"] = []
        return out
    if arm != "shuffled":
        raise PPCError(f"unknown arm: {arm}")
    out = copy.deepcopy(con)
    names = list((out.get("aggregates") or {}))
    rng = random.Random(seed)
    for name in names:
        vals = [row["candidates"][name] for row in out["rows"]]
        rng.shuffle(vals)
        for row, val in zip(out["rows"], vals):
            row["candidates"][name] = val
    out["table_arm"] = "shuffled"
    return out


def render_table(con: dict, max_rows: int = 30) -> str:
    names = list(con.get("aggregates") or {})
    if not con.get("rows"):
        lines = ["NO PER-TASK TABLE (aggregate scores only)", ""]
        for n in names:
            a = con["aggregates"][n]
            lines.append(f"- {n}: score {a.get('score')} · passed {a.get('passed')}/"
                         f"{a.get('n')} · cost/solved {a.get('cost_per_solved')}")
        return "\n".join(lines)
    lines = ["task | skill | base | " + " | ".join(names)]
    lines.append("--- | --- | --- | " + " | ".join("---" for _ in names))
    for row in con["rows"][:max_rows]:
        cells = [f"{'PASS' if row['candidates'][n]['passed'] else 'fail'}"
                 f"/{row['candidates'][n]['error_class']}" for n in names]
        lines.append(f"{row['task_id']} | {row['skill']} | "
                     f"{'PASS' if row['base']['passed'] else 'fail'}/"
                     f"{row['base']['error_class']} | " + " | ".join(cells))
    if len(con["rows"]) > max_rows:
        lines.append(f"... {len(con['rows']) - max_rows} more tasks")
    lines += ["", "AGGREGATES"]
    for n in names:
        a = con["aggregates"][n]
        lines.append(f"- {n}: score {a.get('score')} · passed {a.get('passed')}/"
                     f"{a.get('n')} · delta {a.get('delta_vs_base'):+.2f} · "
                     f"cost/solved {a.get('cost_per_solved')}")
    lines += ["", f"DISAGREEMENT: {con['disagreement']['rate']:.2%} of tasks; "
                  f"diversity Jaccard {con['diversity']['mean_line_jaccard']}"]
    return "\n".join(lines)


def pick_winner(arm_runs: dict[str, dict], arms: list[str]) -> tuple[str, dict]:
    order = {a: i for i, a in enumerate(arms)}
    scored = []
    for name, run in arm_runs.items():
        s = run.get("summary") or {}
        scored.append((s.get("score") or 0, -(s.get("cost_per_solved") or 0),
                       -order.get(name, 99), name))
    scored.sort(reverse=True)
    best = scored[0][-1]
    return best, arm_runs[best]


def _write_json(path: Path, data: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n")
    return path


def run(cfg: dict, round_name: str, *, k: int = 2,
        arms: list[str] | None = None, split: str = "dev",
        propose_many=None, eval_fn=None, compose_many=None,
        library: Library | None = None, seed: int = 0,
        reuse: bool = True) -> dict:
    """Run one H2.1 search round. The private holdout is never touched here."""
    if split not in ("dev", "dev_hard"):
        raise PPCError("H2.1 search must run on dev/dev_hard; guards are separate")
    arms = arms or ["real", "shuffled", "none"]
    record = prereg.create(cfg, round_name, k=k, arms=arms)
    if not propose_many or not eval_fn or not compose_many:
        raise PPCError("run() needs propose_many, eval_fn, and compose_many")

    runs_dir = Path(cfg["paths"]["runs"])
    harness_dir = Path(cfg["paths"]["harness"])
    ledger = Ledger(f"h2.1:{round_name}")
    base_path = harness_dir / "h0_baseline.json"
    base_h = harness_mod.load(base_path)
    base_run_path = runs_dir / f"{round_name}_h0.json"
    if base_run_path.exists() and reuse:
        base_run = json.loads(base_run_path.read_text())
    else:
        base_run = eval_fn(base_path, split, f"{round_name}_h0")
    ledger.add_run("base", base_run)

    tasks = _task_index(cfg, split)
    failures = []
    bmap = {t["task_id"]: t for t in base_run.get("tasks", [])}
    for tid, trace in bmap.items():
        if trace.get("passed"):
            continue
        task = tasks.get(tid, {})
        failures.append({
            "task_id": tid, "title": task.get("title") or tid,
            "prompt": task.get("prompt", "")[:600],
            "error_class": trace.get("error_class"),
            "code": (trace.get("code") or "")[:700],
        })

    lessons = []
    if library is not None:
        # Retrieval is capped; no lesson clears the threshold means no context.
        cue = {"skill": sorted({_skill(tasks.get(f["task_id"], {}), bmap.get(f["task_id"]))
                               for f in failures})[0] if failures else "unclassified",
               "error_class": sorted({f.get("error_class") or "unknown"
                                      for f in failures})[0] if failures else "unknown"}
        lessons = library.retrieve(cue, limit=1)
        if lessons:
            ledger.add("library", "retrieved", calls=1,
                       tokens_in=len(Library.render(lessons)), meta={"cue": cue})

    specs = [{"dim": dim, "index": i}
             for dim in ("INV", "DOM") for i in range(1, k + 1)]
    labels = [f"{round_name}_{s['dim'].lower()}{s['index']}" for s in specs]
    cached = all((harness_dir / f"{label}.json").exists() for label in labels) and reuse
    if cached:
        cand_h = {label: harness_mod.load(harness_dir / f"{label}.json")
                  for label in labels}
        cand_meta = {label: {"cached": True} for label in labels}
        proposal_meta = []
    else:
        proposal_meta = propose_many(cfg, base_h, failures, specs,
                                     lessons=lessons, round_name=round_name)
        cand_h, cand_meta = {}, {}
        for spec, item in zip(specs, proposal_meta):
            label = f"{round_name}_{spec['dim'].lower()}{spec['index']}"
            h, meta = item
            if h is None:
                cand_h[label] = base_h
                meta = {**meta, "fallback": True}
            else:
                h["version"] = label
                ok, errs = harness_mod.validate(h, incumbent=base_h, cfg=cfg)
                if not ok:
                    cand_h[label] = base_h
                    meta = {**meta, "fallback": True, "errors": errs}
                else:
                    cand_h[label] = h
            cand_meta[label] = meta
            ledger.add("proposal", label, calls=1,
                       tokens_in=int(meta.get("tokens_in") or 0),
                       tokens_out=int(meta.get("tokens_out") or 0),
                       wall_s=float(meta.get("wall_s") or 0),
                       dim=spec["dim"], fallback=bool(meta.get("fallback")))

    cand_runs = {}
    for label, h in cand_h.items():
        p = harness_dir / f"{label}.json"
        harness_mod.save(h, p)
        rp = runs_dir / f"{label}.json"
        if rp.exists() and reuse:
            run = json.loads(rp.read_text())
        else:
            run = eval_fn(p, split, label)
        cand_runs[label] = run
        ledger.add_run(label, run)
    con = contrast(base_run, cand_runs, tasks)
    _write_json(runs_dir / f"{round_name}_contrast.json", con)
    _write_json(harness_dir / "cues" / f"{round_name}.json",
                {"round": round_name, "cue_table": con["cue_table"],
                 "source_split": split, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")})

    # Composer arms: the table itself is the experimental variable.
    arm_runs, arm_harnesses = {}, {}
    for arm in arms:
        hp = harness_dir / f"{round_name}_{arm}.json"
        if reuse and hp.exists():
            h = harness_mod.load(hp)
            meta = {"cached": True}
        else:
            variant = table_variant(con, arm, seed=seed)
            out = compose_many(cfg, base_h, cand_h, variant, arm, con["cue_table"],
                               lessons=lessons, round_name=round_name)
            h, meta = out
            if h is None:
                h = base_h
                meta = {**meta, "fallback": True}
            h["version"] = f"{round_name}_{arm}"
            ok, errs = harness_mod.validate(h, incumbent=base_h, cfg=cfg)
            if not ok:
                h = base_h
                meta = {**meta, "fallback": True, "errors": errs}
            harness_mod.save(h, hp)
        arm_harnesses[arm] = h
        rp = runs_dir / f"{round_name}_{arm}.json"
        if rp.exists() and reuse:
            run = json.loads(rp.read_text())
        else:
            run = eval_fn(hp, split, f"{round_name}_{arm}")
        arm_runs[arm] = run
        ledger.add("composer", arm, calls=0 if meta.get("cached") else 1,
                   tokens_in=int(meta.get("tokens_in") or 0),
                   tokens_out=int(meta.get("tokens_out") or 0),
                   wall_s=float(meta.get("wall_s") or 0),
                   fallback=bool(meta.get("fallback")), cached=bool(meta.get("cached")))
        ledger.add_run(f"arm:{arm}", run)

    winner, winner_run = pick_winner(arm_runs, arms)
    best_candidate = max(cand_runs.values(), key=lambda r: r.get("summary", {}).get("score") or 0)
    dev_stats = prereg.paired_stats(base_run, winner_run, seed=seed)
    candidate_stats = prereg.paired_stats(base_run, best_candidate, seed=seed)
    gates = prereg.gate_report(
        record, dev_stats,
        {a: prereg.paired_stats(base_run, r, seed=seed) for a, r in arm_runs.items()},
        con["diversity"])

    result = {
        "experiment": "h2.1",
        "round": round_name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "k": k,
        "arms": arms,
        "split": split,
        "base_run": base_run.get("run_id"),
        "candidates": {n: {"harness": harness_mod.harness_hash(cand_h[n]),
                           "run": r.get("run_id"),
                           "stats": prereg.paired_stats(base_run, r, seed=seed),
                           "proposal": cand_meta.get(n, {})}
                       for n, r in cand_runs.items()},
        "best_candidate": {"label": max(cand_runs, key=lambda n: cand_runs[n]
                                        .get("summary", {}).get("score") or 0),
                           "stats": candidate_stats},
        "arms_result": {a: {"harness": harness_mod.harness_hash(arm_harnesses[a]),
                            "run": r.get("run_id"),
                            "stats": prereg.paired_stats(base_run, r, seed=seed)}
                        for a, r in arm_runs.items()},
        "winner": winner,
        "winner_harness": str(harness_dir / f"{round_name}_{winner}.json"),
        "winner_hash": harness_mod.harness_hash(arm_harnesses[winner]),
        "dev": dev_stats,
        "contrast": con,
        "gates": gates,
        "ledger": ledger.to_dict(),
    }
    _write_json(runs_dir / f"{round_name}_ppc.json", result)
    return result


def finalize(cfg: dict, round_name: str, *, eval_fn, split: str,
             winner_hash: str | None = None) -> dict:
    """Evaluate the frozen winner on a guard split. Private requires the seal key."""
    record = prereg.load(cfg, round_name)
    winner_hash = winner_hash or (record.get("seal") or {}).get("winner_hash")
    if split in ("private_holdout",):
        prereg.guard_split(cfg, round_name, split, winner_hash)
    path = Path(cfg["paths"]["runs"]) / f"{round_name}_ppc.json"
    result = json.loads(path.read_text())
    harness_path = Path(result["winner_harness"])
    run_id = f"{round_name}_{split}"
    run = eval_fn(harness_path, split, run_id)
    base_path = Path(cfg["paths"]["harness"]) / "h0_baseline.json"
    base_run_id = f"{round_name}_{split}_base"
    base_run = eval_fn(base_path, split, base_run_id)
    stats = prereg.paired_stats(base_run, run)
    result.setdefault("final", {})[split] = {
        "run": run.get("run_id"), "stats": stats,
        "gated": run.get("summary"), "base": base_run.get("summary"),
    }
    _write_json(path, result)
    return result["final"][split]


def report(cfg: dict, round_name: str) -> Path:
    path = Path(cfg["paths"]["runs"]) / f"{round_name}_ppc.json"
    r = json.loads(path.read_text())
    lines = [
        f"# H2.1 — parallel propose–probe–compose · `{round_name}`",
        "",
        f"- created: {r['created_at']}",
        f"- k: {r['k']} · arms: {', '.join(r['arms'])}",
        f"- search split: **{r['split']}**",
        f"- winner: **{r['winner']}**",
        "- private holdout: sealed until the winner hash is frozen",
        "",
        "## Pre-registered gates",
        "",
        "| gate | observed | pass |",
        "|---|---|---|",
    ]
    for c in r.get("gates", {}).get("checks", []):
        lines.append(f"| {c['gate']} | {json.dumps(c.get('observed'))} | "
                     f"{'PASS' if c.get('ok') else 'FAIL'} |")
    lines += ["", f"**All gates: {'PASS' if r.get('gates', {}).get('all_pass') else 'FAIL'}**", ""]

    lines += ["## Dev: base vs candidates", "",
              "| candidate | score | delta | wins | losses | sign p | CI95 |",
              "|---|---|---|---|---|---|---|"]
    for n, c in r["candidates"].items():
        s = c["stats"]
        lines.append(f"| `{n}` | {s['candidate_score']:.2f} | {s['delta']:+.2f} | "
                     f"{s['wins']} | {s['losses']} | {s['sign_test_p']:.4f} | "
                     f"[{s['bootstrap_ci95'][0]:+.2f}, {s['bootstrap_ci95'][1]:+.2f}] |")
    lines += ["", "## Dev: composer arms", "",
              "| arm | score | delta | wins | losses | sign p | CI95 |",
              "|---|---|---|---|---|---|---|"]
    for n, c in r["arms_result"].items():
        s = c["stats"]
        lines.append(f"| `{n}` | {s['candidate_score']:.2f} | {s['delta']:+.2f} | "
                     f"{s['wins']} | {s['losses']} | {s['sign_test_p']:.4f} | "
                     f"[{s['bootstrap_ci95'][0]:+.2f}, {s['bootstrap_ci95'][1]:+.2f}] |")
    d = r["contrast"]["diversity"]
    dis = r["contrast"]["disagreement"]
    lines += ["", "## Surprise and diversity", "",
              f"- disagreement rate: **{dis['rate']:.2%}** "
              f"({dis['tasks_with_candidate_disagreement']}/{dis['tasks']} tasks)",
              f"- distinct candidates: **{d['distinct_candidates']}** / {d['candidates']}",
              f"- mean line Jaccard: **{d['mean_line_jaccard']}**",
              f"- unique tool sequences: {d['unique_tool_sequences']}",
              f"- unique cues: {d['unique_cues']}",
              "", "A zero-disagreement round has no contrast to compose; the "
              "composer should keep the base.", ""]
    lines += ["## Cue → harness table (router training signal)", "",
              "| cue | harness | confidence | support | base passes | candidate passes |",
              "|---|---|---|---|---|---|"]
    for c in r["contrast"].get("cue_table", []):
        ev = c["evidence"]
        lines.append(f"| `{c['cue']['skill']}/{c['cue']['error_class']}` | "
                     f"`{c['harness']}` | {c['confidence']:.3f} | {ev['n']} | "
                     f"{ev['base_passes']} | {ev['candidate_passes']} |")
    if not r["contrast"].get("cue_table"):
        lines.append("| — | — | — | — | — | — |")
    lines += ["", "Confidence is a Wilson lower bound over measured counts, never "
              "model self-report. A cue with no confident winner falls back to base.", ""]
    led = r["ledger"]
    lines += ["## Cost ledger", "",
              f"- calls: {led['calls']} · tokens: {led['tokens']:,} · wall: {led['wall_s']:.1f}s",
              "", "| kind | calls | tokens in | tokens out | wall s |",
              "|---|---|---|---|---|"]
    for k, v in led["by_kind"].items():
        lines.append(f"| `{k}` | {v['calls']} | {v['tokens_in']:,} | "
                     f"{v['tokens_out']:,} | {v['wall_s']:.1f} |")
    lines += ["", "Gain per cost unit is reported against the pre-registered greedy "
              "control in `h2_ppc_summary.md`.", ""]
    if r.get("final"):
        lines += ["## Guard splits", "",
                  "| split | base | winner | delta | wins | losses |",
                  "|---|---|---|---|---|---|"]
        for split, f in r["final"].items():
            s = f["stats"]
            lines.append(f"| {split} | {s['base_score']:.2f} | {s['candidate_score']:.2f} | "
                         f"{s['delta']:+.2f} | {s['wins']} | {s['losses']} |")
    lines += ["", "A tie is a result. Report it with the same rigor as a gain.", ""]
    p = Path(cfg["paths"]["reports"]) / "h2_ppc.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines))
    return p
