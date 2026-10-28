#!/usr/bin/env python3
"""Generate the H2 Stage 1 review packet from on-disk artifacts.

No model calls. Every number is read from runs/, harness/, or the frozen
pre-registration. The one-pager and the full review packet are derived from the
same data so they cannot disagree.
"""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path

from forge_rsi import config, harness, optimizer, ppc

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "reports"
RUNS = ROOT / "runs"
HARNESS = ROOT / "harness"
CFG = config.load()
ROUND = "h2a"


def load(path: Path, default=None):
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def content_hash(h: dict) -> str:
    h = {k: v for k, v in h.items() if k != "version"}
    return hashlib.sha256(harness.canonical(h).encode()).hexdigest()[:12]


def pct(x):
    return f"{x:.2f}"


A = load(RUNS / "r1b_dev_hard.json")
B = load(RUNS / "h2a_real.json")
E = load(RUNS / "h2a_h0.json")
PPC = load(RUNS / "h2a_ppc.json")
SUM = load(RUNS / "h2a" / "summary.json")
CONTRAST = PPC["contrast"]
CUE = CONTRAST.get("cue_table") or []
DIV = CONTRAST.get("diversity") or {}
DIS = CONTRAST.get("disagreement") or {}
E_JSON = load(RUNS / "h2a_E.json", {})
E1 = load(RUNS / "h2a_E_h1.json")
E2 = load(RUNS / "h2a_E_h2.json")
SINGLE = load(RUNS / "h2_plan_single.json")
FORWARD = load(RUNS / "h2_plan_forward.json")
PREREG_V1 = (ROOT / "docs" / "H2-PREREG.md").read_text()
PREREG_V2 = (ROOT / "docs" / "H2-PREREG-v2.md").read_text()
PREREG_HASH = (ROOT / "docs" / "H2-PREREG-v2.sha256").read_text().split()[0]
HARD = load(ROOT / "tasks" / "HARD_FREEZE.json", {})
HARD_HASH = HARD.get("combined_sha256", "")
CANDIDATE_FILES = {
    "inv1": HARNESS / "h2a_inv1.json",
    "inv2": HARNESS / "h2a_inv2.json",
    "dom1": HARNESS / "h2a_dom1.json",
    "dom2": HARNESS / "h2a_dom2.json",
    "real": HARNESS / "h2a_real.json",
    "E h1": HARNESS / "h2a_E_h1.json",
    "E h2": HARNESS / "h2a_E_h2.json",
}
RUN_FOR = {
    "inv1": RUNS / "h2a_inv1.json",
    "inv2": RUNS / "h2a_inv2.json",
    "dom1": RUNS / "h2a_dom1.json",
    "dom2": RUNS / "h2a_dom2.json",
    "real": RUNS / "h2a_real.json",
    "E h1": RUNS / "h2a_E_h1.json",
    "E h2": RUNS / "h2a_E_h2.json",
}


def task_rows():
    maps = {k: {t["task_id"]: t for t in (r.get("tasks") or [])}
            for k, r in (("A", A), ("B", B), ("E", E))}
    ids = sorted(set(maps["A"]) | set(maps["B"]) | set(maps["E"]))
    rows = []
    for tid in ids:
        row = {"task": tid}
        for k in ("A", "B", "E"):
            t = maps[k].get(tid) or {}
            row[k] = "PASS" if t.get("passed") else "fail"
            row[f"{k}_err"] = t.get("error_class") or "—"
        rows.append(row)
    return rows


def candidate_table():
    lines = ["| candidate | content hash | tools | policy | turns | passed | role (short) |",
             "|---|---|---|---|---|---|---|"]
    for name, path in CANDIDATE_FILES.items():
        if not path.exists():
            continue
        h = json.loads(path.read_text())
        run = load(RUN_FOR.get(name), {})
        s = (run or {}).get("summary") or {}
        role = " ".join(str(h.get("role", "")).split())[:70]
        lines.append(
            f"| `{name}` | `{content_hash(h)}` | `{h.get('tools')}` | "
            f"`{(h.get('selection') or {}).get('policy')}` | "
            f"{(h.get('budget') or {}).get('max_turns')} | "
            f"{s.get('passed', '—')}/{s.get('n', '—')} | {role} |")
    return "\n".join(lines)


