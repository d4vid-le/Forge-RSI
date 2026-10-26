#!/usr/bin/env python3
"""
Build the Forge-RSI task suite.

Every task ships with a reference solution and a hidden unittest suite. This
script *proves* the reference passes before writing any JSON, so a broken task
can never enter the eval set silently.

Run:
    python3 tasks/build_tasks.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DEV = ROOT / "dev"
HOLDOUT = ROOT / "holdout"

# Each task: id, title, prompt, ref (reference solution), tests, difficulty, tags.
TASKS: list[dict] = []


def task(tid, title, prompt, ref, tests, difficulty="easy", tags=None):
    TASKS.append(dict(id=tid, title=title, prompt=prompt.strip(), ref=ref.strip(),
                      tests=tests.strip(), difficulty=difficulty,
                      tags=tags or []))


# ─────────────────────────────── DEV (20) ────────────────────────────────

task("dev_001", "add_two",
     "Write a function `add(a, b)` that returns the sum of two numbers.",
     """
def add(a, b):
    return a + b
""",
     """
import unittest
from solution import add

class T(unittest.TestCase):
    def test_ints(self):
        self.assertEqual(add(2, 3), 5)
    def test_neg(self):
        self.assertEqual(add(-4, 10), 6)
    def test_floats(self):
        self.assertAlmostEqual(add(0.5, 0.25), 0.75)
    def test_zero(self):
        self.assertEqual(add(0, 0), 0)
""")

task("dev_002", "is_even",
     "Write `is_even(n: int) -> bool` that returns True when n is even, False otherwise. It must work for negative integers too.",
     """
def is_even(n):
    return n % 2 == 0
""",
     """
import unittest
from solution import is_even

class T(unittest.TestCase):
    def test_even(self):
        self.assertTrue(is_even(4))
    def test_odd(self):
        self.assertFalse(is_even(7))
    def test_negative(self):
        self.assertTrue(is_even(-2))
        self.assertFalse(is_even(-3))
    def test_zero(self):
        self.assertTrue(is_even(0))
""")

task("dev_003", "max_of_three",
     "Write `max_of_three(a, b, c)` that returns the largest of three numbers.",
     """
def max_of_three(a, b, c):
    return max(a, b, c)
""",
     """
import unittest
from solution import max_of_three

class T(unittest.TestCase):
    def test_first(self):
        self.assertEqual(max_of_three(9, 2, 1), 9)
    def test_second(self):
        self.assertEqual(max_of_three(1, 9, 2), 9)
    def test_third(self):
        self.assertEqual(max_of_three(1, 2, 9), 9)
    def test_ties(self):
        self.assertEqual(max_of_three(5, 5, 5), 5)
""")

task("dev_004", "reverse_string",
     "Write `reverse_string(s: str) -> str` that returns the string reversed.",
     """
def reverse_string(s):
    return s[::-1]
""",
     """
import unittest
from solution import reverse_string

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(reverse_string("abc"), "cba")
    def test_empty(self):
        self.assertEqual(reverse_string(""), "")
    def test_spaces(self):
        self.assertEqual(reverse_string("a b"), "b a")
    def test_unicode(self):
        self.assertEqual(reverse_string("ab"), "ba")
""")

task("dev_005", "count_vowels",
     "Write `count_vowels(s: str) -> int` that counts vowels (a, e, i, o, u) case-insensitively.",
     """
def count_vowels(s):
    return sum(1 for ch in s.lower() if ch in "aeiou")
""",
     """
import unittest
from solution import count_vowels

class T(unittest.TestCase):
    def test_lower(self):
        self.assertEqual(count_vowels("hello"), 2)
    def test_upper(self):
        self.assertEqual(count_vowels("AEIOU"), 5)
    def test_none(self):
        self.assertEqual(count_vowels("xyz"), 0)
    def test_mixed(self):
        self.assertEqual(count_vowels("Python"), 1)
""")

task("dev_006", "factorial",
     "Write `factorial(n: int) -> int` returning n! for n >= 0. Raise `ValueError` if n is negative.",
     """
def factorial(n):
    if n < 0:
        raise ValueError("negative")
    out = 1
    for i in range(2, n + 1):
        out *= i
    return out
""",
     """
import unittest
from solution import factorial

