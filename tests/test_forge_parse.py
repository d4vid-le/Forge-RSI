"""Deterministic checks for the mlx_lm log parser (stdlib unittest).

Run: python -m unittest discover -s tests
"""
import unittest

from pipeline.forge import parse_train_log

COMPACT = (
    "\x1b[1;35m  iter\x1b[0m   train_loss     tok/s     tokens\n"
    "     1    val 1.636    0.20s\n"
    "     5    val 0.682    0.03s\n"
    "  \x1b[1;32msave\x1b[0m 0000005_adapters.safetensors\n"
    "    10    val 0.281    0.03s\n"
    "    \x1b[38;5;244m 10\x1b[0m    \x1b[1;32m1.045 ▼\x1b[0m    \x1b[1;32m  424\x1b[0m"
    "    \x1b[38;5;244m  0.6k\x1b[0m\n"
    "train ██████████████████████████████ 100% ·    10/10\n"
)

OLD = (
    "Iter 1: Train loss 2.500, Learning Rate 1.000e-04, It/sec 1.1, Tokens/sec 120.0\n"
    "Iter 1: Val loss 2.100, Val took 1.2s\n"
)

FAILED = "Traceback (most recent call last):\nValueError: bad data\n"


class ParseTrainLogTest(unittest.TestCase):
    def test_compact_format(self):
        p = parse_train_log(COMPACT)
        self.assertEqual([t["iter"] for t in p["train"]], [10])
        self.assertAlmostEqual(p["train"][0]["loss"], 1.045)
        self.assertAlmostEqual(p["train"][0]["tok_sec"], 424.0)
        self.assertEqual([v["iter"] for v in p["val"]], [1, 5, 10])
        self.assertAlmostEqual(p["val"][-1]["loss"], 0.281)
        self.assertTrue(p["finished"])
        self.assertIsNone(p["error"])
        self.assertNotIn("\x1b", "\n".join(p["tail"]))

    def test_old_format(self):
        p = parse_train_log(OLD)
        self.assertEqual(len(p["train"]), 1)
        self.assertAlmostEqual(p["train"][0]["loss"], 2.5)
        self.assertAlmostEqual(p["train"][0]["lr"], 1e-4)
        self.assertEqual(len(p["val"]), 1)
        self.assertFalse(p["finished"])

    def test_empty_log_invents_nothing(self):
        p = parse_train_log("")
        self.assertEqual(p["train"], [])
        self.assertEqual(p["val"], [])
        self.assertFalse(p["finished"])

    def test_traceback_is_reported(self):
        p = parse_train_log(FAILED)
        self.assertEqual(p["error"], "traceback in log")


if __name__ == "__main__":
    unittest.main()
