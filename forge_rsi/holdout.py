"""Private-holdout rotation.

The private holdout is deliberately local-only: prompts and hidden tests never
enter the public repo or a published report. Rotation generates a fresh set from
deterministic templates, verifies every reference solution against its own
hidden tests, archives the previous set, and records only counts/hashes.
"""
from __future__ import annotations

import hashlib
import json
import random
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

TEMPLATES = (
    "word_freq",
    "merge_intervals",
    "sum_even",
    "capitalize_words",
    "second_largest",
    "rle",
)

WORDS = ("alpha", "beta", "gamma", "delta", "epsilon", "zeta", "eta", "theta")


class HoldoutError(RuntimeError):
    """Rotation refused or failed verification."""


# ── pure helpers used to compute expected values ────────────────────────────

def _merge_iv(intervals: list[list[int]]) -> list[list[int]]:
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


def _rle(text: str) -> list[list]:
    out: list[list] = []
    for ch in text:
        if out and out[-1][0] == ch:
            out[-1][1] += 1
        else:
            out.append([ch, 1])
    return out


def _second_largest(nums: list[int]):
    uniq = sorted(set(nums), reverse=True)
    return uniq[1] if len(uniq) > 1 else None


def _capitalize(text: str) -> str:
    return " ".join(w[:1].upper() + w[1:].lower() for w in text.split(" "))