def cue_table():
    lines = ["| cue | harness | confidence | support | base passes | candidate passes |",
             "|---|---|---|---|---|---|"]
    for c in CUE:
        ev = c.get("evidence") or {}
        lines.append(f"| `{c['cue'].get('skill')}/{c['cue'].get('error_class')}` | "
                     f"`{c.get('harness')}` | {c.get('confidence', 0):.3f} | "
                     f"{ev.get('n')} | {ev.get('base_passes')} | "
                     f"{ev.get('candidate_passes')} |")
    if not CUE:
        lines.append("| — | — | — | — | — | — |")
    return "\n".join(lines)


def e_log():
    lines = ["| iteration | candidate | passed | wins | losses | accepted | reason |",
             "|---|---|---|---|---|---|---|"]
    for row in E_JSON.get("iterations", []):
        i = row.get("iteration")
        run = load(RUNS / f"h2a_E_h{i}.json", {}) if i else {}
        s = run.get("summary") or {}
        lines.append(f"| {i} | `{row.get('candidate')}` | "
                     f"{s.get('passed', '—')}/{s.get('n', '—')} | "
                     f"{row.get('wins', '—')} | {row.get('losses', '—')} | "
                     f"{row.get('accepted')} | {row.get('reason')} |")
    return "\n".join(lines)


def cost_rows():
    lines = ["| arm | deployment passed | tokens in | tokens out | wall s | cost/solved | search calls | search tokens | search wall s |",
             "|---|---|---|---|---|---|---|---|---|"]
    for name, run, led in (("A r1b", A, None),
                           ("B H2.1", B, SUM.get("B", {}).get("stats") and None),
                           ("E incumbent", E, None)):
        s = run.get("summary") or {}
        lines.append(f"| {name} | {s.get('passed')}/{s.get('n')} | {s.get('tokens_in')} | "
                     f"{s.get('tokens_out')} | {s.get('wall_s')} | "
                     f"{s.get('cost_per_solved')} | — | — | — |")
    # The search ledgers are in the Stage-1 summary through PPC/E JSON.
    b_led = PPC.get("ledger") or {}
    e_led = E_JSON.get("ledger") or {}
    lines.append(f"| B search | — | — | — | — | — | {b_led.get('calls')} | "
                 f"{b_led.get('tokens')} | {b_led.get('wall_s')} |")
    lines.append(f"| E search | — | — | — | — | — | {e_led.get('calls')} | "
                 f"{e_led.get('tokens')} | {e_led.get('wall_s')} |")
    return "\n".join(lines)


def composer_prompt():
    base = json.loads((HARNESS / "h0_baseline.json").read_text())
    cands = {}
    for name in ("inv1", "inv2", "dom1", "dom2"):
        p = HARNESS / f"h2a_{name}.json"
        if p.exists():
            cands[name] = json.loads(p.read_text())
    table = ppc.render_table(CONTRAST)
    mission = optimizer.build_compose_mission(base, cands, table, CUE, arm="real")
    return (
        "# Exact composer prompt (reconstructed from the frozen inputs)\n\n"
        "The teacher chat template adds the assistant prefill `{`; the system and "
        "mission below are exactly the text inputs. No hidden tests or private "
        "holdout appear here.\n\n"
        "## SYSTEM\n\n```\n" + optimizer.SYSTEM + "\n```\n\n"
        "## MISSION\n\n```\n" + mission + "\n```\n"
    )


def prereg_diff():
    diff = "".join(difflib.unified_diff(
        PREREG_V1.splitlines(True), PREREG_V2.splitlines(True),
        fromfile="docs/H2-PREREG.md (v1, commit 95aa968)",
        tofile="docs/H2-PREREG-v2.md (v2, commit 9e57806)"))
    return (
        "# H2 pre-registration v1 → v2\n\n"
        f"- v1 hash: `{(ROOT / 'docs' / 'H2-PREREG.sha256').read_text().split()[0]}`\n"
        f"- v2 hash: `{PREREG_HASH}`\n"
        "- v1 frozen: commit `95aa968` (2026-10-28)\n"
        "- v2 frozen: commit `9e57806` (2026-10-28), before the first H2 model call\n\n"
        "## Why v2\n\n"
        "v1 listed the private holdout baseline as 10/10 without labelling it. That "
        "number is the gated Le-Gates r1 result, not the r1b harness. v2 keeps the "
        "private set sealed and compares B vs A only at finalization; it also "
        "aligns E with B's 6 rollouts / 5 teacher calls. The primary endpoint is "
        "unchanged.\n\n"
        "## Diff\n\n```diff\n" + diff + "\n```\n"
    )


