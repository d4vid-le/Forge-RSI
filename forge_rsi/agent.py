"""Agent runner: one local model, one harness, one task."""
from __future__ import annotations

import ast
import json
import re
import time
from pathlib import Path

import mlx.core as mx

from . import harness as harness_mod
from . import verifier

THINK_RE = re.compile(r"<think>.*?</think>", re.S | re.I)
THINK_ALT_RE = re.compile(r"<\|think\|>.*?<\|/think\|>", re.S | re.I)
BLOCK_RE = re.compile(r"```(?:python|py)?[ \t]*\r?\n(.*?)```", re.S | re.I)
OPEN_BLOCK_RE = re.compile(r"```(?:python|py)?[ \t]*\r?\n(.*)$", re.S | re.I)


def strip_think(text: str) -> str:
    text = THINK_RE.sub("", text or "")
    text = THINK_ALT_RE.sub("", text)
    # Some models emit a bare "Thinking Process:" preamble before the answer.
    if text.lstrip().lower().startswith("thinking process"):
        for marker in ("```", "def ", "{"):
            idx = text.find(marker)
            if idx != -1:
                text = text[idx:]
                break
    return text.strip()


def parse_code(raw: str) -> str:
    text = strip_think(raw)
    blocks = [b.strip() for b in BLOCK_RE.findall(text)]
    if not blocks:
        m = OPEN_BLOCK_RE.search(text)
        if m:
            blocks = [m.group(1).strip()]
    if not blocks:
        return text.strip()
    # Prefer the longest block that defines something.
    with_def = [b for b in blocks if re.search(r"^\s*(def|class)\s+", b, re.M)]
    pool = with_def or blocks
    return max(pool, key=len).strip()


