"""Cost accounting for H2 experiments.

Every model call, rollout, token, and second is recorded. The ledger is written
to disk with the experiment so a gain can be read per call, per token, and per
wall-clock second — not just per round.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Entry:
    kind: str
    label: str
    calls: int = 1
    tokens_in: int = 0
    tokens_out: int = 0
    wall_s: float = 0.0
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return dict(
            kind=self.kind, label=self.label, calls=self.calls,
            tokens_in=self.tokens_in, tokens_out=self.tokens_out,
            wall_s=round(self.wall_s, 3), meta=self.meta,
        )


class Ledger:
    """Append-only accounting for one experiment."""

    def __init__(self, name: str):
        self.name = name
        self.entries: list[Entry] = []
        self.started = time.time()

    def add(self, kind: str, label: str, *, calls: int = 1,
            tokens_in: int = 0, tokens_out: int = 0,
            wall_s: float = 0.0, **meta) -> Entry:
        e = Entry(kind=kind, label=label, calls=int(calls),
                  tokens_in=int(tokens_in), tokens_out=int(tokens_out),
                  wall_s=float(wall_s), meta=dict(meta))
        self.entries.append(e)
        return e

    def add_run(self, label: str, run: dict, kind: str = "rollout") -> Entry:
        s = run.get("summary") or {}
        return self.add(kind, label,
                        calls=len(run.get("tasks") or []) or 1,
                        tokens_in=int(s.get("tokens_in") or 0),
                        tokens_out=int(s.get("tokens_out") or 0),
                        wall_s=float(s.get("wall_s") or 0.0),
                        score=s.get("score"), passed=s.get("passed"), n=s.get("n"))

    def merged(self, other: "Ledger") -> "Ledger":
        out = Ledger(self.name)
        out.entries = list(self.entries) + list(other.entries)
        out.started = min(self.started, other.started)
        return out

    @property
    def calls(self) -> int:
        return sum(e.calls for e in self.entries)

    @property
    def tokens_in(self) -> int:
        return sum(e.tokens_in for e in self.entries)

    @property
    def tokens_out(self) -> int:
        return sum(e.tokens_out for e in self.entries)

    @property
    def tokens(self) -> int:
        return self.tokens_in + self.tokens_out

    @property
    def wall_s(self) -> float:
        return round(sum(e.wall_s for e in self.entries), 3)

    def by_kind(self) -> dict:
        out: dict[str, dict] = {}
        for e in self.entries:
            b = out.setdefault(e.kind, dict(calls=0, tokens_in=0, tokens_out=0,
                                            wall_s=0.0, entries=0))
            b["calls"] += e.calls
            b["tokens_in"] += e.tokens_in
            b["tokens_out"] += e.tokens_out
            b["wall_s"] = round(b["wall_s"] + e.wall_s, 3)
            b["entries"] += 1
        return out

    def gain_per(self, gain: float) -> dict:
        """A gain in dev tasks normalised by each cost unit."""
        return {
            "gain": round(gain, 4),
            "per_call": round(gain / self.calls, 6) if self.calls else None,
            "per_1k_tokens": round(gain / (self.tokens / 1000), 6) if self.tokens else None,
            "per_wall_s": round(gain / self.wall_s, 6) if self.wall_s else None,
        }

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "started": time.strftime("%Y-%m-%dT%H:%M:%S",
                                     time.localtime(self.started)),
            "calls": self.calls,
            "tokens_in": self.tokens_in,
            "tokens_out": self.tokens_out,
            "tokens": self.tokens,
            "wall_s": self.wall_s,
            "by_kind": self.by_kind(),
            "entries": [e.to_dict() for e in self.entries],
        }

    def write(self, path: str | Path) -> Path:
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        return p