class T(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(factorial(0), 1)
    def test_five(self):
        self.assertEqual(factorial(5), 120)
    def test_one(self):
        self.assertEqual(factorial(1), 1)
    def test_negative(self):
        with self.assertRaises(ValueError):
            factorial(-1)
""")

task("dev_007", "fibonacci",
     "Write `fib(n: int) -> int` returning the n-th Fibonacci number with fib(0)=0 and fib(1)=1. Raise `ValueError` for n < 0.",
     """
def fib(n):
    if n < 0:
        raise ValueError("negative")
    a, b = 0, 1
    for _ in range(n):
        a, b = b, a + b
    return a
""",
     """
import unittest
from solution import fib

class T(unittest.TestCase):
    def test_zero(self):
        self.assertEqual(fib(0), 0)
    def test_one(self):
        self.assertEqual(fib(1), 1)
    def test_ten(self):
        self.assertEqual(fib(10), 55)
    def test_negative(self):
        with self.assertRaises(ValueError):
            fib(-1)
""")

task("dev_008", "is_palindrome",
     "Write `is_palindrome(s: str) -> bool` that ignores case and any character that is not a letter or digit. An empty string counts as a palindrome.",
     """
def is_palindrome(s):
    clean = "".join(ch.lower() for ch in s if ch.isalnum())
    return clean == clean[::-1]
""",
     """
import unittest
from solution import is_palindrome

class T(unittest.TestCase):
    def test_basic(self):
        self.assertTrue(is_palindrome("racecar"))
    def test_punct(self):
        self.assertTrue(is_palindrome("A man, a plan, a canal: Panama"))
    def test_false(self):
        self.assertFalse(is_palindrome("hello"))
    def test_empty(self):
        self.assertTrue(is_palindrome(""))
""", "medium")

task("dev_009", "sum_digits",
     "Write `sum_digits(n: int) -> int` returning the sum of the decimal digits of n, ignoring the sign.",
     """
def sum_digits(n):
    return sum(int(ch) for ch in str(abs(n)))
""",
     """
import unittest
from solution import sum_digits

class T(unittest.TestCase):
    def test_positive(self):
        self.assertEqual(sum_digits(123), 6)
    def test_negative(self):
        self.assertEqual(sum_digits(-456), 15)
    def test_zero(self):
        self.assertEqual(sum_digits(0), 0)
    def test_single(self):
        self.assertEqual(sum_digits(9), 9)
""")

task("dev_010", "clamp",
     "Write `clamp(value, lo, hi)` returning value limited to the inclusive range [lo, hi].",
     """
def clamp(value, lo, hi):
    return max(lo, min(value, hi))
""",
     """
import unittest
from solution import clamp

class T(unittest.TestCase):
    def test_inside(self):
        self.assertEqual(clamp(5, 0, 10), 5)
    def test_below(self):
        self.assertEqual(clamp(-3, 0, 10), 0)
    def test_above(self):
        self.assertEqual(clamp(42, 0, 10), 10)
    def test_bounds(self):
        self.assertEqual(clamp(0, 0, 10), 0)
        self.assertEqual(clamp(10, 0, 10), 10)
""")

task("dev_011", "unique_preserve_order",
     "Write `unique(items: list) -> list` that removes duplicates while preserving first-occurrence order.",
     """
def unique(items):
    seen = set()
    out = []
    for x in items:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
""",
     """
import unittest
from solution import unique

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(unique([1, 2, 1, 3, 2]), [1, 2, 3])
    def test_empty(self):
        self.assertEqual(unique([]), [])
    def test_strings(self):
        self.assertEqual(unique(["a", "b", "a"]), ["a", "b"])
    def test_all_same(self):
        self.assertEqual(unique([7, 7, 7]), [7])
""", "medium")

task("dev_012", "word_freq",
     "Write `word_freq(text: str) -> dict` returning a dict mapping each lowercased whitespace-separated word to its count.",
     """
def word_freq(text):
    out = {}
    for w in text.lower().split():
        out[w] = out.get(w, 0) + 1
    return out
""",
     """
import unittest
from solution import word_freq

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(word_freq("a b a"), {"a": 2, "b": 1})
    def test_case(self):
        self.assertEqual(word_freq("Hi hi HI"), {"hi": 3})
    def test_empty(self):
        self.assertEqual(word_freq(""), {})
    def test_punct_kept(self):
        self.assertEqual(word_freq("a, a,"), {"a,": 2})
""", "medium")

task("dev_013", "flatten_one",
     "Write `flatten(items: list) -> list` that flattens exactly one level of nesting. Non-list elements are kept as-is.",
     """
def flatten(items):
    out = []
    for x in items:
        if isinstance(x, list):
            out.extend(x)
        else:
            out.append(x)
    return out
""",
     """
import unittest
from solution import flatten

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(flatten([1, [2, 3], 4]), [1, 2, 3, 4])
    def test_empty_inner(self):
        self.assertEqual(flatten([[], 1]), [1])
    def test_no_nesting(self):
        self.assertEqual(flatten([1, 2]), [1, 2])
    def test_deep_not_fully_flattened(self):
        self.assertEqual(flatten([[1, [2]]]), [1, [2]])
""")

task("dev_014", "binary_search",
     "Write `binary_search(arr, target) -> int` returning the index of target in a sorted list, or -1 if absent. Duplicates may return any matching index.",
     """
def binary_search(arr, target):
    lo, hi = 0, len(arr) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if arr[mid] == target:
            return mid
        if arr[mid] < target:
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
    def test_missing(self):
        self.assertEqual(binary_search([1, 3, 5, 7], 4), -1)
    def test_empty(self):
        self.assertEqual(binary_search([], 1), -1)
    def test_ends(self):
        self.assertEqual(binary_search([2, 4, 6], 2), 0)
        self.assertEqual(binary_search([2, 4, 6], 6), 2)
""", "medium")

task("dev_015", "title_case",
     "Write `title_case(s: str) -> str` that capitalizes the first letter of each whitespace-separated word and lowercases the rest.",
     """
def title_case(s):
    return " ".join(w[:1].upper() + w[1:].lower() for w in s.split(" "))
""",
     """
import unittest
from solution import title_case

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(title_case("hello world"), "Hello World")
    def test_mixed(self):
        self.assertEqual(title_case("hELLO wORLD"), "Hello World")
    def test_single(self):
        self.assertEqual(title_case("x"), "X")
    def test_empty(self):
        self.assertEqual(title_case(""), "")
""")

task("dev_016", "caesar",
     "Write `caesar(s: str, shift: int) -> str` that shifts letters by shift positions, wrapping around the alphabet, preserving case. Non-letters are unchanged. Negative shifts go backwards.",
     """
def caesar(s, shift):
    out = []
    for ch in s:
        if "a" <= ch <= "z":
            out.append(chr((ord(ch) - 97 + shift) % 26 + 97))
        elif "A" <= ch <= "Z":
            out.append(chr((ord(ch) - 65 + shift) % 26 + 65))
        else:
            out.append(ch)
    return "".join(out)
""",
     """
import unittest
from solution import caesar

class T(unittest.TestCase):
    def test_forward(self):
        self.assertEqual(caesar("abc", 1), "bcd")
    def test_wrap(self):
        self.assertEqual(caesar("xyz", 3), "abc")
    def test_case_and_punct(self):
        self.assertEqual(caesar("Az!", 1), "Ba!")
    def test_negative(self):
        self.assertEqual(caesar("abc", -1), "zab")
""", "medium")

task("dev_017", "anagram",
     "Write `is_anagram(a: str, b: str) -> bool` that ignores case and whitespace.",
     """
def is_anagram(a, b):
    def norm(s):
        return sorted(ch.lower() for ch in s if not ch.isspace())
    return norm(a) == norm(b)
""",
     """
import unittest
from solution import is_anagram

class T(unittest.TestCase):
    def test_true(self):
        self.assertTrue(is_anagram("listen", "silent"))
    def test_false(self):
        self.assertFalse(is_anagram("abc", "abd"))
    def test_spaces(self):
        self.assertTrue(is_anagram("Dormitory", "dirty room"))
    def test_empty(self):
        self.assertTrue(is_anagram("", ""))
""", "medium")

task("dev_018", "second_largest",
     "Write `second_largest(nums: list) -> int` returning the second largest distinct value. Raise `ValueError` if there are fewer than two distinct values.",
     """
def second_largest(nums):
    distinct = sorted(set(nums), reverse=True)
    if len(distinct) < 2:
        raise ValueError("need two distinct values")
    return distinct[1]
""",
     """
import unittest
from solution import second_largest

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(second_largest([1, 3, 2]), 2)
    def test_duplicates(self):
        self.assertEqual(second_largest([5, 5, 4]), 4)
    def test_negative(self):
        self.assertEqual(second_largest([-1, -2, -3]), -2)
    def test_too_few(self):
        with self.assertRaises(ValueError):
            second_largest([1, 1])
""", "medium")

task("dev_019", "run_length_encode",
     "Write `rle(s: str) -> str` returning a run-length encoding. Each run of the same character becomes the character followed by its count. Example: `aaab` -> `a3b1`; empty string -> empty string.",
     """
def rle(s):
    if not s:
        return ""
    out = []
    prev = s[0]
    count = 1
    for ch in s[1:]:
        if ch == prev:
            count += 1
        else:
            out.append(prev + str(count))
            prev = ch
            count = 1
    out.append(prev + str(count))
    return "".join(out)
""",
     """
import unittest
from solution import rle

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(rle("aaab"), "a3b1")
    def test_single(self):
        self.assertEqual(rle("a"), "a1")
    def test_empty(self):
        self.assertEqual(rle(""), "")
    def test_alternating(self):
        self.assertEqual(rle("abab"), "a1b1a1b1")
""", "medium")

task("dev_020", "merge_intervals",
     "Write `merge_intervals(intervals: list) -> list` that merges overlapping or touching closed intervals. Each interval is a two-item list [start, end]. Return sorted merged intervals.",
     """
def merge_intervals(intervals):
    if not intervals:
        return []
    ivs = sorted((list(x) for x in intervals), key=lambda p: p[0])
    out = [ivs[0][:]]
    for start, end in ivs[1:]:
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
    def test_touch(self):
        self.assertEqual(merge_intervals([[1, 3], [3, 5]]), [[1, 5]])
    def test_disjoint(self):
        self.assertEqual(merge_intervals([[5, 6], [1, 2]]), [[1, 2], [5, 6]])
    def test_empty(self):
        self.assertEqual(merge_intervals([]), [])
""", "hard")


# ───────────────────────────── HOLDOUT (10) ──────────────────────────────

task("hold_001", "gcd",
     "Write `gcd(a: int, b: int) -> int` returning the greatest common divisor of two non-negative integers. gcd(0, n) == n.",
     """
def gcd(a, b):
    while b:
        a, b = b, a % b
    return abs(a)
""",
     """
import unittest
from solution import gcd

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(gcd(12, 18), 6)
    def test_coprime(self):
        self.assertEqual(gcd(7, 13), 1)
    def test_zero(self):
        self.assertEqual(gcd(0, 5), 5)
    def test_equal(self):
        self.assertEqual(gcd(9, 9), 9)
""", "medium", ["math"])

task("hold_002", "prime_factors",
     "Write `prime_factors(n: int) -> list` returning the prime factors of n in ascending order, with repetition (e.g. 12 -> [2, 2, 3]). Raise `ValueError` for n < 2.",
     """
def prime_factors(n):
    if n < 2:
        raise ValueError("n must be >= 2")
    out = []
    d = 2
    while d * d <= n:
        while n % d == 0:
            out.append(d)
            n //= d
        d += 1
    if n > 1:
        out.append(n)
    return out
""",
     """
import unittest
from solution import prime_factors

class T(unittest.TestCase):
    def test_12(self):
        self.assertEqual(prime_factors(12), [2, 2, 3])
    def test_prime(self):
        self.assertEqual(prime_factors(13), [13])
    def test_power(self):
        self.assertEqual(prime_factors(8), [2, 2, 2])
    def test_invalid(self):
        with self.assertRaises(ValueError):
            prime_factors(1)
""", "medium", ["math"])

task("hold_003", "chunk",
     "Write `chunk(items: list, n: int) -> list` splitting a list into consecutive sublists of length n. The last chunk may be shorter. Raise `ValueError` if n <= 0.",
     """
def chunk(items, n):
    if n <= 0:
        raise ValueError("n must be positive")
    return [items[i:i + n] for i in range(0, len(items), n)]
""",
     """
import unittest
from solution import chunk

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(chunk([1, 2, 3, 4, 5], 2), [[1, 2], [3, 4], [5]])
    def test_exact(self):
        self.assertEqual(chunk([1, 2, 3, 4], 2), [[1, 2], [3, 4]])
    def test_empty(self):
        self.assertEqual(chunk([], 3), [])
    def test_invalid(self):
        with self.assertRaises(ValueError):
            chunk([1], 0)
""", "easy", ["lists"])

task("hold_004", "rotate_list",
     "Write `rotate_right(nums: list, k: int) -> list` rotating the list right by k positions. k may be larger than the list length; an empty list stays empty.",
     """
def rotate_right(nums, k):
    if not nums:
        return []
    k %= len(nums)
    return nums[-k:] + nums[:-k]
""",
     """
import unittest
from solution import rotate_right

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(rotate_right([1, 2, 3, 4], 1), [4, 1, 2, 3])
    def test_large_k(self):
        self.assertEqual(rotate_right([1, 2, 3], 4), [3, 1, 2])
    def test_empty(self):
        self.assertEqual(rotate_right([], 5), [])
    def test_zero(self):
        self.assertEqual(rotate_right([1, 2], 0), [1, 2])
""", "medium", ["lists"])

task("hold_005", "is_balanced",
     "Write `is_balanced(s: str) -> bool` that returns True when all brackets `()[]{}` are correctly balanced and nested. Non-bracket characters are ignored.",
     """
def is_balanced(s):
    pairs = {")": "(", "]": "[", "}": "{"}
    stack = []
    for ch in s:
        if ch in "([{":
            stack.append(ch)
        elif ch in pairs:
            if not stack or stack.pop() != pairs[ch]:
                return False
    return not stack
""",
     """
import unittest
from solution import is_balanced

class T(unittest.TestCase):
    def test_balanced(self):
        self.assertTrue(is_balanced("([]{})"))
    def test_unbalanced(self):
        self.assertFalse(is_balanced("([)]"))
    def test_extra_close(self):
        self.assertFalse(is_balanced("())"))
    def test_ignore_text(self):
        self.assertTrue(is_balanced("a(b)c[d]"))
""", "medium", ["strings"])

task("hold_006", "roman_to_int",
     "Write `roman_to_int(s: str) -> int` converting a valid uppercase Roman numeral to an integer. Handle subtractive pairs (IV, IX, XL, XC, CD, CM).",
     """
def roman_to_int(s):
    vals = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}
    total = 0
    for i, ch in enumerate(s):
        v = vals[ch]
        if i + 1 < len(s) and vals[s[i + 1]] > v:
            total -= v
        else:
            total += v
    return total
