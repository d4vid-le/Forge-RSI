"""H2.3 — plan-level composition, one gate at a time.

The two skills are never blended. A plan executor runs one Le-Gates adapter,
extracts the function it produced, verifies it, then runs the other adapter on
the concrete intermediate artifact. The final file is verified against the
compound task.

Arms:
  single   base model, one generation (single-pass control)
  dual     merged dual-gate adapter, one generation (monolithic control)
  forward  word_freq -> merge_intervals
  reverse  merge_intervals -> word_freq
  random   seeded order per task

The intermediate check is the point: it measures whether pass one preserved the
state pass two needs, not just whether the final file happened to pass.
"""
from __future__ import annotations

import ast
import json
import random
import re
import time
from pathlib import Path

from . import agent, evaluator, harness as harness_mod, verifier

ARMS = ("single", "dual", "forward", "reverse", "random")
SKILLS = {"word_freq": "word_freq", "merge_intervals": "merge_intervals"}


def extract_function(code: str, name: str) -> str | None:
    """Return exactly one top-level function definition, or None."""
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        m = re.search(rf"(?ms)^def\s+{re.escape(name)}\s*\(.*?(?=^def\s|\Z)", code or "")
        return m.group(0).strip() if m else None
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            seg = ast.get_source_segment(code, node)
            return seg.strip() if seg else None
    return None


def _referenced(src: str, names: list[str]) -> set[str]:
    return {n for n in names if re.search(rf"\b{re.escape(n)}\b", src)}


def split_tests(task: dict, selected: set[str]) -> str | None:
    """Build a test module containing only methods that use `selected` functions."""
    try:
        tree = ast.parse(task["tests"])
    except SyntaxError:
        return None
    all_names = set(SKILLS)
    imports = []
    methods = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom) and node.module == "solution":
            keep = [a.name for a in node.names if a.name in selected]
            if keep:
                imports.append(f"from solution import {', '.join(keep)}")
        if isinstance(node, ast.ClassDef):
            for fn in node.body:
                if not isinstance(fn, ast.FunctionDef) or not fn.name.startswith("test"):
                    continue
                src = ast.get_source_segment(task["tests"], fn) or ""
                refs = _referenced(src, list(all_names))
                if refs and refs <= selected:
                    methods.append(src)
    if not methods or not imports:
        return None
    return "import unittest\n" + "\n".join(imports) + "\n\nclass T(unittest.TestCase):\n" + \
           "\n".join("    " + ln if ln.strip() else ln for m in methods for ln in m.splitlines())


def _task_with_tests(task: dict, tests: str | None) -> dict | None:
    if not tests:
        return None
    t = dict(task)
    t["tests"] = tests
    return t


def _step_prompt(task: dict, first: str, second: str, existing: str = "") -> str:
    if existing.strip():
        return (
            f"{task['prompt']}\n\n"
            f"Add the `{second}` function to the current code. Return the complete "
            f"file with both functions, preserving `{first}` exactly.\n\n"
            f"Current code:\n```python\n{existing.strip()}\n```"
        )
    return (
        f"{task['prompt']}\n\n"
        f"This is one step of a two-step build. Write ONLY the `{second}` function "
        f"now. Do not write a second function and do not use prose."
    )


def _one_call(model, tok, h: dict, user: str, cfg: dict, seed: int) -> dict:
    t0 = time.time()
    raw, tok_count = agent.run_one_turn(
        model, tok, [{"role": "system", "content": harness_mod.render(h)},
                     {"role": "user", "content": user}], cfg, seed)
    return {"raw": raw, "code": agent.parse_code(raw),
            "tokens": tok_count, "wall_s": round(time.time() - t0, 3)}


def _check(code: str, task: dict, selected: set[str] | None = None) -> dict:
    t = task if selected is None else _task_with_tests(task, split_tests(task, selected))
    if t is None:
        return {"passed": False, "error_class": "no_part_tests", "output": ""}
    return verifier.verify(code, t)


