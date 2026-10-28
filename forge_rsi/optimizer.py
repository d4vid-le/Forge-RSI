"""Teacher-side harness proposal.

The teacher sees the incumbent harness, the last comparisons, and a compact
summary of failures. It never sees hidden test source and never sees the
holdout.
"""
from __future__ import annotations

import gc
import json
import re
import time

import mlx.core as mx

from . import agent
from . import harness as harness_mod

SYSTEM = (
    "You are a harness optimizer for a local coding agent. You improve the "
    "agent's prompt-level harness. You output only a JSON object."
)

RULES = """
You will be given the current harness, recent comparison history, and failing tasks.
Return a single improved harness as a JSON object with exactly these keys:
  version, role, contract, hops, tools, selection, budget

Hard rules:
- Output ONLY the JSON object. No markdown fences, no commentary.
- Change at most {max_diff} top-level fields compared with the current harness.
- Do not propose a harness identical to a candidate that was already rejected.
  Read RECENT HISTORY and choose a different lever.
- If ENGINEERING PROBES show a configuration with a better dev score at lower
  cost than the incumbent, prefer reusing that configuration over a speculative
  new edit. The probes are measured, not hypothetical.
- If the failure is a syntactic stub and a nonstub_retry probe solved it, use
  nonstub_retry; do not spend a turn on run_tests for a stub.
- Prefer ONE surgical change that directly addresses the observed failure. If the
  failure is a model-capability error (wrong algorithm, wrong API use), do not try
  to fix it with generic prompt advice — keep the incumbent or add the run_tests
  tool so the agent can see the failure and revise.
- Do not add generic "be careful" or "handle edge cases" boilerplate; it distracts
  a small model and has already been measured to hurt.
- Do not mention any task id, test name, test code, "hidden test", "holdout", or "eval set".
- Do not hardcode answers or task-specific constants.
- tools must be a subset of: ["run_tests", "plan_then_code", "nonstub_retry"]. Empty list is allowed.
- "plan_then_code" forces one extra turn: the model outlines the algorithm, then
  writes code. Use it when the model rushes the implementation or emits a stub.
- "nonstub_retry" costs an extra turn only when the first answer is a syntactic
  stub (a single constant/empty return); this is the cheap fix for stub failures.
- selection.policy must be one of: first, longest, majority, test_gated, self_rank.
- budget.max_turns must be 1..4; budget.max_output_tokens must be 200..2000.
- The rendered prompt must stay under {max_chars} characters.
- contract.output must remain a requirement to emit one fenced python block.

Useful levers, in rough order of value:
1. Add the run_tests tool (one extra turn) — the only lever that gives the model
   ground-truth feedback and reliably fixes wrong code.
2. Remove unnecessary instructions; shorter, focused prompts often win on a 9B model.
3. Add one short planning hop only if failures show the model rushed the spec.
4. Adjust budget only when the failure mode is truncation or wasted turns.
Every sentence must change behaviour on this task family.
""".strip()


def _try_json(blob: str) -> dict | None:
    for candidate in (blob, re.sub(r",\s*([}\]])", r"\1", blob)):
        try:
            obj = json.loads(candidate)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict) and "role" in obj and "contract" in obj:
            return obj
    return None


def _extract_json(text: str) -> dict | None:
    """Find a harness object even when the teacher reasons around it.

    The teacher often writes analysis containing braces (e.g. a dict literal)
    before the real JSON. So we try fenced blocks first, then every balanced
    brace span, and keep the one that looks like a harness.
    """
    text = agent.strip_think(text)

    for m in re.finditer(r"```(?:json)?\s*(.*?)```", text, re.S | re.I):
        obj = _try_json(m.group(1).strip())
        if obj is not None:
            return obj

    # Balanced-brace scan; handles nested objects and surrounding prose.
    starts: list[int] = []
    depth = 0
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                starts.append(i)
            depth += 1
        elif ch == "}" and depth:
            depth -= 1
            if depth == 0:
                obj = _try_json(text[starts[-1]:i + 1])
                if obj is not None:
                    return obj
    return None