""",
     """
import unittest
from solution import roman_to_int

class T(unittest.TestCase):
    def test_simple(self):
        self.assertEqual(roman_to_int("XII"), 12)
    def test_subtractive(self):
        self.assertEqual(roman_to_int("IX"), 9)
    def test_large(self):
        self.assertEqual(roman_to_int("MCMXCIV"), 1994)
    def test_one(self):
        self.assertEqual(roman_to_int("I"), 1)
""", "medium", ["strings"])

task("hold_007", "longest_common_prefix",
     "Write `longest_common_prefix(words: list) -> str` returning the longest common prefix of a list of strings. Return the empty string if there is none or the list is empty.",
     """
def longest_common_prefix(words):
    if not words:
        return ""
    prefix = words[0]
    for w in words[1:]:
        while not w.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    return prefix
""",
     """
import unittest
from solution import longest_common_prefix

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(longest_common_prefix(["flower", "flow", "flight"]), "fl")
    def test_none(self):
        self.assertEqual(longest_common_prefix(["dog", "cat"]), "")
    def test_empty_list(self):
        self.assertEqual(longest_common_prefix([]), "")
    def test_single(self):
        self.assertEqual(longest_common_prefix(["abc"]), "abc")
""", "medium", ["strings"])

task("hold_008", "matrix_transpose",
     "Write `transpose(matrix: list) -> list` returning the transpose of a rectangular list-of-lists. An empty matrix returns [].",
     """