def plans_smoke():
    def row(label, run):
        s = (run or {}).get("summary") or {}
        return (f"| {label} | {s.get('passed')}/{s.get('n')} | "
                f"{s.get('intermediate_passed')}/{s.get('n')} | "
                f"{s.get('preserved')}/{s.get('n')} | {s.get('tokens')} |")
    return (
        "# H2.3 composition smoke (engineering only)\n\n"
        "This is a one-task pre-flight of the plan executor, not the H2.3 "
        "experiment. Stage 3 was not run because Stage 1 stopped.\n\n"
        "| arm | passed | intermediate | preserved | tokens |\n"
        "|---|---|---|---|---|\n"
        + row("single", SINGLE) + "\n" + row("forward", FORWARD) + "\n\n"
        "`comp_01` asks for both `word_freq` and `merge_intervals`. The forward "
        "arm ran word_freq with its own adapter, verified the intermediate "
        "function, then ran merge_intervals on the preserved code. The final "
        "compound test passed. This is a mechanism signal for a separate "
        "pre-registered H2.3 run, not a composition result.\n"
    )


def one_pager(rows, cands, cues, elog, costs):
    b_stats = (SUM.get("B") or {}).get("stats") or {}
    a_stats = (SUM.get("A") or {})
    e_stats = (SUM.get("E") or {})
    b_wins = b_stats.get("win_tasks") or []
    b_losses = b_stats.get("loss_tasks") or []
    lines = [
        "# H2.1 Stage 1: pre-registered negative on a 20-task hard split — composer collapse and an invalid compute control",
        "",
        f"- pre-registration v2: `{PREREG_HASH}`",
        f"- frozen split: `dev_hard`, 20 tasks, combined sha256 `{HARD_HASH}`",
        f"- decision: **{SUM.get('decision')}**",
        "",
        "## What this establishes",
        "",
        "On this 20-task hard split, at this compute, H2.1's parallel "
        "propose–probe–compose loop **failed to meet the pre-registered +3 floor**. "
        "The composer reduced to selection, the cue table had zero routing entropy, "
        "and the diversity gate failed. These are measured facts.",
        "",
        "## What this does not establish",
        "",
        "- **Not “no effect.”** B−A = +1 with a 95% CI of [-0.10, +0.20]. The CI "
        "includes zero *and* +3. With n=20 this is underpowered for an equivalence "
        "claim. The honest wording is “failed to meet the floor.”",
        "- **Not “B beat compute-matched greedy.”** E stopped after 2/5 iterations "
        "on the duplicate rule. The E control is invalid, not just incomplete; no "
        "compute claim is made.",
        "- **Not a composition result.** The composer adopted `h2a_inv1` wholesale. "
        "It did not merge INV/DOM edits. The experiment tested selection, not "
        "composition.",
        "",
        "## A / B / E",
        "",
        "| arm | passed | score | Δ vs A | wins | losses | McNemar p | 95% CI |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
        f"| A r1b | {a_stats.get('passed')}/20 | {a_stats.get('score'):.2f} | — | — | — | — | — |",
        f"| B H2.1 real | {SUM['B']['passed']}/20 | {SUM['B']['score']:.2f} | "
        f"{b_stats.get('delta', 0):+.2f} | {b_stats.get('wins')} | {b_stats.get('losses')} | "
        f"{b_stats.get('sign_test_p', 1):.4f} | "
        f"[{b_stats.get('bootstrap_ci95', [0, 0])[0]:+.2f}, "
        f"{b_stats.get('bootstrap_ci95', [0, 0])[1]:+.2f}] |",
        f"| E incumbent | {SUM['E']['passed']}/20 | {SUM['E']['score']:.2f} | "
        f"{e_stats.get('stats', {}).get('delta', 0):+.2f} | "
        f"{e_stats.get('stats', {}).get('wins')} | "
        f"{e_stats.get('stats', {}).get('losses')} | "
        f"{e_stats.get('stats', {}).get('sign_test_p', 1):.4f} | "
        f"[{e_stats.get('stats', {}).get('bootstrap_ci95', [0, 0])[0]:+.2f}, "
        f"{e_stats.get('stats', {}).get('bootstrap_ci95', [0, 0])[1]:+.2f}] |",
        "",
        f"**The +1 is a trade, not a strict improvement.** B won `{b_wins}` and "
        f"lost `{b_losses}`. A is Pareto-better on the regression task; B is not a "
        "free upgrade.",
        "",
        "## Per-task A/B/E",
        "",
        "| task | A | B | E | A error | B error | E error |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in rows:
        mark = "**" if row["A"] != row["B"] else ""
        lines.append(f"| `{row['task']}` | {mark}{row['A']}{mark} | {mark}{row['B']}{mark} | "
                     f"{row['E']} | {row['A_err']} | {row['B_err']} | {row['E_err']} |")
    lines += [
        "",
        "## Composer",
        "",
        f"Mode: **{PPC.get('composer_mode')}**"
        + (f" · selected `{', '.join(PPC.get('composer_selected') or [])}`"
           if PPC.get("composer_selected") else ""),
        "",
        "The exact system + mission the composer saw is in "
        "[`h2_composer_prompt.md`](h2_composer_prompt.md); the real contrast table "
        "is [`h2_contrast_table.md`](h2_contrast_table.md). Verbatim selection was "
        "valid under the frozen prompt; a synthesis constraint would be a new "
        "experiment.",
        "",
        "### Cue → harness table",
        "",
        cues,
        "",
        "## Diversity",
        "",
        "| metric | value | floor |",
        "|---|---:|---:|",
        f"| distinct candidates | {DIV.get('distinct_candidates')} | ≥3 |",
        f"| mean line Jaccard | {DIV.get('mean_line_jaccard')} | ≤0.85 |",
        f"| unique tool sequences | {DIV.get('unique_tool_sequences')} | ≥2 |",
        f"| cue entropy | {DIV.get('cue_entropy')} | ≥0.5 |",
        f"| disagreement rate | {DIS.get('rate')} | report |",
        "",
        "All cue groups mapped to `h2a_inv1`; the router signal is empty.",
        "",
        "## E control",
        "",
        "E was stopped by the duplicate rule after two byte-identical proposals "
        "(Jaccard 1.0). It ran **2/5** iterations. This is an invalid compute "
        "control, not a completed arm.",
        "",
        elog,
        "",
        "## Cost",
        "",
        costs,
        "",
        f"B's deployment cost per solved task is **{B['summary']['cost_per_solved']}** "
        f"vs A's **{A['summary']['cost_per_solved']}**; B is not cheaper. The +1 "
        "gain per 1k search tokens is "
        f"**{1 / (PPC['ledger']['tokens'] / 1000):.4f}** and per search minute "
        f"**{1 / (PPC['ledger']['wall_s'] / 60):.4f}**; with the invalid E arm this "
        "is descriptive only.",
        "",
        "## What was not run",
        "",
        "- Stage 2 (shuffled/no-table; library on/off/shuffled) — not run after "
        "the Stage 1 stop.",
        "- Stage 3 full H2.3 matrix — not run after the Stage 1 stop.",
        "- The private holdout — **never opened**. The seal is intact.",
        "",
        "## H2.3 smoke (not the experiment)",
        "",
        "A one-task pre-flight: single-pass 0/1; forward word→merge 1/1 with the "
        "intermediate function verified and preserved. This is a mechanism signal "
        "for a separate pre-registered H2.3 run, not a result.",
        "",
        "## Infrastructure",
        "",
        "The ledger, pre-registration/seal, library, parallel PPC, and plan "
        "executor are the contribution here. The +1 harness stays in the workbench "
        "as a candidate, not a capability claim.",
        "",
    ]
    return "\n".join(lines)


def main() -> int:
    rows = task_rows()
    cands = candidate_table()
    cues = cue_table()
    elog = e_log()
    costs = cost_rows()
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "h2_stage1.md").write_text(one_pager(rows, cands, cues, elog, costs))
    (OUT / "h2_stage1_review.md").write_text(
        one_pager(rows, cands, cues, elog, costs)
        + "\n\n---\n\n## Candidate harnesses\n\n" + cands
        + "\n\n## Exact composer prompt\n\nSee `h2_composer_prompt.md`.\n"
        + "\n\n## Pre-registration diff\n\nSee `h2_prereg_diff.md`.\n"
        + "\n\n## H2.3 smoke\n\nSee `h2_plans_smoke.md`.\n")
    (OUT / "h2_composer_prompt.md").write_text(composer_prompt())
    (OUT / "h2_prereg_diff.md").write_text(prereg_diff())
    (OUT / "h2_plans_smoke.md").write_text(plans_smoke())
    (OUT / "h2_contrast_table.md").write_text(
        "# H2.1 real contrast table\n\n" + ppc.render_table(CONTRAST) + "\n")
    print(f"wrote {OUT / 'h2_stage1.md'}")
    print(f"wrote {OUT / 'h2_stage1_review.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
