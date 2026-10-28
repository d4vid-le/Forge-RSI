"""Pre-registration, sealed splits, and paired statistics for H2.

The private holdout is sealed before the search starts. It is opened only by
``unseal`` with the hash of the already-frozen winner; the access is written to
the pre-registration record.

The paired test is an exact two-sided sign test over discordant tasks, plus a
deterministic bootstrap interval for the score delta. No scipy dependency.
"""
from __future__ import annotations

import json
import math
import random
import time
from pathlib import Path

DEFAULT_GATES = {
    "min_dev_gain": 3,
    "alpha": 0.05,
    "public_holdout_max_losses": 0,
    "private_holdout_max_losses": 0,
    "min_distinct_candidates": 3,
    "max_mean_jaccard": 0.85,
    "min_cue_entropy": 0.5,
    "contrast_arms": ["real", "shuffled", "none"],
    "library_limits": [1, 2, "all"],
    "library_min_gain": 1,
    "cost_control": "greedy_r1b",
    "cost_metrics": ["per_call", "per_1k_tokens", "per_wall_s"],
}

SEALED_SPLITS = ("private_holdout",)


class PreregError(RuntimeError):
    """Pre-registration or seal violation."""


def _path(cfg: dict, round_name: str) -> Path:
    return Path(cfg["paths"]["runs"]) / f"prereg_{round_name}.json"


def create(cfg: dict, round_name: str, *, k: int = 2,
           arms: list[str] | None = None,
           splits: dict | None = None,
           gates: dict | None = None) -> dict:
    p = _path(cfg, round_name)
    if p.exists():
        return json.loads(p.read_text())
    record = {
        "experiment": "h2.1",
        "round": round_name,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "status": "registered",
        "k": int(k),
        "arms": list(arms or DEFAULT_GATES["contrast_arms"]),
        "splits": splits or {
            "search": ["dev"],
            "guards": ["holdout", "skills"],
            "sealed": list(SEALED_SPLITS),
        },
        "gates": {**DEFAULT_GATES, **(gates or {})},
        "seal": {"sealed": True, "winner_hash": None,
                 "unsealed_at": None, "access_log": []},
        "notes": [
            "search uses dev only",
            "holdout and probes are guards, never search signals",
            "private_holdout stays sealed until the winner hash is frozen",
            "experience-library entries may only cite dev/probe evidence",
            "report a tie or negative result with the same rigor as a gain",
        ],
    }
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(record, indent=2) + "\n")
    return record


def load(cfg: dict, round_name: str) -> dict:
    p = _path(cfg, round_name)
    if not p.exists():
        raise PreregError(f"no pre-registration for {round_name}; run `h2-prereg` first")
    return json.loads(p.read_text())


def save(cfg: dict, round_name: str, record: dict) -> Path:
    p = _path(cfg, round_name)
    p.write_text(json.dumps(record, indent=2) + "\n")
    return p


def guard_split(cfg: dict, round_name: str, split: str,
                winner_hash: str | None = None) -> None:
    """Raise when a sealed split is requested before the winner is frozen."""
    record = load(cfg, round_name)
    seal = record.get("seal") or {}
    if split not in (record.get("splits", {}).get("sealed") or []):
        return
    if seal.get("sealed", True) or not seal.get("winner_hash"):
        raise PreregError(
            f"{split} is sealed until the winner hash is frozen "
            f"(round {round_name})")
    if winner_hash != seal["winner_hash"]:
        raise PreregError(
            f"{split} is sealed for winner {seal['winner_hash'][:12]}; "
            f"got {str(winner_hash)[:12]}")


def unseal(cfg: dict, round_name: str, winner_hash: str,
           reason: str = "final four-split comparison") -> dict:
    if not winner_hash:
        raise PreregError("a frozen winner hash is required to unseal")
    record = load(cfg, round_name)
    seal = record.setdefault("seal", {"sealed": True, "access_log": []})
    seal["sealed"] = False
    seal["winner_hash"] = winner_hash
    seal["unsealed_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    seal.setdefault("access_log", []).append({
        "split": "private_holdout", "at": seal["unsealed_at"],
        "winner_hash": winner_hash, "reason": reason,
    })
    record["status"] = "finalized"
    save(cfg, round_name, record)
    return record


