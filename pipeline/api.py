"""
SkillForge pipeline — local review API.

Dependency-free HTTP API over the pipeline engine, plus the review page it
serves. Standard library only (no FastAPI/uvicorn), so it runs anywhere the
engine runs.

    ./sf serve                 # http://127.0.0.1:8010
    ./sf serve --port 8020 --db data/skillforge.db

Endpoints
    GET  /                      review UI
    GET  /api/health
    GET  /api/sessions
    POST /api/import            {paths:[...]} or {files:[{name,text}], ...}
    GET  /api/session?session=  stats + info
    GET  /api/rows?session=&decision=&flag=&domain=&schema=&q=&offset=&limit=
    POST /api/decide            {ids:[...], decision, note?}
    POST /api/bulk              {session, action:"all_clean"|"reject_flag"|"reset", flag?}
    POST /api/edit              {id, messages:[...], note?}
    GET  /api/quarantine?session=
    POST /api/export            {session, include, format, sort, ...}
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import tempfile
import traceback
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from . import clean as clean_mod
from . import export as export_mod
from . import forge as forge_mod
from . import ingest as ingest_mod
from . import playground as pg_mod
from .store import Store

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB = os.environ.get("SKILLFORGE_DB", str(REPO_ROOT / "data" / "skillforge.db"))
CLASSIC_UI = Path(__file__).resolve().parent / "ui" / "index.html"
UI_DIST = REPO_ROOT / "ui" / "dist"
MAX_BODY = 512 * 1024 * 1024          # upload guard: larger data should be imported by path

SESSION_RE = re.compile(r"^[A-Za-z0-9_\-]+$")


def _jsonable_row(row: dict) -> dict:
    """Row dict -> payload for the UI (parsed JSON fields, trimmed meta)."""
    meta = json.loads(row.get("meta") or "{}")
    meta.pop("original_messages", None)          # exposed separately, keeps payload small
    return dict(
        id=row["id"],
        session=row["session_id"],
        decision=row["decision"],
        flags=json.loads(row.get("flags") or "[]"),
        domain=row.get("domain"),
        schema=row.get("schema"),
        source_file=row.get("source_file"),
        source_line=row.get("source_line"),
        est_tokens=row.get("est_tokens"),
        char_len=row.get("char_len"),
        note=row.get("note"),
        edited=bool(row.get("edited")),
        messages=json.loads(row.get("messages") or "[]"),
        original=json.loads(row.get("original") or "null"),
        meta=meta,
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "SkillForge/0.1"

    # ── plumbing ────────────────────────────────────────────────────────────
    def log_message(self, fmt, *args):
        if os.environ.get("SF_VERBOSE"):
            print(f"[api] {self.address_string()} {fmt % args}")

    def _send(self, obj, code=200, ctype="application/json"):
        body = obj if isinstance(obj, bytes) else json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _err(self, msg, code=400):
        self._send({"ok": False, "error": str(msg)}, code)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > MAX_BODY:
            raise ValueError(f"body too large ({n/1e6:.0f} MB) — import big data by "
                             f"path instead of upload")
        if not n:
            return {}
        raw = self.rfile.read(n)
        return json.loads(raw.decode("utf-8"))

    def _store(self) -> Store:
        return Store(self.server.db_path)

    # ── routes ──────────────────────────────────────────────────────────────
    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path in ("/", "/index.html", "/ui"):
                return self._ui()
            if u.path == "/classic":
                return self._classic_ui()
            if u.path.startswith("/assets/"):
                return self._asset(u.path)
            if u.path == "/api/health":
                return self._send({"ok": True, "db": self.server.db_path,
                                   "time": datetime.now().isoformat(timespec="seconds")})
            if u.path == "/api/sessions":
                with self._store() as st:
                    return self._send({"ok": True, "sessions": st.sessions()})
            if u.path == "/api/session":
                return self._session(q.get("session", ""))
            if u.path == "/api/rows":
                return self._rows(q)
            if u.path == "/api/quarantine":
                return self._quarantine(q)
            if u.path == "/api/forge/status":
                return self._send({"ok": True, **forge_mod.status_overview()})
            if u.path == "/api/forge/base-lock":
                return self._send({"ok": True, "lock": forge_mod.base_lock(
                    q.get("model", ""), verify=q.get("verify") in ("1", "true"))})
            if u.path == "/api/forge/run":
                return self._send({"ok": True, "run": forge_mod.run_status(q.get("name", ""))})
            if u.path == "/api/playground/status":
                return self._send({"ok": True, **pg_mod.status_overview()})
            if u.path == "/api/playground/server":
                return self._send({"ok": True, "server": pg_mod.server_status(
                    int(q.get("port") or 8080))})
            if u.path == "/api/ops/status":
                from dashboard.status import collect
                from forge_rsi import config as forge_cfg
                try:
                    cfg = forge_cfg.load()
                except Exception as e:
                    return self._err(f"config not loaded: {e}", 503)
                return self._send({"ok": True, "status": collect(cfg)})
            if u.path == "/api/ops/report":
                return self._ops_report(q.get("name", ""))
            if u.path == "/api/jobs":
                from .jobs import queue
                return self._send({"ok": True, "jobs": queue().list()})
            if u.path == "/api/jobs/log":
                from .jobs import JobError, queue
                try:
                    text = queue().log_tail(q.get("id", ""),
                                            int(q.get("lines") or 80))
                except JobError as e:
                    return self._err(e, 404)
                return self._send({"ok": True, "text": text})
            return self._err("not found", 404)
        except Exception as e:
            traceback.print_exc()
            return self._err(e, 500)

    def do_POST(self):
        u = urlparse(self.path)
        try:
            body = self._body()
            if u.path == "/api/import":
                return self._import(body)
            if u.path == "/api/decide":
                return self._decide(body)
            if u.path == "/api/bulk":
                return self._bulk(body)
            if u.path == "/api/edit":
                return self._edit(body)
            if u.path == "/api/export":
                return self._export(body)
            if u.path == "/api/forge/prepare":
                return self._forge_prepare(body)
            if u.path == "/api/forge/train":
                return self._forge_train(body)
            if u.path == "/api/forge/stop":
                return self._send({"ok": True, "result": forge_mod.stop_run(
                    body.get("run_name") or "")})
            if u.path == "/api/playground/chat":
                return self._pg_chat(body)
            if u.path == "/api/playground/probe":
                return self._pg_probe(body)
            if u.path == "/api/playground/server/start":
                return self._send({"ok": True, "result": pg_mod.start_mlx_server(
                    body.get("model") or "", body.get("adapter_path"),
                    int(body.get("port") or 8080))})
            if u.path == "/api/playground/server/stop":
                return self._send({"ok": True, "result": pg_mod.stop_mlx_server(
                    int(body.get("port") or 8080))})
            if u.path == "/api/jobs":
                from .jobs import JobError, queue
                try:
                    job = queue().submit(body.get("kind") or "",
                                         body.get("params") or {})
                except JobError as e:
                    return self._err(e, 422)
                return self._send({"ok": True, "job": job})
            if u.path == "/api/jobs/approve":
                from .jobs import JobError, queue
                approve = body.get("approve")
                if not isinstance(approve, bool):
                    return self._err("approve must be true or false", 422)
                try:
                    job = queue().approve(body.get("id") or "", approve,
                                          str(body.get("note") or ""))
                except JobError as e:
                    return self._err(e, 422)
                return self._send({"ok": True, "job": job})
            if u.path == "/api/jobs/cancel":
                from .jobs import JobError, queue
                try:
                    job = queue().cancel(body.get("id") or "")
                except JobError as e:
                    return self._err(e, 422)
                return self._send({"ok": True, "job": job})
            return self._err("not found", 404)
        except Exception as e:
            traceback.print_exc()
            return self._err(e, 500)

    # ── handlers ────────────────────────────────────────────────────────────
    def _ui(self):
        """Serve the built React product, falling back to the classic page."""
        target = UI_DIST / "index.html"
        if not target.exists():
            target = CLASSIC_UI
        if not target.exists():
            return self._err("review UI not found — run `npm --prefix ui run build`", 404)
        self._send(target.read_bytes(), ctype="text/html; charset=utf-8")

    def _classic_ui(self):
        if not CLASSIC_UI.exists():
            return self._err("classic UI not found", 404)
        self._send(CLASSIC_UI.read_bytes(), ctype="text/html; charset=utf-8")

    def _asset(self, path: str):
        rel = path.lstrip("/")
        target = (UI_DIST / rel).resolve()
        root = UI_DIST.resolve()
        if root not in target.parents or not target.is_file():
            return self._err("not found", 404)
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self._send(target.read_bytes(), ctype=ctype)

    def _ops_report(self, name: str):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+\.md", name or ""):
            return self._err("invalid report name")
        from forge_rsi import config as forge_cfg
        try:
            root = Path(forge_cfg.load()["paths"]["reports"]).resolve()
        except Exception as e:
            return self._err(f"config not loaded: {e}", 503)
        path = (root / name).resolve()
        if root not in path.parents or not path.is_file():
            return self._err("report not found", 404)
        self._send({"ok": True, "text": path.read_text()})

    def _session(self, sid: str):
        if not SESSION_RE.match(sid or ""):
            return self._err("bad session id")
        with self._store() as st:
            s = st.session(sid)
            if not s:
                return self._err("no such session", 404)
            s["stats_parsed"] = json.loads(s.get("stats") or "{}")
            s["counts"] = st.counts(sid)
            return self._send({"ok": True, "session": s})

    def _rows(self, q: dict):
        sid = q.get("session", "")
        if not SESSION_RE.match(sid):
            return self._err("bad session id")
        limit = min(int(q.get("limit", 50)), 500)
        offset = max(int(q.get("offset", 0)), 0)
        with self._store() as st:
            rows = [_jsonable_row(r) for r in st.iter_rows(
                sid,
                decision=q.get("decision") or None,
                flag=q.get("flag") or None,
                domain=q.get("domain") or None,
                schema=q.get("schema") or None,
                source_file=q.get("source") or None,
                limit=limit, offset=offset)]
            return self._send({"ok": True, "rows": rows, "offset": offset,
                               "limit": limit, "count": len(rows)})

    def _quarantine(self, q: dict):
        sid = q.get("session", "")
        limit = min(int(q.get("limit", 200)), 1000)
        with self._store() as st:
            rows = [dict(r) for r in st.db.execute(
                "SELECT id, source_file, source_line, reason, excerpt FROM quarantine"
                " WHERE session_id=? LIMIT ?", (sid, limit))]
            return self._send({"ok": True, "rows": rows})

    def _import(self, body: dict):
        paths = [os.path.expanduser(p) for p in (body.get("paths") or []) if p.strip()]
        files = body.get("files") or []
        if files:
            tmp = tempfile.mkdtemp(prefix="sf_upload_")
            for f in files:
                name = os.path.basename(f.get("name") or "upload.jsonl")
                p = os.path.join(tmp, name)
                with open(p, "w", encoding="utf-8") as fh:
                    fh.write(f.get("text") or "")
                paths.append(p)
        if not paths:
            return self._err("nothing to import — give a path/glob or drop files")

        opts = ingest_mod.IngestOptions(
            domain=body.get("domain") or None,
            keep_raw_text=bool(body.get("keep_raw_text")),
        )
        records, quarantine, reports = ingest_mod.ingest(paths, opts)
        if not records:
            return self._err("no rows could be loaded from that input")

        for rec in records:                        # keep pre-clean form for the diff view
            rec.meta["original_messages"] = [dict(m) for m in rec.messages]

        copts = clean_mod.CleanOptions(
            fix_tool_calls=not body.get("no_fix"),
            remove_truncated=not body.get("keep_truncated"),
            mask_secrets=not body.get("no_mask"),
            strict_tools=bool(body.get("strict_tools")),
            max_tokens=int(body.get("max_tokens") or 4096),
            min_chars=int(body.get("min_chars") or 20),
            dedupe=body.get("dedupe") or "both",
        )
        records, stats = clean_mod.clean_records(records, copts)
        summary = ingest_mod.summarize(reports, records, quarantine)

        with self._store() as st:
            sid = st.create_session([r.path for r in reports],
                                    dict(ingest=opts.__dict__, clean=copts.__dict__),
                                    summary, name=body.get("session_name"))
            st.add_records(sid, records)
            st.add_quarantine(sid, quarantine)
            counts = st.counts(sid)
        return self._send({"ok": True, "session": sid, "summary": summary,
                           "stats": dict(stats),
                           "counts": counts,
                           "flags": clean_mod.flag_summary(records)})

    def _decide(self, body: dict):
        ids = [int(i) for i in body.get("ids") or []]
        decision = body.get("decision") or "accepted"
        if not ids:
            return self._err("no ids given")
        if decision not in ("accepted", "rejected", "pending"):
            return self._err("bad decision")
        sid = body.get("session") or ""
        with self._store() as st:
            st.decide(ids, decision, note=body.get("note"))
            counts = st.counts(sid) if sid else {}
        return self._send({"ok": True, "decided": len(ids), "decision": decision,
                           "counts": counts})

    def _bulk(self, body: dict):
        sid = body.get("session") or ""
        action = body.get("action") or ""
        with self._store() as st:
            if action == "all_clean":
                ids = [r["id"] for r in st.db.execute(
                    "SELECT id FROM rows WHERE session_id=? AND decision='pending'"
                    " AND flags='[]'", (sid,))]
                st.decide(ids, "accepted", note="bulk: unflagged")
            elif action == "reject_flag":
                flag = body.get("flag") or ""
                ids = [r["id"] for r in st.db.execute(
                    "SELECT id FROM rows WHERE session_id=? AND flags LIKE ?",
                    (sid, f'%"{flag}"%'))]
                st.decide(ids, "rejected", note=f"bulk: {flag}")
            elif action == "reset":
                ids = [r["id"] for r in st.db.execute(
                    "SELECT id FROM rows WHERE session_id=? AND decision=?",
                    (sid, body.get("decision") or "rejected"))]
                st.reset(ids)
            else:
                return self._err("unknown action")
            counts = st.counts(sid)
        return self._send({"ok": True, "affected": len(ids), "counts": counts})

    def _edit(self, body: dict):
        rid = int(body.get("id") or 0)
        msgs = body.get("messages") or []
        if not rid or not isinstance(msgs, list):
            return self._err("need id and messages")
        clean_msgs = [{"role": m.get("role"), "content": m.get("content") or ""}
                      for m in msgs if m.get("role") in ("system", "user", "assistant", "tool")]
        if not clean_msgs:
            return self._err("edit produced no valid messages")
        with self._store() as st:
            st.edit(rid, clean_msgs, note=body.get("note"))
            row = st.get_row(rid)
            counts = st.counts(row["session_id"])
            payload = _jsonable_row(row)
        return self._send({"ok": True, "row": payload, "counts": counts})

    def _export(self, body: dict):
        sid = body.get("session") or ""
        out = os.path.expanduser(body.get("out") or str(REPO_ROOT / "exports"))
        with self._store() as st:
            man = export_mod.export_session(
                st, sid, out,
                include=body.get("include") or "accepted",
                fmt=body.get("format") or "messages",
                sort=body.get("sort") or "domain",
                dedupe=not body.get("no_dedupe"),
                max_tokens=int(body.get("max_tokens") or 4096),
                allow_flagged=bool(body.get("allow_flagged")),
            )
        return self._send({"ok": True, "manifest": man})


    # ── forge ───────────────────────────────────────────────────────────────
    def _forge_prepare(self, body: dict):
        sid = body.get("session") or ""
        run_name = (body.get("run_name") or "").strip()
        if not run_name:
            return self._err("run_name required")
        with self._store() as st:
            records = st.export_rows(sid, include=body.get("include") or "accepted")
        if not records:
            return self._err("no rows to train on — accept some rows in Data first")
        res = forge_mod.prepare_dataset(
            run_name, records,
            valid_ratio=float(body.get("valid_ratio") or 0.05),
            seed=int(body.get("seed") or 0),
            max_tokens=int(body.get("max_tokens") or 2048),
            allow_flagged=bool(body.get("allow_flagged")))
        if not res.get("ok"):
            v = res.get("validation", {}).get("violations", {})
            return self._send({"ok": False, "error": "dataset failed the training "
                               "gates: " + ", ".join(f"{k}={n}" for k, n in v.items()),
                               **res}, 422)
        return self._send({"ok": True, **res})

    def _forge_train(self, body: dict):
        cfg = dict(
            rank=int(body.get("rank") or 8), alpha=int(body.get("alpha") or 16),
            dropout=float(body.get("dropout") or 0.0),
            batch_size=int(body.get("batch_size") or 1),
            iters=int(body.get("iters") or 100),
            learning_rate=float(body.get("learning_rate") or 1e-4),
            num_layers=int(body.get("num_layers") or 6),
            max_seq_length=int(body.get("max_seq_length") or 2048),
            grad_accum=int(body.get("grad_accum") or 4),
            steps_per_report=int(body.get("steps_per_report") or 10),
            steps_per_eval=int(body.get("steps_per_eval") or 50),
            save_every=int(body.get("save_every") or 50),
            val_batches=int(body.get("val_batches") or 4),
            seed=int(body.get("seed") or 0),
            mask_prompt=bool(body.get("mask_prompt", True)),
            grad_checkpoint=bool(body.get("grad_checkpoint", False)),
        )
        if body.get("dry_run"):
            return self._send({"ok": True, "preview": forge_mod.preview_command(
                (body.get("run_name") or "").strip(),
                (body.get("model") or "").strip(), cfg)})
        res = forge_mod.start_run((body.get("run_name") or "").strip(),
                                  (body.get("model") or "").strip(), cfg)
        if not res.get("ok"):
            return self._send({"ok": False, "error": res.get("reason", "refused")}, 422)
        return self._send({"ok": True, **res})

    # ── playground ──────────────────────────────────────────────────────────
    def _pg_messages(self, body: dict) -> list[dict]:
        msgs = body.get("messages")
        if isinstance(msgs, list) and msgs:
            return msgs
        out = []
        if (body.get("system") or "").strip():
            out.append({"role": "system", "content": body["system"]})
        out.append({"role": "user", "content": body.get("prompt") or ""})
        return out

    def _pg_chat(self, body: dict):
        try:
            res = pg_mod.chat(self._pg_messages(body),
                              model=body.get("model") or None,
                              endpoint=body.get("endpoint") or None,
                              kind=body.get("kind") or None,
                              temperature=float(body.get("temperature") if
                                                body.get("temperature") is not None else 0.0),
                              max_tokens=int(body.get("max_tokens") or 512))
        except Exception as e:
            return self._send({"ok": False, "error": f"{type(e).__name__}: {e}"}, 503)
        return self._send({"ok": True, **res})

    def _pg_probe(self, body: dict):
        try:
            res = pg_mod.probe(self._pg_messages(body),
                               n_samples=int(body.get("n") or 6),
                               temperature=float(body.get("temperature") if
                                                 body.get("temperature") is not None else 0.3),
                               model=body.get("model") or None,
                               endpoint=body.get("endpoint") or None,
                               kind=body.get("kind") or None,
                               max_tokens=int(body.get("max_tokens") or 512))
        except Exception as e:
            return self._send({"ok": False, "error": f"{type(e).__name__}: {e}"}, 503)
        return self._send({"ok": True, **res})


def serve(db_path: str = DEFAULT_DB, host: str = "127.0.0.1", port: int = 8010):
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    httpd = ThreadingHTTPServer((host, port), Handler)
    httpd.db_path = db_path
    url = f"http://{host}:{port}"
    print(f"SkillForge review UI  ->  {url}")
    print(f"database              ->  {db_path}")
    print("Ctrl-C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        httpd.server_close()


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8010)
    a = ap.parse_args()
    serve(a.db, a.host, a.port)
