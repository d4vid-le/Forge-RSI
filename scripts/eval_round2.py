#!/usr/bin/env python3
"""Evaluate round 1 vs round 2 on a private holdout and public splits.

Promotion rule for this round:
  private_delta > 0  AND  public_dev_delta >= 0
  AND public_probe_delta >= 0  AND no forgetting.
Ties keep round 1.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forge_rsi import config

PY = sys.executable


def run(args: list[str]) -> None:
    cmd = [PY, "-m", "forge_rsi"] + args
    print("[eval-round2]", " ".join(cmd), flush=True)
    rc = subprocess.call(cmd)
    if rc:
        raise SystemExit(f"eval failed: {rc}")


def report(cfg: dict, name: str) -> dict:
    p = Path(cfg["paths"]["runs"]) / f"{name}_gated_report.json"
    if not p.exists():
        raise FileNotFoundError(p)
    return json.loads(p.read_text())


def main() -> int:
    cfg = config.load()
    r1 = str(Path(cfg["paths"]["adapters"]) / "skills" / "registry.json")
    r2 = str(Path(cfg["paths"]["adapters"]) / "skills" / "r2" / "registry.json")
    if not Path(r2).exists():
        raise SystemExit("round-2 registry missing; run scripts/train_round2.py first")

    # Round 1 public reports already exist from the first round. Re-run only the
    # round-2 public evaluations, plus both private holdout evaluations.
    run(["skills-eval", "--splits", "dev", "--run-id", "r2_public",
         "--registry", r2, "--router", "keyword"])
    run(["skills-eval", "--splits", "private_holdout", "--run-id", "private_r1",
         "--registry", r1, "--router", "keyword"])
    run(["skills-eval", "--splits", "private_holdout", "--run-id", "private_r2",
         "--registry", r2, "--router", "keyword"])

    r1_dev = report(cfg, "legates_final_dev")
    r1_skills = report(cfg, "skills24_fixed_r1_skills")
    r2_dev = report(cfg, "r2_public_dev")
    r2_skills = report(cfg, "skills24_fixed_r2_skills")
    p1 = report(cfg, "private_r1_private_holdout")
    p2 = report(cfg, "private_r2_private_holdout")

    private_delta = round(p2["gated_summary"]["score"] - p1["gated_summary"]["score"], 4)
    public_dev_delta = round(r2_dev["gated_summary"]["score"] - r1_dev["gated_summary"]["score"], 4)
    public_probe_delta = round(r2_skills["gated_summary"]["score"] - r1_skills["gated_summary"]["score"], 4)
    forgetting_ok = all(
        r["non_routed_identical"] and r["base_unchanged"] is not False
        for r in (p1, p2, r2_dev, r2_skills)
    )
    promote = (private_delta > 0 and public_dev_delta >= 0
               and public_probe_delta >= 0 and forgetting_ok)
    if private_delta == 0:
        reason = "private holdout tie; keep round 1"
    elif private_delta < 0:
        reason = "round 2 regressed on the private holdout; quarantine it"
    elif not forgetting_ok:
        reason = "zero-forgetting check failed; quarantine round 2"
    elif public_dev_delta < 0 or public_probe_delta < 0:
        reason = "round 2 gained private but regressed public splits; keep round 1"
    elif promote:
        reason = "private gain with no public regression; promote round 2"
    else:
        reason = "promotion rule not met; keep round 1"

    decision = {
        "round1_registry": r1,
        "round2_registry": r2,
        "private_r1": p1["gated_summary"],
        "private_r2": p2["gated_summary"],
        "r2_public_dev": r2_dev["gated_summary"],
        "r2_public_skills": r2_skills["gated_summary"],
        "private_delta": private_delta,
        "public_dev_delta": public_dev_delta,
        "public_probe_delta": public_probe_delta,
        "forgetting_ok": forgetting_ok,
        "promote": promote,
        "reason": reason,
    }
    out = Path(cfg["paths"]["runs"]) / "private_round2_decision.json"
    out.write_text(json.dumps(decision, indent=2) + "\n")
    write_private_md(cfg, p1, p2, decision)
    print(json.dumps(decision, indent=2))
    print(f"[eval-round2] decision -> {out}")
    return 0


def write_private_md(cfg: dict, p1: dict, p2: dict, decision: dict) -> None:
    r1 = {c["task_id"]: c for c in p1["changes"]}
    r2 = {c["task_id"]: c for c in p2["changes"]}
    ids = sorted(set(r1) | set(r2))
    lines = [
        "# Private holdout + round 2",
        "",
        "10 synthetic tasks, withheld from the public repository: 4 word-frequency",
        "variants, 4 interval variants, 2 unrelated controls. The function names",
        "and test data are new; the adapters never saw them.",
        "",
        "| run | base | gated | delta | routed | non-routed identical | base unchanged |",
        "|---|---|---|---|---|---|---|",
    ]
    for tag, r in (("round 1", p1), ("round 2", p2)):
        b, g = r["base_summary"], r["gated_summary"]
        lines.append(
            f"| {tag} | {b['passed']}/{b['n']} ({b['score']:.2f}) | "
            f"{g['passed']}/{g['n']} ({g['score']:.2f}) | {r['delta_score']:+.2f} | "
            f"{len(r['routed_tasks'])} | {r['non_routed_identical']} | {r['base_unchanged']} |"
        )
    lines += ["", "| task | skill | round 1 | round 2 | delta |", "|---|---|---|---|---|"]
    for tid in ids:
        a, b = r1.get(tid), r2.get(tid)
        skill = (a or b)["skill"]
        av = a["gated_passed"] if a else None
        bv = b["gated_passed"] if b else None
        delta = (int(bv) - int(av)) if av is not None and bv is not None else "—"
        lines.append(f"| `{tid}` | `{skill}` | {av} | {bv} | {delta} |")
    lines += [
        "",
        "## Decision",
        "",
        f"- private holdout delta: **{decision['private_delta']:+.2f}**",
        f"- public dev delta: {decision['public_dev_delta']:+.2f}",
        f"- public 24-probe delta: {decision['public_probe_delta']:+.2f}",
        f"- zero-forgetting checks: {decision['forgetting_ok']}",
        f"- **promote round 2: {decision['promote']}**",
        f"- reason: {decision['reason']}",
        "",
        "The task definitions are withheld; only aggregate and per-task-id outcomes",
        "are reported. A future blind claim needs a fresh private holdout again.",
        "",
    ]
    (Path(cfg["paths"]["reports"]) / "private_holdout.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
