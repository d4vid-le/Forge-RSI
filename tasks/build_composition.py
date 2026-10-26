#!/usr/bin/env python3
"""Build the composition probe.

Each task requires BOTH word_freq and merge_intervals in one solution. The
composition experiment asks whether the parts still work when the whole is
asked for under different gate configurations.

Run: python3 tasks/build_composition.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "composition"

REF = '''def word_freq(text):
    counts = {}
    for word in text.lower().split():
        counts[word] = counts.get(word, 0) + 1
    return counts


def merge_intervals(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged
'''

PROMPT = (
    "Write two functions in one fenced ```python block:\n"
    "1. `word_freq(text: str) -> dict` returning a dict mapping each "
    "lowercased whitespace-separated word to its count.\n"
    "2. `merge_intervals(intervals: list) -> list` merging overlapping or "
    "touching closed [start, end] intervals and returning a sorted list.\n"
    "Include both functions. No prose outside the block."
)

CASES = [
    ("comp_01", "a b a", [[1, 3], [2, 6]]),
    ("comp_02", "Hi hi HI", [[1, 3], [3, 5]]),
    ("comp_03", "red blue red", [[5, 6], [1, 2]]),
    ("comp_04", "x y z x", [[1, 10], [2, 3]]),
    ("comp_05", "one two one two one", [[-5, -1], [-3, 0]]),
]

TESTS = '''
import unittest
from solution import word_freq, merge_intervals

class T(unittest.TestCase):
    def test_word_basic(self):
        self.assertEqual(word_freq({text!r}), {wf})
    def test_word_case(self):
        self.assertEqual(word_freq("Hi hi HI"), {{"hi": 3}})
    def test_merge_overlap(self):
        self.assertEqual(merge_intervals({intervals!r}), {mi})
    def test_merge_touch(self):
        self.assertEqual(merge_intervals([[1, 3], [3, 5]]), [[1, 5]])
'''


def verify(ref: str, tests: str) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "solution.py").write_text(ref + "\n")
        (td / "test_solution.py").write_text(tests + "\n")
        p = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_solution"],
                           cwd=td, capture_output=True, text=True, timeout=20)
        return p.returncode == 0, (p.stdout + p.stderr)[-1500:]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    for tid, text, intervals in CASES:
        counts: dict[str, int] = {}
        for w in text.lower().split():
            counts[w] = counts.get(w, 0) + 1
        ivs = sorted(intervals, key=lambda x: x[0])
        merged = [list(ivs[0])]
        for s, e in ivs[1:]:
            if s <= merged[-1][1]:
                merged[-1][1] = max(merged[-1][1], e)
            else:
                merged.append([s, e])
        tests = TESTS.format(text=text, wf=repr(counts), intervals=intervals,
                             mi=repr(merged)).strip()
        ok, out = verify(REF, tests)
        if not ok:
            print(f"[FAIL] {tid}\n{out}")
            return 1
        task = {
            "id": tid, "title": "word_freq + merge_intervals",
            "prompt": PROMPT, "tests": tests, "entry": "solution.py",
            "timeout_s": 20, "tags": ["composition", "word_freq", "merge_intervals"],
            "difficulty": "hard",
        }
        (OUT / f"{tid}.json").write_text(json.dumps(task, indent=2) + "\n")
        print(f"[ok] {tid}")
    print(f"wrote {len(CASES)} composition tasks -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
