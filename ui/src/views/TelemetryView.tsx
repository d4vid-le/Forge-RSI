import { useCallback, useEffect, useState } from "react";
import { Activity, FileText, RefreshCw } from "lucide-react";
import { api, errorMessage } from "../api";
import type { ForgeStatus, OpsStatus } from "../types";
import {
  Button, Card, CardHeader, Empty, ErrorBanner, KV, PageHeader, Pill, Score,
  Stat, ViewShell, cx, fmt,
} from "../components/ui";

export function TelemetryView() {
  const [forge, setForge] = useState<ForgeStatus | null>(null);
  const [ops, setOps] = useState<OpsStatus | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState("final.md");
  const [reportText, setReportText] = useState("");

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [f, o] = await Promise.all([
        api.get<ForgeStatus>("/api/forge/status"),
        api.get<{ status: OpsStatus }>("/api/ops/status"),
      ]);
      setForge(f); setOps(o.status);
    } catch (e) { setError(errorMessage(e)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const openReport = async (name: string) => {
    setReport(name);
    setReportText("loading…");
    try {
      const d = await api.get<{ text: string }>(`/api/ops/report?name=${encodeURIComponent(name)}`);
      setReportText(d.text);
    } catch (e) { setReportText(`Could not load ${name}: ${errorMessage(e)}`); }
  };
  useEffect(() => {
    if (!reportText && ops?.reports?.length) openReport(report);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ops]);

  const runs = forge?.runs || [];
  const ev = ops?.evaluations || [];
  const last = runs[0];

  return (
    <ViewShell>
      <PageHeader
        title="Telemetry"
        subtitle="What actually ran: real MLX runs, gated evaluations, base-lock state, and the reports generated from disk."
        actions={<Button onClick={load} disabled={loading}><RefreshCw size={13} /> Refresh</Button>}
      />
      {error && <ErrorBanner error={error} onRetry={load} />}

      <div className="mt-1 grid grid-cols-2 gap-3 md:grid-cols-4">
        <Stat label="Models" value={forge?.models?.length ?? "—"} note="discovered by inspection" />
        <Stat label="Adapters" value={forge?.adapters?.length ?? "—"} note="nested Le-Gates included" />
        <Stat label="Runs" value={runs.length} note="real mlx_lm runs on disk" />
        <Stat
          label="Last run"
          value={last?.status || "—"}
          note={last ? `${last.name} · ${last.data?.train ?? 0}/${last.data?.valid ?? 0} rows` : "no runs"}
          tone={last?.status === "finished" ? "ok" : last?.status === "failed" ? "err" : "neutral"}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader title="Training runs" subtitle="Loss comes from `mlx_lm.lora` output, not a simulation" right={<Activity size={15} className="text-accent" />} />
          <div className="max-h-[320px] overflow-auto">
            <table className="data-table">
              <thead><tr><th>run</th><th>status</th><th className="num">train</th><th className="num">valid</th><th className="num">last train</th><th className="num">last val</th><th>adapter</th></tr></thead>
              <tbody>
                {runs.map((r) => (
                  <tr key={r.name}>
                    <td className="mono text-fg">{r.name}</td>
                    <td><Pill tone={r.status === "running" ? "warn" : r.status === "finished" ? "ok" : r.status === "failed" ? "err" : "neutral"}>{r.status || "—"}</Pill></td>
                    <td className="num text-muted">{r.data?.train ?? "—"}</td>
                    <td className="num text-muted">{r.data?.valid ?? "—"}</td>
                    <td className="num text-muted">{fmt(r.last_train?.loss, 4)}</td>
                    <td className="num text-muted">{fmt(r.last_val?.loss, 4)}</td>
                    <td className="max-w-[220px] truncate mono text-[10px] text-dim" title={r.adapter_path}>{r.adapter_path || "—"}</td>
                  </tr>
                ))}
                {!runs.length && <tr><td colSpan={7}><Empty title="No training runs found" detail="Train an adapter in the Train view." /></td></tr>}
              </tbody>
            </table>
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="px-4 py-4">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-dim">Base lock</div>
            <div className="mt-1 flex items-center gap-2">
              <span className={cx("h-2 w-2 rounded-full", ops?.base?.checksums_ok ? "bg-ok" : "bg-warn")} />
              <span className="text-sm font-semibold">
                {ops?.base?.checksums_ok === true ? "verified" : ops?.base?.checksums_ok === false ? "mismatch" : "not recorded"}
              </span>
            </div>
            <div className="mt-2 break-all mono text-[10px] text-dim">{ops?.base?.path || "—"}</div>
            <div className="mt-2 text-[11px] text-muted">{ops?.base?.exists ? "model present" : "model missing"}</div>
          </Card>
          <Card className="px-4 py-4">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-dim">Task suite</div>
            <div className="mt-2">
              {Object.entries(ops?.tasks?.counts || {}).map(([k, v]) => <KV key={k} k={k} v={v} mono />)}
              <KV k="lint" v={ops?.tasks?.lint?.ok ? "PASS" : "FAIL"} />
            </div>
          </Card>
        </div>
      </div>

      <Card className="mt-4">
        <CardHeader title="Evaluation matrix" subtitle="Base vs gated, with the zero-forgetting gate" />
        <div className="max-h-[340px] overflow-auto">
          <table className="data-table">
            <thead><tr><th>run</th><th>split</th><th className="num">base</th><th className="num">gated</th><th className="num">Δ</th><th className="num">routed</th><th>identical</th><th>base</th></tr></thead>
            <tbody>
              {ev.map((r) => (
                <tr key={r.run}>
                  <td className="mono text-fg">{r.run}</td>
                  <td className="text-muted">{r.split}</td>
                  <td className="num"><Score s={r.base} /></td>
                  <td className="num"><Score s={r.gated} /></td>
                  <td className="num text-muted">{r.delta == null ? "—" : `${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(2)}`}</td>
                  <td className="num text-muted">{r.routed}</td>
                  <td>{r.non_routed_identical === true ? <Pill tone="ok">yes</Pill> : "—"}</td>
                  <td>{r.base_unchanged === true ? <Pill tone="ok">OK</Pill> : "—"}</td>
                </tr>
              ))}
              {!ev.length && <tr><td colSpan={8}><Empty title="No evaluations found" /></td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="mt-4">
        <CardHeader title="Reports" subtitle="Generated from disk; no hand-typed numbers" right={<FileText size={14} className="text-dim" />} />
        <div className="flex flex-wrap gap-1.5 border-b border-line px-4 py-3">
          {(ops?.reports || []).map((r) => (
            <button key={r.name} onClick={() => openReport(r.name)}
              className={cx("rounded-md border px-2 py-1 text-[11px]",
                report === r.name ? "border-accent/40 bg-accent/10 text-accent" : "border-line bg-elevated/50 text-muted hover:text-fg")}>
              {r.name}
            </button>
          ))}
        </div>
        <pre className="mono max-h-[320px] overflow-auto whitespace-pre-wrap px-4 py-3 text-[11px] leading-relaxed text-muted">
          {reportText || "Select a report."}
        </pre>
      </Card>
    </ViewShell>
  );
}
