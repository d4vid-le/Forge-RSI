import { useCallback, useEffect, useMemo, useState } from "react";
import { Check, Database, RefreshCw, RotateCcw, Upload, X } from "lucide-react";
import { api, errorMessage } from "../api";
import type { Row, Session, SessionCounts } from "../types";
import {
  Button, Card, CardHeader, Empty, ErrorBanner, Field, Input, KV, Pill, Select,
  Spinner, Textarea, cx, dateLabel, fmt,
} from "../components/ui";

type Filters = { decision: string; flag: string; domain: string; schema: string };
type SessionWithCounts = Session & { counts?: SessionCounts };

const EMPTY_FILTERS: Filters = { decision: "", flag: "", domain: "", schema: "" };

function decisionTone(d: string) {
  if (d === "accepted" || d === "edited") return "ok" as const;
  if (d === "rejected") return "err" as const;
  return "neutral" as const;
}

export function DataView() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [sessionId, setSessionId] = useState("");
  const [session, setSession] = useState<SessionWithCounts | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [hasMore, setHasMore] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [importPaths, setImportPaths] = useState("");
  const [importDomain, setImportDomain] = useState("");
  const [importStrict, setImportStrict] = useState(false);
  const [importRaw, setImportRaw] = useState(false);
  const [busy, setBusy] = useState("");
  const [editMode, setEditMode] = useState(false);
  const [editMessages, setEditMessages] = useState<{ role: string; content: string }[]>([]);
  const [showDiff, setShowDiff] = useState(false);
  const [exportInclude, setExportInclude] = useState("accepted");
  const [exportFormat, setExportFormat] = useState("messages");
  const [exportSort, setExportSort] = useState("domain");
  const [exportResult, setExportResult] = useState<any>(null);

  const selected = useMemo(
    () => rows.find((r) => r.id === selectedId) || null,
    [rows, selectedId],
  );
  const counts = session?.counts || {};

  const fetchRows = useCallback(async (
    sid: string, reset: boolean, nextOffset: number, f: Filters,
  ) => {
    if (!sid) return;
    const q = new URLSearchParams({ session: sid, offset: String(nextOffset), limit: "50" });
    if (f.decision) q.set("decision", f.decision);
    if (f.flag) q.set("flag", f.flag);
    if (f.domain) q.set("domain", f.domain);
    if (f.schema) q.set("schema", f.schema);
    try {
      const d = await api.get<{ rows: Row[]; count: number }>(`/api/rows?${q}`);
      setRows((prev) => (reset ? d.rows : [...prev, ...d.rows]));
      setHasMore(d.count >= 50);
      setSelectedId((prev) => {
        if (!reset && prev != null) return prev;
        return d.rows[0]?.id ?? null;
      });
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  const selectSession = useCallback(async (sid: string) => {
    if (!sid) return;
    setSessionId(sid);
    setLoading(true);
    setError("");
    setNotice("");
    setEditMode(false);
    try {
      const d = await api.get<{ session: SessionWithCounts }>(`/api/session?session=${encodeURIComponent(sid)}`);
      setSession(d.session);
      setRows([]);
      setSelectedId(null);
      await fetchRows(sid, true, 0, filters);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [fetchRows, filters]);

  const loadSessions = useCallback(async () => {
    setLoading(true);
    try {
      const d = await api.get<{ sessions: Session[] }>("/api/sessions");
      setSessions(d.sessions || []);
      if (!sessionId && d.sessions?.length) await selectSession(d.sessions[0].id);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const refreshCounts = useCallback(async () => {
    if (!sessionId) return;
    try {
      const d = await api.get<{ session: SessionWithCounts }>(`/api/session?session=${encodeURIComponent(sessionId)}`);
      setSession(d.session);
    } catch { /* counts are advisory */ }
  }, [sessionId]);

  useEffect(() => { loadSessions(); }, [loadSessions]);

  const setFilter = (patch: Partial<Filters>) => {
    const next = { ...filters, ...patch };
    setFilters(next);
    if (sessionId) fetchRows(sessionId, true, 0, next);
  };

  const decide = async (decision: string) => {
    if (!selected || !sessionId) return;
    setBusy(decision);
    try {
      const d = await api.post<{ counts: SessionCounts }>("/api/decide", {
        ids: [selected.id], session: sessionId, decision,
      });
      setRows((prev) => prev.map((r) => r.id === selected.id ? { ...r, decision } : r));
      if (d.counts) setSession((s) => s ? { ...s, counts: d.counts } : s);
      setNotice(`row #${selected.id} → ${decision}`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const bulk = async (action: "all_clean" | "reset") => {
    if (!sessionId) return;
    setBusy(action);
    try {
      const d = await api.post<{ affected: number; counts: SessionCounts }>("/api/bulk", {
        session: sessionId, action,
        ...(action === "reset" ? { decision: "rejected" } : {}),
      });
      if (d.counts) setSession((s) => s ? { ...s, counts: d.counts } : s);
      setNotice(`${action}: ${d.affected} rows`);
      await fetchRows(sessionId, true, 0, filters);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const doImport = async () => {
    const paths = importPaths.split("\n").map((s) => s.trim()).filter(Boolean);
    if (!paths.length) { setNotice("Add one path per line first."); return; }
    setBusy("import");
    setError("");
    try {
      const d = await api.post<{ session: string; summary: any }>("/api/import", {
        paths, domain: importDomain || null,
        strict_tools: importStrict, keep_raw_text: importRaw,
      });
      setNotice(`imported ${d.summary?.rows_kept ?? "?"} rows · ${d.summary?.quarantined ?? 0} quarantined`);
      setImportPaths("");
      await loadSessions();
      await selectSession(d.session);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const doExport = async () => {
    if (!sessionId) return;
    setBusy("export");
    setError("");
    try {
      const d = await api.post<{ manifest: any }>("/api/export", {
        session: sessionId, include: exportInclude, format: exportFormat, sort: exportSort,
      });
      setExportResult(d.manifest);
      setNotice(`exported ${d.manifest.rows} rows`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const beginEdit = () => {
    if (!selected) return;
    setEditMessages(selected.messages.map((m) => ({ role: m.role, content: m.content })));
    setEditMode(true);
    setShowDiff(false);
  };

  const saveEdit = async () => {
    if (!selected) return;
    setBusy("edit");
    try {
      const d = await api.post<{ row: Row; counts: SessionCounts }>("/api/edit", {
        id: selected.id, messages: editMessages,
      });
      setRows((prev) => prev.map((r) => r.id === selected.id ? d.row : r));
      if (d.counts) setSession((s) => s ? { ...s, counts: d.counts } : s);
      setEditMode(false);
      setNotice(`row #${selected.id} edited`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const loadMore = () => {
    if (sessionId) fetchRows(sessionId, false, rows.length, filters);
  };

  const total = counts.total || 0;
  const acc = (counts.by_decision?.accepted || 0) + (counts.by_decision?.edited || 0);
  const rej = counts.by_decision?.rejected || 0;
  const pend = counts.by_decision?.pending || 0;
  const bar = (n: number) => total ? `${(n / total) * 100}%` : "0%";
  const flags = Object.keys(counts.by_flag || {}).sort();
  const domains = Object.keys(counts.by_domain || {}).sort();
  const schemas = Object.keys(counts.by_schema || {}).sort();

  return (
    <div className="flex h-full min-h-0">
      <aside className="hidden w-[276px] shrink-0 flex-col gap-3 overflow-y-auto border-r border-line bg-[#0b1117] p-4 md:flex">
        <div>
          <h1 className="text-sm font-semibold">Data curation</h1>
          <p className="mt-1 text-[11px] leading-relaxed text-dim">
            Import → clean → review → export. Only clean rows reach training.
          </p>
        </div>

        <Card>
          <CardHeader title="Sessions" subtitle={`${sessions.length} total`} right={
            <button onClick={loadSessions} className="text-dim hover:text-fg"><RefreshCw size={13} /></button>
          } />
          <div className="max-h-[260px] overflow-auto p-1.5">
            {sessions.map((s) => (
              <button key={s.id} onClick={() => selectSession(s.id)}
                className={cx(
                  "block w-full rounded-lg border px-2.5 py-2 text-left",
                  sessionId === s.id ? "border-accent/30 bg-accent/10" : "border-transparent hover:bg-elevated/50",
                )}>
                <div className="truncate text-[11.5px] font-medium text-fg">{s.name || s.id}</div>
                <div className="mt-0.5 truncate text-[10px] text-dim">{s.id}</div>
              </button>
            ))}
            {!sessions.length && <div className="px-3 py-4 text-center text-[11px] text-dim">No sessions yet.</div>}
          </div>
        </Card>

        <Card>
          <CardHeader title="Import" subtitle="Paths, globs, or folders" />
          <div className="space-y-2.5 p-3">
            <Textarea rows={3} value={importPaths} onChange={(e) => setImportPaths(e.target.value)}
              placeholder={"curriculum/01_raw/*.jsonl\n/path/to/export.json"} />
            <Input value={importDomain} onChange={(e) => setImportDomain(e.target.value)}
              placeholder="domain (optional)" />
            <div className="flex gap-3 text-[10.5px] text-muted">
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={importStrict} onChange={(e) => setImportStrict(e.target.checked)} /> strict tools
              </label>
              <label className="flex items-center gap-1.5">
                <input type="checkbox" checked={importRaw} onChange={(e) => setImportRaw(e.target.checked)} /> keep raw
              </label>
            </div>
            <Button variant="primary" className="w-full" onClick={doImport} disabled={busy === "import"}>
              <Upload size={13} /> {busy === "import" ? "Importing…" : "Import files"}
            </Button>
          </div>
        </Card>

        <div className="text-[10px] leading-relaxed text-dim">
          Hard gates run at export: secrets, host paths, invalid tool JSON, orphan
          observations, oversize rows. A failed gate blocks training.
        </div>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="border-b border-line bg-panel/40 px-5 py-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <Database size={15} className="text-accent" />
                <h2 className="truncate text-sm font-semibold">{session?.name || sessionId || "Select a session"}</h2>
                {session?.name && <span className="mono text-[10px] text-dim">{session.id}</span>}
              </div>
              <div className="mt-1 flex flex-wrap items-center gap-3 text-[10.5px] text-dim">
                <span><span className="text-ok">{acc}</span> kept</span>
                <span><span className="text-err">{rej}</span> rejected</span>
                <span><span className="text-muted">{pend}</span> pending</span>
                <span>{total} total</span>
              </div>
            </div>
            <div className="flex items-center gap-1.5">
              <Button size="sm" onClick={() => bulk("all_clean")} disabled={!sessionId || busy === "all_clean"}>
                <Check size={12} /> Accept clean
              </Button>
              <Button size="sm" onClick={() => bulk("reset")} disabled={!sessionId || busy === "reset"}>
                <RotateCcw size={12} /> Reset rejected
              </Button>
              <Button size="sm" onClick={() => selectSession(sessionId)} disabled={!sessionId}>
                <RefreshCw size={12} />
              </Button>
            </div>
          </div>
          <div className="mt-3 flex h-1 overflow-hidden rounded-full bg-[#0b1219]">
            <div className="bg-ok" style={{ width: bar(acc) }} />
            <div className="bg-err" style={{ width: bar(rej) }} />
            <div className="bg-[#3a4655]" style={{ width: bar(pend) }} />
          </div>
          {(error || notice) && (
            <div className="mt-3">
              {error ? <ErrorBanner error={error} onRetry={() => selectSession(sessionId)} /> :
                <div className="rounded-lg border border-ok/30 bg-ok/10 px-3 py-2 text-[11px] text-ok">{notice}</div>}
            </div>
          )}
          <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-4">
            <Select value={filters.decision} onChange={(e) => setFilter({ decision: e.target.value })}>
              <option value="">decision: all</option>
              <option value="pending">pending</option>
              <option value="accepted">accepted</option>
              <option value="rejected">rejected</option>
            </Select>
            <Select value={filters.flag} onChange={(e) => setFilter({ flag: e.target.value })}>
              <option value="">flag: none</option>
              {flags.map((f) => <option key={f} value={f}>{f} ({counts.by_flag?.[f]})</option>)}
            </Select>
            <Select value={filters.domain} onChange={(e) => setFilter({ domain: e.target.value })}>
              <option value="">domain: all</option>
              {domains.map((d) => <option key={d} value={d}>{d}</option>)}
            </Select>
            <Select value={filters.schema} onChange={(e) => setFilter({ schema: e.target.value })}>
              <option value="">schema: all</option>
              {schemas.map((s) => <option key={s} value={s}>{s}</option>)}
            </Select>
          </div>
        </div>

        <div className="min-h-0 flex-1 overflow-auto">
          {loading && !rows.length ? (
            <div className="p-6"><Spinner /></div>
          ) : !sessionId ? (
            <Empty title="Select a session" detail="Or import a JSONL file from the left panel." />
          ) : !rows.length ? (
            <Empty title="No rows match this filter" detail="Try resetting the filters, or accept/import rows." />
          ) : (
            <table className="data-table">
              <thead>
                <tr>
                  <th className="w-12">#</th><th>decision</th><th>domain</th>
                  <th className="num">tok</th><th>flags</th><th>preview</th><th>source</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => {
                  const preview = r.messages?.find((m) => m.role === "user")?.content || "";
                  return (
                    <tr key={r.id} onClick={() => { setSelectedId(r.id); setEditMode(false); setShowDiff(false); }}
                      className={cx("cursor-pointer", selectedId === r.id && "bg-accent/5")}>
                      <td className="mono text-dim">{r.id}</td>
                      <td><Pill tone={decisionTone(r.decision)}>{r.decision}</Pill></td>
                      <td className="text-muted">{r.domain || "—"}</td>
                      <td className="num text-muted">{r.est_tokens ?? "—"}</td>
                      <td>
                        {r.flags?.length ? (
                          <div className="flex flex-wrap gap-1">
                            {r.flags.slice(0, 2).map((f) => <Pill key={f} tone="warn">{f}</Pill>)}
                            {r.flags.length > 2 && <span className="text-[10px] text-dim">+{r.flags.length - 2}</span>}
                          </div>
                        ) : <span className="text-[10px] text-ok">clean</span>}
                      </td>
                      <td className="max-w-[460px]">
                        <div className="truncate text-[11.5px] text-muted">{preview || "(no user message)"}</div>
                      </td>
                      <td className="max-w-[150px] truncate text-[10px] text-dim">{r.source_file}:{r.source_line}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          )}
        </div>

        <div className="flex shrink-0 items-center justify-between border-t border-line px-5 py-2 text-[10.5px] text-dim">
          <span>{rows.length} loaded{hasMore ? " · more available" : ""}</span>
          {hasMore && <Button size="sm" onClick={loadMore} disabled={loading}>Load more</Button>}
        </div>
      </section>

      <aside className="hidden w-[390px] shrink-0 flex-col gap-3 overflow-y-auto border-l border-line bg-[#0b1117] p-4 xl:flex">
        <Card className="flex-1">
          <CardHeader title="Row" subtitle={selected ? `#${selected.id}` : "select a row"} />
          {selected ? (
            <div className="space-y-3 p-3">
              <div className="flex flex-wrap items-center gap-1.5">
                <Pill tone={decisionTone(selected.decision)}>{selected.decision}</Pill>
                {selected.edited && <Pill tone="accent">edited</Pill>}
                <span className="text-[10px] text-dim">{selected.domain} · {selected.schema}</span>
                <span className="text-[10px] text-dim">· {selected.est_tokens} tok</span>
              </div>
              <div className="flex flex-wrap gap-1">
                {selected.flags?.length ? selected.flags.map((f) => <Pill key={f} tone="warn">{f}</Pill>) :
                  <Pill tone="ok">clean</Pill>}
              </div>
              <div className="text-[10px] text-dim">{selected.source_file}:{selected.source_line}</div>

              {editMode ? (
                <div className="space-y-2">
                  {editMessages.map((m, i) => (
                    <div key={i}>
                      <div className="mb-1 text-[9.5px] uppercase tracking-[0.08em] text-dim">{m.role}</div>
                      <Textarea rows={4} value={m.content}
                        onChange={(e) => setEditMessages((prev) => prev.map((x, j) => j === i ? { ...x, content: e.target.value } : x))} />
                    </div>
                  ))}
                  <div className="flex gap-1.5">
                    <Button variant="primary" size="sm" onClick={saveEdit} disabled={busy === "edit"}>Save edit</Button>
                    <Button size="sm" onClick={() => setEditMode(false)}>Cancel</Button>
                  </div>
                </div>
              ) : (
                <div className="space-y-2">
                  {(showDiff && selected.original ? selected.original : selected.messages).map((m, i) => (
                    <div key={i} className="rounded-lg border border-line bg-[#0b1219] px-2.5 py-2">
                      <div className="mb-1 text-[9.5px] uppercase tracking-[0.08em] text-dim">{m.role}</div>
                      <div className="max-h-[220px] overflow-auto whitespace-pre-wrap text-[11px] leading-relaxed text-muted">{m.content}</div>
                    </div>
                  ))}
                </div>
              )}

              <div className="flex flex-wrap gap-1.5 border-t border-line pt-3">
                <Button variant="success" size="sm" onClick={() => decide("accepted")} disabled={!!busy}><Check size={12} /> Accept</Button>
                <Button variant="danger" size="sm" onClick={() => decide("rejected")} disabled={!!busy}><X size={12} /> Reject</Button>
                <Button size="sm" onClick={() => decide("pending")} disabled={!!busy}>Reset</Button>
                <Button size="sm" onClick={beginEdit} disabled={!!busy}>Edit</Button>
                {selected.original && <Button size="sm" onClick={() => setShowDiff((v) => !v)}>{showDiff ? "Hide" : "Diff"}</Button>}
              </div>
            </div>
          ) : (
            <Empty title="Select a row" detail="Click any row in the table to inspect, edit, accept, or reject it." />
          )}
        </Card>

        <Card>
          <CardHeader title="Export" subtitle="Hard gates must pass" />
          <div className="space-y-2.5 p-3">
            <div className="grid grid-cols-2 gap-2">
              <Field label="include">
                <Select value={exportInclude} onChange={(e) => setExportInclude(e.target.value)}>
                  <option value="accepted">accepted + edited</option>
                  <option value="clean">clean</option>
                  <option value="all">all</option>
                </Select>
              </Field>
              <Field label="format">
                <Select value={exportFormat} onChange={(e) => setExportFormat(e.target.value)}>
                  <option value="messages">messages</option>
                  <option value="chatml">chatml</option>
                  <option value="both">both</option>
                </Select>
              </Field>
            </div>
            <Field label="sort">
              <Select value={exportSort} onChange={(e) => setExportSort(e.target.value)}>
                <option value="domain">domain</option>
                <option value="tokens">tokens</option>
                <option value="source">source</option>
                <option value="none">none</option>
              </Select>
            </Field>
            <Button variant="primary" className="w-full" onClick={doExport} disabled={!sessionId || busy === "export"}>
              {busy === "export" ? "Exporting…" : "Export clean file"}
            </Button>
            {exportResult && (
              <div className="rounded-lg border border-line bg-[#0b1219] p-2.5 text-[10.5px]">
                <div className={cx("font-semibold", exportResult.validation?.passed ? "text-ok" : "text-err")}>
                  {exportResult.validation?.passed ? "hard gates: PASSED" : "hard gates: FAILED"}
                </div>
                <div className="mt-1 text-muted">{exportResult.rows} rows · {exportResult.duplicates_removed || 0} duplicates removed</div>
                <div className="mono mt-1 break-all text-dim">{exportResult.file}</div>
                {!exportResult.validation?.passed && (
                  <div className="mt-1 text-err">{JSON.stringify(exportResult.validation?.violations)}</div>
                )}
              </div>
            )}
            <div className="text-[10px] text-dim">
              Exports go to <span className="mono">exports/</span> and print a manifest + rejected bundle.
            </div>
          </div>
        </Card>
      </aside>
    </div>
  );
}
