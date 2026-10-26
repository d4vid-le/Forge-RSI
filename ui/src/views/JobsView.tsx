import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Check, ChevronRight, ListChecks, RefreshCw, ShieldCheck, Square, X,
} from "lucide-react";
import { api, errorMessage } from "../api";
import type { Job } from "../types";
import {
  Button, Card, CardHeader, Empty, ErrorBanner, Field, Input, Pill, Select,
  Spinner, ViewShell, cx, dateLabel,
} from "../components/ui";

const KINDS: { id: string; label: string; detail: string }[] = [
  { id: "skills_round", label: "Skill round", detail: "corpora → train → gated eval → human gate → reports" },
  { id: "rsi_round", label: "RSI round", detail: "harness loop → human gate → reports" },
  { id: "reports", label: "Reports only", detail: "regenerate the measured reports from disk" },
];

function tone(status: string) {
  if (status === "completed") return "ok" as const;
  if (status === "failed") return "err" as const;
  if (status === "awaiting_approval") return "warn" as const;
  if (status === "running") return "accent" as const;
  if (status === "rejected" || status === "cancelled") return "err" as const;
  return "neutral" as const;
}

function summary(job: Job) {
  if (job.kind === "skills_round") {
    return `${job.params.skills} · ${job.params.rows} rows · ${job.params.iters} iters · ${job.params.run_id}`;
  }
  if (job.kind === "rsi_round") {
    return `round ${job.params.round} · ${job.params.iterations} iterations`;
  }
  return "skills report + final report";
}