def _models_for(cfg: dict, arm: str) -> dict:
    base = cfg["paths"]["agent"]
    adapters = Path(cfg["paths"]["adapters"]) / "skills"
    if arm == "single":
        m, tok = agent.load_model(base)
        return {"base": (m, tok)}
    if arm == "dual":
        m, tok = agent.load_model(base, adapter_path=str(adapters / "_composition" / "full"))
        return {"dual": (m, tok)}
    wm, wt = agent.load_model(base, adapter_path=str(adapters / "word_freq"))
    mm, mt = agent.load_model(base, adapter_path=str(adapters / "merge_intervals"))
    return {"word": (wm, wt), "merge": (mm, mt)}


def _run_pass(model, tok, h, task, first, second, cfg, seed) -> dict:
    key = lambda name: "word" if name == "word_freq" else "merge"
    s1 = _one_call(model[key(first)], tok[key(first)], h,
                   _step_prompt(task, second, first), cfg, seed)
    part = extract_function(s1["code"], first)
    s1["function"] = part
    s1["intermediate"] = (_check(part, task, {first}) if part else
                          {"passed": False, "error_class": "extract_failed"})
    existing = part or s1["code"]
    s2 = _one_call(model[key(second)], tok[key(second)], h,
                   _step_prompt(task, first, second, existing), cfg, seed + 1)
    w = extract_function(s2["code"], first)
    m = extract_function(s2["code"], second)
    combined = "\n\n".join(x for x in (w, m) if x)
    s2["word"] = w
    s2["merge"] = m
    s2["combined"] = combined
    s2["final"] = verifier.verify(combined, task) if combined else {
        "passed": False, "error_class": "extract_failed", "output": ""}
    s2["preserved"] = {
        "first_present": bool(w if first == "word_freq" else m),
        "first_verified": bool(_check(w if first == "word_freq" else m, task, {first})["passed"])
        if (w or m) else False,
    }
    return {"first": first, "second": second, "step1": s1, "step2": s2,
            "tokens": s1["tokens"] + s2["tokens"],
            "wall_s": round(s1["wall_s"] + s2["wall_s"], 3)}


def _run_single(model, tok, h, task, cfg, seed) -> dict:
    x = _one_call(model, tok, h, task["prompt"], cfg, seed)
    x["final"] = verifier.verify(x["code"], task)
    x["word"] = extract_function(x["code"], "word_freq")
    x["merge"] = extract_function(x["code"], "merge_intervals")
    return {"first": "single", "second": "single", "step1": x,
            "step2": x, "tokens": x["tokens"], "wall_s": x["wall_s"]}