def is_stub(code: str) -> bool:
    """True when every function body is a single constant/empty return.

    This is a generic code-quality check, not a task-specific rule: it catches
    the common small-model failure mode of emitting a syntactically valid stub.
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    funcs = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if not funcs:
        return False
    for fn in funcs:
        body = list(fn.body)
        # Ignore a leading docstring.
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            body = body[1:]
        if len(body) != 1 or not isinstance(body[0], ast.Return):
            return False
        value = body[0].value
        if value is None:
            continue
        if isinstance(value, (ast.Constant, ast.Dict, ast.List, ast.Tuple, ast.Set)):
            continue
        return False
    return True


def normalize_code(code: str) -> str:
    """Whitespace/comment-insensitive key for majority voting."""
    code = re.sub(r"#.*", "", code or "")
    return re.sub(r"\s+", "", code)


def pick(candidates: list[dict], policy: str) -> dict:
    if not candidates:
        return {"code": "", "passed": False, "error_class": "empty", "raw": "", "tokens_out": 0}
    if policy == "longest":
        return max(candidates, key=lambda c: len(c.get("code", "")))
    if policy == "majority":
        groups: dict[str, list[dict]] = {}
        for c in candidates:
            groups.setdefault(normalize_code(c.get("code", "")), []).append(c)
        best = max(groups.values(), key=len)
        return best[0]
    if policy in ("test_gated", "best_of_k_oracle"):
        for c in candidates:
            if c.get("passed"):
                return c
        return candidates[0]
    return candidates[0]


def load_model(path: str, adapter_path: str | None = None):
    from mlx_lm import load
    return load(path, adapter_path=adapter_path)


def run_one_turn(model, tok, messages: list[dict], cfg: dict, seed: int,
                 temperature: float | None = None,
                 enable_thinking: bool = False) -> tuple[str, int]:
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler
    prompt = tok.apply_chat_template(
        messages, add_generation_prompt=True, tokenize=False,
        enable_thinking=enable_thinking,
    )
    mx.random.seed(seed)
    sampler = make_sampler(
        temp=float(temperature if temperature is not None else cfg["agent"]["temperature"]),
        top_p=float(cfg["agent"]["top_p"]),
    )
    raw = generate(
        model, tok, prompt=prompt,
        max_tokens=int(cfg["agent"]["max_output_tokens"]),
        sampler=sampler,
        verbose=False,
    )
    return raw, len(tok.encode(prompt)) + len(tok.encode(raw))


def run_task(model, tok, h: dict, task: dict, cfg: dict, seed: int = 0,
             samples: int = 1, use_tools: bool = True,
             temperature: float | None = None) -> dict:
    """Run one task, returning a trace with every candidate generated."""
    system = harness_mod.render(h)
    budget = h.get("budget", {})
    max_turns = int(budget.get("max_turns", 1))
    tools = h.get("tools", []) if use_tools else []
    policy = h.get("selection", {}).get("policy", "first")
    thinking = bool(budget.get("enable_thinking", cfg["agent"].get("enable_thinking", False)))
    plan_mode = "plan_then_code" in tools and max_turns >= 2
    # `samples` is the number of independent generations we want cached. The
    # selection policy is applied *after* generation, so Dream replay can
    # re-rank the same candidates under different policies.
    k = max(1, int(samples))

    candidates: list[dict] = []
    t0 = time.time()
    tokens_in_total = 0
    turns_total = 0

    for s in range(k):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": task["prompt"]},
        ]
        turns = 0
        raw = ""
        code = ""
        result = {"passed": False, "output": "empty solution", "error_class": "empty", "seconds": 0.0}
        tokens_in = 0
        tokens_out = 0

        # Optional two-pass mode: force an explicit algorithm plan before any
        # code. This is a harness-controlled lever, not a hardcoded behaviour.
        plan = ""
        if plan_mode:
            messages.append({
                "role": "user",
                "content": ("Before writing code, outline the algorithm in at most 3 short "
                            "bullets. Do not write code yet."),
            })
            plan_raw, tin = run_one_turn(
                model, tok, messages, cfg, seed + s * 17,
                temperature=temperature, enable_thinking=thinking,
            )
            turns += 1
            tokens_in += tin
            tokens_out += len(tok.encode(plan_raw))
            plan = strip_think(plan_raw)
            messages.append({"role": "assistant", "content": plan})
            messages.append({
                "role": "user",
                "content": ("Now write the complete solution in one ```python block. "
                            "Do not repeat the plan."),
            })

        while turns < max_turns:
            turns += 1
            raw, tin = run_one_turn(
                model, tok, messages, cfg, seed + s * 17 + turns,
                temperature=temperature, enable_thinking=thinking,
            )
            tokens_in += tin
            code = parse_code(raw)
            tokens_out += len(tok.encode(raw))
            result = verifier.verify(code, task)
            if result["passed"]:
                break
            if turns < max_turns and "nonstub_retry" in tools and is_stub(code):
                messages.append({"role": "assistant", "content": raw})
                messages.append({
                    "role": "user",
                    "content": (
                        "Your function body is only a placeholder (a constant or empty return). "
                        "Implement the full logic described in the task. "
                        "Output the complete corrected solution in one ```python block."
                    ),
                })
                continue
            if "run_tests" in tools and turns < max_turns:
                messages.append({"role": "assistant", "content": raw})
                # Deliberately minimal: pass/fail + error class only. Test names,
                # assertions and expected values stay out of the model's context.
                messages.append({
                    "role": "user",
                    "content": (
                        f"Your code failed the hidden tests with a {result['error_class']} error. "
                        "Re-read the task specification, find the logic bug yourself, and output "
                        "a complete corrected solution in one ```python block. "
                        "Do not describe or guess the tests."
                    ),
                })
                continue
            break
        tokens_in_total += tokens_in
        turns_total += turns
        candidates.append({
            "raw": raw, "code": code, "plan": plan, "passed": result["passed"],
            "error_class": result["error_class"], "feedback": result["output"][-800:],
            "tokens_in": tokens_in, "tokens_out": tokens_out, "turns": turns,
        })

    chosen = pick(candidates, policy)
    trace = {
        "task_id": task["id"],
        "harness": h.get("version", "?"),
        "harness_hash": harness_mod.harness_hash(h),
        "policy": policy,
        "passed": bool(chosen.get("passed")),
        "error_class": chosen.get("error_class", "unknown"),
        "code": chosen.get("code", ""),
        "feedback": chosen.get("feedback", ""),
        "candidates": candidates,
        "tokens_in": tokens_in_total,
        "tokens_out": sum(c["tokens_out"] for c in candidates),
        "turns": turns_total,
        "wall_s": round(time.time() - t0, 2),
        "seed": seed,
    }
    return trace
