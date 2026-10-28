"""End-to-end deterministic checks for the H2.1 orchestrator (no model)."""
import json
import tempfile
import unittest
from pathlib import Path

from forge_rsi import harness, ppc


def _h(version, role="You are a Python engineer.", tools=None):
    return {
        "version": version, "role": role,
        "contract": {"output": "one fenced python block"},
        "hops": [{"name": "write", "instruction": "write the function"}],
        "tools": tools or [], "selection": {"policy": "first"},
        "budget": {"max_turns": 1, "max_output_tokens": 400},
    }


class PPCRunTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cfg = {
            "paths": {
                "project": str(root), "tasks": str(root / "tasks"),
                "runs": str(root / "runs"), "harness": str(root / "harness"),
                "reports": str(root / "reports"),
            },
            "loop": {"max_diff_fields": 3, "max_prompt_chars": 7200,
                     "score_tolerance": 0.05, "cost_ceiling": 1.5},
            "teacher": {"seed": 1, "temperature": 0.3, "top_p": 0.95,
                        "max_output_tokens": 500},
        }
        for p in ("tasks/dev_hard", "runs", "harness", "reports"):
            (root / p).mkdir(parents=True, exist_ok=True)
        for i in (1, 2):
            task = {
                "id": f"h{i}", "title": f"task {i}", "prompt": f"Write `f{i}`.",
                "tests": "import unittest\n", "entry": "solution.py",
                "timeout_s": 20, "tags": ["word_freq"], "difficulty": "hard",
            }
            (root / "tasks" / "dev_hard" / f"h{i}.json").write_text(json.dumps(task))
        harness.save(_h("h0"), root / "harness" / "h0_baseline.json")

    def tearDown(self):
        self.tmp.cleanup()

    def test_run_writes_contrast_and_picks_composer(self):
        calls = {"eval": 0}

        def eval_fn(path, split, run_id):
            calls["eval"] += 1
            name = Path(path).stem
            if name in ("h0_baseline", "h0"):
                passed = 0
            elif name.endswith("inv1"):
                passed = 1
            else:
                passed = 2
            tasks = [{"task_id": "h1", "passed": True, "error_class": "none",
                      "tokens_out": 10, "turns": 1, "wall_s": 0.1},
                     {"task_id": "h2", "passed": passed == 2,
                      "error_class": "none" if passed == 2 else "assertion",
                      "tokens_out": 10, "turns": 1, "wall_s": 0.1}]
            return {"run_id": run_id, "split": split, "harness": _h(name),
                    "summary": {"n": 2, "passed": passed, "score": passed / 2,
                                "tokens_in": 20, "tokens_out": 20, "wall_s": 0.2,
                                "cost_per_solved": 20},
                    "tasks": tasks}

        def propose_many(cfg, base, failures, specs, **kw):
            out = []
            for s in specs:
                h = _h(f"{s['dim'].lower()}{s['index']}",
                       role=f"You are candidate {s['dim']}{s['index']}.")
                out.append((h, {"dim": s["dim"], "index": s["index"],
                                "tokens_in": 1, "tokens_out": 1, "wall_s": 0.1}))
            return out

        def compose_many(cfg, base, candidates, variant, arm, cues, **kw):
            return _h(f"{arm}", role="You are the composed harness."), {
                "arm": arm, "tokens_in": 1, "tokens_out": 1, "wall_s": 0.1}

        result = ppc.run(self.cfg, "t", k=2, arms=["real"], split="dev_hard",
                         propose_many=propose_many, eval_fn=eval_fn,
                         compose_many=compose_many, reuse=False)
        self.assertEqual(result["winner"], "real")
        self.assertEqual(result["arms_result"]["real"]["stats"]["candidate_score"], 1.0)
        self.assertTrue(result["contrast"]["cue_table"])
        out = Path(self.cfg["paths"]["runs"])
        self.assertTrue((out / "t_ppc.json").exists())
        self.assertTrue((out.parent / "harness" / "cues" / "t.json").exists())
        self.assertEqual(calls["eval"], 6)  # base + 4 candidates + 1 arm


if __name__ == "__main__":
    unittest.main()
