"""Deterministic checks for gap detection and verified corpus mining."""
import json
import tempfile
import unittest
from pathlib import Path

from forge_rsi import gaps

HARNESS = {
    "version": "h0",
    "role": "You are a Python engineer.",
    "contract": {"output": "one fenced python block"},
    "hops": [],
    "tools": [],
    "selection": {"policy": "first"},
    "budget": {"max_turns": 1, "max_output_tokens": 400},
}

TASK = {
    "id": "skill_1",
    "title": "count words",
    "prompt": "Write `count_words(text: str) -> dict` returning word counts.",
    "tests": (
        "import unittest\n"
        "from solution import count_words\n\n"
        "class T(unittest.TestCase):\n"
        "    def test_one(self):\n"
        "        self.assertEqual(count_words('a b a'), {'a': 2, 'b': 1})\n"
    ),
    "entry": "solution.py",
    "timeout_s": 10,
    "tags": ["skill_probe", "word_freq"],
    "difficulty": "easy",
}

GOOD = "def count_words(text):\n    out = {}\n    for w in text.split():\n        out[w] = out.get(w, 0) + 1\n    return out\n"
BAD = "def count_words(text):\n    return {}\n"


class GapTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cfg = {"paths": {
            "tasks": str(root / "tasks"),
            "runs": str(root / "runs"),
            "reports": str(root / "reports"),
            "curriculum": str(root / "curriculum"),
            "harness": str(root / "harness"),
        }}
        for key in ("tasks", "runs", "reports", "harness"):
            (root / key).mkdir(parents=True, exist_ok=True)
        (root / "tasks" / "skills").mkdir(parents=True, exist_ok=True)
        (root / "tasks" / "skills" / "skill_1.json").write_text(json.dumps(TASK))
        (root / "harness" / "h0_baseline.json").write_text(json.dumps(HARNESS))
        self.write_run("base", "skills", [
            {"task_id": "skill_1", "passed": False, "error_class": "assertion",
             "code": BAD, "tokens_out": 10},
        ], passed=0)
        self.write_run("later", "skills", [
            {"task_id": "skill_1", "passed": True, "error_class": "none",
             "code": GOOD, "tokens_out": 20},
        ], passed=1, started="2026-10-26T01:00:01")

    def tearDown(self):
        self.tmp.cleanup()

    def write_run(self, name, split, tasks, passed, started="2026-10-26T01:00:00"):
        run = {
            "run_id": name, "split": split, "model": "local-model",
            "started_at": started, "harness": HARNESS,
            "summary": {"n": len(tasks), "passed": passed},
            "tasks": tasks,
        }
        Path(self.cfg["paths"]["runs"], f"{name}.json").write_text(json.dumps(run))

    def test_detect_clusters_failures(self):
        report = gaps.detect(self.cfg, "base")
        self.assertEqual(report["split"], "skills")
        self.assertEqual(len(report["clusters"]), 1)
        c = report["clusters"][0]
        self.assertEqual(c["key"], "word_freq")
        self.assertEqual((c["failed"], c["total"]), (1, 1))
        self.assertTrue(Path(self.cfg["paths"]["reports"], "gaps.md").exists())

    def test_mine_writes_only_reverified_rows(self):
        report = gaps.mine(self.cfg, "base", min_rows=1)
        corpus = report["corpus"]
        self.assertEqual(corpus["rows"], 2)
        self.assertEqual(corpus["by_kind"], {"success": 1, "repair": 1})
        self.assertEqual(corpus["missing"], [])
        path = Path(corpus["file"])
        rows = [json.loads(line) for line in path.read_text().splitlines()]
        self.assertEqual({r["meta"]["kind"] for r in rows}, {"success", "repair"})
        for row in rows:
            self.assertNotIn("skill_1", row["messages"][1]["content"])
            self.assertTrue(row["meta"]["verified"])

    def test_holdout_is_refused_and_never_mined(self):
        hold = dict(TASK, id="hold_1", tags=["holdout"])
        (Path(self.cfg["paths"]["tasks"]) / "holdout").mkdir()
        (Path(self.cfg["paths"]["tasks"]) / "holdout" / "hold_1.json").write_text(
            json.dumps(hold))
        self.write_run("hold", "holdout", [
            {"task_id": "hold_1", "passed": False, "error_class": "assertion",
             "code": BAD, "tokens_out": 1},
        ], passed=0, started="2026-10-26T01:00:02")
        with self.assertRaises(gaps.GapError):
            gaps.detect(self.cfg, "hold")
        report = gaps.mine(self.cfg, "base", min_rows=1)
        ids = {r["meta"]["task_id"] for r in
               (json.loads(x) for x in
                Path(report["corpus"]["file"]).read_text().splitlines())}
        self.assertNotIn("hold_1", ids)

    def test_no_verified_pass_reports_missing(self):
        self.write_run("later", "skills", [
            {"task_id": "skill_1", "passed": True, "error_class": "none",
             "code": "def count_words(text):\n    return 'wrong'\n",
             "tokens_out": 20},
        ], passed=1, started="2026-10-26T01:00:01")
        with self.assertRaises(gaps.GapError):
            gaps.mine(self.cfg, "base", min_rows=1)
        report = json.loads(Path(self.cfg["paths"]["runs"], "gaps_base.json").read_text())
        self.assertEqual(len(report["corpus"]["missing"]), 1)
        self.assertEqual(report["corpus"]["rows"], 0)


if __name__ == "__main__":
    unittest.main()
