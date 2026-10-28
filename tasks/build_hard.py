#!/usr/bin/env python3
"""Build the frozen dev_hard search split (20 tasks).

The original dev split is saturated by r1b (20/20). H2.1 needs a search set with
real headroom, so this split is deliberately harder: edge cases, wrapping,
rectangular matrices, parsing, and multi-step list work. Every reference is
verified before the task is written.

Run:
    python -m tasks.build_hard
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "dev_hard"
FREEZE = ROOT / "HARD_FREEZE.json"

TASKS: list[dict] = []


def task(tid, title, prompt, ref, tests, tags=None):
    TASKS.append(dict(id=tid, title=title, prompt=prompt.strip(), ref=ref.strip(),
                      tests=tests.strip(), tags=tags or []))


task("hard_001", "rle_encode",
     "Write `rle_encode(text: str) -> list` returning run-length encoding as a list of [character, count] pairs in order.",
     """
def rle_encode(text):
    out = []
    for ch in text:
        if out and out[-1][0] == ch:
            out[-1][1] += 1
        else:
            out.append([ch, 1])
    return out
""",
     """
import unittest
from solution import rle_encode

class T(unittest.TestCase):
    def test_runs(self):
        self.assertEqual(rle_encode("aaabbc"), [["a", 3], ["b", 2], ["c", 1]])
    def test_single(self):
        self.assertEqual(rle_encode("a"), [["a", 1]])
    def test_empty(self):
        self.assertEqual(rle_encode(""), [])
    def test_mixed(self):
        self.assertEqual(rle_encode("abba"), [["a", 1], ["b", 2], ["a", 1]])
""", ["strings"])

task("hard_002", "rle_decode",
     "Write `rle_decode(pairs: list) -> str` that expands [character, count] pairs back into a string.",
     """
def rle_decode(pairs):
    return "".join(ch * n for ch, n in pairs)
""",
     """
import unittest
from solution import rle_decode

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(rle_decode([["a", 3], ["b", 2]]), "aaabb")
    def test_empty(self):
        self.assertEqual(rle_decode([]), "")
    def test_zero(self):
        self.assertEqual(rle_decode([["x", 0], ["y", 2]]), "yy")
    def test_single(self):
        self.assertEqual(rle_decode([["z", 1]]), "z")
""", ["strings"])

task("hard_003", "merge_intervals",
     "Write `merge_intervals(intervals: list) -> list` that merges overlapping or touching closed intervals and returns the sorted result, including negative values.",
     """
def merge_intervals(intervals):
    if not intervals:
        return []
    ordered = sorted((list(x) for x in intervals), key=lambda x: (x[0], x[1]))
    out = [ordered[0]]
    for start, end in ordered[1:]:
        if start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return out
""",
     """
import unittest
from solution import merge_intervals

class T(unittest.TestCase):
    def test_overlap(self):
        self.assertEqual(merge_intervals([[1, 3], [2, 6]]), [[1, 6]])
    def test_touch_unsorted(self):
        self.assertEqual(merge_intervals([[5, 6], [1, 2], [2, 3], [3, 4]]), [[1, 4], [5, 6]])
    def test_negative(self):
        self.assertEqual(merge_intervals([[-5, -1], [-3, 0], [2, 2]]), [[-5, 0], [2, 2]])
    def test_empty(self):
        self.assertEqual(merge_intervals([]), [])
""", ["lists", "merge_intervals"])

task("hard_004", "word_freq",
     "Write `word_freq(text: str) -> dict` mapping each lowercased whitespace-separated token to its count. Punctuation stays part of the token.",
     """
def word_freq(text):
    out = {}
    for word in text.lower().split():
        out[word] = out.get(word, 0) + 1
    return out
""",
     """
import unittest
from solution import word_freq

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(word_freq("A a B"), {"a": 2, "b": 1})
    def test_punct(self):
        self.assertEqual(word_freq("a, a, b"), {"a,": 2, "b": 1})
    def test_empty(self):
        self.assertEqual(word_freq(""), {})
    def test_whitespace(self):
        self.assertEqual(word_freq("x  y\tx"), {"x": 2, "y": 1})
