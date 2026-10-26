import { useCallback, useEffect, useState } from "react";
import { FileText, RefreshCw } from "lucide-react";
import { api, errorMessage } from "../api";
import type { EvalRow, OpsStatus } from "../types";
import {
  Button, Card, CardHeader, Empty, ErrorBanner, KV, PageHeader, Pill, Score,
  Stat, ViewShell, cx, fmt,
} from "../components/ui";

function evalTag(run: string) {
  if (run.includes("fixed")) return <Pill tone="ok" className="ml-1.5">fixed</Pill>;
  if (run === "skills24_r1_skills" || run === "r2_public_skills") {
    return <Pill tone="warn" className="ml-1.5">pre-fix</Pill>;
  }
  return null;
}

export function OverviewView() {
  const [status, setStatus] = useState<OpsStatus | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [report, setReport] = useState("final.md");
  const [reportText, setReportText] = useState("");
  const [reportLoading, setReportLoading] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const d = await api.get<{ status: OpsStatus }>("/api/ops/status");
      setStatus(d.status);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const openReport = useCallback(async (name: string) => {
    setReport(name);
    setReportLoading(true);
    try {
      const d = await api.get<{ text: string }>(`/api/ops/report?name=${encodeURIComponent(name)}`);
      setReportText(d.text);
    } catch (e) {
      setReportText(`Could not load ${name}: ${errorMessage(e)}`);
    } finally {
      setReportLoading(false);
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (status?.reports.length && !reportText) openReport(report);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  const ev = status?.evaluations || [];
  const pick = (name: string) => ev.find((r) => r.run === name);
  const dev = pick("legates_final_dev") || pick("r2_public_dev");
  const hold = pick("legates_final_holdout");
  const probes = pick("skills24_fixed_r1_skills")
    || ev.find((r) => r.run.includes("skills24_fixed") && r.split === "skills");
  const priv = pick("private_r1_private_holdout")
    || ev.find((r) => r.run.startsWith("private_r1") && r.split === "private_holdout");
  const lint = status?.tasks?.lint;
  const decision = status?.private_decision || {};
  const cfgs = status?.composition?.configs || {};

  return (
    <ViewShell>
      <PageHeader
        title="Overview"
        subtitle="One frozen base. Measured harness search, isolated skills, and a clean regression trail."
        actions={<Button onClick={load} disabled={loading}><RefreshCw size={13} /> Refresh</Button>}
      />

      {error && <ErrorBanner error={error} onRetry={load} />}

      <div className="mt-1 grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Dev" value={<Score s={dev?.gated} />} note={dev ? `base ${dev.base.passed}/${dev.base.n}` : "no run"} />
        <Stat label="Holdout" value={<Score s={hold?.gated} />} note={hold ? `base ${hold.base.passed}/${hold.base.n}` : "no run"} />
        <Stat label="24 probes" value={<Score s={probes?.gated} />} note={probes ? `base ${probes.base.passed}/${probes.base.n}` : "no run"} tone="accent" />
        <Stat label="Private holdout" value={<Score s={priv?.gated} />} note={priv ? `base ${priv.base.passed}/${priv.base.n}` : "no run"} tone="accent" />
        <Stat label="Task lint" value={lint?.ok ? "PASS" : "FAIL"} note={`${lint?.n ?? 0} tasks`} tone={lint?.ok ? "ok" : "err"} />
        <Stat
          label="Base lock"
          value={status?.base?.checksums_ok === true ? "OK" : status?.base?.checksums_ok === false ? "FAIL" : "—"}
          note={status?.base?.exists ? "model present" : "model missing"}
          tone={status?.base?.checksums_ok === false ? "err" : "ok"}
        />
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader title="Skill adapters" subtitle="Le-Gates registry, rounds 1 and 2" />
          <div className="max-h-[330px] overflow-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>round</th><th>skill</th><th>status</th><th className="num">rows</th>
                  <th className="num">iters</th><th className="num">train</th><th className="num">val</th>
                  <th>base</th><th>decision</th>
                </tr>
              </thead>
              <tbody>
                {(status?.skills || []).map((s, i) => {
                  const st = s.adapter_exists ? s.status : "untrained";
                  return (
                    <tr key={`${s.round}-${s.skill}-${i}`}>
                      <td className="text-dim">{s.round}</td>
                      <td className="mono text-fg">{s.skill}</td>
                      <td><Pill tone={st === "promoted" ? "ok" : st === "candidate" ? "accent" : st === "quarantined" ? "err" : "neutral"}>{st}</Pill></td>
                      <td className="num text-muted">{s.rows ?? "—"}</td>
                      <td className="num text-muted">{s.iters ?? "—"}</td>
                      <td className="num text-muted">{fmt(s.train_loss, 3)}</td>
                      <td className="num text-muted">{fmt(s.val_loss, 3)}</td>
                      <td>{s.base_unchanged === true ? <Pill tone="ok">OK</Pill> : "—"}</td>
                      <td className="max-w-[230px] truncate text-[11px] text-dim" title={s.decision?.reason}>{s.decision?.reason || "—"}</td>
                    </tr>
                  );
                })}
                {!status?.skills?.length && <tr><td colSpan={9}><Empty title="No skill registry found" detail="Train adapters with `python -m forge_rsi skills-train`." /></td></tr>}
              </tbody>
            </table>
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="px-4 py-4">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-dim">Round 2 decision</div>
            <div className={cx("mt-1 text-xl font-semibold", decision.promote ? "text-ok" : "text-fg")}>
              {decision.promote === undefined ? "—" : decision.promote ? "PROMOTE" : "KEEP ROUND 1"}
            </div>
            <div className="mt-1 text-[11px] text-muted">{decision.reason || "No private-holdout decision yet."}</div>
            <div className="mt-3">
              <KV k="private Δ" v={fmt(decision.private_delta, 2)} mono />
              <KV k="public dev Δ" v={fmt(decision.public_dev_delta, 2)} mono />
              <KV k="probe Δ" v={fmt(decision.public_probe_delta, 2)} mono />
              <KV k="forgetting ok" v={String(decision.forgetting_ok ?? "—")} />
            </div>
          </Card>

          <Card>
            <CardHeader title="Composition" subtitle="Parts vs the whole" />
            <table className="data-table">
              <thead><tr><th>config</th><th className="num">word</th><th className="num">merge</th><th className="num">whole</th></tr></thead>
              <tbody>
                {Object.entries(cfgs).map(([name, c]) => (
                  <tr key={name}>
                    <td className="mono text-fg">{name}</td>
                    <td className="num text-muted">{c.parts_word ?? "—"}/{c.parts_word_n ?? "—"}</td>
                    <td className="num text-muted">{c.parts_merge ?? "—"}/{c.parts_merge_n ?? "—"}</td>
                    <td className="num"><strong>{c.whole_pass}/{c.whole_n}</strong></td>
                  </tr>
                ))}
                {!Object.keys(cfgs).length && <tr><td colSpan={4} className="text-dim">No composition matrix found.</td></tr>}
              </tbody>
            </table>
          </Card>
        </div>
      </div>

      <Card className="mt-4">
        <CardHeader title="Evaluations" subtitle="Every gated run on disk, including the superseded 23/24 pass" />
        <div className="max-h-[300px] overflow-auto">
          <table className="data-table">
            <thead><tr><th>run</th><th>split</th><th className="num">base</th><th className="num">gated</th><th className="num">Δ</th><th className="num">routed</th><th>identical</th><th>base</th></tr></thead>
            <tbody>
              {ev.map((r: EvalRow) => (
                <tr key={r.run}>
                  <td className="mono text-fg">{r.run}{evalTag(r.run)}</td>
                  <td className="text-muted">{r.split}</td>
                  <td className="num"><Score s={r.base} /></td>
                  <td className="num"><Score s={r.gated} /></td>
                  <td className={cx("num", (r.delta || 0) > 0 ? "text-ok" : (r.delta || 0) < 0 ? "text-err" : "text-muted")}>
                    {r.delta == null ? "—" : `${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(2)}`}
                  </td>
                  <td className="num text-muted">{r.routed}</td>
                  <td>{r.non_routed_identical === true ? <Pill tone="ok">yes</Pill> : "—"}</td>
                  <td>{r.base_unchanged === true ? <Pill tone="ok">OK</Pill> : "—"}</td>
                </tr>
              ))}
              {!ev.length && <tr><td colSpan={8}><Empty title="No gated evaluations found" /></td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="RSI rounds" subtitle="Acceptance is pairwise and cost-aware" />
          <table className="data-table">
            <thead><tr><th>round</th><th className="num">#</th><th>candidate</th><th className="num">W/L</th><th className="num">dev</th><th className="num">Δ</th><th>decision</th></tr></thead>
            <tbody>
              {(status?.rsi?.iterations || []).map((r) => (
                <tr key={`${r.round}-${r.iteration}`}>
                  <td className="text-dim">{r.round}</td>
                  <td className="num text-muted">{r.iteration}</td>
                  <td className="mono text-fg">{r.candidate}</td>
                  <td className="num text-muted">{r.wins}/{r.losses}</td>
                  <td className="num">{fmt(r.candidate_score, 2)}</td>
                  <td className={cx("num", (r.delta || 0) > 0 ? "text-ok" : (r.delta || 0) < 0 ? "text-err" : "text-muted")}>
                    {r.delta == null ? "—" : `${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(2)}`}
                  </td>
                  <td><Pill tone={r.accepted ? "ok" : "err"}>{r.accepted ? "accepted" : "rejected"}</Pill></td>
                </tr>
              ))}
              {!status?.rsi?.iterations?.length && <tr><td colSpan={7}><Empty title="No RSI rounds found" /></td></tr>}
            </tbody>
          </table>
          <div className="grid gap-3 border-t border-line p-4 sm:grid-cols-2">
            {(status?.rsi?.holdout || []).map((h) => (
              <div key={h.round} className="rounded-lg border border-line bg-[#0b1219] px-3 py-2.5">
                <div className="text-[10px] uppercase tracking-[0.08em] text-dim">{h.round} holdout</div>
                <div className="mt-1 flex items-baseline gap-2">
                  <span className="text-lg font-semibold num">{fmt(h.final_score, 2)}</span>
                  <span className="text-[11px] text-dim">base {fmt(h.baseline_score, 2)}</span>
                </div>
                <div className="mt-0.5 text-[11px] text-muted">
                  Δ {fmt(h.delta, 2)} · not worse: {h.not_worse ? "yes" : "no"} · winner <span className="mono">{h.winner_harness || "—"}</span>
                </div>
              </div>
            ))}
          </div>
        </Card>

        <Card className="flex min-h-[300px] flex-col">
          <CardHeader
            title="Reports"
            subtitle="Sanitized evidence, generated from on-disk artifacts"
            right={<FileText size={14} className="text-dim" />}
          />
          <div className="flex flex-wrap gap-1.5 border-b border-line px-4 py-3">
            {(status?.reports || []).map((r) => (
              <button
                key={r.name}
                onClick={() => openReport(r.name)}
                className={cx(
                  "rounded-md border px-2 py-1 text-[11px]",
                  report === r.name ? "border-accent/40 bg-accent/10 text-accent" : "border-line bg-elevated/50 text-muted hover:text-fg",
                )}
              >{r.name}</button>
            ))}
          </div>
          <pre className="mono min-h-0 flex-1 overflow-auto whitespace-pre-wrap px-4 py-3 text-[11px] leading-relaxed text-muted">
            {reportLoading ? "loading…" : reportText || "Select a report."}
          </pre>
        </Card>
      </div>
    </ViewShell>
  );
}