def transpose(matrix):
    if not matrix:
        return []
    return [list(row) for row in zip(*matrix)]
""",
     """
import unittest
from solution import transpose

class T(unittest.TestCase):
    def test_square(self):
        self.assertEqual(transpose([[1, 2], [3, 4]]), [[1, 3], [2, 4]])
    def test_rect(self):
        self.assertEqual(transpose([[1, 2, 3], [4, 5, 6]]), [[1, 4], [2, 5], [3, 6]])
    def test_empty(self):
        self.assertEqual(transpose([]), [])
    def test_single(self):
        self.assertEqual(transpose([[1]]), [[1]])
""", "easy", ["lists"])

task("hold_009", "snake_to_camel",
     "Write `snake_to_camel(s: str) -> str` converting a snake_case identifier to lowerCamelCase. Leading/trailing/duplicate underscores should be handled gracefully.",
     """
def snake_to_camel(s):
    parts = [p for p in s.split("_") if p]
    if not parts:
        return ""
    return parts[0].lower() + "".join(p[:1].upper() + p[1:].lower() for p in parts[1:])
""",
     """
import unittest
from solution import snake_to_camel

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(snake_to_camel("hello_world"), "helloWorld")
    def test_single(self):
        self.assertEqual(snake_to_camel("abc"), "abc")
    def test_extra(self):
        self.assertEqual(snake_to_camel("_a__b_"), "aB")
    def test_empty(self):
        self.assertEqual(snake_to_camel(""), "")
