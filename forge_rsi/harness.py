"""Harness representation: load, validate, render, hash, diff.

A harness is a JSON document. It is the only object Layer 1 is allowed to
change. Validation is deliberately strict: a harness that leaks the task
suite, the tests, or the expected answers is rejected before it can run.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

REQUIRED = ("version", "role", "contract", "hops", "tools", "selection", "budget")
POLICIES = {"first", "longest", "majority", "test_gated", "self_rank", "best_of_k_oracle"}
ALLOWED_TOOLS = {"run_tests", "plan_then_code", "nonstub_retry"}

FORBIDDEN = [
    (re.compile(r"\bdev_\d{3}\b"), "task id leak (dev_###)"),
    (re.compile(r"\bhold_\d{3}\b"), "task id leak (hold_###)"),
    (re.compile(r"\bunittest\b"), "test framework reference"),
    (re.compile(r"\bassertEqual\b"), "test assertion reference"),
    (re.compile(r"\bsolution\.py\b"), "solution file reference"),
    (re.compile(r"\bhidden test", re.I), "hidden-test reference"),
    (re.compile(r"\bholdout\b", re.I), "holdout reference"),
    (re.compile(r"\beval(uation)? set\b", re.I), "eval-set reference"),
    (re.compile(r"ignore (all )?previous", re.I), "prompt-injection style override"),
]


def load(path: str | Path) -> dict:
    with open(path) as f:
        h = json.load(f)
    ok, errors = validate(h)
    if not ok:
        raise ValueError(f"invalid harness {path}: {errors}")
    return h


def save(h: dict, path: str | Path) -> Path:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(h, indent=2) + "\n")
    return p


def canonical(h: dict) -> str:
    return json.dumps(h, sort_keys=True, separators=(",", ":"))


def harness_hash(h: dict) -> str:
    return hashlib.sha256(canonical(h).encode()).hexdigest()[:16]


def list_value(v) -> str:
    if isinstance(v, (list, tuple)):
        return "; ".join(str(x) for x in v)
    return str(v)


def render(h: dict) -> str:
    """Render the harness into the system prompt the agent actually sees."""
    parts: list[str] = []
    parts.append(f"ROLE:\n{h['role'].strip()}")

    contract = h.get("contract", {})
    lines = [f"- {k.replace('_', ' ')}: {list_value(v)}" for k, v in contract.items()]
    parts.append("CONTRACT:\n" + "\n".join(lines))

    hops = h.get("hops", [])
    hop_lines = []
    for i, hop in enumerate(hops, 1):
        hop_lines.append(f"{i}. {hop['name']}: {hop['instruction']}")
    parts.append("WORKFLOW:\n" + "\n".join(hop_lines))

    tools = h.get("tools", [])
    if tools:
        parts.append("TOOLS:\n" + "\n".join(f"- {t}" for t in tools))

    budget = h.get("budget", {})
    parts.append(
        "BUDGET:\n"
        f"- max turns: {budget.get('max_turns', 1)}\n"
        f"- max output tokens: {budget.get('max_output_tokens', 900)}"
    )
    return "\n\n".join(parts)


def diff_fields(a: dict, b: dict) -> list[str]:
    keys = set(a) | set(b)
    changed = []
    for k in sorted(keys):
        if json.dumps(a.get(k), sort_keys=True) != json.dumps(b.get(k), sort_keys=True):
            changed.append(k)
    return changed


def validate(h: dict, incumbent: dict | None = None, cfg: dict | None = None) -> tuple[bool, list[str]]:
    errs: list[str] = []
    if not isinstance(h, dict):
        return False, ["harness is not a JSON object"]

    for k in REQUIRED:
        if k not in h:
            errs.append(f"missing key: {k}")
    if errs:
        return False, errs

    if not isinstance(h["role"], str) or len(h["role"].strip()) < 10:
        errs.append("role must be a non-trivial string")
    if not isinstance(h["contract"], dict) or "output" not in h["contract"]:
        errs.append("contract.output is required")
    if not isinstance(h["hops"], list) or not (1 <= len(h["hops"]) <= 5):
        errs.append("hops must be a list of 1..5 items")
    else:
        for i, hop in enumerate(h["hops"]):
            if not isinstance(hop, dict) or "name" not in hop or "instruction" not in hop:
                errs.append(f"hop {i} needs name + instruction")
    if not isinstance(h["tools"], list) or any(t not in ALLOWED_TOOLS for t in h["tools"]):
        errs.append(f"tools must be a subset of {sorted(ALLOWED_TOOLS)}")
    sel = h.get("selection", {})
    if not isinstance(sel, dict) or sel.get("policy") not in POLICIES:
        errs.append(f"selection.policy must be one of {sorted(POLICIES)}")
    budget = h.get("budget", {})
    if not isinstance(budget, dict):
        errs.append("budget must be an object")
    else:
        turns = budget.get("max_turns", 1)
        toks = budget.get("max_output_tokens", 900)
        if not isinstance(turns, int) or not (1 <= turns <= 4):
            errs.append("budget.max_turns must be 1..4")
        if not isinstance(toks, int) or not (200 <= toks <= 2000):
            errs.append("budget.max_output_tokens must be 200..2000")
        if isinstance(h.get("tools"), list):
            if "run_tests" in h["tools"] and isinstance(turns, int) and turns < 2:
                errs.append("run_tests requires budget.max_turns >= 2")
            if "plan_then_code" in h["tools"] and isinstance(turns, int) and turns < 2:
                errs.append("plan_then_code requires budget.max_turns >= 2")
            if "nonstub_retry" in h["tools"] and isinstance(turns, int) and turns < 2:
                errs.append("nonstub_retry requires budget.max_turns >= 2")

    rendered = render(h) if not errs else ""
    max_chars = (cfg or {}).get("loop", {}).get("max_prompt_chars", 7200)
    if rendered and len(rendered) > max_chars:
        errs.append(f"rendered harness too long: {len(rendered)} > {max_chars} chars")

    for rx, why in FORBIDDEN:
        if rx.search(rendered):
            errs.append(f"forbidden content: {why}")

    if incumbent is not None:
        max_diff = (cfg or {}).get("loop", {}).get("max_diff_fields", 3)
        # `version` is bookkeeping, not a behavioural change.
        changed = [k for k in diff_fields(incumbent, h) if k != "version"]
        if len(changed) > max_diff:
            errs.append(f"too many changed fields: {changed} (max {max_diff})")

    return (not errs), errs