""", ["strings", "word_freq"])

task("hard_005", "top_k_words",
     "Write `top_k_words(text: str, k: int) -> list` returning the k most frequent lowercased tokens as (word, count) tuples, ties sorted alphabetically. If k is larger than the vocabulary, return all words.",
     """
def top_k_words(text, k):
    counts = {}
    for word in text.lower().split():
        counts[word] = counts.get(word, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return ranked[:max(0, k)]
""",
     """
import unittest
from solution import top_k_words

class T(unittest.TestCase):
    def test_rank(self):
        self.assertEqual(top_k_words("b a b c a b", 2), [("b", 3), ("a", 2)])
    def test_tie_alpha(self):
        self.assertEqual(top_k_words("z y x", 2), [("x", 1), ("y", 1)])
    def test_k_large(self):
        self.assertEqual(top_k_words("a b", 10), [("a", 1), ("b", 1)])
    def test_empty(self):
        self.assertEqual(top_k_words("", 3), [])
""", ["strings", "word_freq"])

task("hard_006", "parse_duration",
     "Write `parse_duration(text: str) -> int` that parses durations like `1h30m15s`, `45s`, or `2h` into seconds. An empty string or a malformed duration raises `ValueError`.",
     """
import re

def parse_duration(text):
    if not text:
        raise ValueError("empty duration")
    m = re.fullmatch(r"(?:(\\d+)h)?(?:(\\d+)m)?(?:(\\d+)s)?", text)
    if not m or not any(m.groups()):
        raise ValueError("bad duration")
    h, mnt, sec = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mnt * 60 + sec
""",
     """
import unittest
from solution import parse_duration

class T(unittest.TestCase):
    def test_full(self):
        self.assertEqual(parse_duration("1h30m15s"), 5415)
    def test_seconds(self):
        self.assertEqual(parse_duration("45s"), 45)
    def test_hours(self):
        self.assertEqual(parse_duration("2h"), 7200)
    def test_invalid(self):
        with self.assertRaises(ValueError):
            parse_duration("")
        with self.assertRaises(ValueError):
            parse_duration("soon")
""", ["parsing"])

task("hard_007", "chunk",
     "Write `chunk(items: list, size: int) -> list` splitting items into consecutive lists of length size; the last chunk may be shorter. Raise `ValueError` when size <= 0.",
     """
def chunk(items, size):
    if size <= 0:
        raise ValueError("size must be positive")
    return [items[i:i + size] for i in range(0, len(items), size)]
""",
     """
import unittest
from solution import chunk

class T(unittest.TestCase):
    def test_remainder(self):
        self.assertEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
    def test_exact(self):
        self.assertEqual(chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
    def test_empty(self):
        self.assertEqual(chunk([], 3), [])
    def test_invalid(self):
        with self.assertRaises(ValueError):
            chunk([1], 0)
""", ["lists"])

task("hard_008", "binary_search",
     "Write `binary_search(nums: list, target: int) -> int` returning an index of target in a sorted list, or -1 if absent. Duplicates may return any matching index.",
     """
def binary_search(nums, target):
    lo, hi = 0, len(nums) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if nums[mid] == target:
            return mid
        if nums[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return -1
""",
     """
import unittest
from solution import binary_search

class T(unittest.TestCase):
    def test_found(self):
        self.assertEqual(binary_search([1, 3, 5, 7], 5), 2)
    def test_duplicates(self):
        self.assertIn(binary_search([1, 2, 2, 2, 3], 2), [1, 2, 3])
    def test_missing(self):
        self.assertEqual(binary_search([1, 3, 5], 4), -1)
    def test_empty(self):
        self.assertEqual(binary_search([], 1), -1)
""", ["lists"])

task("hard_009", "flatten",
     "Write `flatten(items: list) -> list` that recursively flattens nested lists and tuples, preserving order. Strings are values, not sequences to flatten.",
     """
def flatten(items):
    out = []
    for x in items:
        if isinstance(x, (list, tuple)):
            out.extend(flatten(x))
        else:
            out.append(x)
    return out
""",
     """
import unittest
from solution import flatten

class T(unittest.TestCase):
    def test_nested(self):
        self.assertEqual(flatten([1, [2, [3, 4]], 5]), [1, 2, 3, 4, 5])
    def test_tuples(self):
        self.assertEqual(flatten([(1, 2), [3]]), [1, 2, 3])
    def test_empty(self):
        self.assertEqual(flatten([]), [])
    def test_strings(self):
        self.assertEqual(flatten(["ab", ["cd"]]), ["ab", "cd"])
""", ["lists"])

task("hard_010", "rotate_matrix",
     "Write `rotate_matrix(matrix: list) -> list` rotating a rectangular matrix 90 degrees clockwise. Return a new list of lists; do not mutate the input.",
     """
def rotate_matrix(matrix):
    if not matrix:
        return []
    return [list(row) for row in zip(*matrix[::-1])]
""",
     """
import unittest
from solution import rotate_matrix

class T(unittest.TestCase):
    def test_square(self):
        self.assertEqual(rotate_matrix([[1, 2], [3, 4]]), [[3, 1], [4, 2]])
    def test_rectangular(self):
        self.assertEqual(rotate_matrix([[1, 2, 3], [4, 5, 6]]), [[4, 1], [5, 2], [6, 3]])
    def test_empty(self):
        self.assertEqual(rotate_matrix([]), [])
    def test_single(self):
        self.assertEqual(rotate_matrix([[7]]), [[7]])
""", ["lists", "matrices"])

task("hard_011", "valid_parentheses",
     "Write `valid_parentheses(text: str) -> bool` that returns True when every (), [], and {} is correctly opened and closed in order. An empty string is valid.",
     """
def valid_parentheses(text):
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for ch in text:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack
""",
     """
import unittest
from solution import valid_parentheses

class T(unittest.TestCase):
    def test_mixed(self):
        self.assertTrue(valid_parentheses("{[()]}"))
    def test_wrong_order(self):
        self.assertFalse(valid_parentheses("([)]"))
    def test_empty(self):
        self.assertTrue(valid_parentheses(""))
    def test_extra_close(self):
        self.assertFalse(valid_parentheses("())"))
""", ["strings"])

task("hard_012", "caesar",
     "Write `caesar(text: str, shift: int) -> str` shifting ASCII letters by shift, wrapping around the alphabet, preserving case, and leaving non-letters unchanged. Negative shifts are allowed.",
     """
def caesar(text, shift):
    out = []
    for ch in text:
        if ch.isalpha():
            base = ord("A") if ch.isupper() else ord("a")
            out.append(chr((ord(ch) - base + shift) % 26 + base))
        else:
            out.append(ch)
    return "".join(out)
""",
     """
import unittest
from solution import caesar

class T(unittest.TestCase):
    def test_wrap(self):
        self.assertEqual(caesar("xyz", 3), "abc")
    def test_case_and_punct(self):
        self.assertEqual(caesar("Ab-c!", 1), "Bc-d!")
    def test_negative(self):
        self.assertEqual(caesar("abc", -1), "zab")
    def test_empty(self):
        self.assertEqual(caesar("", 5), "")
""", ["strings"])

task("hard_013", "roman_to_int",
     "Write `roman_to_int(text: str) -> int` converting a valid Roman numeral using subtractive notation. An empty string returns 0.",
     """
def roman_to_int(text):
    values = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for i, ch in enumerate(text):
        v = values[ch]
        if i + 1 < len(text) and values[text[i + 1]] > v:
            total -= v
        else:
            total += v
    return total
""",
     """
import unittest
from solution import roman_to_int

class T(unittest.TestCase):
    def test_subtractive(self):
        self.assertEqual(roman_to_int("MCMXCIV"), 1994)
    def test_simple(self):
        self.assertEqual(roman_to_int("XIV"), 14)
    def test_empty(self):
        self.assertEqual(roman_to_int(""), 0)
    def test_large(self):
        self.assertEqual(roman_to_int("MMMCMXCIX"), 3999)
""", ["strings", "parsing"])

task("hard_014", "int_to_roman",
     "Write `int_to_roman(n: int) -> str` converting an integer from 1 to 3999 to a Roman numeral using subtractive notation. Raise `ValueError` outside that range.",
     """
def int_to_roman(n):
    if not 1 <= n <= 3999:
        raise ValueError("out of range")
    vals = [(1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
            (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
            (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I")]
    out = []
    for value, sym in vals:
        while n >= value:
            out.append(sym)
            n -= value
    return "".join(out)
""",
     """
import unittest
from solution import int_to_roman

class T(unittest.TestCase):
    def test_1994(self):
        self.assertEqual(int_to_roman(1994), "MCMXCIV")
    def test_58(self):
        self.assertEqual(int_to_roman(58), "LVIII")
    def test_one(self):
        self.assertEqual(int_to_roman(1), "I")
    def test_invalid(self):
        with self.assertRaises(ValueError):
            int_to_roman(0)
""", ["strings"])

task("hard_015", "merge_sorted",
     "Write `merge_sorted(a: list, b: list) -> list` returning one ascending list containing both inputs, including duplicates. Do not use `sorted`.",
     """
def merge_sorted(a, b):
    i = j = 0
    out = []
    while i < len(a) and j < len(b):
        if a[i] <= b[j]:
            out.append(a[i]); i += 1
        else:
            out.append(b[j]); j += 1
    out.extend(a[i:]); out.extend(b[j:])
    return out
""",
     """
import unittest
from solution import merge_sorted

class T(unittest.TestCase):
    def test_merge(self):
        self.assertEqual(merge_sorted([1, 3, 5], [2, 4, 6]), [1, 2, 3, 4, 5, 6])
    def test_duplicates(self):
        self.assertEqual(merge_sorted([1, 2, 2], [2, 3]), [1, 2, 2, 2, 3])
    def test_empty(self):
        self.assertEqual(merge_sorted([], []), [])
    def test_negative(self):
        self.assertEqual(merge_sorted([-3, -1], [-2]), [-3, -2, -1])
""", ["lists"])

task("hard_016", "pair_sum",
     "Write `pair_sum(nums: list, target: int) -> bool` returning True if two different positions in nums add up to target, else False. An element cannot pair with itself.",
     """
def pair_sum(nums, target):
    seen = set()
    for n in nums:
        if target - n in seen:
            return True
        seen.add(n)
    return False
""",
     """
import unittest
from solution import pair_sum

class T(unittest.TestCase):
    def test_true(self):
        self.assertTrue(pair_sum([2, 7, 11, 15], 9))
    def test_false(self):
        self.assertFalse(pair_sum([1, 2, 3], 100))
    def test_self_not_allowed(self):
        self.assertFalse(pair_sum([3], 6))
    def test_duplicate_positions(self):
        self.assertTrue(pair_sum([3, 3], 6))
""", ["lists"])

task("hard_017", "longest_common_prefix",
     "Write `longest_common_prefix(strings: list) -> str` returning the longest common prefix of all strings. Return an empty string for an empty list or no common prefix.",
     """
def longest_common_prefix(strings):
    if not strings:
        return ""
    prefix = strings[0]
    for s in strings[1:]:
        while not s.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix
""",
     """
import unittest
from solution import longest_common_prefix

class T(unittest.TestCase):
    def test_common(self):
        self.assertEqual(longest_common_prefix(["flower", "flow", "flight"]), "fl")
    def test_none(self):
        self.assertEqual(longest_common_prefix(["dog", "cat"]), "")
    def test_empty(self):
        self.assertEqual(longest_common_prefix([]), "")
    def test_single(self):
        self.assertEqual(longest_common_prefix(["solo"]), "solo")
""", ["strings"])

task("hard_018", "spiral_order",
     "Write `spiral_order(matrix: list) -> list` returning the values of a rectangular matrix in clockwise spiral order starting at the top-left.",
     """
def spiral_order(matrix):
    out = []
    while matrix:
        out.extend(matrix.pop(0))
        if matrix and matrix[0]:
            for row in matrix:
                out.append(row.pop())
        if matrix:
            out.extend(matrix.pop()[::-1])
        if matrix and matrix[0]:
            for row in reversed(matrix):
                out.append(row.pop(0))
    return out
""",
     """
import unittest
from solution import spiral_order

class T(unittest.TestCase):
    def test_square(self):
        self.assertEqual(spiral_order([[1, 2, 3], [4, 5, 6], [7, 8, 9]]), [1, 2, 3, 6, 9, 8, 7, 4, 5])
    def test_rectangular(self):
        self.assertEqual(spiral_order([[1, 2, 3], [4, 5, 6]]), [1, 2, 3, 6, 5, 4])
    def test_empty(self):
        self.assertEqual(spiral_order([]), [])
    def test_single(self):
        self.assertEqual(spiral_order([[7]]), [7])
""", ["lists", "matrices"])

task("hard_019", "group_anagrams",
     "Write `group_anagrams(words: list) -> list` grouping words that are anagrams. Return groups sorted internally and groups ordered by their first word. Comparisons are case-sensitive.",
     """
def group_anagrams(words):
    groups = {}
    for w in words:
        groups.setdefault("".join(sorted(w)), []).append(w)
    return sorted((sorted(v) for v in groups.values()), key=lambda g: g[0])
""",
     """
import unittest
from solution import group_anagrams

class T(unittest.TestCase):
    def test_groups(self):
        got = group_anagrams(["eat", "tea", "tan", "ate", "nat", "bat"])
        self.assertEqual(got, [["ate", "eat", "tea"], ["bat"], ["nat", "tan"]])
    def test_empty(self):
        self.assertEqual(group_anagrams([]), [])
    def test_no_anagrams(self):
        self.assertEqual(group_anagrams(["a", "b"]), [["a"], ["b"]])
    def test_case_sensitive(self):
        self.assertEqual(group_anagrams(["A", "a"]), [["A"], ["a"]])
""", ["strings"])

task("hard_020", "normalize_path",
     "Write `normalize_path(path: str) -> str` simplifying an absolute POSIX path: collapse `.` and empty segments, resolve `..` against existing parents, and never return a trailing slash except for the root `/`.",
     """
def normalize_path(path):
    parts = []
    for part in path.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            if parts:
                parts.pop()
        else:
            parts.append(part)
    return "/" + "/".join(parts)
""",
     """
import unittest
from solution import normalize_path

class T(unittest.TestCase):
    def test_simplify(self):
        self.assertEqual(normalize_path("/a/./b/../c"), "/a/c")
    def test_root_parent(self):
        self.assertEqual(normalize_path("/../a"), "/a")
    def test_root(self):
        self.assertEqual(normalize_path("/"), "/")
    def test_slashes(self):
        self.assertEqual(normalize_path("/a//b/"), "/a/b")
""", ["strings", "parsing"])


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
    for t in TASKS:
        ok, out = verify(t["ref"], t["tests"])
        if not ok:
            print(f"[FAIL] {t['id']}\n{out}")
            return 1
        payload = {
            "id": t["id"], "title": t["title"], "prompt": t["prompt"],
            "tests": t["tests"], "entry": "solution.py", "timeout_s": 20,
            "tags": t["tags"], "difficulty": "hard",
        }
        (OUT / f"{t['id']}.json").write_text(json.dumps(payload, indent=2) + "\n")

    files = sorted(OUT.glob("*.json"))
    entries = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    combined = hashlib.sha256(
        "".join(f"{k}:{v}" for k, v in sorted(entries.items())).encode()).hexdigest()
    freeze = {
        "frozen_at": __import__("time").strftime("%Y-%m-%dT%H:%M:%S"),
        "task_count": len(files),
        "combined_sha256": combined,
        "files": entries,
        "note": "frozen search split; not a blind holdout",
    }
    FREEZE.write_text(json.dumps(freeze, indent=2) + "\n")
    print(f"[hard] {len(files)} tasks verified; combined={combined[:16]}…")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
