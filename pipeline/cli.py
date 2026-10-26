"""
SkillForge pipeline — command line interface.

    python -m pipeline import data/*.json --domain sql
    python -m pipeline stats sf_20260913_101500
    python -m pipeline accept sf_... --all-clean          # keep every clean row
    python -m pipeline reject sf_... --where flag=secret
    python -m pipeline export sf_... --out ./exports
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import clean as clean_mod
from . import export as export_mod
from . import ingest as ingest_mod
from .store import Store
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = os.environ.get("SKILLFORGE_DB", str(REPO_ROOT / "data" / "skillforge.db"))


def _print_summary(summary: dict, stats, records):
    print(f"\n  files          : {summary['files']}")
    print(f"  rows seen      : {summary['rows_seen']:,}")
    print(f"  rows kept      : {summary['rows_kept']:,}")
    print(f"  quarantined    : {summary['quarantined']:,}")
    if summary["schemas"]:
        print(f"  schemas        : " +
              ", ".join(f"{k}={v}" for k, v in
                        sorted(summary["schemas"].items(), key=lambda kv: -kv[1])))
    if summary["failures"]:
        print(f"  load failures  : " +
              ", ".join(f"{k}={v}" for k, v in summary["failures"].items()))
    flags = clean_mod.flag_summary(records)
    print(f"  clean rows     : {stats['rows_clean']:,} "
          f"({100*stats['rows_clean']/max(1,len(records)):.1f}%)")
    print(f"  flagged rows   : {stats['rows_flagged']:,}")
    if flags:
        print("  top flags      : " + ", ".join(f"{k}={v}" for k, v in
                                                list(flags.items())[:10]))
    for key in ("tool_calls_repaired", "tool_calls_removed",
                "orphan_observations_removed", "secret", "hostpath",
                "mojibake", "lone_surrogate", "oversize"):
        if stats.get(key):
            print(f"    · {key}: {stats[key]:,}")


def cmd_import(a):
    opts = ingest_mod.IngestOptions(
        domain=a.domain, keep_raw_text=a.keep_raw_text, max_file_mb=a.max_file_mb)
    records, quarantine, reports = ingest_mod.ingest(a.inputs, opts)
    if not records:
        print("no rows could be loaded — check the input files", file=sys.stderr)
        return 2

    # keep the pre-clean form so the review UI can show a real diff
    for rec in records:
        rec.meta["original_messages"] = [dict(m) for m in rec.messages]

    copts = clean_mod.CleanOptions(
        fix_tool_calls=not a.no_fix,
        remove_truncated=not a.keep_truncated,
        mask_secrets=not a.no_mask,
        strict_tools=a.strict_tools,
        max_tokens=a.max_tokens,
        min_chars=a.min_chars,
        dedupe=a.dedupe,
    )
    records, stats = clean_mod.clean_records(records, copts)
    summary = ingest_mod.summarize(reports, records, quarantine)

    cfg = dict(ingest=opts.__dict__, clean=copts.__dict__)
    with Store(a.db) as st:
        sid = st.create_session([r.path for r in reports], cfg, summary,
                               name=a.session_name)
        st.add_records(sid, records)
        st.add_quarantine(sid, quarantine)

    print(f"[import] session {sid}")
    _print_summary(summary, stats, records)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(
            dict(session=sid, summary=summary, stats=dict(stats)), indent=2))
    print(f"\n  session        : {sid}\n  db             : {a.db}")
    print(f"\n  next: python -m pipeline accept {sid} --all-clean"
          f"\n        python -m pipeline export {sid} --out ./exports")
    return 0


def cmd_sessions(a):
    with Store(a.db) as st:
        rows = st.sessions()
    if not rows:
        print("no sessions yet")
        return 1
    print(f"{'session':24}{'created':21}{'total':>8}{'reviewed':>10}  name")
    for s in rows:
        stats = json.loads(s["stats"] or "{}")
        print(f"{s['id']:24}{s['created_at']:21}"
              f"{stats.get('rows_kept', 0):>8,}{'':>10}  {s['name']}")
    return 0


def cmd_stats(a):
    with Store(a.db) as st:
        if not st.session(a.session):
            print(f"no such session: {a.session}", file=sys.stderr)
            return 2
        c = st.counts(a.session)
    if a.json_out:
        Path(a.json_out).write_text(json.dumps(c, indent=2))
    print(f"session {a.session}  —  {c['total']:,} rows, {c['reviewed']:,} reviewed")
    print("\n  decision :")
    for k in ("accepted", "edited", "rejected", "pending"):
        print(f"    {k:9}: {c['by_decision'].get(k, 0):,}")
    print("\n  domains  : " + ", ".join(f"{k}={v}" for k, v in c["by_domain"].items()))
    print("  schemas  : " + ", ".join(f"{k}={v}" for k, v in c["by_schema"].items()))
    if c["by_flag"]:
        print("\n  flags    :")
        for k, v in c["by_flag"].items():
            print(f"    {k:26}: {v:,}")
    if c["quarantine"]:
        print("\n  quarantine (unparseable at load):")
        for k, v in c["quarantine"].items():
            print(f"    {k:26}: {v:,}")
    return 0


def cmd_show(a):
    with Store(a.db) as st:
        row = st.get_row(a.row_id)
    if not row:
        print(f"no such row: {a.row_id}", file=sys.stderr)
        return 2
    print(f"row {row['id']}  [{row['decision']}]  {row['source_file']}:{row['source_line']}"
          f"  domain={row['domain']} schema={row['schema']}")
    if row["flags"] != "[]":
        print("flags: " + ", ".join(json.loads(row["flags"])))
    msgs = json.loads(row["messages"])
    orig = json.loads(row["original"] or "null")
    for i, m in enumerate(msgs):
        print(f"\n── {m['role']} " + "─" * 50)
        print((m["content"] or "")[:a.chars])
    if a.diff and orig and orig != msgs:
        print("\n══ CHANGED BY CLEANING " + "═" * 40)
        for m in orig:
            print(f"  [{m['role']}] {(m['content'] or '')[:120]}")
    return 0


def _resolve_ids(st, a) -> list[int]:
    if a.ids:
        return [int(x) for x in a.ids.replace(",", " ").split()]
    if a.where:
        key, _, val = a.where.partition("=")
        key, val = key.strip(), val.strip()
        kwargs = {"session_id": a.session} if False else {}
        q = "SELECT id FROM rows WHERE session_id=?"
        args = [a.session]
        if key in ("flag", "flags"):
            q += " AND flags LIKE ?"; args.append(f'%"{val}"%')
        elif key in ("domain", "schema", "source_file"):
            q += f" AND {key}=?"; args.append(val)
        elif key == "decision":
            q += " AND decision=?"; args.append(val)
        elif key == "clean":
            q += " AND flags='[]'"
        elif key == "id":
            q += " AND id>=?"; args.append(int(val))
        else:
            raise SystemExit(f"unknown --where key: {key}")
        return [r["id"] for r in st.db.execute(q, args)]
    raise SystemExit("pass --ids, --where, or --all-clean")


def _apply(a, decision: str):
    with Store(a.db) as st:
        if a.all_clean:
            ids = [r["id"] for r in st.db.execute(
                "SELECT id FROM rows WHERE session_id=? AND decision='pending'"
                " AND flags='[]'", (a.session,))]
        else:
            ids = [i for i in _resolve_ids(st, a)
                   if st.get_row(i)["session_id"] == a.session]
        if not ids:
            print("no matching rows"); return 1
        if len(ids) > 200 and not a.yes:
            print(f"{len(ids)} rows will be marked '{decision}'. Re-run with --yes.")
            return 1
        st.decide(ids, decision, note=a.note)
        c = st.counts(a.session)
    print(f"{decision}: {len(ids):,} rows  "
          f"(accepted={c['by_decision'].get('accepted',0):,} "
          f"rejected={c['by_decision'].get('rejected',0):,} "
          f"pending={c['by_decision'].get('pending',0):,})")
    return 0


def cmd_quarantine(a):
    with Store(a.db) as st:
        rows = st.db.execute(
            "SELECT * FROM quarantine WHERE session_id=? LIMIT ?",
            (a.session, a.limit)).fetchall()
    if not rows:
        print("quarantine is empty")
        return 0
    for r in rows:
        print(f"[{r['reason']}] {r['source_file']}:{r['source_line']}")
        if r["excerpt"]:
            print("    " + (r["excerpt"] or "")[:200])
    return 0


def cmd_export(a):
    with Store(a.db) as st:
        man = export_mod.export_session(
            st, a.session, a.out, include=a.include, fmt=a.format, sort=a.sort,
            dedupe=not a.no_dedupe, max_tokens=a.max_tokens,
            name=a.name, allow_flagged=a.allow_flagged)
    v = man["validation"]
    print(f"\n[export] {man['rows']:,} rows → {man['file']}")
    if man["duplicates_removed"]:
        print(f"  duplicates removed at export: {man['duplicates_removed']:,}")
    print(f"  est. tokens: {man['est_tokens']:,}   sha256: {man['sha256'][:16]}…")
    print(f"  report: {man['report']}")
    print(f"  manifest: {man['manifest']}")
    if "rejected_bundle" in man:
        print(f"  rejected/quarantine: {man['rejected_bundle']}")
    if v["passed"]:
        print("  hard gates: PASSED")
        return 0
    print("  hard gates: FAILED")
    for k, c in sorted(v["violations"].items()):
        print(f"    {k}: {c}   e.g. {v['examples'].get(k,'')}")
    if a.allow_flagged:
        print("  (accepted knowingly via --allow-flagged)")
        return 0
    print("  re-export with --allow-flagged to accept these knowingly")
    return 3


def cmd_serve(a):
    """Run the local review API + UI."""
    from .api import serve
    serve(a.db, a.host, a.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="pipeline", description="SkillForge data pipeline")
    p.add_argument("--db", default=DEFAULT_DB, help=f"session database (default {DEFAULT_DB})")
    sub = p.add_subparsers(dest="cmd", required=True)

    i = sub.add_parser("import", help="load one or more json/jsonl files into a session")
    i.add_argument("inputs", nargs="+", help="files, globs, or directories")
    i.add_argument("--session-name")
    i.add_argument("--domain", help="override domain (else inferred from filename)")
    i.add_argument("--keep-raw-text", action="store_true",
                   help="keep unstructured prose rows (off by default)")
    i.add_argument("--no-fix", action="store_true", help="do not repair tool-call JSON")
    i.add_argument("--keep-truncated", action="store_true",
                   help="keep truncated tool calls instead of removing them")
    i.add_argument("--no-mask", action="store_true", help="do not mask secrets")
    i.add_argument("--strict-tools", action="store_true",
                   help="flag every tool name outside the executor schema")
    i.add_argument("--max-tokens", type=int, default=4096)
    i.add_argument("--min-chars", type=int, default=20)
    i.add_argument("--dedupe", choices=["both", "exact", "normalized", "none"],
                   default="both")
    i.add_argument("--max-file-mb", type=float, default=4096.0)
    i.add_argument("--json-out")
    i.set_defaults(func=cmd_import)

    s = sub.add_parser("sessions", help="list import sessions")
    s.set_defaults(func=cmd_sessions)

    st = sub.add_parser("stats", help="session statistics")
    st.add_argument("session")
    st.add_argument("--json-out")
    st.set_defaults(func=cmd_stats)

    sh = sub.add_parser("show", help="print one row")
    sh.add_argument("row_id", type=int)
    sh.add_argument("--chars", type=int, default=1500)
    sh.add_argument("--diff", action="store_true", help="also show the pre-clean text")
    sh.set_defaults(func=cmd_show)

    for name, fn, helptext in (("accept", cmd_accept := lambda a: _apply(a, "accepted"),
                                "mark rows accepted (kept)"),
                               ("reject", cmd_reject := lambda a: _apply(a, "rejected"),
                                "mark rows rejected (dropped)")):
        c = sub.add_parser(name, help=helptext)
        c.add_argument("session")
        c.add_argument("--ids", help="comma/space separated row ids")
        c.add_argument("--where", help="filter e.g. flag=secret, domain=sql, clean")
        c.add_argument("--all-clean", action="store_true",
                       help="every pending row with no flags")
        c.add_argument("--note")
        c.add_argument("--yes", action="store_true", help="confirm large batches")
        c.set_defaults(func=fn)

    q = sub.add_parser("quarantine", help="show rows that could not be loaded")
    q.add_argument("session")
    q.add_argument("--limit", type=int, default=50)
    q.set_defaults(func=cmd_quarantine)

    e = sub.add_parser("export", help="write the clean training file")
    e.add_argument("session")
    e.add_argument("--out", default=str(REPO_ROOT / "exports"))
    e.add_argument("--include", choices=["accepted", "clean", "all"], default="accepted")
    e.add_argument("--format", choices=export_mod.FORMATS, default="messages")
    e.add_argument("--sort", choices=export_mod.SORTS, default="domain")
    e.add_argument("--no-dedupe", action="store_true")
    e.add_argument("--name", help="override the auto-generated filename")
    e.add_argument("--max-tokens", type=int, default=4096)
    e.add_argument("--allow-flagged", action="store_true")
    e.set_defaults(func=cmd_export)

    sv = sub.add_parser("serve", help="run the local review UI + API")
    sv.add_argument("--host", default="127.0.0.1")
    sv.add_argument("--port", type=int, default=8010)
    sv.set_defaults(func=cmd_serve)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
