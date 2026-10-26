"""
SkillForge pipeline — ingestion.

Takes any number of downloaded files (JSON arrays, JSONL, nested containers,
globs, whole directories) and produces one uniform stream of records.

Design rules:
  * Never silently drop a row. Anything that cannot be normalised is returned
    with a reason so it can be quarantined and reviewed.
  * Provenance is preserved (file + line/element index) so any row in the
    review UI can be traced back to its origin.
  * Schema detection is explicit and reported — you always know what the
    importer thought each file contained.
"""

from __future__ import annotations

import glob
import json
import os
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .schema import (
    Record, looks_like_chatml, normalize_messages, parse_chatml,
)

# containers commonly used to wrap a dataset
CONTAINER_KEYS = ("data", "rows", "examples", "samples", "instances", "items",
                  "records", "train", "dataset", "entries", "conversations",
                  "messages", "chats")

# field-name pairs that mean (user, assistant)
PAIR_KEYS = (
    ("prompt", "response"), ("prompt", "completion"), ("prompt", "output"),
    ("instruction", "output"), ("instruction", "response"),
    ("question", "answer"), ("query", "response"), ("query", "answer"),
    ("input", "output"), ("problem", "solution"), ("human", "assistant"),
)

SKIP_NAMES = {".DS_Store", ".gitattributes", ".gitignore", "README.md"}


@dataclass
class IngestOptions:
    domain: str | None = None          # override; else inferred from filename
    text_field: str = "text"           # field holding ChatML/raw text
    keep_raw_text: bool = False        # keep unstructured prose rows
    max_file_mb: float = 4096.0


@dataclass
class FileReport:
    path: str
    kind: str = "?"                    # json-array | jsonl | json-object
    rows_seen: int = 0
    rows_kept: int = 0
    schemas: Counter = field(default_factory=Counter)
    failures: Counter = field(default_factory=Counter)

    def to_dict(self) -> dict:
        return dict(path=self.path, kind=self.kind, rows_seen=self.rows_seen,
                    rows_kept=self.rows_kept, schemas=dict(self.schemas),
                    failures=dict(self.failures))


# ── path handling ───────────────────────────────────────────────────────────

def expand_paths(inputs: list[str]) -> list[str]:
    """Expand files, globs and directories into a sorted list of data files."""
    out: list[str] = []
    for raw in inputs:
        p = Path(os.path.expanduser(raw))
        if p.is_dir():
            for ext in ("*.jsonl", "*.json"):
                out.extend(str(x) for x in sorted(p.rglob(ext)))
        elif any(ch in raw for ch in "*?["):
            out.extend(sorted(glob.glob(os.path.expanduser(raw), recursive=True)))
        elif p.exists():
            out.append(str(p))
        else:
            raise FileNotFoundError(f"input not found: {raw}")
    # de-duplicate while preserving order, skip junk
    seen, final = set(), []
    for f in out:
        if os.path.basename(f) in SKIP_NAMES or f in seen:
            continue
        seen.add(f)
        final.append(f)
    if not final:
        raise FileNotFoundError("no .json/.jsonl data files found in the given inputs")
    return final


def infer_domain(path: str, override: str | None) -> str:
    if override:
        return override
    stem = Path(path).stem
    for pref in ("train_", "test_", "valid_", "val_", "eval_", "part_", "shard_"):
        if stem.startswith(pref):
            stem = stem[len(pref):]
    # strip trailing _v2, -00001-of-00003 etc.
    stem = stem.split("-of-")[0].rstrip("_-")
    return stem or "unknown"


# ── file readers ────────────────────────────────────────────────────────────

def sniff_kind(path: str) -> str:
    """Decide whether a file is JSONL or a JSON document."""
    with open(path, "rb") as f:
        head = f.read(65536)
    text = head.decode("utf-8", "replace").lstrip()   # bytes -> str, or the
    if not text:                                      # comparisons below lie
        return "empty"
    if path.endswith(".jsonl"):
        return "jsonl"
    if text[0] == "[":
        return "json-array"
    if text[0] == "{":
        # a JSONL file often starts with a single object too — check line 1
        first = text.split("\n", 1)[0]
        try:
            json.loads(first)
            rest = text.split("\n", 1)
            if len(rest) > 1 and rest[1].strip():
                return "jsonl"
        except Exception:
            pass
        return "json-object"
    return "jsonl"


def iter_file(path: str, rep: FileReport):
    """Yield (index, obj) pairs from any supported file shape."""
    kind = sniff_kind(path)
    rep.kind = kind

    if kind == "empty":
        rep.failures["empty_file"] += 1
        return

    if kind == "jsonl":
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, 1):
                if not line.strip():
                    continue
                try:
                    yield i, json.loads(line)
                except Exception:
                    rep.failures["unparseable_line"] += 1
                    yield i, None
        return

    # whole-document JSON
    size_mb = os.path.getsize(path) / 1e6
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            doc = json.load(f)
    except Exception:
        rep.failures["unparseable_document"] += 1
        return
    if size_mb > 200:
        rep.failures["large_document_loaded_fully"] += 1

    items = unwrap(doc)
    for i, obj in enumerate(items, 1):
        yield i, obj


