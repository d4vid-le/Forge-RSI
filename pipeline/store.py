"""
SkillForge pipeline — SQLite session store.

Review is a long, interruptible human process, so every import becomes a
session that can be closed and resumed. Decisions are stored as data (not chat),
which is what lets the next run inherit the policy instead of re-deriving it.

Tables:
  sessions    one row per import (sources, config, stats)
  rows        one row per training line: messages, flags, decision, edit
  quarantine  rows the loader could not normalise, with the reason

Nothing is ever deleted from the database by the review actions — a rejected
row keeps its content and decision, so an export can always be reproduced and
audited.
"""

from __future__ import annotations

import json
import os
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Iterable, Iterator

from .schema import Record, json_safe

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS sessions (
    id          TEXT PRIMARY KEY,
    name        TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    sources     TEXT NOT NULL DEFAULT '[]',
    config      TEXT NOT NULL DEFAULT '{}',
    stats       TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS rows (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    source_file  TEXT,
    source_line  INTEGER,
    schema       TEXT,
    domain       TEXT,
    messages     TEXT NOT NULL,
    original     TEXT,
    flags        TEXT NOT NULL DEFAULT '[]',
    meta         TEXT NOT NULL DEFAULT '{}',
    dedupe_hash  TEXT,
    est_tokens   INTEGER,
    char_len     INTEGER,
    decision     TEXT NOT NULL DEFAULT 'pending',
    edited       TEXT,
    note         TEXT,
    reviewed_at  TEXT
);

CREATE INDEX IF NOT EXISTS idx_rows_session_decision ON rows(session_id, decision);
CREATE INDEX IF NOT EXISTS idx_rows_session_hash     ON rows(session_id, dedupe_hash);
CREATE INDEX IF NOT EXISTS idx_rows_session_domain   ON rows(session_id, domain);

CREATE TABLE IF NOT EXISTS quarantine (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id   TEXT NOT NULL,
    source_file  TEXT,
    source_line  INTEGER,
    reason       TEXT,
    excerpt      TEXT
);
CREATE INDEX IF NOT EXISTS idx_quarantine_session ON quarantine(session_id, reason);
"""

DECISIONS = ("pending", "accepted", "rejected", "edited")


class Store:
    def __init__(self, path: str):
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.path = path
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(SCHEMA)

    def close(self):
        self.db.commit()
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    # ── sessions ────────────────────────────────────────────────────────────
    def create_session(self, sources: list[str], config: dict, stats: dict,
                       name: str | None = None) -> str:
        sid = "sf_" + datetime.now().strftime("%Y%m%d_%H%M%S")
        n = 1
        while self.db.execute("SELECT 1 FROM sessions WHERE id=?", (sid,)).fetchone():
            sid = "sf_" + datetime.now().strftime("%Y%m%d_%H%M%S") + f"_{n}"
            n += 1
        now = datetime.now().isoformat(timespec="seconds")
        self.db.execute(
            "INSERT INTO sessions(id,name,created_at,updated_at,sources,config,stats)"
            " VALUES(?,?,?,?,?,?,?)",
            (sid, name or sid, now, now, json_safe(sources), json_safe(config),
             json_safe(stats)))
        self.db.commit()
        return sid

    def update_session_stats(self, sid: str, stats: dict):
        self.db.execute("UPDATE sessions SET stats=?, updated_at=? WHERE id=?",
                        (json_safe(stats), datetime.now().isoformat(timespec="seconds"), sid))
        self.db.commit()

    def sessions(self) -> list[dict]:
        rows = self.db.execute("SELECT * FROM sessions ORDER BY created_at DESC").fetchall()
        return [dict(r) for r in rows]

    def session(self, sid: str) -> dict | None:
        r = self.db.execute("SELECT * FROM sessions WHERE id=?", (sid,)).fetchone()
        return dict(r) if r else None

    # ── rows ────────────────────────────────────────────────────────────────
    def add_records(self, sid: str, records: Iterable[Record], batch: int = 2000):
        """Bulk insert. `original` preserves the pre-clean messages for diffing."""
        buf = []
        for rec in records:
            buf.append((
                sid, rec.source_file, rec.source_line, rec.schema, rec.domain,
                json_safe(rec.messages),
                json_safe(rec.meta.get("original_messages", rec.messages)),
                json_safe(rec.flags),
                json_safe(rec.meta),
                rec.dedupe_hash, rec.est_tokens, rec.char_len,
            ))
            if len(buf) >= batch:
                self._insert_rows(buf); buf = []
        if buf:
            self._insert_rows(buf)

    def _insert_rows(self, buf: list):
        self.db.executemany(
            "INSERT INTO rows(session_id,source_file,source_line,schema,domain,"
            "messages,original,flags,meta,dedupe_hash,est_tokens,char_len)"
            " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", buf)
        self.db.commit()

    def add_quarantine(self, sid: str, items: Iterable[dict]):
        self.db.executemany(
            "INSERT INTO quarantine(session_id,source_file,source_line,reason,excerpt)"
            " VALUES(?,?,?,?,?)",
            [(sid, i.get("source_file"), i.get("source_line"), i.get("reason"),
              (i.get("excerpt") or "")[:500]) for i in items])
        self.db.commit()

    def iter_rows(self, sid: str, decision: str | None = None,
                  flag: str | None = None, domain: str | None = None,
                  schema: str | None = None, source_file: str | None = None,
                  limit: int | None = None, offset: int = 0,
                  order: str = "id") -> Iterator[dict]:
        q = "SELECT * FROM rows WHERE session_id=?"
        args: list = [sid]
        if decision:
            q += " AND decision=?"
            args.append(decision)
        if domain:
            q += " AND domain=?"
            args.append(domain)
        if schema:
            q += " AND schema=?"
            args.append(schema)
        if source_file:
            q += " AND source_file=?"
            args.append(source_file)
        if flag:
            q += " AND flags LIKE ?"
            args.append(f'%"{flag}"%')
        q += f" ORDER BY {order}"
        if limit:
            q += " LIMIT ? OFFSET ?"
            args += [limit, offset]
        for r in self.db.execute(q, args):
            yield dict(r)

    def get_row(self, row_id: int) -> dict | None:
        r = self.db.execute("SELECT * FROM rows WHERE id=?", (row_id,)).fetchone()
        return dict(r) if r else None

    def row_to_record(self, row: dict) -> Record:
        msgs = json.loads(row["edited"] or row["messages"])
        return Record(messages=msgs, source_file=row["source_file"] or "",
                      source_line=row["source_line"] or 0,
                      schema=row["schema"] or "", domain=row["domain"] or "",
                      flags=json.loads(row["flags"] or "[]"),
                      meta=json.loads(row["meta"] or "{}"),
                      row_id=row["id"], decision=row["decision"])

    # ── review actions ──────────────────────────────────────────────────────
    def decide(self, row_ids: list[int], decision: str, note: str | None = None):
        assert decision in DECISIONS, decision
        now = datetime.now().isoformat(timespec="seconds")
        self.db.executemany(
            "UPDATE rows SET decision=?, note=COALESCE(?,note), reviewed_at=? WHERE id=?",
            [(decision, note, now, rid) for rid in row_ids])
        self.db.commit()

    def edit(self, row_id: int, messages: list[dict], note: str | None = None):
        """Save a human edit; the row counts as accepted in its edited form."""
        now = datetime.now().isoformat(timespec="seconds")
        self.db.execute(
            "UPDATE rows SET edited=?, decision='edited', note=COALESCE(?,note),"
            " reviewed_at=? WHERE id=?",
            (json_safe(messages), note, now, row_id))
        self.db.commit()

    def reset(self, row_ids: list[int]):
        self.db.executemany(
            "UPDATE rows SET decision='pending', reviewed_at=NULL WHERE id=?",
            [(rid,) for rid in row_ids])
        self.db.commit()

    # ── reporting ───────────────────────────────────────────────────────────
    def counts(self, sid: str) -> dict:
        by_decision = Counter()
        for r in self.db.execute(
                "SELECT decision, COUNT(*) c FROM rows WHERE session_id=? GROUP BY decision",
                (sid,)):
            by_decision[r["decision"]] = r["c"]
        by_flag = Counter()
        for r in self.db.execute("SELECT flags FROM rows WHERE session_id=?", (sid,)):
            for f in json.loads(r["flags"] or "[]"):
                by_flag[f] += 1
        by_domain = Counter()
        for r in self.db.execute(
                "SELECT domain, COUNT(*) c FROM rows WHERE session_id=? GROUP BY domain",
                (sid,)):
            by_domain[r["domain"]] = r["c"]
        by_schema = Counter()
        for r in self.db.execute(
                "SELECT schema, COUNT(*) c FROM rows WHERE session_id=? GROUP BY schema",
                (sid,)):
            by_schema[r["schema"]] = r["c"]
        quarantine = Counter()
        for r in self.db.execute(
                "SELECT reason, COUNT(*) c FROM quarantine WHERE session_id=? GROUP BY reason",
                (sid,)):
            quarantine[r["reason"]] = r["c"]
        total = sum(by_decision.values())
        return dict(
            total=total,
            by_decision=dict(by_decision),
            by_flag=dict(by_flag.most_common()),
            by_domain=dict(by_domain.most_common()),
            by_schema=dict(by_schema.most_common()),
            quarantine=dict(quarantine.most_common()),
            reviewed=by_decision.get("accepted", 0) + by_decision.get("rejected", 0)
            + by_decision.get("edited", 0),
        )

    def export_rows(self, sid: str, include: str = "accepted") -> list[Record]:
        """Rows to write out. `include`:
             accepted  — accepted + edited (the default, human-approved)
             clean     — accepted + edited + pending rows that carry no flags
             all       — everything not rejected
        """
        if include == "accepted":
            q = "SELECT * FROM rows WHERE session_id=? AND decision IN ('accepted','edited')"
            args = [sid]
        elif include == "clean":
            q = ("SELECT * FROM rows WHERE session_id=? AND ("
                 "decision IN ('accepted','edited') OR "
                 "(decision='pending' AND flags='[]'))")
            args = [sid]
        else:
            q = "SELECT * FROM rows WHERE session_id=? AND decision!='rejected'"
            args = [sid]
        return [self.row_to_record(dict(r)) for r in self.db.execute(q + " ORDER BY id", args)]

    def rejected_rows(self, sid: str) -> list[dict]:
        return [dict(r) for r in self.db.execute(
            "SELECT * FROM rows WHERE session_id=? AND decision='rejected' ORDER BY id",
            (sid,))]
