"""Layer 2 — Dream replay over cached candidates.

No model calls. We re-rank candidates that were already generated, so this is
honest offline policy search, not a claim to evaluate new prompts.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import agent

POLICIES = ["first", "longest", "majority", "test_gated", "best_of_k_oracle"]


def _choose(task: dict, policy: str) -> tuple[dict, int]:
    cands = task.get("candidates") or [{
        "code": task.get("code", ""), "passed": task.get("passed", False),
        "tokens_out": task.get("tokens_out", 0),
    }]
    if policy == "longest":
        return max(cands, key=lambda c: len(c.get("code", ""))), len(cands)
    if policy == "majority":
        groups: dict[str, list[dict]] = {}
        for c in cands:
            groups.setdefault(agent.normalize_code(c.get("code", "")), []).append(c)
        return max(groups.values(), key=len)[0], len(cands)
    if policy in ("test_gated", "best_of_k_oracle"):
        for c in cands:
            if c.get("passed"):
                return c, len(cands)
        return cands[0], len(cands)
    return cands[0], 1


def evaluate(run: dict) -> dict:
    rows = []
    n_tasks = len(run["tasks"])
    for policy in POLICIES:
        passed = 0
        tokens = 0
        calls = 0
        for task in run["tasks"]:
            chosen, k = _choose(task, policy)
            passed += 1 if chosen.get("passed") else 0
            tokens += sum(int(c.get("tokens_out", 0)) for c in (task.get("candidates") or [chosen])[:k])
            calls += k
        score = round(passed / n_tasks, 4) if n_tasks else 0.0
        # Dream-RSI value: reward score, penalise generation calls.
        value = round(score - 0.01 * calls + 0.005 * calls / 1.0, 4)
        rows.append({
            "policy": policy,
            "passed": passed,
            "n": n_tasks,
            "score": score,
            "calls": calls,
            "tokens_out": tokens,
            "cost_per_solved": round(tokens / passed, 1) if passed else None,
            "value": value,
        })
    # Winner: highest score, then lowest tokens, then declared policy order.
    order = {p: i for i, p in enumerate(POLICIES)}
    winner = sorted(rows, key=lambda r: (-r["score"], r["tokens_out"], order[r["policy"]]))[0]
    return {
        "run_id": run["run_id"],
        "harness": run.get("harness", {}).get("version"),
        "policies": rows,
        "winner": winner["policy"],
        "winner_row": winner,
        "note": "best_of_k_oracle is an upper bound, never deployed.",
    }


def run_and_write(cfg: dict, run: dict) -> dict:
    result = evaluate(run)
    out = Path(cfg["paths"]["runs"]) / f"dream_{run['run_id']}.json"
    out.write_text(json.dumps(result, indent=2) + "\n")
    return result


def load_result(cfg: dict, run_id: str | None = None) -> dict:
    runs = Path(cfg["paths"]["runs"])
    if run_id:
        candidates = [runs / run_id, runs / f"{run_id}.json",
                      runs / f"dream_{run_id}.json"]
        for p in candidates:
            if p.exists():
                d = json.loads(p.read_text())
                if isinstance(d, dict) and "policies" in d:
                    return d
        raise FileNotFoundError(f"no Dream replay for {run_id!r}")
    files = [p for p in sorted(runs.glob("dream_*.json"),
                               key=lambda x: x.stat().st_mtime, reverse=True)
             if "policies" in json.loads(p.read_text())]
    if not files:
        raise FileNotFoundError("no Dream replay found; run `dream --run <run-id>` first")
    return json.loads(files[0].read_text())


def write_report(cfg: dict, run_id: str | None = None) -> tuple[Path, dict]:
    result = load_result(cfg, run_id)
    reports = Path(cfg["paths"]["reports"])
    reports.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Dream replay",
        "",
        f"- source run: `{result.get('run_id')}`",
        f"- harness: `{result.get('harness') or '—'}`",
        f"- winner: **{result.get('winner')}**",
        f"- note: {result.get('note', '')}",
        "",
        "| policy | score | passed | calls | tokens out | value |",
        "|---|---|---|---|---|---|",
    ]
    for r in result.get("policies", []):
        lines.append(
            f"| `{r['policy']}` | {r['score']:.2f} | {r['passed']}/{r['n']} | "
            f"{r['calls']} | {r['tokens_out']} | {r['value']:.3f} |")
    lines += [
        "",
        "This is offline policy search over cached candidates. It makes no model",
        "calls and does not claim a new prompt was evaluated. The winner is chosen",
        "by score; tokens break ties. `value` is diagnostic. `best_of_k_oracle`",
        "is an upper bound and is never deployed.",
        "",
    ]
    path = reports / "dream.md"
    path.write_text("\n".join(lines) + "\n")
    return path, result


def format_table(result: dict) -> str:
    lines = [f"Dream replay — {result['run_id']} (harness {result['harness']})",
             f"{'policy':18}{'score':>8}{'passed':>9}{'calls':>7}{'tokens':>9}{'V':>9}"]
    for r in result["policies"]:
        lines.append(f"{r['policy']:18}{r['score']:>8.2f}{r['passed']:>9}"
                     f"{r['calls']:>7}{r['tokens_out']:>9}{r['value']:>9.3f}")
    lines.append(f"winner: {result['winner']} (oracle excluded from deployment)")
    return "\n".join(lines)
