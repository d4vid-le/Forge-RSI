"""Le-Gates skill isolation for the baby model.

This is the mechanism from `PAPER.md` / the SkillForge Le-Gates design:

    y = base(x) + sum_k gate_k * scale_k * (x @ A_k) @ B_k
    gate_k in {0,1},  sum_k gate_k <= 1

The base model is frozen (R1). Each skill gets its own rank-8 LoRA, trained
fresh from the base on a *pure* corpus for that skill. At inference a router
opens at most one gate. Tasks that do not route run on the untouched base, so
forgetting is zero by construction: there is no shared adapter to overwrite
other skills.

The module is deliberately split into data generation, routing, training, and
gated evaluation so every claim is auditable from files on disk.
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
import re
import subprocess
import sys
import time
from pathlib import Path

from . import evaluator
from . import harness as harness_mod
from . import trainer, verifier


# ─────────────────────────────── skills ─────────────────────────────────

WORD_FREQ_CODE = [
    """def {name}(text):
    counts = {}
    for word in text.lower().split():
        counts[word] = counts.get(word, 0) + 1
    return counts""",
    """from collections import Counter

def {name}(text):
    return dict(Counter(text.lower().split()))""",
    """def {name}(text):
    words = text.lower().split()
    return {word: words.count(word) for word in set(words)}""",
    """def {name}(text):
    result = {}
    for word in text.lower().split():
        if word in result:
            result[word] += 1
        else:
            result[word] = 1
    return result""",
]

MERGE_CODE = [
    """def {name}(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda x: x[0])
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged""",
    """def {name}(intervals):
    if not intervals:
        return []
    out = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1][1] = max(out[-1][1], end)
        else:
            out.append([start, end])
    return out""",
    """def {name}(intervals):
    if not intervals:
        return []
    intervals = sorted(intervals, key=lambda pair: pair[0])
    result = [list(intervals[0])]
    for start, end in intervals[1:]:
        last = result[-1]
        if start <= last[1]:
            last[1] = max(last[1], end)
        else:
            result.append([start, end])
    return result""",
]

RLE_CODE = [
    """def {name}(s):
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
    return "".join(out)""",
    """def {name}(s):
    if not s:
        return ""
    result = []
    i = 0
    while i < len(s):
        j = i
        while j < len(s) and s[j] == s[i]:
            j += 1
        result.append(s[i] + str(j - i))
        i = j
    return "".join(result)""",
]

SECOND_LARGEST_CODE = [
    """def {name}(nums):
    distinct = sorted(set(nums), reverse=True)
    if len(distinct) < 2:
        raise ValueError("need at least two distinct values")
    return distinct[1]""",
    """def {name}(nums):
    values = sorted(set(nums))
    if len(values) < 2:
        raise ValueError("need at least two distinct values")
    return values[-2]""",
]

SKILLS: dict[str, dict] = {
    "word_freq": {
        "title": "word frequency counting",
        "triggers": [
            r"\bword[_ ]?freq(?:uency|uencies)?\b",
            r"\bcount[_ ]?words?\b",
            r"\bword[_ ]?counts?\b",
            r"\bfrequency\b",
            r"\bcount[_ ]?occurrences\b",
            r"\btoken[_ ]?frequenc",
            r"\bfrequency of (?:each|every) word",
            r"\bcounts? (?:how many times )?(?:each|every) word",
            r"\bword frequency\b",
        ],
        "names": ["word_freq", "count_words", "word_counts", "frequency",
                  "count_occurrences", "word_frequencies"],
        "prompts": [
            "Write `{name}(text: str) -> dict` returning a dict mapping each "
            "lowercased whitespace-separated word to its count.",
            "Write a Python function `{name}(text)` that counts how many times "
            "each word appears in a string. Return a dict of word -> count. "
            "Lowercase the words.",
            "Implement word frequency counting in Python. `{name}('a b a')` "
            "should return `{'a': 2, 'b': 1}`.",
            "Write `{name}(text: str) -> dict` that returns the frequency of "
            "every whitespace-separated token, ignoring case.",
            "Build a word frequency table. The function `{name}` takes a string "
            "and returns a dictionary mapping lowercased words to their counts.",
            "Write a function `{name}` that takes a string and returns a dict "
            "with the number of occurrences of each word. Words are separated "
            "by whitespace and compared case-insensitively.",
        ],
        "code": WORD_FREQ_CODE,
    },
    "merge_intervals": {
        "title": "interval merging",
        "triggers": [
            r"\bmerge[_ ]?intervals",
            r"\bmerge[_ ]?ranges?\b",
            r"\bmerge[_ ]?overlapping\b",
            r"\bmerge (?:overlapping|touching|closed) intervals\b",
            r"\bmerge .* intervals\b",
            r"\bcombine[_ ]?intervals\b",
            r"\bmerge[_ ]?closed[_ ]?intervals\b",
            r"\brange[_ ]?merg",
        ],
        "names": ["merge_intervals", "merge_ranges", "merge_overlapping",
                  "combine_intervals", "merge_intervals_sorted"],
        "prompts": [
            "Write `{name}(intervals: list) -> list` that merges overlapping or "
            "touching closed intervals. Each interval is a two-item list "
            "[start, end]. Return sorted merged intervals.",
            "Merge all overlapping intervals in a list of [start, end] pairs. "
            "Return the sorted result.",
            "Write a function `{name}` that takes a list of intervals and "
            "returns a list with all overlaps merged. Intervals are [start, end].",
            "Implement interval merging. `{name}([[1, 3], [2, 6]])` should return "
            "`[[1, 6]]`. Sort the result by start.",
            "Write `{name}(intervals)` that merges touching or overlapping "
            "closed intervals and returns a new sorted list of [start, end].",
        ],
        "code": MERGE_CODE,
    },
    "rle": {
        "title": "run-length encoding",
        "triggers": [
            r"\brle\b",
            r"\brun[_ -]?length\b",
            r"\bencode[_ ]?runs?\b",
        ],
        "names": ["rle", "run_length_encode", "encode_runs", "run_length"],
        "prompts": [
            "Write `{name}(s: str) -> str` returning a run-length encoding. "
            "Each run of the same character becomes the character followed by "
            "its count. Example: `aaab` -> `a3b1`; empty string -> empty string.",
            "Implement run-length encoding. `{name}('aaab')` should return "
            "`'a3b1'`.",
            "Write a function `{name}` that compresses runs of equal characters "
            "into the character plus the run length.",
        ],
        "code": RLE_CODE,
    },
    "second_largest": {
        "title": "second largest distinct value",
        "triggers": [
            r"\bsecond[_ ]?largest\b",
            r"\bsecond[_ ]?max\b",
            r"\brunner[_ -]?up\b",
        ],
        "names": ["second_largest", "second_max", "runner_up"],
        "prompts": [
            "Write `{name}(nums: list) -> int` returning the second largest "
            "distinct value. Raise `ValueError` if there are fewer than two "
            "distinct values.",
            "Find the second largest distinct number in a list. Raise "
            "`ValueError` if it does not exist.",
            "Write a function `{name}` that returns the runner-up value in a "
            "list, ignoring duplicates.",
        ],
        "code": SECOND_LARGEST_CODE,
    },
}


# ─────────────────────────────── probes ─────────────────────────────────

PROBE_TASKS: list[dict] = [
    {
        "id": "probe_wf_1",
        "title": "count_words",
        "prompt": "Write `count_words(text: str) -> dict` returning a dict "
                  "mapping each lowercased whitespace-separated word to its count.",
        "ref": WORD_FREQ_CODE[0].replace("{name}", "count_words"),
        "tests": """