def _word_counts(text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for word in text.lower().split():
        out[word] = out.get(word, 0) + 1
    return out


# ── task construction ───────────────────────────────────────────────────────

def _task(skill: str, name: str, rng: random.Random) -> dict:
    if skill == "word_freq":
        words = rng.sample(WORDS, 4)
        text1 = " ".join(words + [words[0], words[2]])
        text2 = " ".join(w.upper() if i % 2 else w for i, w in enumerate(words + words[:1]))
        prompt = (f"Write `{name}(text: str) -> dict` returning a dict mapping each "
                  f"lowercased, whitespace-separated word to its count.")
        ref = (
            f"def {name}(text):\n"
            "    counts = {}\n"
            "    for word in text.lower().split():\n"
            "        counts[word] = counts.get(word, 0) + 1\n"
            "    return counts\n"
        )
        cases = [
            (f'{name}("{text1}")', _word_counts(text1)),
            (f'{name}("{text2}")', _word_counts(text2)),
            (f'{name}("")', {}),
            (f'{name}("{words[1]},{words[1]}")', {f"{words[1]},{words[1]}": 1}),
        ]
    elif skill == "merge_intervals":
        a, b, c, d = sorted(rng.sample(range(-5, 12), 4))
        overlapping = [[a, c], [b, d]]
        touching = [[a, b], [b, c]]
        disjoint = [[c, d], [a, b]]
        prompt = (f"Write `{name}(intervals: list) -> list` that merges overlapping "
                  f"or touching closed [start, end] intervals and returns a sorted list.")
        ref = (
            f"def {name}(intervals):\n"
            "    if not intervals:\n"
            "        return []\n"
            "    intervals = sorted((list(x) for x in intervals), key=lambda x: tuple(x))\n"
            "    merged = [intervals[0]]\n"
            "    for start, end in intervals[1:]:\n"
            "        if start <= merged[-1][1]:\n"
            "            merged[-1][1] = max(merged[-1][1], end)\n"
            "        else:\n"
            "            merged.append([start, end])\n"
            "    return merged\n"
        )
        cases = [
            (f"{name}({overlapping!r})", _merge_iv(overlapping)),
            (f"{name}({touching!r})", _merge_iv(touching)),
            (f"{name}({disjoint!r})", _merge_iv(disjoint)),
            (f"{name}([])", []),
        ]
    elif skill == "sum_even":
        nums = [rng.randint(-9, 20) for _ in range(6)]
        prompt = (f"Write `{name}(nums: list) -> int` returning the sum of the even "
                  f"integers in the list.")
        ref = f"def {name}(nums):\n    return sum(n for n in nums if n % 2 == 0)\n"
        cases = [
            (f"{name}({nums!r})", sum(n for n in nums if n % 2 == 0)),
            (f"{name}([])", 0),
            (f"{name}([1, 3, 5])", 0),
            (f"{name}([-2, 4])", 2),
        ]
    elif skill == "capitalize_words":
        words = rng.sample(WORDS, 4)
        mixed = [w.upper() if i % 2 else w[:1].upper() + w[1:] for i, w in enumerate(words)]
        text = " ".join(mixed)
        prompt = (f"Write `{name}(text: str) -> str` that capitalizes the first letter "
                  f"of each space-separated word and lowercases the rest.")
        ref = (
            f"def {name}(text):\n"
            '    return " ".join(w[:1].upper() + w[1:].lower() for w in text.split(" "))\n'
        )
        cases = [
            (f'{name}("{text}")', _capitalize(text)),
            (f'{name}("hello world")', "Hello World"),
            (f'{name}("")', ""),
            (f'{name}("x")', "X"),
        ]
    elif skill == "second_largest":
        nums = rng.sample(range(-20, 40), 6)
        prompt = (f"Write `{name}(nums: list) -> int` returning the second-largest "
                  f"distinct value, or None if there is no second value.")
        ref = (
            f"def {name}(nums):\n"
            "    uniq = sorted(set(nums), reverse=True)\n"
            "    return uniq[1] if len(uniq) > 1 else None\n"
        )
        cases = [
            (f"{name}({nums!r})", _second_largest(nums)),
            (f"{name}([1, 1, 2])", 1),
            (f"{name}([5])", None),
            (f"{name}([-3, -1, -2])", -2),
        ]
    elif skill == "rle":
        letters = rng.sample("abcdef", 4)
        text = (
            letters[0] * 3 + letters[1] + letters[2] * 2 + letters[3] * 4
        )
        prompt = (f"Write `{name}(text: str) -> list` returning run-length encoding "
                  f"as a list of [character, count] pairs.")
        ref = (
            f"def {name}(text):\n"
            "    out = []\n"
            "    for ch in text:\n"
            "        if out and out[-1][0] == ch:\n"
            "            out[-1][1] += 1\n"
            "        else:\n"
            "            out.append([ch, 1])\n"
            "    return out\n"
        )
        cases = [
            (f'{name}("{text}")', _rle(text)),
            (f'{name}("")', []),
            (f'{name}("aaa")', [["a", 3]]),
            (f'{name}("ab")', [["a", 1], ["b", 1]]),
        ]
    else:  # pragma: no cover - guarded by TEMPLATES
        raise HoldoutError(f"unknown template: {skill}")

    lines = ["import unittest", f"from solution import {name}", "", "class T(unittest.TestCase):"]
    for i, (call, expected) in enumerate(cases, 1):
        lines += [f"    def test_{i}(self):",
                  f"        self.assertEqual({call}, {expected!r})"]
    tests = "\n".join(lines) + "\n"
    return {
        "id": f"priv_{name}",
        "title": name,
        "prompt": prompt,
        "tests": tests,
        "entry": "solution.py",
        "timeout_s": 20,
        "tags": ["private_holdout", skill],
        "difficulty": "medium",
        "_ref": ref,
    }


def _verify(ref: str, tests: str, timeout_s: int = 20) -> None:
    with tempfile.TemporaryDirectory(prefix="sf_holdout_") as td:
        td = Path(td)
        (td / "solution.py").write_text(ref.rstrip() + "\n")
        (td / "test_solution.py").write_text(tests.rstrip() + "\n")
        p = subprocess.run(
            [sys.executable, "-m", "unittest", "-q", "test_solution"],
            cwd=td, capture_output=True, text=True, timeout=timeout_s,
        )
        if p.returncode != 0:
            raise HoldoutError(
                f"generated task failed its own reference:\n{(p.stderr or p.stdout)[-1200:]}")


def generate(count: int = 10, seed: int | None = None) -> list[dict]:
    if not 4 <= count <= 40:
        raise HoldoutError("count must be between 4 and 40")
    seed = int(seed if seed is not None else time.time_ns() // 1_000_000 % 0xFFFFFF)
    rng = random.Random(seed)
    tasks = []
    for i in range(count):
        skill = TEMPLATES[i % len(TEMPLATES)]
        name = f"{skill}_{seed:x}_{i + 1}"
        task = _task(skill, name, rng)
        _verify(task.pop("_ref"), task["tests"], task.get("timeout_s", 20))
        tasks.append(task)
    return tasks


# ── persistence ─────────────────────────────────────────────────────────────

def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_digest(files: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(files):
        h.update(f"{p.name}:{_sha(p)}".encode())
    return h.hexdigest()


def _write_tasks(out: Path, tasks: list[dict], seed: int, count: int) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    entries = []
    for task in tasks:
        p = out / f"{task['id']}.json"
        p.write_text(json.dumps(task, indent=2, sort_keys=True) + "\n")
        entries.append({"id": task["id"], "file": p.name, "sha256": _sha(p),
                        "skill": task["tags"][-1]})
    files = [out / e["file"] for e in entries]
    manifest = {
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "generator": "forge_rsi.holdout v1",
        "seed": seed,
        "count": len(tasks),
        "blind": True,
        "combined_sha256": _tree_digest(files),
        "tasks": entries,
        "note": "prompts and hidden tests are local-only and never published",
    }
    (out / "MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


def status(cfg: dict) -> dict:
    tasks_root = Path(cfg["paths"]["tasks"])
    current = tasks_root / "private_holdout"
    archives_dir = tasks_root / "private_holdout_archive"
    out = {"path": str(current), "exists": current.exists(),
           "count": 0, "manifest": None, "combined_sha256": None,
           "archives": [], "latest_archive": None}
    if current.exists():
        files = sorted(p for p in current.glob("*.json") if p.name != "MANIFEST.json")
        out["count"] = len(files)
        if files:
            out["combined_sha256"] = _tree_digest(files)
        man = current / "MANIFEST.json"
        if man.exists():
            try:
                out["manifest"] = json.loads(man.read_text())
            except ValueError:
                out["manifest"] = None
    if archives_dir.exists():
        out["archives"] = sorted(p.name for p in archives_dir.iterdir() if p.is_dir())
        if out["archives"]:
            out["latest_archive"] = out["archives"][-1]
    return out


def _report(cfg: dict, manifest: dict, archived: str | None) -> Path:
    reports = Path(cfg["paths"]["reports"])
    reports.mkdir(parents=True, exist_ok=True)
    lines = [
        "# Private holdout rotation",
        "",
        f"- created: {manifest['created_at']}",
        f"- tasks: **{manifest['count']}**",
        f"- seed: `{manifest['seed']}`",
        f"- combined sha256: `{manifest['combined_sha256']}`",
        f"- archived previous set: {'yes — ' + archived if archived else 'no (first set)'}",
        "- visibility: **blind** — prompts and hidden tests are local-only",
        "",
        "The public 10-task holdout remains a regression set. Any future blind",
        "claim must be made on this rotated private set, never on the public set.",
        "",
        "## Skills in the new set",
        "",
    ]
    counts: dict[str, int] = {}
    for t in manifest["tasks"]:
        counts[t["skill"]] = counts.get(t["skill"], 0) + 1
    for skill, n in sorted(counts.items()):
        lines.append(f"- `{skill}`: {n}")
    path = reports / "holdout_rotation.md"
    path.write_text("\n".join(lines) + "\n")
    return path


def rotate(cfg: dict, count: int = 10, seed: int | None = None,
           force: bool = False) -> dict:
    tasks_root = Path(cfg["paths"]["tasks"])
    current = tasks_root / "private_holdout"
    if current.exists() and not force:
        raise HoldoutError("private holdout already exists; force is required to rotate")
    stamp = time.strftime("%Y%m%d-%H%M%S")
    temp = tasks_root / f".private_holdout_new_{stamp}"
    archive_dir: Path | None = None
    if temp.exists():
        shutil.rmtree(temp)
    try:
        used_seed = int(seed if seed is not None else time.time_ns() // 1_000_000 % 0xFFFFFF)
        tasks = generate(count=count, seed=used_seed)
        manifest = _write_tasks(temp, tasks, used_seed, count)
        archive_name = None
        if current.exists():
            archive_dir = tasks_root / "private_holdout_archive" / stamp
            archive_dir.parent.mkdir(parents=True, exist_ok=True)
            if archive_dir.exists():
                shutil.rmtree(archive_dir)
            shutil.copytree(current, archive_dir)
            archive_name = stamp
            shutil.rmtree(current)
        temp.rename(current)
        report = _report(cfg, manifest, archive_name)
        return {
            "ok": True,
            "path": str(current),
            "count": manifest["count"],
            "seed": manifest["seed"],
            "combined_sha256": manifest["combined_sha256"],
            "archived": archive_name,
            "report": str(report),
        }
    except Exception:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
        # Never leave the operator without a private set.
        if archive_dir is not None and archive_dir.exists() and not current.exists():
            try:
                shutil.copytree(archive_dir, current)
            except OSError:
                pass
        raise


def format_status(st: dict) -> str:
    if not st["exists"]:
        return "private holdout: missing"
    man = st.get("manifest") or {}
    return (
        f"private holdout: {st['count']} tasks\n"
        f"  created: {man.get('created_at', '—')}\n"
        f"  seed: {man.get('seed', '—')}\n"
        f"  combined sha256: {st.get('combined_sha256') or '—'}\n"
        f"  archives: {len(st.get('archives') or [])} (latest {st.get('latest_archive') or '—'})"
    )
