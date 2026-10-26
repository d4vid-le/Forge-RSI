"""Deterministic checks for private-holdout generation and rotation."""
import json
import tempfile
import unittest
from pathlib import Path

from forge_rsi import holdout


class HoldoutTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.cfg = {"paths": {"tasks": str(root / "tasks"),
                              "reports": str(root / "reports")}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_generate_is_unique_and_verified(self):
        tasks = holdout.generate(count=6, seed=7)
        self.assertEqual(len(tasks), 6)
        self.assertEqual(len({t["id"] for t in tasks}), 6)
        for t in tasks:
            self.assertIn("private_holdout", t["tags"])
            self.assertIn("from solution import", t["tests"])
            self.assertNotIn("_ref", t)

    def test_rotate_status_and_archive(self):
        first = holdout.rotate(self.cfg, count=6, seed=11)
        self.assertEqual(first["count"], 6)
        self.assertFalse(first["archived"])
        st = holdout.status(self.cfg)
        self.assertTrue(st["exists"])
        self.assertEqual(st["count"], 6)
        self.assertEqual(st["manifest"]["seed"], 11)
        self.assertTrue(st["manifest"]["blind"])
        self.assertIsNotNone(st["combined_sha256"])

        second = holdout.rotate(self.cfg, count=6, seed=12, force=True)
        self.assertEqual(second["count"], 6)
        self.assertTrue(second["archived"])
        st2 = holdout.status(self.cfg)
        self.assertEqual(st2["manifest"]["seed"], 12)
        self.assertEqual(len(st2["archives"]), 1)
        self.assertEqual(st2["latest_archive"], second["archived"])
        self.assertTrue(Path(second["report"]).exists())

    def test_requires_force_to_replace(self):
        holdout.rotate(self.cfg, count=6, seed=11)
        with self.assertRaises(holdout.HoldoutError):
            holdout.rotate(self.cfg, count=6, seed=12)

    def test_report_has_no_prompts_or_tests(self):
        result = holdout.rotate(self.cfg, count=6, seed=11)
        text = Path(result["report"]).read_text()
        self.assertIn("Private holdout rotation", text)
        self.assertNotIn("assertEqual", text)
        self.assertNotIn("Write `", text)
        self.assertIn(result["combined_sha256"], text)

    def test_count_bounds(self):
        with self.assertRaises(holdout.HoldoutError):
            holdout.generate(count=2, seed=1)
        with self.assertRaises(holdout.HoldoutError):
            holdout.generate(count=41, seed=1)


if __name__ == "__main__":
    unittest.main()