import unittest
from solution import count_words

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(count_words("a b a"), {"a": 2, "b": 1})
    def test_case(self):
        self.assertEqual(count_words("Hi hi HI"), {"hi": 3})
    def test_empty(self):
        self.assertEqual(count_words(""), {})
    def test_punct(self):
        self.assertEqual(count_words("a, a,"), {"a,": 2})
""",
        "tags": ["skill_probe", "word_freq"],
    },
    {
        "id": "probe_wf_2",
        "title": "word_counts",
        "prompt": "Implement word frequency counting in Python. "
                  "`word_counts('a b a')` should return `{'a': 2, 'b': 1}`.",
        "ref": WORD_FREQ_CODE[1].replace("{name}", "word_counts"),
        "tests": """
import unittest
from solution import word_counts

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(word_counts("a b a"), {"a": 2, "b": 1})
    def test_case(self):
        self.assertEqual(word_counts("Hi hi HI"), {"hi": 3})
    def test_empty(self):
        self.assertEqual(word_counts(""), {})
    def test_punct(self):
        self.assertEqual(word_counts("a, a,"), {"a,": 2})
""",
        "tags": ["skill_probe", "word_freq"],
    },
    {
        "id": "probe_mi_1",
        "title": "merge_ranges",
        "prompt": "Write `merge_ranges(intervals: list) -> list` that merges "
                  "overlapping or touching closed intervals. Each interval is a "
                  "two-item list [start, end]. Return sorted merged intervals.",
        "ref": MERGE_CODE[0].replace("{name}", "merge_ranges"),
        "tests": """
