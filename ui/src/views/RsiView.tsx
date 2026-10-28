import { useCallback, useEffect, useState } from "react";
import { Check, Copy, FlaskConical, RefreshCw } from "lucide-react";
import { api, errorMessage } from "../api";
import type { OpsStatus } from "../types";
import {
  Button, Card, CardHeader, Empty, ErrorBanner, KV, PageHeader, Pill, ViewShell, fmt,
} from "../components/ui";

const COMMANDS = `python -m forge_rsi loop --round r2 --iterations 5
python -m forge_rsi gaps-detect --run latest
python -m forge_rsi gaps-mine --run latest
python -m forge_rsi dream --run <run-id> && python -m forge_rsi dream-report
python -m forge_rsi holdout-rotate --count 10 --force`;

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
  const dream = status?.dream || null;
  const gaps = status?.gaps || null;
  const h2 = status?.h2 || null;

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
        <CardHeader
          title="H2.1 harness search"
          subtitle={h2 ? `${h2.round} · pre-reg ${h2.prereg_sha256?.slice(0, 12) || "—"}` : "Pre-registered parallel propose–probe–compose"}
          right={h2 ? (
            <Pill tone={h2.promoted ? "ok" : h2.decision.startsWith("STOP") ? "err" : "warn"}>
              {h2.decision}
            </Pill>
          ) : undefined}
        />
        {h2 ? (
          <>
            <div className="max-h-[260px] overflow-auto">
              <table className="data-table">
                <thead><tr><th>arm</th><th className="num">passed</th><th className="num">score</th><th className="num">Δ</th><th className="num">W/L</th><th className="num">sign p</th><th>CI95</th></tr></thead>
                <tbody>
                  {(["A", "B", "E"] as const).map((key) => {
                    const arm = h2[key];
                    const s = arm?.stats;
                    return (
                      <tr key={key}>
                        <td className="mono text-fg">{key}{key === "A" ? " · r1b" : key === "B" ? " · H2.1 real" : " · greedy same budget"}</td>
                        <td className="num">{arm?.passed ?? "—"}/20</td>
                        <td className="num">{fmt(arm?.score, 2)}</td>
                        <td className={cx("num", (s?.delta || 0) > 0 ? "text-ok" : (s?.delta || 0) < 0 ? "text-err" : "text-muted")}>
                          {s ? `${s.delta >= 0 ? "+" : ""}${s.delta.toFixed(2)}` : "—"}
                        </td>
                        <td className="num text-muted">{s ? `${s.wins}/${s.losses}` : "—"}</td>
                        <td className="num text-muted">{s ? s.sign_test_p.toFixed(4) : "—"}</td>
                        <td className="mono text-[10px] text-dim">{s ? `[${s.bootstrap_ci95[0].toFixed(2)}, ${s.bootstrap_ci95[1].toFixed(2)}]` : "—"}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap items-center gap-1.5 border-t border-line px-4 py-3 text-[10px]">
              <Pill tone={h2.primary ? "ok" : "err"}>primary +3</Pill>
              <Pill tone={h2.beats_e ? "ok" : "err"}>B &gt; E</Pill>
              <Pill tone={h2.replication ? "ok" : "err"}>probes +3</Pill>
              <Pill tone={h2.holdout_ok ? "ok" : "err"}>holdout guard</Pill>
              <Pill tone={h2.private_ok ? "ok" : "err"}>private guard</Pill>
              <span className="ml-auto text-dim">Stage 2/3 only if B wins; private sealed until final.</span>
            </div>
          </>
        ) : (
          <Empty title="No H2 round yet" detail="Run `python -m forge_rsi h2-stage1` on the frozen dev_hard split." />
        )}
      </Card>

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
            Prefer the <span className="text-muted">Jobs</span> view: it runs the same
            allowlisted chains, streams the child's log, and stops at the human gate.
          </div>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader
            title="Dream replay"
            subtitle={dream ? `${dream.run_id} · harness ${dream.harness || "—"}` : "Offline policy search over cached candidates"}
          />
          {dream ? (
            <>
              <table className="data-table">
                <thead><tr><th>policy</th><th className="num">score</th><th className="num">passed</th><th className="num">calls</th><th className="num">tokens</th><th className="num">value</th></tr></thead>
                <tbody>
                  {dream.policies.map((p) => (
                    <tr key={p.policy} className={p.policy === dream.winner ? "text-ok" : undefined}>
                      <td className="mono">{p.policy}{p.policy === dream.winner ? " · winner" : ""}</td>
                      <td className="num">{fmt(p.score, 2)}</td>
                      <td className="num">{p.passed}/{p.n}</td>
                      <td className="num">{p.calls}</td>
                      <td className="num">{p.tokens_out}</td>
                      <td className="num">{fmt(p.value, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="border-t border-line px-4 py-3 text-[10.5px] text-dim">
                {dream.note || "Offline replay; no model calls."} The winner is a
                selection policy, not a new prompt claim.
              </div>
            </>
          ) : (
            <Empty title="No Dream replay yet" detail="Queue a Dream round from Jobs to collect K candidates and replay the policies offline." />
          )}
        </Card>

        <Card>
          <CardHeader
            title="Skill gaps"
            subtitle={gaps ? `${gaps.run_id} · ${gaps.split}` : "Measured failures, grouped by skill"}
          />
          {gaps ? (
            <>
              <table className="data-table">
                <thead><tr><th>skill</th><th className="num">failed</th><th className="num">total</th><th>errors</th><th className="num">rows</th><th className="num">missing</th></tr></thead>
                <tbody>
                  {gaps.clusters.map((c) => (
                    <tr key={c.key}>
                      <td className="mono text-fg">{c.key}</td>
                      <td className="num text-err">{c.failed}</td>
                      <td className="num text-muted">{c.total}</td>
                      <td className="max-w-[180px] truncate text-[10.5px] text-dim" title={JSON.stringify(c.by_error)}>
                        {Object.entries(c.by_error).map(([k, v]) => `${k} ${v}`).join(", ") || "—"}
                      </td>
                      <td className="num text-muted">{c.verified_rows}</td>
                      <td className="num">{c.missing ? <span className="text-warn">{c.missing}</span> : "0"}</td>
                    </tr>
                  ))}
                  {!gaps.clusters.length && <tr><td colSpan={6}><Empty title="No gap clusters found" /></td></tr>}
                </tbody>
              </table>
              <div className="border-t border-line px-4 py-3 text-[10.5px] text-dim">
                {gaps.corpus
                  ? `Corpus: ${gaps.corpus.rows} verified rows (${gaps.corpus.file}). Import and review before training.`
                  : "No corpus mined yet. Queue a Gap round from Jobs."}
                {" "}Holdouts are excluded from mining.
              </div>
            </>
          ) : (
            <Empty title="No gap report yet" detail="Queue a Gap round from Jobs to detect failing clusters and mine verified traces." />
          )}
        </Card>
      </div>
    </ViewShell>
  );
}
