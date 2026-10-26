"""
SkillForge pipeline — export.

Turns a reviewed session into ONE clean training file plus the paperwork that
makes it trustworthy: a manifest (provenance + hashes + counts), a human report,
and the reject/quarantine bundle so nothing is lost and every decision is
auditable.

Exports are fail-closed: the output is checked against the protocol's hard gates
(invalid tool JSON, orphan observations, secrets, host paths, oversize rows).
Violations are reported loudly and the exit status is non-zero unless the caller
explicitly accepts them with --allow-flagged. A green export must mean something.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime
from pathlib import Path

from .clean import (
    HOSTPATH, SECRETS, classify_json_failure, iter_call_bodies,
)
from .schema import (Record, IM_END, IM_START, json_safe, parse_chatml,
                     render_chatml)

FORMATS = ("messages", "chatml", "both")
SORTS = ("domain", "tokens", "source", "none")


def slug(s: str, maxlen: int = 40) -> str:
    s = re.sub(r"[^A-Za-z0-9._\-]+", "-", (s or "").strip()).strip("-")
    return (s[:maxlen] or "data")


def auto_name(records: list[Record], session_id: str) -> str:
    """Human-readable, collision-resistant, self-describing file name."""
    domains = Counter(r.domain for r in records)
    if len(domains) == 1:
        part = slug(next(iter(domains)))
    else:
        top = domains.most_common(2)
        part = f"mixed-{len(domains)}dom-{slug(top[0][0],16)}"
    tokens = sum(r.est_tokens for r in records)
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return f"{part}__{len(records)}rows__{tokens//1000}ktok__{stamp}__clean.jsonl"


def unique_path(path: Path) -> Path:
    """Never overwrite an existing export."""
    if not path.exists():
        return path
    for i in range(2, 1000):
        cand = path.with_name(f"{path.stem}_v{i}{path.suffix}")
        if not cand.exists():
            return cand
    raise RuntimeError(f"cannot find a free filename near {path}")


def sort_records(records: list[Record], how: str) -> list[Record]:
    if how == "domain":
        return sorted(records, key=lambda r: (r.domain, r.source_file, r.source_line))
    if how == "tokens":
        return sorted(records, key=lambda r: r.est_tokens)
    if how == "source":
        return sorted(records, key=lambda r: (r.source_file, r.source_line))
    return records


def dedupe_records(records: list[Record]) -> tuple[list[Record], int]:
    """Keep the first occurrence of each normalised row."""
    seen, kept, dropped = set(), [], 0
    for r in records:
        h = r.dedupe_hash
        if h in seen:
            dropped += 1
            continue
        seen.add(h)
        kept.append(r)
    return kept, dropped


def render_row(rec: Record, fmt: str) -> dict:
    if fmt == "messages":
        return {"messages": rec.messages}
    if fmt == "chatml":
        return {"text": render_chatml(rec.messages)}
    return {"messages": rec.messages, "text": render_chatml(rec.messages)}


def validate_export(records: list[Record], max_tokens: int = 4096) -> dict:
    """Hard gates from the curation protocol. Any violation is reported."""
    v: Counter = Counter()
    examples: dict[str, str] = {}
    for rec in records:
        for m in rec.messages:
            c = m.get("content") or ""
            if SECRETS.search(c):
                v["secret"] += 1
                examples.setdefault("secret", f"{rec.source_file}:{rec.source_line}")
            if HOSTPATH.search(c):
                v["hostpath"] += 1
                examples.setdefault("hostpath", f"{rec.source_file}:{rec.source_line}")
            for body in iter_call_bodies(c):
                mode = classify_json_failure(body)
                if mode:
                    v["bad_tool_json"] += 1
                    v[f"bad_tool_json:{mode}"] += 1
                    examples.setdefault("bad_tool_json",
                                        f"{rec.source_file}:{rec.source_line}")
        rendered = render_chatml(rec.messages)
        if IM_START not in rendered or IM_END not in rendered:
            v["render_broken"] += 1
            examples.setdefault("render_broken",
                                f"{rec.source_file}:{rec.source_line}")
        elif parse_chatml(rendered) != rec.messages:
            v["render_roundtrip_failed"] += 1
            examples.setdefault("render_roundtrip_failed",
                                f"{rec.source_file}:{rec.source_line}")
        if rec.est_tokens > max_tokens:
            v["oversize"] += 1
            examples.setdefault("oversize", f"{rec.source_file}:{rec.source_line}")
        if "orphan_observation" in rec.flags:
            v["orphan_observation"] += 1
            examples.setdefault("orphan_observation",
                                f"{rec.source_file}:{rec.source_line}")
    return dict(violations=dict(v), examples=examples,
                passed=not any(k in v for k in
                               ("secret", "hostpath", "bad_tool_json",
                                "orphan_observation", "oversize",
                                "render_broken", "render_roundtrip_failed")))


def sha256_file(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def export_session(store, session_id: str, out_dir: str, include: str = "accepted",
                   fmt: str = "messages", sort: str = "domain",
                   dedupe: bool = True, max_tokens: int = 4096,
                   name: str | None = None, allow_flagged: bool = False) -> dict:
    """Write the reviewed data out. Returns the manifest dict."""
    records = store.export_rows(session_id, include=include)
    if not records:
        raise SystemExit("nothing to export — no rows matched "
                         f"(include={include}). Accept some rows first.")

    before = len(records)
    dups_removed = 0
    if dedupe:
        records, dups_removed = dedupe_records(records)
    records = sort_records(records, sort)

    out_path = Path(out_dir).expanduser()
    out_path.mkdir(parents=True, exist_ok=True)
    target = unique_path(out_path / (name or auto_name(records, session_id)))

    row_hashes = []
    with open(target, "w", encoding="utf-8") as f:
        for rec in records:
            line = json_safe(render_row(rec, fmt))
            f.write(line + "\n")
            row_hashes.append(hashlib.md5(line.encode()).hexdigest())

    validation = validate_export(records, max_tokens=max_tokens)

    # ── paperwork ───────────────────────────────────────────────────────────
    sess = store.session(session_id) or {}
    counts = store.counts(session_id)
    manifest = dict(
        session=session_id,
        exported_at=datetime.now().isoformat(timespec="seconds"),
        file=str(target),
        rows=len(records),
        rows_before_dedupe=before,
        duplicates_removed=dups_removed,
        format=fmt,
        sort=sort,
        include=include,
        est_tokens=sum(r.est_tokens for r in records),
        domains=dict(Counter(r.domain for r in records)),
        schemas=dict(Counter(r.schema for r in records)),
        sources=json.loads(sess.get("sources") or "[]"),
        config=json.loads(sess.get("config") or "{}"),
        session_counts=counts,
        validation=validation,
        sha256=sha256_file(str(target)),
        row_hashes_sample=row_hashes[:5],
    )
    man_path = target.with_suffix(target.suffix + ".manifest.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # rejected + unparseable bundle (never deleted, always traceable)
    rejected = store.rejected_rows(session_id)
    quarantine = [dict(r) for r in store.db.execute(
        "SELECT * FROM quarantine WHERE session_id=?", (session_id,))]
    if rejected or quarantine:
        q_path = target.with_suffix(target.suffix + ".rejected.jsonl")
        with open(q_path, "w", encoding="utf-8") as f:
            for r in rejected:
                f.write(json_safe(
                    {"reason": "human_rejected", "note": r["note"],
                     "flags": json.loads(r["flags"] or "[]"),
                     "source_file": r["source_file"], "source_line": r["source_line"],
                     "messages": json.loads(r["messages"])}) + "\n")
            for r in quarantine:
                f.write(json.dumps(
                    {"reason": r["reason"], "source_file": r["source_file"],
                     "source_line": r["source_line"], "excerpt": r["excerpt"]},
                    ensure_ascii=False) + "\n")
        manifest["rejected_bundle"] = str(q_path)
        manifest["rejected_rows"] = len(rejected)
        manifest["unparseable_rows"] = len(quarantine)

    # human report
    rep_path = target.with_suffix(target.suffix + ".report.md")
    with open(rep_path, "w", encoding="utf-8") as f:
        w = f.write
        w(f"# Export report — {target.name}\n\n")
        w(f"- session: `{session_id}`\n- rows exported: **{len(records)}**")
        if dups_removed:
            w(f" ({dups_removed} duplicates removed at export)")
        w(f"\n- estimated tokens: {manifest['est_tokens']:,}\n")
        w(f"- format: `{fmt}`, sort: `{sort}`, include: `{include}`\n")
        w(f"- sha256: `{manifest['sha256']}`\n\n")
        w("## Sources\n")
        for s in manifest["sources"]:
            w(f"- {s}\n")
        w("\n## Domains\n")
        for d, c in manifest["domains"].items():
            w(f"- {d}: {c}\n")
        w("\n## Session review state\n")
        for k, c in counts["by_decision"].items():
            w(f"- {k}: {c}\n")
        w("\n## Flags present in exported rows\n")
        fc = Counter()
        for r in records:
            for fl in r.flags:
                fc[fl] += 1
        if fc:
            for fl, c in fc.most_common():
                w(f"- {fl}: {c}\n")
        else:
            w("- none — every exported row is clean\n")
        w("\n## Hard gates\n")
        if validation["passed"]:
            w("- PASSED: no secrets, host paths, invalid tool JSON, orphan "
              "observations, or oversize rows\n")
        else:
            w("- **FAILED** — violations:\n")
            for k, c in sorted(validation["violations"].items()):
                w(f"  - {k}: {c}  (e.g. {validation['examples'].get(k,'')})\n")
            w("\n  Fix these, or re-export with `--allow-flagged` to accept them "
              "knowingly.\n")
    manifest["report"] = str(rep_path)
    manifest["manifest"] = str(man_path)
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest
