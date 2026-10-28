"""Deterministic checks for the H2 experiment layer (stdlib unittest)."""
import json
import tempfile
import unittest
from pathlib import Path

from forge_rsi import ledger, library, plans, ppc, prereg


HARNESS = {
    "version": "h0", "role": "You are a Python engineer.",
    "contract": {"output": "one fenced python block"},
    "hops": [{"name": "write", "instruction": "write the function"}],
    "tools": [], "selection": {"policy": "first"},
    "budget": {"max_turns": 1, "max_output_tokens": 400},
}


def _run(run_id, tasks, score=None):
    n = len(tasks)
    passed = sum(1 for t in tasks if t["passed"])
    return {
        "run_id": run_id, "split": "dev", "harness": dict(HARNESS),
        "summary": {"n": n, "passed": passed, "score": score if score is not None else passed / n,
                    "tokens_in": 10, "tokens_out": 20, "wall_s": 1.0,
                    "cost_per_solved": 20},
        "tasks": tasks,
    }


class LedgerTest(unittest.TestCase):
    def test_gain_per_cost(self):
        led = ledger.Ledger("t")
        led.add("proposal", "p", calls=2, tokens_in=100, tokens_out=50, wall_s=4)
        self.assertEqual(led.calls, 2)
        self.assertEqual(led.tokens, 150)
        g = led.gain_per(3)
        self.assertAlmostEqual(g["per_call"], 1.5)
        self.assertAlmostEqual(g["per_1k_tokens"], 20.0)
        self.assertAlmostEqual(g["per_wall_s"], 0.75)


class PreregTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cfg = {"paths": {"runs": str(Path(self.tmp.name) / "runs"),
                              "reports": str(Path(self.tmp.name) / "reports"),
                              "harness": str(Path(self.tmp.name) / "harness")}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_private_is_sealed_until_winner_hash(self):
        rec = prereg.create(self.cfg, "t", k=2)
        self.assertTrue(rec["seal"]["sealed"])
        with self.assertRaises(prereg.PreregError):
            prereg.guard_split(self.cfg, "t", "private_holdout", "abc")
        prereg.unseal(self.cfg, "t", "abc")
        prereg.guard_split(self.cfg, "t", "private_holdout", "abc")
        with self.assertRaises(prereg.PreregError):
            prereg.guard_split(self.cfg, "t", "private_holdout", "wrong")

    def test_paired_stats(self):
        base = _run("b", [dict(task_id=f"t{i}", passed=True) for i in range(4)])
        cand = _run("c", [dict(task_id=f"t{i}", passed=i >= 2) for i in range(4)])
        s = prereg.paired_stats(base, cand, bootstrap=200)
        self.assertEqual((s["wins"], s["losses"], s["ties"]), (0, 2, 2))
        self.assertEqual(s["delta"], -0.5)
        self.assertGreaterEqual(s["sign_test_p"], 0.5)


class LibraryTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lib = library.Library(Path(self.tmp.name) / "lessons.jsonl")
        self.word = self.lib.add(library.Lesson(
            cue={"skill": "word_freq", "error_class": "assertion"},
            lesson="lowercase before splitting", evidence={"passes": 8, "n": 10},
            confidence=library.wilson_lower(8, 10), source_split="dev"))
        self.merge = self.lib.add(library.Lesson(
            cue={"skill": "merge_intervals", "error_class": "assertion"},
            lesson="sort by start before merging", evidence={"passes": 7, "n": 10},
            confidence=library.wilson_lower(7, 10), source_split="dev"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_private_lesson_is_refused(self):
        with self.assertRaises(PermissionError):
            self.lib.add(library.Lesson(cue={}, lesson="x", evidence={},
                                        confidence=1.0, source_split="private_holdout"))

    def test_retrieval_is_capped_and_thresholded(self):
        got = self.lib.retrieve({"skill": "word_freq", "error_class": "assertion"}, limit=1)
        self.assertEqual([x.id for x in got], [self.word.id])
        self.assertEqual(len(self.lib.retrieve({"skill": "word_freq"}, limit=2)), 1)
        self.assertEqual(self.lib.retrieve({"skill": "nope"}, threshold=0.5), [])

    def test_build_from_cue_table_uses_measured_confidence(self):
        cues = [{
            "cue": {"skill": "word_freq", "error_class": "assertion"},
            "harness": "h2a_inv1",
            "confidence": 0.99,
            "evidence": {"n": 4, "base_passes": 0, "candidate_passes": 3,
                         "task_ids": ["t1", "t2", "t3", "t4"]},
            "lesson": "lowercase first",
        }]
        lessons, labels = self.lib.build_from_contrast(cues, source_split="dev_hard")
        self.assertEqual(len(lessons), 1)
        self.assertAlmostEqual(lessons[0].confidence,
                               library.wilson_lower(3, 4), places=4)
        self.assertEqual(labels[0]["lesson_id"], lessons[0].id)

    def test_retrieval_benchmark_conditions(self):
        labeled = [
            {"cue": {"skill": "word_freq", "error_class": "assertion"},
             "lesson_id": self.word.id},
            {"cue": {"skill": "merge_intervals", "error_class": "assertion"},
             "lesson_id": self.merge.id},
        ]
        b = self.lib.benchmark(labeled, limits=(1, 2, "all"))
        self.assertEqual(b["limits"]["1"]["with"]["precision"], 1.0)
        self.assertGreaterEqual(b["limits"]["1"]["with"]["mrr"], 1.0)
        self.assertEqual(b["limits"]["1"]["without"]["precision"], 0.0)


class PPCTest(unittest.TestCase):
    def test_contrast_and_cue_table(self):
        tasks = {
            "w1": {"id": "w1", "title": "count words", "tags": ["word_freq"]},
            "w2": {"id": "w2", "title": "count words", "tags": ["word_freq"]},
            "m1": {"id": "m1", "title": "merge intervals", "tags": ["merge_intervals"]},
            "m2": {"id": "m2", "title": "merge intervals", "tags": ["merge_intervals"]},
        }
        base = _run("base", [
            dict(task_id="w1", passed=False, error_class="assertion", tokens_out=1),
            dict(task_id="w2", passed=False, error_class="assertion", tokens_out=1),
            dict(task_id="m1", passed=False, error_class="assertion", tokens_out=1),
            dict(task_id="m2", passed=False, error_class="assertion", tokens_out=1),
        ])
        c1 = _run("c1", [
            dict(task_id="w1", passed=True, error_class="none", tokens_out=2),
            dict(task_id="w2", passed=True, error_class="none", tokens_out=2),
            dict(task_id="m1", passed=False, error_class="assertion", tokens_out=2),
            dict(task_id="m2", passed=False, error_class="assertion", tokens_out=2),
        ])
        c2 = _run("c2", [
            dict(task_id="w1", passed=False, error_class="assertion", tokens_out=3),
            dict(task_id="w2", passed=False, error_class="assertion", tokens_out=3),
            dict(task_id="m1", passed=True, error_class="none", tokens_out=3),
            dict(task_id="m2", passed=True, error_class="none", tokens_out=3),
        ])
        con = ppc.contrast(base, {"inv1": c1, "dom1": c2}, tasks)
        self.assertEqual(con["disagreement"]["tasks_with_candidate_disagreement"], 4)
        cues = {c["cue"]["skill"]: c for c in con["cue_table"]}
        self.assertEqual(cues["word_freq"]["harness"], "inv1")
        self.assertEqual(cues["merge_intervals"]["harness"], "dom1")
        self.assertGreater(cues["word_freq"]["confidence"], 0.3)
        shuffled = ppc.table_variant(con, "shuffled", seed=1)
        self.assertEqual(shuffled["aggregates"], con["aggregates"])
        self.assertEqual(len(shuffled["rows"]), len(con["rows"]))
        none = ppc.table_variant(con, "none")
        self.assertEqual(none["rows"], [])

    def test_winner_tie_prefers_declared_order(self):
        a = _run("a", [dict(task_id="t1", passed=True)])
        b = _run("b", [dict(task_id="t1", passed=True)])
        name, _ = ppc.pick_winner({"real": a, "shuffled": b}, ["real", "shuffled"])
        self.assertEqual(name, "real")


class PlansTest(unittest.TestCase):
    TASK = {
        "id": "c1",
        "prompt": "Write both functions.",
        "tests": (
            "import unittest\n"
            "from solution import word_freq, merge_intervals\n\n"
            "class T(unittest.TestCase):\n"
            "    def test_word(self):\n"
            "        self.assertEqual(word_freq('a a'), {'a': 2})\n"
            "    def test_merge(self):\n"
            "        self.assertEqual(merge_intervals([[1, 2], [2, 3]]), [[1, 3]])\n"
        ),
    }

    def test_extract_function(self):
        code = "x = 1\n\ndef word_freq(text):\n    return {}\n\ndef other():\n    return 2\n"
        self.assertIn("def word_freq", plans.extract_function(code, "word_freq"))
        self.assertNotIn("def other", plans.extract_function(code, "word_freq"))

    def test_split_tests_by_function(self):
        w = plans.split_tests(self.TASK, {"word_freq"})
        self.assertIn("test_word", w)
        self.assertNotIn("test_merge", w)
        m = plans.split_tests(self.TASK, {"merge_intervals"})
        self.assertIn("test_merge", m)
        self.assertNotIn("test_word", m)


if __name__ == "__main__":
    unittest.main()