""", "medium", ["strings"])

task("hold_010", "top_k_frequent",
     "Write `top_k_frequent(nums: list, k: int) -> list` returning the k most frequent values. Break ties by first occurrence in the input (earlier first). Return fewer than k values if the input has fewer distinct values.",
     """
def top_k_frequent(nums, k):
    counts = {}
    first = {}
    for i, x in enumerate(nums):
        counts[x] = counts.get(x, 0) + 1
        if x not in first:
            first[x] = i
    ordered = sorted(counts, key=lambda x: (-counts[x], first[x]))
    return ordered[:k]
""",
     """
import unittest
from solution import top_k_frequent

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(top_k_frequent([1, 1, 2, 2, 3], 2), [1, 2])
    def test_tie(self):
        self.assertEqual(top_k_frequent([3, 1, 3, 1, 2], 2), [3, 1])
    def test_k_too_large(self):
        self.assertEqual(top_k_frequent([1, 2], 5), [1, 2])
    def test_empty(self):
        self.assertEqual(top_k_frequent([], 3), [])
""", "hard", ["lists"])


# ─────────────────────────────── builder ─────────────────────────────────

def run_reference(ref: str, tests: str, timeout=20) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as td:
        td = Path(td)
        (td / "solution.py").write_text(ref + "\n")
        (td / "test_solution.py").write_text(tests + "\n")
        p = subprocess.run([sys.executable, "-m", "unittest", "-q", "test_solution"],
                           cwd=td, capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stdout + p.stderr)[-2000:]


def main() -> int:
    DEV.mkdir(parents=True, exist_ok=True)
    HOLDOUT.mkdir(parents=True, exist_ok=True)
    failures = 0
    seen = set()
    for t in TASKS:
        if t["id"] in seen:
            print(f"[dup] {t['id']}")
            failures += 1
            continue
        seen.add(t["id"])
        ok, out = run_reference(t["ref"], t["tests"])
        if not ok:
            failures += 1
            print(f"[FAIL] {t['id']} — reference does not pass its own tests\n{out}")
            continue
        outdir = DEV if t["id"].startswith("dev_") else HOLDOUT
        payload = {k: t[k] for k in ("id", "title", "prompt", "tests", "difficulty", "tags")}
        payload["entry"] = "solution.py"
        payload["timeout_s"] = 20
        (outdir / f"{t['id']}.json").write_text(json.dumps(payload, indent=2) + "\n")
        print(f"[ok] {t['id']:9} {t['title']}")

    dev = list(DEV.glob("*.json"))
    hold = list(HOLDOUT.glob("*.json"))
    print(f"\nwrote {len(dev)} dev + {len(hold)} holdout; reference failures={failures}")
    print(f"dev ids:    {', '.join(sorted(p.stem for p in dev))}")
    print(f"holdout ids:{', '.join(sorted(p.stem for p in hold))}")
    return 0 if failures == 0 and len(dev) == 20 and len(hold) == 10 else 1


if __name__ == "__main__":
    raise SystemExit(main())