def build_prompt(incumbent: dict, history: list[dict], failures: list[dict], cfg: dict,
                 probes: list[dict] | None = None) -> str:
    loop = cfg["loop"]
    rules = RULES.format(max_diff=loop["max_diff_fields"],
                         max_chars=loop["max_prompt_chars"])
    hist = []
    for h in history[-4:]:
        hist.append({
            "harness": h.get("harness", {}).get("version"),
            "wins": h.get("wins"), "losses": h.get("losses"),
            "score": h.get("score"), "accepted": h.get("accepted"),
            "reason": h.get("reason"),
        })
    fails = []
    for f in failures[:12]:
        fails.append({
            "title": f.get("title"),
            "prompt": f.get("prompt", "")[:600],
            "error_class": f.get("error_class"),
            "model_code": (f.get("code") or "")[:700],
        })
    probe_block = ""
    if probes:
        probe_block = (
            "\n\nENGINEERING PROBES (same dev split, measured; these are evidence, "
            "not a mandate to copy them):\n"
            + json.dumps(probes[-6:], indent=2)
        )
    return (
        f"{rules}\n\n"
        f"CURRENT HARNESS:\n{json.dumps(incumbent, indent=2)}\n\n"
        f"RECENT HISTORY:\n{json.dumps(hist, indent=2)}\n\n"
        f"FAILING TASKS:\n{json.dumps(fails, indent=2)}"
        f"{probe_block}\n\n"
        "Return the improved harness JSON now."
    )


def propose(cfg: dict, incumbent: dict, history: list[dict], failures: list[dict],
            version: str, probes: list[dict] | None = None) -> tuple[dict | None, str, list[str]]:
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler
    model, tok = agent.load_model(cfg["paths"]["teacher"])
    prompt_text = build_prompt(incumbent, history, failures, cfg, probes=probes)
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt_text}]
    prompt = tok.apply_chat_template(messages, add_generation_prompt=True, tokenize=False)
    # Force JSON mode: the reasoning model otherwise spends the whole budget
    # deliberating and never emits an object. The "{" is a prefill.
    prompt = prompt + "{"
    mx.random.seed(int(cfg["teacher"]["seed"]))
    sampler = make_sampler(
        temp=float(cfg["teacher"]["temperature"]),
        top_p=float(cfg["teacher"]["top_p"]),
    )
    raw = generate(
        model, tok, prompt=prompt,
        max_tokens=int(cfg["teacher"]["max_output_tokens"]),
        sampler=sampler,
        verbose=False,
    )

    candidate = _extract_json(raw)
    if candidate is None:
        # The prefill means the continuation usually starts with `"version"`.
        candidate = _extract_json("{" + raw)
    if candidate is None:
        _release(model)
        return None, raw, ["teacher did not return parseable JSON"]

    candidate["version"] = version
    ok, errors = harness_mod.validate(candidate, incumbent=incumbent, cfg=cfg)
    if not ok:
        _release(model)
        return None, raw, errors
    _release(model)
    return candidate, raw, []


# ── H2.1: parallel propose / compose ────────────────────────────────────────

PPC_INV = """
You are an INVARIANT candidate. Change how the agent works, not what it knows:
role, contract, workflow hops, tools, selection policy, or budget. Prefer ONE
surgical change that a specific failure in the evidence justifies. Do not add
task ids, test names, hidden-test references, or task-specific constants.
""".strip()

PPC_DOM = """
You are a DOMAIN candidate. Add task-family knowledge that generalizes across
tasks: e.g. lowercase before splitting words; sort intervals by start before
merging; handle empty input; preserve a previous helper when adding a function.
Do not add task ids, test names, hidden-test references, or task-specific
constants. Keep the change short enough for a 9B model to follow.
""".strip()


def _release(model=None):
    try:
        del model
    except Exception:
        pass
    gc.collect()
    try:
        mx.clear_cache()
    except Exception:
        pass


def _ppc_prompt(base: dict, failures: list[dict], spec: dict, lessons: list | None) -> str:
    dim = spec["dim"]
    block = PPC_INV if dim == "INV" else PPC_DOM
    fails = []
    for f in failures[:12]:
        fails.append({
            "title": f.get("title"),
            "prompt": f.get("prompt", "")[:500],
            "error_class": f.get("error_class"),
            "model_code": (f.get("code") or "")[:600],
        })
    lesson_block = ""
    if lessons:
        from .library import Library
        lesson_block = "\n\n" + Library.render(lessons)
    return (
        f"You are adapting a local coding agent's harness on a frozen task suite.\n"
        f"{block}\n\n"
        f"Return ONLY a JSON object with exactly these keys:\n"
        f"version, role, contract, hops, tools, selection, budget\n\n"
        f"You are candidate {spec['index']} on the {dim} dimension.\n\n"
        f"CURRENT HARNESS:\n{json.dumps(base, indent=2)}\n\n"
        f"FAILING TASKS (symptoms only; no test source):\n{json.dumps(fails, indent=2)}"
        f"{lesson_block}\n\n"
        f"Return the improved harness JSON now."
    )