def unwrap(doc) -> list:
    """Flatten a JSON document into a list of candidate row objects."""
    if isinstance(doc, list):
        return doc
    if not isinstance(doc, dict):
        return [doc]

    # A dict that is itself one conversation: {"messages":[...]} or
    # {"conversations":[{"from":..,"value":..}]} — return it whole.
    for key in ("messages", "conversations", "conversation", "chat"):
        val = doc.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            inner = val[0]
            if inner.get("role") or inner.get("from") or inner.get("speaker"):
                return [doc]

    for key in CONTAINER_KEYS:
        val = doc.get(key)
        if isinstance(val, list):
            return val
        if isinstance(val, dict):
            return unwrap(val)
    return [doc]


# ── schema detection ────────────────────────────────────────────────────────

def detect_and_normalize(obj, opts: IngestOptions):
    """Return (messages, schema_name) or (None, failure_reason)."""
    if obj is None:
        return None, "unparseable_line"
    if isinstance(obj, str):
        if looks_like_chatml(obj):
            return parse_chatml(obj), "chatml_text"
        return None, "bare_string"

    if not isinstance(obj, dict):
        return None, "not_an_object"

    # 1. ChatML stored in a text field (most of the existing corpora)
    for key in (opts.text_field, "content", "conversation", "chat"):
        val = obj.get(key)
        if isinstance(val, str) and looks_like_chatml(val):
            msgs = parse_chatml(val)
            if msgs:
                return msgs, "chatml_text"

    # 2. OpenAI / role-content messages
    for key in ("messages", "conversation", "conversations", "chat"):
        val = obj.get(key)
        if isinstance(val, list) and val and isinstance(val[0], dict):
            msgs = normalize_messages(val)
            if msgs:
                return msgs, "messages"

    # 3. sharegpt variants at top level
    if obj.get("from") or obj.get("speaker"):
        msgs = normalize_messages([obj])
        if msgs:
            return msgs, "sharegpt_turn"

    # 4. (prompt, response) family
    for uk, ak in PAIR_KEYS:
        u, a = obj.get(uk), obj.get(ak)
        if isinstance(u, str) and isinstance(a, str) and u.strip() and a.strip():
            sys_p = obj.get("system") or obj.get("system_prompt")
            msgs = []
            if isinstance(sys_p, str) and sys_p.strip():
                msgs.append({"role": "system", "content": sys_p})
            msgs += [{"role": "user", "content": u}, {"role": "assistant", "content": a}]
            if uk == "instruction" and isinstance(obj.get("input"), str) and obj["input"].strip():
                msgs[-2]["content"] = f"{u}\n\n{obj['input']}"
            return msgs, "prompt_response" if uk != "instruction" else "alpaca"

    # 5. tool-call-only / agent traces with a "tools" schema but no messages
    if "tools" in obj and "messages" not in obj:
        return None, "tools_schema_without_messages"

    # 6. raw prose (opt-in only — it is not a training conversation)
    val = obj.get(opts.text_field)
    if isinstance(val, str) and val.strip() and opts.keep_raw_text:
        return [{"role": "user", "content": val.strip()}], "raw_text"

    return None, "unrecognized_schema"


# ── main entry point ────────────────────────────────────────────────────────

def ingest(inputs: list[str], opts: IngestOptions | None = None):
    """Load every input into (records, quarantine, reports).

    quarantine rows are (source_file, source_line, reason, excerpt).
    """
    opts = opts or IngestOptions()
    paths = expand_paths(inputs)
    records: list[Record] = []
    quarantine: list[dict] = []
    reports: list[FileReport] = []

    for path in paths:
        rep = FileReport(path=os.path.basename(path))
        domain = infer_domain(path, opts.domain)
        for idx, obj in iter_file(path, rep):
            rep.rows_seen += 1
            if obj is None:
                # already counted by iter_file — do not double-report
                quarantine.append(dict(source_file=os.path.basename(path),
                                       source_line=idx, reason="unparseable_line",
                                       excerpt=""))
                continue
            msgs, schema = detect_and_normalize(obj, opts)
            if msgs is None:
                rep.failures[schema] += 1
                excerpt = ""
                if isinstance(obj, dict):
                    excerpt = json.dumps(obj, ensure_ascii=False)[:300]
                quarantine.append(dict(source_file=os.path.basename(path),
                                       source_line=idx, reason=schema,
                                       excerpt=excerpt))
                continue
            rep.schemas[schema] += 1
            rep.rows_kept += 1
            records.append(Record(
                messages=msgs,
                source_file=os.path.basename(path),
                source_line=idx,
                schema=schema,
                domain=domain,
                meta={"source_path": path},
            ))
        reports.append(rep)

    return records, quarantine, reports


def summarize(reports: list[FileReport], records: list[Record],
              quarantine: list[dict]) -> dict:
    schemas: Counter = Counter()
    for r in records:
        schemas[r.schema] += 1
    failures: Counter = Counter()
    for q in quarantine:
        failures[q["reason"]] += 1
    return dict(
        files=len(reports),
        rows_seen=sum(r.rows_seen for r in reports),
        rows_kept=len(records),
        quarantined=len(quarantine),
        schemas=dict(schemas),
        failures=dict(failures),
        by_file=[r.to_dict() for r in reports],
    )
