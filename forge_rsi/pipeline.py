"""End-to-end round orchestration: RSI -> Dream -> SkillForge -> adapter."""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from . import bridge, dream, evaluator, harness as harness_mod, report, trainer


def _run(args: list[str]) -> int:
    cmd = [sys.executable, "-m", "forge_rsi"] + args
    print("[run]", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


def _iter_rows(cfg: dict, round_name: str) -> list[dict]:
    p = Path(cfg["paths"]["runs"]) / f"iterations_{round_name}.jsonl"
    if not p.exists():
        return []
    return [json.loads(x) for x in p.read_text().splitlines() if x.strip()]


def find_winner_run(cfg: dict, round_name: str) -> str:
    rows = _iter_rows(cfg, round_name)
    accepted = [r for r in rows if r.get("accepted")]
    if accepted:
        return accepted[-1]["candidate_run"]
    return f"{round_name}_h0"


def sf_import_export(cfg: dict, raw_path: Path, round_name: str) -> dict:
    """Import one raw file, accept clean rows, export through the hard gate."""
    project = Path(cfg["paths"]["project"])
    sf = project / "sf"
    imp = subprocess.run(
        [str(sf), "import", str(raw_path), "--session-name", f"forge-rsi {round_name}"],
        cwd=project, capture_output=True, text=True,
    )
    print(imp.stdout[-2000:])
    m = re.search(r"session\s+(sf_[A-Za-z0-9_]+)", imp.stdout)
    if not m:
        return {"ok": False, "stage": "import", "output": imp.stdout + imp.stderr}
    sid = m.group(1)
    acc = subprocess.run([str(sf), "accept", sid, "--all-clean", "--yes"],
                         cwd=project, capture_output=True, text=True)
    print(acc.stdout[-1000:])
    out_dir = Path(cfg["paths"]["curriculum"]) / "03_ready-for-training"
    exp = subprocess.run(
        [str(sf), "export", sid, "--out", str(out_dir),
         "--format", "messages", "--sort", "domain"],
        cwd=project, capture_output=True, text=True,
    )
    print(exp.stdout[-2000:])
    passed = "hard gates: PASSED" in exp.stdout
    file_m = re.search(r"→\s*(\S+)", exp.stdout)
    return {
        "ok": passed,
        "session": sid,
        "passed_gate": passed,
        "export_file": file_m.group(1) if file_m else None,
        "stdout": exp.stdout[-3000:],
        "stderr": exp.stderr[-1000:],
    }


def promote_decision(base_dev: dict, base_hold: dict, ad_dev: dict, ad_hold: dict) -> dict:
    dev_delta = ad_dev["summary"]["score"] - base_dev["summary"]["score"]
    hold_delta = ad_hold["summary"]["score"] - base_hold["summary"]["score"]
    dev_base = base_dev["summary"]["score"]

    if dev_base >= 1.0:
        # Ceiling case: there is no dev headroom, so require no regression and
        # a holdout gain. This is the only sensible promotion rule at 100% dev.
        promote = (dev_delta >= 0) and (hold_delta > 0)
        rule = ("dev is saturated (1.00); promote iff dev delta >= 0 and "
                "holdout delta > 0")
    else:
        promote = (hold_delta >= 0) and (dev_delta > 0)
        rule = "promote iff holdout delta >= 0 and dev delta > 0"

    return {
        "promote": promote,
        "dev_base": dev_base,
        "dev_adapter": ad_dev["summary"]["score"],
        "dev_delta": round(dev_delta, 4),
        "hold_base": base_hold["summary"]["score"],
        "hold_adapter": ad_hold["summary"]["score"],
        "hold_delta": round(hold_delta, 4),
        "rule": rule,
    }


def full_round(cfg: dict, round_name: str, start_harness: str | None = None,
               adapter: str | None = None, iterations: int | None = None,
               skip_train: bool = False, skip_loop: bool = False,
               force_loop: bool = False) -> dict:
    project = Path(cfg["paths"]["project"])
    start = start_harness or str(Path(cfg["paths"]["harness"]) / "h0_baseline.json")
    iterations = iterations or int(cfg["loop"]["iterations"])
    winner_path = Path(cfg["paths"]["harness"]) / f"{round_name}_winner.json"

    if skip_loop and winner_path.exists() and not force_loop:
        print(f"[pipeline] winner exists, skipping live loop: {winner_path}", flush=True)
    else:
        args = ["loop", "--round", round_name, "--iterations", str(iterations),
                "--start-harness", start]
        if adapter:
            args += ["--adapter", adapter]
        if _run(args) != 0:
            return {"ok": False, "stage": "loop"}

    winner_run_id = find_winner_run(cfg, round_name)
    winner_run = evaluator.load_run(cfg, winner_run_id)

    # Dream needs K>1 candidates; use a 3-sample run of the winning harness.
    dream_run_id = f"{round_name}_dream"
    if not (Path(cfg["paths"]["runs"]) / f"{dream_run_id}.json").exists():
        _run(["eval", "--harness", str(winner_path), "--split", "dev",
              "--run-id", dream_run_id, "--samples", "3"])
    dream_result = None
    try:
        dream_result = dream.run_and_write(cfg, evaluator.load_run(cfg, dream_run_id))
        print(dream.format_table(dream_result))
    except Exception as e:  # pragma: no cover - defensive
        print(f"[pipeline] dream skipped: {e!r}")

    # Bridge every run in this round (baseline + candidates).
    run_ids = [f"{round_name}_h0"]
    for i in range(1, iterations + 1):
        rid = f"{round_name}_h{i}"
        if (Path(cfg["paths"]["runs"]) / f"{rid}.json").exists():
            run_ids.append(rid)
    runs = [evaluator.load_run(cfg, r) for r in run_ids]
    raw_path, manifest = bridge.write_raw(cfg, runs, round_name)
    print(f"[pipeline] bridge: {manifest['rows']} rows -> {raw_path}")

    sf_result = {"ok": False, "stage": "skipped", "reason": "not enough rows"}
    adapter_result = None
    decision = None
    if not skip_train and manifest["rows"] >= int(cfg["skillforge"]["min_rows"]):
        sf_result = sf_import_export(cfg, raw_path, round_name)
        if sf_result.get("passed_gate") and sf_result.get("export_file"):
            export = Path(sf_result["export_file"])
            if not export.is_absolute():
                export = project / export
            data_dir = Path(cfg["paths"]["adapters"]) / f"{round_name}_data"
            info = trainer.prepare_data(export, data_dir)
            print(f"[pipeline] prepared adapter data: {info}")
            adapter_dir = Path(cfg["paths"]["adapters"]) / f"{round_name}_adapter"
            train_res = trainer.train(cfg, data_dir, adapter_dir)
            print(f"[pipeline] train rc={train_res['returncode']} adapter={adapter_dir}")
            if train_res["returncode"] == 0 and trainer.adapter_ready(adapter_dir):
                # Compare the adapter against the *same* winning harness,
                # unadapted, so the delta measures the adapter alone.
                base_dev = winner_run
                base_hold = evaluator.load_run(cfg, f"{round_name}_final_holdout")
                if _run(["eval", "--harness", str(winner_path), "--split", "dev",
                         "--run-id", f"{round_name}_adapter_dev", "--adapter", str(adapter_dir)]) == 0:
                    if _run(["eval", "--harness", str(winner_path), "--split", "holdout",
                             "--run-id", f"{round_name}_adapter_holdout", "--adapter", str(adapter_dir)]) == 0:
                        ad_dev = evaluator.load_run(cfg, f"{round_name}_adapter_dev")
                        ad_hold = evaluator.load_run(cfg, f"{round_name}_adapter_holdout")
                        decision = promote_decision(base_dev, base_hold, ad_dev, ad_hold)
                        decision["adapter"] = str(adapter_dir)
                        adapter_result = {"train": train_res, "decision": decision}
                        print(f"[pipeline] adapter decision: {json.dumps(decision, indent=2)}")

    summary = {
        "round": round_name,
        "start_harness": start,
        "adapter_in": adapter,
        "winner_run": winner_run_id,
        "winner_harness": winner_run["harness"].get("version"),
        "winner_dev": winner_run["summary"],
        "dream": dream_result,
        "bridge": manifest,
        "skillforge": sf_result,
        "adapter": adapter_result,
    }
    out = Path(cfg["paths"]["reports"]) / f"{round_name}_full.json"
    out.write_text(json.dumps(summary, indent=2) + "\n")
    report.write_round(cfg, round_name)
    print(f"[pipeline] summary -> {out}")
    return summary