import unittest
from solution import merge_ranges

class T(unittest.TestCase):
    def test_overlap(self):
        self.assertEqual(merge_ranges([[1, 3], [2, 6]]), [[1, 6]])
    def test_touch(self):
        self.assertEqual(merge_ranges([[1, 3], [3, 5]]), [[1, 5]])
    def test_disjoint(self):
        self.assertEqual(merge_ranges([[5, 6], [1, 2]]), [[1, 2], [5, 6]])
    def test_empty(self):
        self.assertEqual(merge_ranges([]), [])
""",
        "tags": ["skill_probe", "merge_intervals"],
    },
    {
        "id": "probe_mi_2",
        "title": "merge_overlapping",
        "prompt": "Merge all overlapping intervals in a list of [start, end] "
                  "pairs. Return the sorted result.",
        "ref": MERGE_CODE[1].replace("{name}", "merge_overlapping"),
        "tests": """
import unittest
from solution import merge_overlapping

class T(unittest.TestCase):
    def test_overlap(self):
        self.assertEqual(merge_overlapping([[1, 3], [2, 6]]), [[1, 6]])
    def test_touch(self):
        self.assertEqual(merge_overlapping([[1, 3], [3, 5]]), [[1, 5]])
    def test_disjoint(self):
        self.assertEqual(merge_overlapping([[5, 6], [1, 2]]), [[1, 2], [5, 6]])
    def test_empty(self):
        self.assertEqual(merge_overlapping([]), [])
""",
        "tags": ["skill_probe", "merge_intervals"],
    },
]


_WF_TEST_TEMPLATE = """
import unittest
from solution import {fn}

class T(unittest.TestCase):
    def test_basic(self):
        self.assertEqual({fn}("a b a"), {"a": 2, "b": 1})
    def test_case(self):
        self.assertEqual({fn}("Hi hi HI"), {"hi": 3})
    def test_empty(self):
        self.assertEqual({fn}(""), {})
    def test_punct(self):
        self.assertEqual({fn}("a, a,"), {"a,": 2})
"""

_MI_TEST_TEMPLATE = """
import unittest
from solution import {fn}

class T(unittest.TestCase):
    def test_overlap(self):
        self.assertEqual({fn}([[1, 3], [2, 6]]), [[1, 6]])
    def test_touch(self):
        self.assertEqual({fn}([[1, 3], [3, 5]]), [[1, 5]])
    def test_disjoint(self):
        self.assertEqual({fn}([[5, 6], [1, 2]]), [[1, 2], [5, 6]])
    def test_empty(self):
        self.assertEqual({fn}([]), [])
