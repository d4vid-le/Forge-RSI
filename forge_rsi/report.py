"""Markdown reports for a round."""
from __future__ import annotations

import json
from pathlib import Path

from . import evaluator


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def write_round(cfg: dict, round_name: str) -> Path:
    runs_dir = Path(cfg["paths"]["runs"])
    rows = _read_jsonl(runs_dir / f"iterations_{round_name}.jsonl")
    iters = [r for r in rows if "iteration" in r]
    hold = next((r for r in rows if r.get("kind") == "holdout"), None)

    baseline_id = f"{round_name}_h0"
    baseline = None
    try:
        baseline = evaluator.load_run(cfg, baseline_id)
    except FileNotFoundError:
        pass

    lines = [f"# Forge-RSI — {round_name}", ""]
    if baseline:
        s = baseline["summary"]
        lines += [
            f"**Baseline harness:** `{baseline['harness'].get('version')}`  ",
            f"**Dev score:** {s['passed']}/{s['n']} ({s['score']:.2f})  ",
            f"**Baseline tokens out:** {s['tokens_out']:,}  ",
            f"**Baseline cost/solved:** {s['cost_per_solved']}  ",
            "",
        ]

    lines += ["## Iterations", "",
              "| # | candidate | wins | losses | dev score | delta | accepted | reason |",
              "|---|---|---|---|---|---|---|---|"]
    for r in iters:
        lines.append(
            f"| {r['iteration']} | `{r.get('candidate')}` | {r.get('wins')} | "
            f"{r.get('losses')} | {r.get('candidate_score'):.2f} | "
            f"{r.get('delta'):+.2f} | {r.get('accepted')} | {r.get('reason')} |"
        )
    if not iters:
        lines.append("| — | — | — | — | — | — | — | no iterations recorded |")

    if hold:
        lines += ["", "## Holdout", "",
                  f"- baseline: {hold['baseline_score']:.2f} (`{hold['baseline']}`)",
                  f"- final: {hold['final_score']:.2f} (`{hold['final']}`)",
                  f"- delta: {hold['delta']:+.2f}",
                  f"- not worse: **{hold['not_worse']}** ({hold['reason']})",
                  f"- winner harness: `{hold['winner_harness']}`"]

    # Per-iteration run details
    lines += ["", "## Run details", ""]
    for r in iters:
        rid = r.get("candidate_run")
        if not rid:
            continue
        try:
            run = evaluator.load_run(cfg, rid)
        except FileNotFoundError:
            continue
        s = run["summary"]
        lines += [
            f"### `{rid}` — {run['harness'].get('version')}",
            "",
            f"- score: {s['passed']}/{s['n']} ({s['score']:.2f})",
            f"- tokens in/out: {s['tokens_in']:,} / {s['tokens_out']:,}",
            f"- wall: {run['wall_s']/60:.1f} min",
            f"- errors: {json.dumps(s['by_error'])}",
            "",
        ]

    out = Path(cfg["paths"]["reports"]) / f"{round_name}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return out
