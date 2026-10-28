"""The experience library: Le-Gates for text.

Each entry is a cue → lesson mapping with evidence and a calibrated confidence.
Retrieval is capped (one, two, or all) because too many lessons in context is the
text-side analogue of opening two gates. A cue that clears no confidence
threshold returns nothing — the ``don't open the gate`` decision.

Confidence is computed from held-out counts with a Wilson lower bound. A model's
self-reported confidence is never used.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

PRIVATE = "private_holdout"
TOKEN_RE = re.compile(r"[a-z0-9_]+")


def wilson_lower(passes: int, n: int, z: float = 1.96) -> float:
    if n <= 0:
        return 0.0
    p = max(0.0, min(1.0, passes / n))
    d = 1 + z * z / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n)
    return max(0.0, min(1.0, (centre - spread) / d))


def _tokens(value) -> set[str]:
    if isinstance(value, dict):
        value = " ".join(str(v) for v in value.values())
    return set(TOKEN_RE.findall(str(value).lower()))


def cue_match(cue: dict, entry_cue: dict) -> float:
    """Lexical cue match with exact-field boosts.

    The score is deliberately simple and deterministic: a router should be
    auditable before it is clever.
    """
    a, b = _tokens(cue), _tokens(entry_cue)
    if not a or not b:
        return 0.0
    jac = len(a & b) / len(a | b)
    boost = 0.0
    for field in ("skill", "error_class", "kind"):
        av, bv = cue.get(field), entry_cue.get(field)
        if av and bv and str(av).lower() == str(bv).lower():
            boost += 0.15
    return min(1.0, jac + boost)


@dataclass
class Lesson:
    cue: dict
    lesson: str
    evidence: dict
    confidence: float
    harness: str | None = None
    source_split: str = "dev"
    created_at: str = field(default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S"))
    id: str = ""

    def __post_init__(self):
        if not self.id:
            raw = json.dumps([self.cue, self.lesson, self.evidence], sort_keys=True)
            self.id = "les_" + hashlib.sha256(raw.encode()).hexdigest()[:12]

    def to_dict(self) -> dict:
        return dict(id=self.id, cue=self.cue, lesson=self.lesson,
                    evidence=self.evidence, confidence=round(float(self.confidence), 4),
                    harness=self.harness, source_split=self.source_split,
                    created_at=self.created_at)


class Library:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load(self) -> list[Lesson]:
        if not self.path.exists():
            return []
        out = []
        for line in self.path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                out.append(Lesson(**json.loads(line)))
            except (TypeError, ValueError):
                continue
        return out

    def save(self, lessons: list[Lesson]) -> Path:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("".join(json.dumps(x.to_dict()) + "\n" for x in lessons))
        return self.path

    def add(self, lesson: Lesson) -> Lesson:
        self._assert_public(lesson)
        lessons = [x for x in self.load() if x.id != lesson.id]
        lessons.append(lesson)
        self.save(lessons)
        return lesson

    def _assert_public(self, lesson: Lesson) -> None:
        if lesson.source_split == PRIVATE:
            raise PermissionError("private-holdout evidence cannot enter the library")
        blob = json.dumps([lesson.evidence, lesson.lesson, lesson.cue]).lower()
        if PRIVATE in blob:
            raise PermissionError("private-holdout reference found in a lesson")

    def retrieve(self, cue: dict, *, limit: int | str = 1,
                 threshold: float = 0.2, shuffle: bool = False,
                 seed: int = 0) -> list[Lesson]:
        lessons = self.load()
        if shuffle:
            random.Random(seed).shuffle(lessons)
            return lessons[:self._cap(limit)]
        scored = []
        for x in lessons:
            m = cue_match(cue, x.cue)
            if m >= threshold and x.confidence >= threshold:
                scored.append((m + 0.5 * x.confidence, m, x.confidence, x))
        scored.sort(key=lambda t: (-t[0], -t[1], -t[2], t[3].id))
        return [x[3] for x in scored[:self._cap(limit)]]

    @staticmethod
    def _cap(limit: int | str) -> int | None:
        if limit == "all":
            return None
        return max(0, int(limit))

    @staticmethod
    def render(lessons: list[Lesson]) -> str:
        if not lessons:
            return ""
        lines = ["# RETRIEVED LESSONS (evidence-backed; at most a few)"]
        for x in lessons:
            lines += [
                f"## {x.id} · confidence {x.confidence:.2f}",
                f"cue: {json.dumps(x.cue, sort_keys=True)}",
                f"lesson: {x.lesson}",
                f"evidence: {json.dumps(x.evidence, sort_keys=True)}",
            ]
            if x.harness:
                lines.append(f"harness: {x.harness}")
        return "\n".join(lines)

    def from_cue_table(self, cue_table: list[dict], *,
                       source_split: str = "dev") -> list[Lesson]:
        """Import measured cue→harness rows; confidence must be evidence-derived."""
        added = []
        for row in cue_table:
            ev = row.get("evidence") or {}
            passes = int(ev.get("candidate_passes") or 0)
            n = int(ev.get("n") or 0)
            calibrated = wilson_lower(passes, n) if n else 0.0
            lesson = Lesson(
                cue=row.get("cue") or {},
                lesson=row.get("lesson") or (
                    f"for this cue, prefer {row.get('harness')}"),
                evidence=ev,
                confidence=calibrated,
                harness=row.get("harness"),
                source_split=source_split,
            )
            added.append(self.add(lesson))
        return added

    def build_from_contrast(self, cue_table: list[dict], *,
                            source_split: str = "dev_hard") -> tuple[list[Lesson], list[dict]]:
        """Turn a measured cue table into lessons plus a labeled retrieval set."""
        lessons: list[Lesson] = []
        labels: list[dict] = []
        for row in cue_table:
            ev = row.get("evidence") or {}
            passes = int(ev.get("candidate_passes") or 0)
            n = int(ev.get("n") or 0)
            lesson = Lesson(
                cue=row.get("cue") or {},
                lesson=row.get("lesson") or f"prefer {row.get('harness')}",
                evidence=ev,
                confidence=wilson_lower(passes, n),
                harness=row.get("harness"),
                source_split=source_split,
            )
            self.add(lesson)
            lessons.append(lesson)
            labels.append({"cue": row.get("cue") or {}, "lesson_id": lesson.id})
        return lessons, labels

    def benchmark(self, labeled: list[dict], *,
                  limits: tuple = (1, 2, "all"),
                  threshold: float = 0.2) -> dict:
        """Retrieval-only ablation: with, shuffled, and without the library.

        ``precision`` is the fraction of cues whose correct lesson is in the
        retrieved set. ``mrr`` rewards putting it first. This is a retrieval
        measurement, not a claim about generation quality.
        """
        out = {}
        for limit in limits:
            key = str(limit)
            with_hits = shuf_hits = 0
            with_rr = shuf_rr = 0.0
            with_chars = shuf_chars = 0
            for i, item in enumerate(labeled):
                want = item["lesson_id"]
                got = self.retrieve(item["cue"], limit=limit, threshold=threshold)
                ids = [x.id for x in got]
                with_hits += int(want in ids)
                with_rr += (1.0 / (ids.index(want) + 1)) if want in ids else 0.0
                with_chars += len(self.render(got))
                sgot = self.retrieve(item["cue"], limit=limit, threshold=threshold,
                                     shuffle=True, seed=i)
                sids = [x.id for x in sgot]
                shuf_hits += int(want in sids)
                shuf_rr += (1.0 / (sids.index(want) + 1)) if want in sids else 0.0
                shuf_chars += len(self.render(sgot))
            n = max(1, len(labeled))
            out[key] = {
                "with": {"precision": round(with_hits / n, 4),
                         "mrr": round(with_rr / n, 4),
                         "avg_context_chars": round(with_chars / n, 1)},
                "shuffled": {"precision": round(shuf_hits / n, 4),
                             "mrr": round(shuf_rr / n, 4),
                             "avg_context_chars": round(shuf_chars / n, 1)},
                "without": {"precision": 0.0, "mrr": 0.0, "avg_context_chars": 0.0},
            }
        return {"n": len(labeled), "limits": out, "threshold": threshold}


def format_benchmark(result: dict) -> str:
    lines = [f"# Experience library — retrieval benchmark ({result['n']} cues)", "",
             "| limit | condition | precision | MRR | avg context chars |",
             "|---|---|---|---|---|"]
    for limit, arms in result["limits"].items():
        for name in ("with", "shuffled", "without"):
            a = arms[name]
            lines.append(f"| {limit} | {name} | {a['precision']:.2f} | "
                         f"{a['mrr']:.2f} | {a['avg_context_chars']:.0f} |")
    lines += ["", "One lesson vs two vs all is the text-side interference test. "
              "If MRR or precision falls as the cap rises, the extra lesson is "
              "diluting the cue, the analogue of opening a second gate.", ""]
    return "\n".join(lines)