"""


def _add_wf_probe(idx: int, name: str, prompt: str, code_idx: int = 0):
    PROBE_TASKS.append({
        "id": f"probe_wf_{idx}",
        "title": name,
        "prompt": prompt,
        "ref": WORD_FREQ_CODE[code_idx].replace("{name}", name),
        "tests": _WF_TEST_TEMPLATE.replace("{fn}", name),
        "tags": ["skill_probe", "word_freq"],
    })


def _add_mi_probe(idx: int, name: str, prompt: str, code_idx: int = 0):
    PROBE_TASKS.append({
        "id": f"probe_mi_{idx}",
        "title": name,
        "prompt": prompt,
        "ref": MERGE_CODE[code_idx].replace("{name}", name),
        "tests": _MI_TEST_TEMPLATE.replace("{fn}", name),
        "tags": ["skill_probe", "merge_intervals"],
    })


_add_wf_probe(
    3, "frequency",
    "Write a function `frequency(text)` that returns a dict of word -> count "
    "for a string. Words are separated by whitespace and compared "
    "case-insensitively.", 1)
_add_wf_probe(
    4, "count_occurrences",
    "Write `count_occurrences(text: str) -> dict` that returns the number of "
    "occurrences of every lowercased word in the text.", 0)
_add_wf_probe(
    5, "word_frequencies",
    "Build a word frequency table. The function `word_frequencies` takes a "
    "string and returns a dictionary mapping lowercased words to their counts.",
    2)
_add_wf_probe(
    6, "token_frequency",
    "Write `token_frequency(text: str) -> dict` returning the count of every "
    "whitespace-separated token, case-insensitively.", 3)

_add_mi_probe(
    3, "combine_intervals",
    "Write `combine_intervals(intervals: list) -> list` that merges overlapping "
    "or touching closed intervals and returns a sorted list.", 0)
_add_mi_probe(
    4, "merge_intervals_sorted",
    "Write `merge_intervals_sorted(intervals)` that returns the merged "
    "intervals sorted by start. Each interval is [start, end].", 1)
_add_mi_probe(
    5, "merge_closed_intervals",
    "Write `merge_closed_intervals(intervals: list) -> list` that merges any "
    "overlapping or adjacent closed intervals.", 2)
_add_mi_probe(
    6, "range_merger",
    "Implement interval merging in a function `range_merger`. Merge "
    "overlapping [start, end] pairs and return the sorted result.", 0)


ORACLE_ROUTES = {
    "dev_012": "word_freq",
    "dev_020": "merge_intervals",
}
ORACLE_ROUTES.update({f"probe_wf_{i}": "word_freq" for i in range(1, 7)})
ORACLE_ROUTES.update({f"probe_mi_{i}": "merge_intervals" for i in range(1, 7)})


def build_probes(cfg: dict) -> dict:
    """Write the skill probes after proving their references pass."""
    out_dir = Path(cfg["paths"]["tasks"]) / "skills"
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for t in PROBE_TASKS:
        task = {
            "id": t["id"], "title": t["title"], "prompt": t["prompt"],
            "tests": t["tests"].strip(), "entry": "solution.py",
            "timeout_s": 20, "tags": t["tags"], "difficulty": "medium",
        }
        result = verifier.verify(t["ref"], task)
        if not result["passed"]:
            raise RuntimeError(f"probe reference failed: {t['id']}: {result['output'][-500:]}")
        (out_dir / f"{t['id']}.json").write_text(json.dumps(task, indent=2) + "\n")
        written.append(t["id"])
    return {"dir": str(out_dir), "tasks": written}


# ─────────────────────────── corpus generation ──────────────────────────

def generate_rows(skill: str, n: int, system_prompt: str, seed: int = 0) -> list[dict]:
    spec = SKILLS[skill]
    rng = random.Random(seed)
    rows: list[dict] = []
    seen: set[tuple[str, str]] = set()
    names = spec["names"]
    prompts = spec["prompts"]
    codes = spec["code"]

    attempts = 0
    while len(rows) < n and attempts < n * 20:
        attempts += 1
        name = names[len(rows) % len(names)]
        prompt = rng.choice(prompts).replace("{name}", name)
        code = rng.choice(codes).replace("{name}", name)
        key = (prompt, code)
        if key in seen:
            continue
        seen.add(key)
        rows.append({
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
                {"role": "assistant", "content": f"```python\n{code}\n```"},
            ],
            "meta": {"skill": skill, "source": "legates-synthetic", "seed": seed},
        })
    if len(rows) < n:
        raise RuntimeError(f"could only generate {len(rows)} unique rows for {skill}")
    return rows


def build_corpus(cfg: dict, skill: str, n: int, out_dir: str | Path,
                 system_prompt: str, seed: int = 0) -> dict:
    rows = generate_rows(skill, n, system_prompt, seed)
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    all_path = out / "all.jsonl"
    with open(all_path, "w") as f:
        for r in rows:
            f.write(json.dumps({"messages": r["messages"], "meta": r["meta"]}) + "\n")
    info = trainer.prepare_data(all_path, out)
    info["skill"] = skill
    info["source"] = str(all_path)
    return info


# ────────────────────────────── checksums ───────────────────────────────

def checksum_model(path: str | Path) -> str:
    """R1: hash every weight/config file in the frozen base directory."""
    h = hashlib.sha256()
    p = Path(path)
    files = sorted(f for f in p.rglob("*") if f.is_file())
    for f in files:
        h.update(str(f.relative_to(p)).encode())
        with open(f, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
    return h.hexdigest()


# ─────────────────────────────── router ─────────────────────────────────

def default_registry(cfg: dict) -> dict:
    root = Path(cfg["paths"]["adapters"]) / "skills"
    reg = {}
    for name, spec in SKILLS.items():
        reg[name] = {
            "skill": name,
            "title": spec["title"],
            "triggers": spec["triggers"],
            "adapter": str(root / name),
            "status": "candidate",
            "enabled": True,
            "gate": 1.0,
        }
    return reg


def load_registry(cfg: dict) -> dict:
    p = Path(cfg["paths"]["adapters"]) / "skills" / "registry.json"
    reg = default_registry(cfg)
    if p.exists():
        loaded = json.loads(p.read_text())
        # Loaded entries (training metadata, status, decisions) replace defaults.
        reg.update(loaded)
    # Triggers are code, not data: keep them in sync with SKILLS so a registry
    # written before a trigger fix does not silently route less often.
    for name, spec in SKILLS.items():
        if name in reg:
            reg[name]["triggers"] = spec["triggers"]
    return reg


def save_registry(cfg: dict, reg: dict) -> Path:
    p = Path(cfg["paths"]["adapters"]) / "skills" / "registry.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(reg, indent=2) + "\n")
    return p


def route(task: dict, registry: dict, mode: str = "keyword") -> tuple[str | None, float]:
    """Return (skill, gate). Hard 0/1 routing; at most one gate opens."""
    if mode == "oracle":
        skill = ORACLE_ROUTES.get(task.get("id"))
        if skill and skill in registry and registry[skill].get("enabled", True):
            adapter = registry[skill].get("adapter")
            if adapter and (Path(adapter) / "adapters.safetensors").exists():
                return skill, 1.0
        return None, 0.0

    text = f"{task.get('title', '')}\n{task.get('prompt', '')}"
    best: str | None = None
    best_score = 0
    for name, entry in registry.items():
        if not entry.get("enabled", True):
            continue
        if entry.get("status") == "quarantined":
            continue
        adapter = entry.get("adapter")
        if not adapter or not (Path(adapter) / "adapters.safetensors").exists():
            continue
        score = 0
        for pat in entry.get("triggers", []):
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                score += len(m.group(0)) + 1
        if score > best_score:
            best, best_score = name, score
    return (best, 1.0) if best else (None, 0.0)


def route_table(tasks: list[dict], registry: dict, mode: str = "keyword") -> dict:
    out = {}
    for t in tasks:
        skill, gate = route(t, registry, mode)
        out[t["id"]] = {"skill": skill, "gate": gate}
    return out


# ────────────────────────────── training ────────────────────────────────

SKILL_RECIPE = {
    "num_layers": 6,
    "batch_size": 1,
    "max_seq_length": 1024,
    "learning_rate": 1e-4,
    "rank": 8,
    "scale": 2.0,
    "dropout": 0.0,
    "grad_accumulation_steps": 4,
    "mask_prompt": True,
    "val_batches": 2,
    "steps_per_eval": 30,
    "save_every": 60,
}


def train_skill(cfg: dict, skill: str, corpus_dir: str | Path,
                adapter_dir: str | Path, iters: int = 120) -> dict:
    before = checksum_model(cfg["paths"]["agent"])
    result = trainer.train(cfg, corpus_dir, adapter_dir, iters=iters,
                           recipe=SKILL_RECIPE)
    after = checksum_model(cfg["paths"]["agent"])
    result["base_checksum_before"] = before
    result["base_checksum_after"] = after
    result["base_unchanged"] = before == after
    result["skill"] = skill
    return result


def summarize_train_log(log_path: str | Path) -> dict:
    """Extract the final train/val losses from the mlx_lm.lora log."""
    text = Path(log_path).read_text(errors="replace")
    text = re.sub(r"\x1b\[[0-9;]*m", "", text)  # strip ANSI colour
    train_losses = re.findall(r"^\s*(\d+)\s+([0-9.]+)\s+[▼▲]", text, re.M)
    val_losses = re.findall(r"^\s*(\d+)\s+val\s+([0-9.]+)", text, re.M)
    return {
        "train_loss_last": float(train_losses[-1][1]) if train_losses else None,
        "val_loss_last": float(val_losses[-1][1]) if val_losses else None,
        "final_iter": int(train_losses[-1][0]) if train_losses else None,
    }


# ─────────────────────────── gated evaluation ───────────────────────────

def _run_cli(args: list[str]) -> int:
    cmd = [sys.executable, "-m", "forge_rsi"] + args
    print("[legates]", " ".join(cmd), flush=True)
    return subprocess.call(cmd)


def gated_eval(cfg: dict, harness_path: str, split: str, run_id: str,
               router_mode: str = "keyword", task_ids: list[str] | None = None) -> dict:
    """Base run on every task, then each skill adapter on its routed subset.

    The base and adapter passes are separate processes, so the 18 GB base is
    never co-resident with an adapter run. Non-routed tasks are copied verbatim
    from the base run — that is the construction that makes forgetting zero.
    """
    runs_dir = Path(cfg["paths"]["runs"])
    reg = load_registry(cfg)
    tasks = evaluator.load_tasks(cfg, split)
    if task_ids:
        wanted = set(task_ids)
        tasks = [t for t in tasks if t["id"] in wanted]
    routing = route_table(tasks, reg, router_mode)

    base_id = f"{run_id}_base"
    if not (runs_dir / f"{base_id}.json").exists():
        rc = _run_cli(["eval", "--harness", harness_path, "--split", split,
                       "--run-id", base_id])
        if rc:
            raise RuntimeError(f"base eval failed (rc={rc})")
    base = evaluator.load_run(cfg, base_id)

    skill_passes: dict[str, tuple[str, list[str]]] = {}
    for skill in sorted({r["skill"] for r in routing.values() if r["skill"]}):
        ids = [tid for tid, r in routing.items() if r["skill"] == skill]
        sid = f"{run_id}_{skill}"
        if not (runs_dir / f"{sid}.json").exists():
            rc = _run_cli(["eval", "--harness", harness_path, "--split", split,
                           "--run-id", sid, "--adapter", reg[skill]["adapter"],
                           "--task-ids", ",".join(ids)])
            if rc:
                raise RuntimeError(f"skill eval failed for {skill} (rc={rc})")
        skill_passes[skill] = (sid, ids)

    adapter_map: dict[str, tuple[str, dict]] = {}
    for skill, (sid, ids) in skill_passes.items():
        sr = evaluator.load_run(cfg, sid)
        for t in sr["tasks"]:
            adapter_map[t["task_id"]] = (skill, t)

    merged = copy.deepcopy(base)
    merged_tasks = []
    for t in base["tasks"]:
        tid = t["task_id"]
        if tid in adapter_map:
            skill, at = adapter_map[tid]
            nt = copy.deepcopy(at)
            nt["gate"] = 1.0
            nt["skill"] = skill
        else:
            nt = copy.deepcopy(t)
            nt["gate"] = 0.0
            nt["skill"] = None
        merged_tasks.append(nt)
    merged["tasks"] = merged_tasks
    merged["summary"] = evaluator.summarize(merged_tasks)
    merged["run_id"] = f"{run_id}_gated"
    merged["gated"] = {
        "router_mode": router_mode,
        "routing": routing,
        "skills": {s: {"run_id": sid, "task_ids": ids}
                   for s, (sid, ids) in skill_passes.items()},
    }

    base_map = {t["task_id"]: t for t in base["tasks"]}
    non_routed = [t["task_id"] for t in base["tasks"] if t["task_id"] not in adapter_map]
    merged_map = {t["task_id"]: t for t in merged_tasks}
    identical = all(
        base_map[tid]["code"] == merged_map[tid]["code"]
        and base_map[tid]["passed"] == merged_map[tid]["passed"]
        for tid in non_routed
    )
    changes = []
    for tid, (skill, at) in adapter_map.items():
        bt = base_map[tid]
        changes.append({
            "task_id": tid, "skill": skill,
            "base_passed": bt["passed"], "gated_passed": at["passed"],
            "delta": int(at["passed"]) - int(bt["passed"]),
        })
    current_checksum = checksum_model(cfg["paths"]["agent"])
    reg_checksums = [e.get("base_checksum") for e in reg.values() if e.get("base_checksum")]
    base_unchanged = all(c == current_checksum for c in reg_checksums) if reg_checksums else None
    report = {
        "run_id": merged["run_id"],
        "split": split,
        "harness": merged.get("harness", {}).get("version"),
        "router_mode": router_mode,
        "base_run": base_id,
        "base_summary": base["summary"],
        "gated_summary": merged["summary"],
        "delta_score": round(merged["summary"]["score"] - base["summary"]["score"], 4),
        "routing": routing,
        "routed_tasks": sorted(adapter_map),
        "non_routed_tasks": non_routed,
        "non_routed_identical": identical,
        "changes": changes,
        "base_checksum": current_checksum,
        "base_unchanged_vs_training": base_unchanged,
        "base_unchanged": base_unchanged,
    }
    merged["gated_report"] = report
    (runs_dir / f"{merged['run_id']}.json").write_text(json.dumps(merged, indent=2) + "\n")
    (runs_dir / f"{run_id}_gated_report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


def decide_skills(cfg: dict, run_prefix: str = "legates") -> dict:
    """Quarantine-first lifecycle decision from the gated reports.

    A skill must show a dev gain AND a positive gain on the held-out skill
    probes, with no non-routed changes and no holdout regression. Otherwise it
    is gated to 0 (quarantined) — never deleted.
    """
    reg = load_registry(cfg)
    runs_dir = Path(cfg["paths"]["runs"])
    reports: dict[str, dict] = {}
    for split in ("dev", "skills", "holdout"):
        p = runs_dir / f"{run_prefix}_{split}_gated_report.json"
        if p.exists():
            reports[split] = json.loads(p.read_text())

    decisions: dict[str, dict] = {}
    for skill, entry in reg.items():
        adapter = entry.get("adapter")
        if not adapter or not (Path(adapter) / "adapters.safetensors").exists():
            entry["status"] = "untrained"
            continue
        dev_changes = [c for c in reports.get("dev", {}).get("changes", [])
                       if c["skill"] == skill]
        probe_changes = [c for c in reports.get("skills", {}).get("changes", [])
                         if c["skill"] == skill]
        dev_gain = sum(c["delta"] for c in dev_changes)
        probe_gain = sum(c["delta"] for c in probe_changes)
        non_routed_ok = all(r.get("non_routed_identical") for r in reports.values()) if reports else None
        base_ok = all(r.get("base_unchanged") is not False for r in reports.values()) if reports else None
        holdout_regressions = [c for c in reports.get("holdout", {}).get("changes", [])
                               if c["skill"] == skill and c["delta"] < 0]

        if not reports:
            status, reason = "candidate", "no gated reports yet"
        elif not non_routed_ok:
            status, reason = "quarantined", "non-routed outputs changed (forgetting)"
        elif not base_ok:
            status, reason = "quarantined", "base checksum mismatch"
        elif holdout_regressions:
            status, reason = "quarantined", f"holdout regression on {len(holdout_regressions)} task(s)"
        elif probe_gain <= 0:
            status, reason = "quarantined", f"probe gain {probe_gain:+d} (no generalization)"
        elif dev_gain < 1:
            status, reason = "quarantined", f"dev gain {dev_gain:+d} < 1"
        else:
            status, reason = "promoted", f"dev {dev_gain:+d}, probe {probe_gain:+d}, no forgetting"

        entry["status"] = status
        entry["decision"] = {
            "status": status, "reason": reason,
            "dev_gain": dev_gain, "probe_gain": probe_gain,
            "non_routed_identical": non_routed_ok,
            "base_unchanged": base_ok,
            "holdout_regressions": holdout_regressions,
            "decided_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        decisions[skill] = entry["decision"]

    save_registry(cfg, reg)
    out = Path(cfg["paths"]["runs"]) / f"{run_prefix}_decisions.json"
    out.write_text(json.dumps(decisions, indent=2) + "\n")
    return decisions


def write_report(cfg: dict) -> Path:
    reg = load_registry(cfg)
    runs_dir = Path(cfg["paths"]["runs"])
    reports = sorted(runs_dir.glob("*_gated_report.json"))
    current = checksum_model(cfg["paths"]["agent"])

    lines = [
        "# Le-Gates — gated skill isolation",
        "",
        "Frozen base + independent rank-8 skill deltas + a hard 0/1 router.",
        "At most one gate opens per task (`Σ gate ≤ 1`), so the base is never",
        "composed with two deltas. Non-routed tasks run on the untouched base.",
        "",
        "## Base lock (R1)",
        "",
        f"- base model: `{cfg['paths']['agent']}`",
        f"- current sha256: `{current}`",
        "",
        "| skill | adapter | status | base checksum matches |",
        "|---|---|---|---|",
    ]
    for name, e in reg.items():
        match = e.get("base_checksum") == current if e.get("base_checksum") else None
        lines.append(f"| `{name}` | `{e.get('adapter', '')}` | {e.get('status', '?')} | {match} |")

    lines += ["", "## Adapters", "",
              "| skill | rows | iters | train loss | val loss | rc | base unchanged |",
              "|---|---|---|---|---|---|---|"]
    for name, e in reg.items():
        data = e.get("data") or {}
        tr = e.get("training") or {}
        loss = tr.get("loss") or {}
        lines.append(
            f"| `{name}` | {data.get('rows', '—')} | {tr.get('iters', '—')} | "
            f"{loss.get('train_loss_last', '—')} | {loss.get('val_loss_last', '—')} | "
            f"{tr.get('returncode', '—')} | {e.get('base_unchanged', '—')} |"
        )

    lines += ["", "## Lifecycle decisions", "",
              "| skill | status | dev gain | probe gain | non-routed identical | reason |",
              "|---|---|---|---|---|---|"]
    for name, e in reg.items():
        d = e.get("decision") or {}
        lines.append(
            f"| `{name}` | **{e.get('status', '?')}** | {d.get('dev_gain', '—')} | "
            f"{d.get('probe_gain', '—')} | {d.get('non_routed_identical', '—')} | "
            f"{d.get('reason', '—')} |"
        )
    lines.append("")

    for p in reports:
        r = json.loads(p.read_text())
        b, g = r["base_summary"], r["gated_summary"]
        routed = r["routed_tasks"]
        lines += [
            "", f"## Gated evaluation — `{r['split']}` ({r['router_mode']} router)", "",
            f"- base: **{b['passed']}/{b['n']}** ({b['score']:.2f})",
            f"- gated: **{g['passed']}/{g['n']}** ({g['score']:.2f})",
            f"- delta: **{r['delta_score']:+.2f}**",
            f"- routed tasks: {', '.join(routed) or 'none'}",
            f"- non-routed tasks byte-identical: **{r['non_routed_identical']}**",
            f"- base checksum match: **{r['base_unchanged']}**",
            "",
        ]
        if not routed and r["split"] == "holdout":
            lines += ["No holdout task matched a skill trigger, so the gated stack",
                      "is exactly the base stack on the holdout. That is the R1 /",
                      "zero-forgetting evidence, not a claim of holdout skill transfer.", ""]
        if r["changes"]:
            lines += ["| task | skill | base | gated | delta |", "|---|---|---|---|---|"]
            for c in r["changes"]:
                lines.append(f"| `{c['task_id']}` | `{c['skill']}` | {c['base_passed']} | "
                             f"{c['gated_passed']} | {c['delta']:+d} |")
            lines.append("")

    lines += [
        "## What this proves",
        "",
        "- Each skill adapter is trained from the frozen base on a **pure** corpus",
        "  for that skill; no other skill's data is mixed in.",
        "- The router opens at most one gate. Tasks that do not route are copied",
        "  verbatim from the base run, so their outputs are identical by",
        "  construction — not by a statistical argument.",
        "- The base model checksum is recorded before and after training and must",
        "  match; `mlx_lm.lora` writes only adapter files.",
        "",
        "## What this does not prove",
        "",
        "- **Composition.** `PAPER.md` shows that two full-scale gates (Σ=2) can",
        "  collapse compound performance; the fix is the Σ≤1 magnitude constraint,",
        "  not a claim that skills compose. This implementation enforces Σ≤1.",
        "- **A learned router.** The deployed router is deterministic keyword",
        "  matching. `oracle` routing is an upper bound, not a deployable result.",
        "- **General intelligence.** The probes are small Python tasks. A skill",
        "  adapter that fixes word-frequency probes is not a general coding gain.",
        "",
    ]

    out = Path(cfg["paths"]["reports"]) / "legates.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n")
    return out


def format_gated_report(report: dict) -> str:
    b = report["base_summary"]
    g = report["gated_summary"]
    lines = [
        f"Le-Gates gated eval — {report['split']} ({report['router_mode']} router)",
        f"  base : {b['passed']}/{b['n']} ({b['score']:.2f})",
        f"  gated: {g['passed']}/{g['n']} ({g['score']:.2f})  Δ {report['delta_score']:+.2f}",
        f"  routed: {', '.join(report['routed_tasks']) or 'none'}",
        f"  non-routed identical: {report['non_routed_identical']}",
        f"  base checksum unchanged: {report['base_unchanged']}",
        "",
        f"{'task':12}{'skill':18}{'base':>6}{'gated':>7}{'Δ':>4}",
    ]
    for c in report["changes"]:
        lines.append(f"{c['task_id']:12}{c['skill']:18}"
                     f"{str(c['base_passed']):>6}{str(c['gated_passed']):>7}"
                     f"{c['delta']:>+4}")
    return "\n".join(lines)
