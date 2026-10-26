import { useCallback, useEffect, useState } from "react";
import { Check, Copy, FlaskConical, RefreshCw } from "lucide-react";
import { api, errorMessage } from "../api";
import type { OpsStatus } from "../types";
import {
  Button, Card, CardHeader, Empty, ErrorBanner, KV, PageHeader, Pill, ViewShell, fmt,
} from "../components/ui";

const COMMANDS = `python -m forge_rsi loop --round r2 --iterations 5
python -m forge_rsi skills-eval --splits dev,holdout,skills --run-id legates_final
python -m forge_rsi skills-report
python -m forge_rsi final-report`;

export function RsiView() {
  const [status, setStatus] = useState<OpsStatus | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const d = await api.get<{ status: OpsStatus }>("/api/ops/status");
      setStatus(d.status);
    }
    catch (e) { setError(errorMessage(e)); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => { load(); }, [load]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(COMMANDS);
      setCopied(true);
      setTimeout(() => setCopied(false), 1400);
    } catch { /* clipboard unavailable */ }
  };

  const decision = status?.private_decision || {};
  const iterations = status?.rsi?.iterations || [];
  const holdout = status?.rsi?.holdout || [];
  const cfgs = status?.composition?.configs || {};

  return (
    <ViewShell>
      <PageHeader
        title="RSI"
        subtitle="The harness loop keeps a candidate only when it beats the incumbent task-by-task, stays near its cost, and passes the anti-leak validator."
        actions={<Button onClick={load} disabled={loading}><RefreshCw size={13} /> Refresh</Button>}
      />
      {error && <ErrorBanner error={error} onRetry={load} />}

      <div className="mt-1 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader title="Acceptance rule" subtitle="Ties keep the incumbent" right={<FlaskConical size={15} className="text-accent" />} />
          <div className="grid gap-2 p-4 text-[11.5px] text-muted sm:grid-cols-2">
            <div className="rounded-lg border border-line bg-[#0b1219] px-3 py-2"><span className="text-dim">1 · win</span> wins &gt; losses on the same dev tasks</div>
            <div className="rounded-lg border border-line bg-[#0b1219] px-3 py-2"><span className="text-dim">2 · score</span> not more than 0.05 below incumbent</div>
            <div className="rounded-lg border border-line bg-[#0b1219] px-3 py-2"><span className="text-dim">3 · cost</span> at most 1.5× cost per solved task</div>
            <div className="rounded-lg border border-line bg-[#0b1219] px-3 py-2"><span className="text-dim">4 · safety</span> anti-leak validator passes</div>
          </div>
          <div className="px-4 pb-4 text-[11px] leading-relaxed text-dim">
            The holdout is a regression guard, not an optimization signal. The
            first `run_tests` proposals tied and were rejected; the anti-stub
            `nonstub_retry` proposal won two tasks and was accepted.
          </div>
        </Card>

        <Card className="px-4 py-4">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-dim">Round 2 decision</div>
          <div className="mt-1 text-lg font-semibold">{decision.promote === undefined ? "—" : decision.promote ? "PROMOTE" : "KEEP ROUND 1"}</div>
          <div className="mt-1 text-[11px] text-muted">{decision.reason || "No private-holdout decision yet."}</div>
          <div className="mt-3">
            <KV k="private Δ" v={fmt(decision.private_delta, 2)} mono />
            <KV k="public dev Δ" v={fmt(decision.public_dev_delta, 2)} mono />
            <KV k="24-probe Δ" v={fmt(decision.public_probe_delta, 2)} mono />
          </div>
        </Card>
      </div>

      <Card className="mt-4">
        <CardHeader title="Iterations" subtitle="Every proposal, including the rejected ones" />
        <div className="max-h-[320px] overflow-auto">
          <table className="data-table">
            <thead><tr><th>round</th><th className="num">#</th><th>candidate</th><th className="num">W</th><th className="num">L</th><th className="num">dev</th><th className="num">Δ</th><th>decision</th><th>reason</th></tr></thead>
            <tbody>
              {iterations.map((r) => (
                <tr key={`${r.round}-${r.iteration}`}>
                  <td className="text-dim">{r.round}</td>
                  <td className="num text-muted">{r.iteration}</td>
                  <td className="mono text-fg">{r.candidate}</td>
                  <td className="num text-muted">{r.wins ?? "—"}</td>
                  <td className="num text-muted">{r.losses ?? "—"}</td>
                  <td className="num">{fmt(r.candidate_score, 2)}</td>
                  <td className="num text-muted">{r.delta == null ? "—" : `${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(2)}`}</td>
                  <td><Pill tone={r.accepted ? "ok" : "err"}>{r.accepted ? "accepted" : "rejected"}</Pill></td>
                  <td className="max-w-[280px] truncate text-[11px] text-dim" title={r.reason}>{r.reason || "—"}</td>
                </tr>
              ))}
              {!iterations.length && <tr><td colSpan={9}><Empty title="No RSI rounds found" /></td></tr>}
            </tbody>
          </table>
        </div>
        <div className="grid gap-3 border-t border-line p-4 sm:grid-cols-2">
          {holdout.map((h) => (
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

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Composition" subtitle="Parts work; the whole does not" />
          <table className="data-table">
            <thead><tr><th>config</th><th className="num">parts word</th><th className="num">parts merge</th><th className="num">whole</th></tr></thead>
            <tbody>
              {Object.entries(cfgs).map(([name, c]) => (
                <tr key={name}>
                  <td className="mono text-fg">{name}</td>
                  <td className="num text-muted">{c.parts_word ?? "—"}/{c.parts_word_n ?? "—"}</td>
                  <td className="num text-muted">{c.parts_merge ?? "—"}/{c.parts_merge_n ?? "—"}</td>
                  <td className="num"><strong>{c.whole_pass}/{c.whole_n}</strong></td>
                </tr>
              ))}
              {!Object.keys(cfgs).length && <tr><td colSpan={4}><Empty title="No composition matrix found" /></td></tr>}
            </tbody>
          </table>
        </Card>

        <Card>
          <CardHeader title="Run the loop" subtitle="Long-running stages are CLI for now" right={
            <Button size="sm" onClick={copy}>{copied ? <Check size={12} /> : <Copy size={12} />} {copied ? "Copied" : "Copy"}</Button>
          } />
          <pre className="mono overflow-auto whitespace-pre-wrap px-4 py-3 text-[11px] leading-relaxed text-muted">{COMMANDS}</pre>
          <div className="border-t border-line px-4 py-3 text-[10.5px] text-dim">
            The UI is deliberately read-only for long loops; training/eval jobs
            remain explicit CLI actions until a job queue with base-lock checks ships.
          </div>
        </Card>
      </div>
    </ViewShell>
  );
}
