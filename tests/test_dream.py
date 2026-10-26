"""Deterministic checks for Dream replay and its report."""
import json
import tempfile
import unittest
from pathlib import Path

from forge_rsi import dream


def _run(run_id="r"):
    return {
        "run_id": run_id,
        "harness": {"version": "h0"},
        "tasks": [
            {"task_id": "t1", "passed": True, "candidates": [
                {"code": "a", "passed": True, "tokens_out": 10},
                {"code": "b", "passed": False, "tokens_out": 10},
            ]},
            {"task_id": "t2", "passed": False, "candidates": [
                {"code": "c", "passed": False, "tokens_out": 10},
                {"code": "d", "passed": True, "tokens_out": 10},
            ]},
        ],
    }


class DreamTest(unittest.TestCase):
    def test_policy_replay_separates_first_from_test_gated(self):
        result = dream.evaluate(_run())
        by = {p["policy"]: p for p in result["policies"]}
        self.assertEqual((by["first"]["passed"], by["first"]["n"]), (1, 2))
        self.assertEqual(by["test_gated"]["passed"], 2)
        self.assertEqual(result["winner"], "test_gated")
        self.assertIn("oracle", result["note"])

    def test_load_result_ignores_an_eval_run_with_the_same_stem(self):
        with tempfile.TemporaryDirectory() as td:
            runs = Path(td) / "runs"
            runs.mkdir()
            cfg = {"paths": {"runs": str(runs), "reports": str(Path(td) / "reports")}}
            eval_run = {"run_id": "dream_live", "split": "dev", "tasks": []}
            (runs / "dream_live.json").write_text(json.dumps(eval_run))
            replay = dream.evaluate(_run("dream_live"))
            (runs / "dream_dream_live.json").write_text(json.dumps(replay))
            got = dream.load_result(cfg, "dream_live")
            self.assertEqual(got["winner"], "test_gated")
            path, _ = dream.write_report(cfg, "dream_live")
            text = path.read_text()
            self.assertIn("test_gated", text)
            self.assertNotIn(str(Path(td)), text)


if __name__ == "__main__":
    unittest.main()