def run_arm(cfg: dict, arm: str, *, task_ids: list[str] | None = None,
            limit: int | None = None, seed: int = 0) -> dict:
    if arm not in ARMS:
        raise ValueError(f"unknown arm: {arm}")
    tasks = evaluator.load_tasks(cfg, "composition")
    if task_ids:
        wanted = set(task_ids)
        tasks = [t for t in tasks if t["id"] in wanted]
    if limit:
        tasks = tasks[:limit]
    h = harness_mod.load(Path(cfg["paths"]["harness"]) / "h0_baseline.json")
    models = _models_for(cfg, arm)
    out = []
    for i, task in enumerate(tasks):
        if arm == "single":
            r = _run_single(models["base"][0], models["base"][1], h, task, cfg, seed + i * 101)
        elif arm == "dual":
            r = _run_single(models["dual"][0], models["dual"][1], h, task, cfg, seed + i * 101)
        elif arm == "forward":
            model_d = {k: v[0] for k, v in models.items()}
            tok_d = {k: v[1] for k, v in models.items()}
            r = _run_pass(model_d, tok_d, h, task,
                          "word_freq", "merge_intervals", cfg, seed + i * 101)
        elif arm == "reverse":
            model_d = {k: v[0] for k, v in models.items()}
            tok_d = {k: v[1] for k, v in models.items()}
            r = _run_pass(model_d, tok_d, h, task,
                          "merge_intervals", "word_freq", cfg, seed + i * 101)
        else:
            order = random.Random(seed + i).choice(
                [("word_freq", "merge_intervals"), ("merge_intervals", "word_freq")])
            model_d = {k: v[0] for k, v in models.items()}
            tok_d = {k: v[1] for k, v in models.items()}
            r = _run_pass(model_d, tok_d, h, task,
                          order[0], order[1], cfg, seed + i * 101)
        r["task_id"] = task["id"]
        r["title"] = task.get("title")
        out.append(r)
        passed = r["step2"].get("final", {}).get("passed") or r.get("step1", {}).get("final", {}).get("passed")
        print(f"[plans {arm}] {i+1:02d}/{len(tasks)} {task['id']:8} "
              f"{'PASS' if passed else 'fail':4} {r['tokens']} tok", flush=True)

    n = len(out)
    passed = sum(1 for r in out
                 if (r.get("step2") or r.get("step1") or {}).get("final", {}).get("passed"))
    intermediate = sum(1 for r in out
                       if (r.get("step1") or {}).get("intermediate", {}).get("passed"))
    preserved = sum(1 for r in out
                    if (r.get("step2") or {}).get("preserved", {}).get("first_verified"))
    summary = {
        "arm": arm, "n": n, "passed": passed,
        "score": round(passed / n, 4) if n else 0.0,
        "intermediate_passed": intermediate,
        "intermediate_rate": round(intermediate / n, 4) if n else 0.0,
        "preserved": preserved,
        "preserved_rate": round(preserved / n, 4) if n else 0.0,
        "tokens": sum(r.get("tokens", 0) for r in out),
        "wall_s": round(sum(r.get("wall_s", 0) for r in out), 2),
    }
    result = {"arm": arm, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
              "seed": seed, "summary": summary, "tasks": out}
    p = Path(cfg["paths"]["runs"]) / f"h2_plan_{arm}.json"
    p.write_text(json.dumps(result, indent=2) + "\n")
    print(f"[plans {arm}] {json.dumps(summary)}")
    return result


def report(cfg: dict) -> Path:
    runs = Path(cfg["paths"]["runs"])
    lines = ["# H2.3 — plan-level composition", "",
             "No weight blending. One gate at a time, with an intermediate check "
             "between passes.", "",
             "| arm | passed | intermediate | preserved | tokens | wall s |",
             "|---|---|---|---|---|---|"]
    found = []
    for arm in ("single", "dual", "forward", "reverse", "random"):
        p = runs / f"h2_plan_{arm}.json"
        if not p.exists():
            continue
        r = json.loads(p.read_text())["summary"]
        found.append(r)
        lines.append(f"| `{arm}` | {r['passed']}/{r['n']} | "
                     f"{r['intermediate_passed']}/{r['n']} | "
                     f"{r['preserved']}/{r['n']} | {r['tokens']:,} | {r['wall_s']:.0f} |")
    if not found:
        lines.append("| — | — | — | — | — | — |")
    lines += ["", "**Intermediate** is a part-test on the first artifact. "
              "**Preserved** means the first function was still present and passing "
              "after the second generation. A final pass without preservation is "
              "context corruption, not composition.", ""]
    by = {r["arm"]: r for r in found}
    two = [by[a]["passed"] for a in ("forward", "reverse", "random") if a in by]
    one = [by[a]["passed"] for a in ("single", "dual") if a in by]
    if two and one:
        lines += ["## Pre-registered composition gates", "",
                  f"- two-pass best: **{max(two)}/{by.get('forward', by.get('reverse', {})).get('n', 5)}**",
                  f"- one-pass best: **{max(one)}/{by.get('single', by.get('dual', {})).get('n', 5)}**",
                  "- gate: two-pass must beat one-pass, and preservation must hold.",
                  ""]
    p = Path(cfg["paths"]["reports"]) / "h2_composition.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines))
    return p