def propose_ppc_many(cfg: dict, base: dict, failures: list[dict], specs: list[dict],
                     *, lessons: list | None = None, round_name: str = "h2") -> list[tuple]:
    """Load the teacher once and generate one candidate per spec."""
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler
    model, tok = agent.load_model(cfg["paths"]["teacher"])
    out = []
    for spec in specs:
        t0 = time.time()
        prompt_text = _ppc_prompt(base, failures, spec, lessons)
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt_text}]
        prompt = tok.apply_chat_template(messages, add_generation_prompt=True,
                                         tokenize=False) + "{"
        mx.random.seed(int(cfg["teacher"]["seed"]) + 1000 + spec["index"]
                       + (0 if spec["dim"] == "INV" else 100))
        sampler = make_sampler(temp=float(cfg["teacher"]["temperature"]),
                               top_p=float(cfg["teacher"]["top_p"]))
        raw = generate(model, tok, prompt=prompt,
                       max_tokens=int(cfg["teacher"]["max_output_tokens"]),
                       sampler=sampler, verbose=False)
        cand = _extract_json(raw) or _extract_json("{" + raw)
        meta = {
            "dim": spec["dim"], "index": spec["index"],
            "tokens_in": len(tok.encode(prompt)),
            "tokens_out": len(tok.encode(raw)),
            "wall_s": round(time.time() - t0, 3),
            "raw_chars": len(raw),
        }
        if cand is None:
            meta["error"] = "teacher did not return parseable JSON"
            out.append((None, meta))
            continue
        out.append((cand, meta))
    _release(model)
    return out


def compose_ppc_many(cfg: dict, base: dict, candidates: dict[str, dict],
                     variants: dict[str, dict], cue_table: list[dict],
                     *, lessons: list | None = None,
                     round_name: str = "h2") -> dict[str, tuple]:
    """Load the teacher once and compose one harness per table arm."""
    from mlx_lm import generate
    from mlx_lm.sample_utils import make_sampler
    from . import ppc
    model, tok = agent.load_model(cfg["paths"]["teacher"])
    out = {}
    for arm, variant in variants.items():
        t0 = time.time()
        table = ppc.render_table(variant)
        cue_block = ""
        if arm == "real" and cue_table:
            cue_block = ("\n\nMEASURED CUE → HARNESS TABLE (use it to choose a "
                         "harness when the failure signature matches):\n"
                         + json.dumps(cue_table, indent=2))
        lesson_block = ""
        if lessons:
            from .library import Library
            lesson_block = "\n\n" + Library.render(lessons)
        mission = (
            "You are composing THE final harness from a base and several candidate "
            "harnesses. You may MERGE edits, ADOPT one candidate wholesale, or KEEP "
            "BASE. Do not concatenate conflicting instructions.\n\n"
            "The table below is measured on the same dev tasks. Use task-level "
            "contrasts, not just aggregate scores. Every decision must cite a task "
            "or a repeated pattern. Do not mention task ids, tests, holdout, or eval "
            "sets in the harness.\n\n"
            f"BASE HARNESS:\n{json.dumps(base, indent=2)}\n\n"
            f"CANDIDATE HARNESSES:\n{json.dumps(candidates, indent=2)}\n\n"
            f"CONTRAST TABLE:\n{table}{cue_block}{lesson_block}\n\n"
            "Return ONLY the final harness JSON with keys: version, role, contract, "
            "hops, tools, selection, budget."
        )
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": mission}]
        prompt = tok.apply_chat_template(messages, add_generation_prompt=True,
                                         tokenize=False) + "{"
        mx.random.seed(int(cfg["teacher"]["seed"]) + 4000
                       + list(variants).index(arm))
        sampler = make_sampler(temp=float(cfg["teacher"]["temperature"]),
                               top_p=float(cfg["teacher"]["top_p"]))
        raw = generate(model, tok, prompt=prompt,
                       max_tokens=int(cfg["teacher"]["max_output_tokens"]),
                       sampler=sampler, verbose=False)
        cand = _extract_json(raw) or _extract_json("{" + raw)
        meta = {
            "arm": arm, "tokens_in": len(tok.encode(prompt)),
            "tokens_out": len(tok.encode(raw)),
            "wall_s": round(time.time() - t0, 3),
            "raw_chars": len(raw),
        }
        if cand is None:
            meta["error"] = "teacher did not return parseable JSON"
            out[arm] = (None, meta)
        else:
            out[arm] = (cand, meta)
    _release(model)
    return out