def paired_stats(base: dict, candidate: dict, *, seed: int = 0,
                 bootstrap: int = 2000) -> dict:
    """Exact sign test + deterministic bootstrap CI over task-level outcomes."""
    amap = {t["task_id"]: bool(t.get("passed")) for t in base.get("tasks", [])}
    bmap = {t["task_id"]: bool(t.get("passed")) for t in candidate.get("tasks", [])}
    ids = sorted(set(amap) & set(bmap))
    wins = [i for i in ids if bmap[i] and not amap[i]]
    losses = [i for i in ids if amap[i] and not bmap[i]]
    ties = [i for i in ids if amap[i] == bmap[i]]
    n = len(wins) + len(losses)
    if n == 0:
        p_value = 1.0
    else:
        tail = sum(math.comb(n, i) for i in range(0, min(len(wins), len(losses)) + 1))
        p_value = min(1.0, 2 * tail / (2 ** n))

    rng = random.Random(seed)
    deltas = []
    for _ in range(max(1, bootstrap)):
        pick = [rng.choice(ids) for _ in ids] if ids else []
        if not pick:
            deltas.append(0.0)
            continue
        b = sum(1 for i in pick if amap[i]) / len(pick)
        c = sum(1 for i in pick if bmap[i]) / len(pick)
        deltas.append(c - b)
    deltas.sort()
    lo = deltas[int(0.025 * (len(deltas) - 1))]
    hi = deltas[int(0.975 * (len(deltas) - 1))]
    return {
        "n": len(ids),
        "wins": len(wins),
        "losses": len(losses),
        "ties": len(ties),
        "win_tasks": wins,
        "loss_tasks": losses,
        "base_score": round(sum(amap[i] for i in ids) / len(ids), 4) if ids else 0.0,
        "candidate_score": round(sum(bmap[i] for i in ids) / len(ids), 4) if ids else 0.0,
        "delta": round((sum(bmap[i] for i in ids) - sum(amap[i] for i in ids)) / len(ids), 4)
        if ids else 0.0,
        "sign_test_p": round(p_value, 6),
        "bootstrap_ci95": [round(lo, 4), round(hi, 4)],
        "bootstrap_samples": max(1, bootstrap),
        "seed": seed,
    }


def gate_report(record: dict, dev: dict, arms: dict, diversity: dict,
                holdout: dict | None = None, private: dict | None = None,
                library: dict | None = None) -> dict:
    """Evaluate the pre-registered gates; a missing guard is reported, not passed."""
    g = record.get("gates", {})
    checks = []
    checks.append({
        "gate": f"dev gain >= +{g.get('min_dev_gain', 3)}",
        "ok": dev.get("delta", 0) >= g.get("min_dev_gain", 3),
        "observed": dev.get("delta"),
        "p": dev.get("sign_test_p"),
        "alpha": g.get("alpha", 0.05),
    })
    if holdout:
        checks.append({
            "gate": "public holdout no regression",
            "ok": holdout.get("losses", 999) <= g.get("public_holdout_max_losses", 0),
            "observed": holdout.get("losses"),
        })
    if private:
        checks.append({
            "gate": "private holdout no regression",
            "ok": private.get("losses", 999) <= g.get("private_holdout_max_losses", 0),
            "observed": private.get("losses"),
        })
    checks.append({
        "gate": "diversity floor",
        "ok": (diversity.get("distinct_candidates", 0) >= g.get("min_distinct_candidates", 3)
               and diversity.get("mean_line_jaccard", 1.0) <= g.get("max_mean_jaccard", 0.85)
               and diversity.get("cue_entropy", 0.0) >= g.get("min_cue_entropy", 0.5)),
        "observed": diversity,
    })
    if arms and all(a in arms for a in ("real", "shuffled", "none")):
        real = (arms.get("real") or {}).get("delta", -999)
        shuffled = (arms.get("shuffled") or {}).get("delta", -999)
        none = (arms.get("none") or {}).get("delta", -999)
        checks.append({
            "gate": "contrast table: real > shuffled >= none",
            "ok": real > shuffled and real >= none,
            "observed": {"real": real, "shuffled": shuffled, "none": none},
        })
    if library:
        checks.append({
            "gate": "library beats no-library and shuffled-library",
            "ok": (library.get("with", {}).get("precision", 0)
                   > library.get("without", {}).get("precision", 0)
                   and library.get("with", {}).get("precision", 0)
                   > library.get("shuffled", {}).get("precision", 0)),
            "observed": library,
        })
    return {"checks": checks, "all_pass": all(c["ok"] for c in checks)}