export function JobsView() {
  const [jobs, setJobs] = useState<Job[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [log, setLog] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);
  const [kind, setKind] = useState("skills_round");
  const [skills, setSkills] = useState("word_freq,merge_intervals");
  const [rows, setRows] = useState(40);
  const [iters, setIters] = useState(120);
  const [runId, setRunId] = useState(
    () => `queue_${new Date().toISOString().slice(0, 10).replace(/-/g, "")}`,
  );
  const [round, setRound] = useState("r3");
  const [iterations, setIterations] = useState(3);

  const load = useCallback(async (quiet = false) => {
    if (!quiet) setLoading(true);
    try {
      const d = await api.get<{ jobs: Job[] }>("/api/jobs");
      setJobs(d.jobs || []);
      setSelected((prev) => prev || d.jobs?.[0]?.id || "");
      setError("");
    } catch (e) {
      if (!quiet) setError(errorMessage(e));
    } finally {
      if (!quiet) setLoading(false);
    }
  }, []);

  const loadLog = useCallback(async (id: string) => {
    if (!id) { setLog(""); return; }
    try {
      const d = await api.get<{ text: string }>(`/api/jobs/log?id=${encodeURIComponent(id)}&lines=200`);
      setLog(d.text || "");
    } catch (e) {
      setLog(`log unavailable: ${errorMessage(e)}`);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    const fresh = jobs.some((j) => j.status === "running" || j.status === "queued");
    const t = setInterval(() => load(true), fresh ? 3000 : 8000);
    return () => clearInterval(t);
  }, [jobs, load]);
  useEffect(() => {
    const job = jobs.find((j) => j.id === selected);
    if (!job) { setLog(""); return; }
    loadLog(job.id);
    if (job.status !== "running" && job.status !== "queued") return;
    const t = setInterval(() => loadLog(job.id), 3000);
    return () => clearInterval(t);
  }, [selected, jobs, loadLog]);

  const submit = async () => {
    setBusy("submit"); setError(""); setNotice("");
    const params: Record<string, unknown> = {};
    if (kind === "skills_round") Object.assign(params, { skills, rows, iters, run_id: runId });
    if (kind === "rsi_round") Object.assign(params, { round, iterations });
    try {
      const d = await api.post<{ job: Job }>("/api/jobs", { kind, params });
      setNotice(`queued ${d.job.id}`);
      setSelected(d.job.id);
      await load(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const approve = async (id: string, ok: boolean) => {
    setBusy(id); setError(""); setNotice("");
    try {
      const d = await api.post<{ job: Job }>("/api/jobs/approve", { id, approve: ok });
      setNotice(`${d.job.id} → ${d.job.status}`);
      await load(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally { setBusy(""); }
  };

  const cancel = async (id: string) => {
    setBusy(id); setError("");
    try {
      await api.post("/api/jobs/cancel", { id });
      await load(true);
    } catch (e) {
      setError(errorMessage(e));
    } finally { setBusy(""); }
  };

  const job = useMemo(() => jobs.find((j) => j.id === selected) || null, [jobs, selected]);
  const awaiting = jobs.filter((j) => j.status === "awaiting_approval").length;

  return (
    <ViewShell>
      <div className="flex flex-wrap items-start justify-between gap-3 pb-5">
        <div className="min-w-0">
          <h1 className="text-xl font-semibold tracking-tight">Jobs</h1>
          <p className="mt-1 max-w-3xl text-sm text-muted">
            Guarded, sequential steps with a human gate before anything is promoted.
            Commands are allowlisted; there is no shell and no free-form argv.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {awaiting > 0 && <Pill tone="warn">{awaiting} awaiting approval</Pill>}
          <Button onClick={() => load()} disabled={loading}><RefreshCw size={13} /> Refresh</Button>
        </div>
      </div>

      {error && <ErrorBanner error={error} onRetry={() => load()} />}
      {notice && (
        <div className="mb-4 rounded-lg border border-ok/30 bg-ok/10 px-3 py-2 text-[11px] text-ok">{notice}</div>
      )}

      <div className="grid gap-4 xl:grid-cols-[360px_minmax(0,1fr)]">
        <div className="space-y-4">
          <Card>
            <CardHeader title="New job" subtitle="One running job at a time" right={<ListChecks size={15} className="text-accent" />} />
            <div className="space-y-3 p-4">
              <Field label="kind">
                <Select value={kind} onChange={(e) => setKind(e.target.value)}>
                  {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
                </Select>
              </Field>
              <div className="rounded-lg border border-line bg-[#0b1219] px-2.5 py-2 text-[10.5px] text-dim">
                {KINDS.find((k) => k.id === kind)?.detail}
              </div>

              {kind === "skills_round" && (
                <>
                  <Field label="skills" hint="comma-separated registry names">
                    <Input value={skills} onChange={(e) => setSkills(e.target.value)} />
                  </Field>
                  <div className="grid grid-cols-2 gap-2">
                    <Field label="rows per skill">
                      <Input type="number" value={rows} onChange={(e) => setRows(Number(e.target.value))} />
                    </Field>
                    <Field label="train iters">
                      <Input type="number" value={iters} onChange={(e) => setIters(Number(e.target.value))} />
                    </Field>
                  </div>
                  <Field label="run id" hint="used by skills-eval and skills-decide">
                    <Input value={runId} onChange={(e) => setRunId(e.target.value)} />
                  </Field>
                </>
              )}

              {kind === "rsi_round" && (
                <div className="grid grid-cols-2 gap-2">
                  <Field label="round">
                    <Input value={round} onChange={(e) => setRound(e.target.value)} />
                  </Field>
                  <Field label="iterations">
                    <Input type="number" value={iterations} onChange={(e) => setIterations(Number(e.target.value))} />
                  </Field>
                </div>
              )}

              <Button variant="primary" className="w-full" onClick={submit} disabled={busy === "submit"}>
                {busy === "submit" ? "Queuing…" : "Queue job"}
              </Button>
              <div className="flex items-start gap-1.5 text-[10px] leading-relaxed text-dim">
                <ShieldCheck size={12} className="mt-0.5 shrink-0 text-ok" />
                Training steps check the base lock first. A mismatch fails the job before any weights are touched.
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader title="Queue" subtitle={`${jobs.length} jobs on disk`} />
            <div className="max-h-[430px] overflow-auto p-2">
              {jobs.map((j) => (
                <button key={j.id} onClick={() => setSelected(j.id)}
                  className={cx(
                    "mb-1 block w-full rounded-lg border px-2.5 py-2 text-left",
                    selected === j.id ? "border-accent/30 bg-accent/10" : "border-transparent hover:bg-elevated/50",
                  )}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="mono truncate text-[11px] text-fg">{j.kind}</span>
                    <Pill tone={tone(j.status)}>{j.status.replace("_", " ")}</Pill>
                  </div>
                  <div className="mt-0.5 truncate text-[10px] text-dim">{summary(j)}</div>
                  <div className="mt-0.5 text-[9.5px] text-dim">{dateLabel(j.created)}</div>
                </button>
              ))}
              {!jobs.length && <div className="px-3 py-6 text-center text-[11px] text-dim">No jobs yet.</div>}
            </div>
          </Card>
        </div>

        <Card className="flex min-h-[560px] flex-col">
          <CardHeader
            title={job ? job.id : "Job detail"}
            subtitle={job ? summary(job) : "Select a job to inspect its steps and log"}
            right={job ? <Pill tone={tone(job.status)}>{job.status.replace("_", " ")}</Pill> : undefined}
          />
          {!job ? (
            <Empty title="No job selected" detail="Queue one on the left, or pick an existing job." />
          ) : (
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="border-b border-line px-4 py-3">
                <div className="flex flex-wrap items-center gap-1.5">
                  {job.steps.map((s, i) => (
                    <div key={i} className="flex items-center gap-1.5">
                      <span className={cx(
                        "inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[10px]",
                        s.status === "done" ? "border-ok/40 bg-ok/10 text-ok" :
                          s.status === "running" ? "border-accent/40 bg-accent/10 text-accent" :
                            s.status === "failed" || s.status === "cancelled" ? "border-err/40 bg-err/10 text-err" :
                              "border-line bg-elevated/40 text-dim",
                      )}>
                        {s.status === "done" ? <Check size={10} /> : s.status === "running"
                          ? <span className="h-2 w-2 animate-pulse rounded-full bg-accent" /> : null}
                        {s.name}
                        {s.gate && <span className="text-[9px] text-warn">gate</span>}
                      </span>
                      {i < job.steps.length - 1 && <ChevronRight size={11} className="text-dim" />}
                    </div>
                  ))}
                </div>
                {job.note && <div className="mt-2 text-[11px] text-muted">{job.note}</div>}
                {job.status === "awaiting_approval" && (
                  <div className="mt-3 flex flex-wrap items-center gap-2 rounded-lg border border-warn/35 bg-warn/10 px-3 py-2">
                    <span className="text-[11px] text-warn">
                      Measurement is done. Promotion is a human decision.
                    </span>
                    <div className="ml-auto flex gap-1.5">
                      <Button variant="success" size="sm" onClick={() => approve(job.id, true)} disabled={busy === job.id}>
                        <Check size={12} /> Approve
                      </Button>
                      <Button variant="danger" size="sm" onClick={() => approve(job.id, false)} disabled={busy === job.id}>
                        <X size={12} /> Reject
                      </Button>
                    </div>
                  </div>
                )}
                {(job.status === "running" || job.status === "queued") && (
                  <div className="mt-3">
                    <Button variant="danger" size="sm" onClick={() => cancel(job.id)} disabled={busy === job.id}>
                      <Square size={12} /> Cancel
                    </Button>
                  </div>
                )}
              </div>
              <pre className="mono min-h-0 flex-1 overflow-auto whitespace-pre-wrap bg-[#0b1219] px-4 py-3 text-[10.5px] leading-relaxed text-muted">
                {log || "No output yet."}
              </pre>
            </div>
          )}
        </Card>
      </div>
    </ViewShell>
  );
}
