#!/usr/bin/env python3
"""Lint task prompts against the names their hidden tests import.

A benchmark task must tell the model which function name to define. If the
tests import `merge_overlapping` but the prompt never says that name, the task
is under-specified and the failure is a benchmark bug, not a model failure.

Run:
    python3 tasks/lint_tasks.py
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SPLITS = ("dev", "dev_hard", "holdout", "skills", "composition", "private_holdout")


def imported_names(tests: str) -> list[str]:
    names: list[str] = []
    for chunk in re.findall(r"from solution import ([A-Za-z0-9_, ]+)", tests):
        for name in chunk.split(","):
            name = name.strip()
            if name and name not in names:
                names.append(name)
    return names


def main() -> int:
    failures = 0
    total = 0
    for split in SPLITS:
        d = ROOT / split
        if not d.exists():
            continue
        for p in sorted(d.glob("*.json")):
            total += 1
            task = json.loads(p.read_text())
            wanted = imported_names(task.get("tests", ""))
            if not wanted:
                print(f"[FAIL] {split}/{task.get('id')}: tests import no solution name")
                failures += 1
                continue
            missing = [n for n in wanted if not re.search(rf"\b{re.escape(n)}\b", task.get("prompt", ""))]
            if missing:
                print(f"[FAIL] {split}/{task.get('id')}: prompt omits {missing}")
                failures += 1
    print(f"linted {total} tasks; failures={failures}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
