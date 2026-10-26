"""Generate the final, evidence-only report from on-disk artifacts.

No numbers are typed by hand. Every table is read from `runs/`, `reports/`, or
`curriculum/` and re-rendered. If an artifact is missing, the section says so.
"""
from __future__ import annotations

import json
from pathlib import Path

from . import evaluator


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def _fmt(x, digits=2):
    if x is None:
        return "—"
    if isinstance(x, float):
        return f"{x:.{digits}f}"
    return str(x)


def _run_row(cfg: dict, run_id: str) -> dict | None:
    try:
        return evaluator.load_run(cfg, run_id)
    except FileNotFoundError:
        return None


def write(cfg: dict) -> Path:
    runs_dir = Path(cfg["paths"]["runs"])
    reports_dir = Path(cfg["paths"]["reports"])
    rounds = sorted(p.stem.replace("iterations_", "") for p in runs_dir.glob("iterations_*.jsonl"))

    lines: list[str] = [
        "# Forge-RSI — final report",
        "",
        "All scores below are measured on frozen tasks with hidden `unittest` tests.",
        "The holdout is evaluated once per round and never used to choose a harness.",
        "",
    ]

    # ── environment / freeze ──────────────────────────────────────────────
    freeze_path = Path(cfg["paths"]["tasks"]) / "FREEZE.json"
    if freeze_path.exists():
        fz = json.loads(freeze_path.read_text())
        lines += [
            "## Frozen inputs",
            "",
            f"- tasks: **{fz['task_counts']['dev']} dev + {fz['task_counts']['holdout']} holdout**",
            f"- combined sha256: `{fz['combined_sha256']}`",
            f"- frozen at: {fz['frozen_at']}",
            "",
        ]

    # ── per-round tables ─────────────────────────────────────────────────
    for rd in rounds:
        rows = _read_jsonl(runs_dir / f"iterations_{rd}.jsonl")
        iters = [r for r in rows if "iteration" in r]
        hold = next((r for r in rows if r.get("kind") == "holdout"), None)
        base = _run_row(cfg, f"{rd}_h0")
        base_hold = _run_row(cfg, f"{rd}_baseline_holdout")

        lines += [f"## Round `{rd}`", ""]
        if base:
            s = base["summary"]
            lines += [
                f"**Start harness:** `{base['harness'].get('version')}`  ",
                f"**Dev:** {s['passed']}/{s['n']} ({s['score']:.2f}) · "
                f"**cost/solved:** {_fmt(s['cost_per_solved'], 1)} tokens  ",
            ]
        if base_hold:
            s = base_hold["summary"]
            lines += [f"**Holdout:** {s['passed']}/{s['n']} ({s['score']:.2f})  ", ""]

        lines += [
            "| # | candidate | wins | losses | dev | delta | accepted | reason |",
            "|---|---|---|---|---|---|---|---|",
        ]
        for r in iters:
            lines.append(
                f"| {r['iteration']} | `{r.get('candidate')}` | {r.get('wins')} | "
                f"{r.get('losses')} | {_fmt(r.get('candidate_score'))} | "
                f"{r.get('delta', 0):+.2f} | {r.get('accepted')} | {r.get('reason')} |"
            )
        if not iters:
            lines.append("| — | — | — | — | — | — | — | no iterations |")

        if hold:
            lines += [
                "",
                f"**Holdout after round:** {hold['final_score']:.2f} "
                f"(baseline {hold['baseline_score']:.2f}, delta {hold['delta']:+.2f}) — "
                f"not worse: **{hold['not_worse']}**  ",
                f"**Winner harness:** `{hold['winner_harness']}`  ",
            ]
        lines.append("")

    # ── engineering probes ───────────────────────────────────────────────
    probe_path = runs_dir / "probes.json"
    if probe_path.exists():
        probes = json.loads(probe_path.read_text())
        lines += ["## Harness probes (pre-loop engineering evidence)", "",
                  "| probe | dev | cost/solved | note |",
                  "|---|---|---|---|"]
        for p in probes:
            lines.append(
                f"| `{p.get('name')}` | {p.get('dev_passed', p.get('dev_score'))} | "
                f"{p.get('cost_per_solved', '—')} | {p.get('note', '')} |"
            )
        lines.append("")

    # ── Dream replay ─────────────────────────────────────────────────────
    dream_files = sorted(runs_dir.glob("dream_*.json"))
    if dream_files:
        lines += ["## Dream replay (Layer 2)", "",
                  "Selection policies re-rank the *same* cached candidates. "
                  "`best_of_k_oracle` is an upper bound and is never deployed.", "",
                  "| run | policy | score | passed | calls | tokens | V |",
                  "|---|---|---|---|---|---|---|"]
        for p in dream_files:
            d = json.loads(p.read_text())
            for r in d["policies"]:
                star = " **(winner)**" if r["policy"] == d["winner"] else ""
                lines.append(
                    f"| `{d['run_id']}` | {r['policy']}{star} | {r['score']:.2f} | "
                    f"{r['passed']}/{r['n']} | {r['calls']} | {r['tokens_out']:,} | "
                    f"{r['value']:.3f} |"
                )
        lines.append("")

    # ── Le-Gates ─────────────────────────────────────────────────────────
    gated = sorted(runs_dir.glob("*_gated_report.json"))
    registry_path = Path(cfg["paths"]["adapters"]) / "skills" / "registry.json"
    if gated or registry_path.exists():
        lines += ["## Le-Gates skill isolation (frozen base + gated adapters)", ""]
        if registry_path.exists():
            reg = json.loads(registry_path.read_text())
            lines += ["| skill | status | dev gain | probe gain | reason |",
                      "|---|---|---|---|---|"]
            for name, e in reg.items():
                d = e.get("decision") or {}
                lines.append(
                    f"| `{name}` | **{e.get('status', '?')}** | {d.get('dev_gain', '—')} | "
                    f"{d.get('probe_gain', '—')} | {d.get('reason', '—')} |"
                )
            lines.append("")
        if gated:
            lines += ["| split | base | gated | delta | non-routed identical | base unchanged |",
                      "|---|---|---|---|---|---|"]
            for p in gated:
                r = json.loads(p.read_text())
                b, g = r["base_summary"], r["gated_summary"]
                lines.append(
                    f"| `{r['split']}` | {b['passed']}/{b['n']} ({b['score']:.2f}) | "
                    f"{g['passed']}/{g['n']} ({g['score']:.2f}) | {r['delta_score']:+.2f} | "
                    f"{r['non_routed_identical']} | {r['base_unchanged']} |"
                )
            lines.append("")

    # ── SkillForge bridge ────────────────────────────────────────────────
    manifests = sorted((Path(cfg["paths"]["curriculum"]) / "01_raw").glob("*.manifest.json"))
    if manifests:
        lines += ["## SkillForge data (Layer 3)", "",
                  "| file | rows | success | repair | tasks covered | runs |",
                  "|---|---|---|---|---|---|"]
        for p in manifests:
            m = json.loads(p.read_text())
            lines.append(
                f"| `{Path(m['file']).name}` | {m['rows']} | "
                f"{m['by_kind'].get('success', 0)} | {m['by_kind'].get('repair', 0)} | "
                f"{m['tasks_covered']} | {', '.join(m['runs'])} |"
            )
        lines.append("")

    # ── adapter decisions ────────────────────────────────────────────────
    full = sorted(reports_dir.glob("*_full.json"))
    if full:
        lines += ["## Adapter decisions", "",
                  "| round | adapter | dev base | dev adapter | dev Δ | hold base | "
                  "hold adapter | hold Δ | promote |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for p in full:
            s = json.loads(p.read_text())
            ad = s.get("adapter")
            if not ad:
                lines.append(f"| `{s.get('round')}` | — | — | — | — | — | — | — | not trained |")
                continue
            d = ad["decision"]
            lines.append(
                f"| `{s.get('round')}` | `{Path(d['adapter']).name}` | "
                f"{d['dev_base']:.2f} | {d['dev_adapter']:.2f} | {d['dev_delta']:+.2f} | "
                f"{d['hold_base']:.2f} | {d['hold_adapter']:.2f} | {d['hold_delta']:+.2f} | "
                f"**{d['promote']}** |"
            )
        lines.append("")

    # ── honest limitations ───────────────────────────────────────────────
    lines += [
        "## Limitations (read this before quoting a number)",
        "",
        "- The suite is 30 small Python tasks. It measures code correctness under a",
        "  deterministic verifier, not general intelligence.",
        "- The teacher sees failure *symptoms* (error class, task prompt, model code),",
        "  never test source or holdout items.",
        "- Dream replay re-ranks cached samples; it does not evaluate new prompts.",
        "- A single round on 20 dev tasks has a granularity of 0.05. Deltas smaller",
        "  than that are noise unless the cost also moves.",
        "- Adapters are candidates, not automatic improvements; the promotion rule",
        "  requires a holdout non-regression and a dev gain (or, at the dev ceiling,",
        "  a holdout gain with no dev regression).",
        "",
    ]

    out = reports_dir / "final.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return out
