import { useCallback, useEffect, useState } from "react";
import { Layers3, RefreshCw, ShieldCheck } from "lucide-react";
import { api, errorMessage } from "../api";
import type { OpsStatus } from "../types";
import {
  Button, Card, CardHeader, Empty, ErrorBanner, KV, PageHeader, Pill, Score,
  Stat, ViewShell, cx, dateLabel, fmt,
} from "../components/ui";

export function SkillsView() {
  const [status, setStatus] = useState<OpsStatus | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

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

  const ev = status?.evaluations || [];
  const pick = (run: string) => ev.find((r) => r.run === run);
  const dev = pick("legates_final_dev");
  const hold = pick("legates_final_holdout");
  const priv = pick("private_r1_private_holdout");
  const cfgs = status?.composition?.configs || {};
  const decision = status?.private_decision || {};

  return (
    <ViewShell>
      <PageHeader
        title="Skills"
        subtitle="Independent rank-8 adapters on a frozen base. One gate at a time; a bad skill is quarantined, never unlearned."
        actions={<Button onClick={load} disabled={loading}><RefreshCw size={13} /> Refresh</Button>}
      />
      {error && <ErrorBanner error={error} onRetry={load} />}

      <div className="mt-1 grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <Card>
          <CardHeader title="Le-Gates mechanism" subtitle="The only forward pass the runtime allows" right={<Layers3 size={15} className="text-accent" />} />
          <div className="p-4">
            <div className="mono rounded-lg border border-line bg-[#0b1219] px-4 py-3 text-[12px] text-accent">
              y = W_base(x) + Σ gate_k · scale_k · (B_k A_k) x
            </div>
            <div className="mt-3 grid gap-2 text-[11.5px] text-muted sm:grid-cols-2">
              <div><span className="text-dim">base</span> frozen + checksum-verified</div>
              <div><span className="text-dim">deltas</span> rank-8, one pure corpus each</div>
              <div><span className="text-dim">gate</span> 0/1, at most one open per task</div>
              <div><span className="text-dim">invariant</span> Σ gate ≤ 1</div>
            </div>
            <div className="mt-3 text-[11px] leading-relaxed text-dim">
              The base is never updated. A skill that fails its probes or the
              holdout is gated to 0 and kept on disk. Composition is explicitly
              not claimed; the measured compound-task result is on this page.
            </div>
          </div>
        </Card>

        <div className="space-y-4">
          <Card className="px-4 py-4">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-dim">Base lock</div>
            <div className="mt-1 flex items-center gap-2">
              <ShieldCheck size={18} className={status?.base?.checksums_ok ? "text-ok" : "text-warn"} />
              <span className="text-sm font-semibold">
                {status?.base?.checksums_ok === true ? "verified" : status?.base?.checksums_ok === false ? "mismatch" : "not recorded"}
              </span>
            </div>
            <div className="mt-2 space-y-1 text-[11px] text-muted">
              <div className="truncate mono">{status?.base?.path || "—"}</div>
              <div>{status?.base?.exists ? "model present" : "model missing"}</div>
            </div>
          </Card>
          <Card className="px-4 py-4">
            <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-dim">Zero forgetting</div>
            <div className="mt-2">
              <KV k="dev" v={`${dev?.base.passed ?? "—"}/${dev?.base.n ?? "—"} → ${dev?.gated.passed ?? "—"}/${dev?.gated.n ?? "—"}`} mono />
              <KV k="holdout" v={`${hold?.base.passed ?? "—"}/${hold?.base.n ?? "—"} → ${hold?.gated.passed ?? "—"}/${hold?.gated.n ?? "—"}`} mono />
              <KV k="private" v={`${priv?.base.passed ?? "—"}/${priv?.base.n ?? "—"} → ${priv?.gated.passed ?? "—"}/${priv?.gated.n ?? "—"}`} mono />
              <KV k="non-routed identical" v={String(priv?.non_routed_identical ?? hold?.non_routed_identical ?? "—")} />
              <KV k="private holdout" v={status?.holdout?.exists ? `${status.holdout.count} tasks` : "missing"} />
              <KV k="rotated" v={status?.holdout?.created_at ? dateLabel(status.holdout.created_at) : "not recorded"} />
            </div>
            <div className="mt-2 text-[10px] leading-relaxed text-dim">
              Rotation is a gated job. The public 10-task holdout stays a regression
              set; a blind claim needs the private set.
            </div>
          </Card>
        </div>
      </div>

      <Card className="mt-4">
        <CardHeader title="Skill registry" subtitle="Round 1 and round 2 adapters" />
        <div className="max-h-[360px] overflow-auto">
          <table className="data-table">
            <thead><tr><th>round</th><th>skill</th><th>status</th><th className="num">rows</th><th className="num">iters</th><th className="num">train</th><th className="num">val</th><th>adapter</th><th>decision</th></tr></thead>
            <tbody>
              {(status?.skills || []).map((s, i) => {
                const st = s.adapter_exists ? s.status : "untrained";
                return (
                  <tr key={`${s.round}-${s.skill}-${i}`}>
                    <td className="text-dim">{s.round}</td>
                    <td className="mono text-fg">{s.skill}</td>
                    <td><Pill tone={st === "promoted" ? "ok" : st === "quarantined" ? "err" : st === "candidate" ? "accent" : "neutral"}>{st}</Pill></td>
                    <td className="num text-muted">{s.rows ?? "—"}</td>
                    <td className="num text-muted">{s.iters ?? "—"}</td>
                    <td className="num text-muted">{fmt(s.train_loss, 3)}</td>
                    <td className="num text-muted">{fmt(s.val_loss, 3)}</td>
                    <td className="max-w-[240px] truncate mono text-[10px] text-dim" title={s.adapter || ""}>{s.adapter || "—"}</td>
                    <td className="max-w-[240px] truncate text-[11px] text-dim" title={s.decision?.reason}>{s.decision?.reason || "—"}</td>
                  </tr>
                );
              })}
              {!status?.skills?.length && <tr><td colSpan={9}><Empty title="No skill registry found" /></td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <Card className="mt-4">
        <CardHeader title="Gated evaluations" subtitle="Base vs the gated stack, with the zero-forgetting check" />
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
              {!ev.length && <tr><td colSpan={8}><Empty title="No gated evaluations found" /></td></tr>}
            </tbody>
          </table>
        </div>
      </Card>

      <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Composition" subtitle="Parts vs the whole; the deployed router is Σ≤1" />
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
        <Card className="px-4 py-4">
          <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-dim">Round 2 decision</div>
          <div className="mt-1 text-lg font-semibold">{decision.promote === undefined ? "—" : decision.promote ? "PROMOTE" : "KEEP ROUND 1"}</div>
          <div className="mt-1 text-[11px] text-muted">{decision.reason || "No private-holdout decision yet."}</div>
          <div className="mt-3">
            <KV k="private Δ" v={fmt(decision.private_delta, 2)} mono />
            <KV k="public dev Δ" v={fmt(decision.public_dev_delta, 2)} mono />
            <KV k="24-probe Δ" v={fmt(decision.public_probe_delta, 2)} mono />
            <KV k="forgetting ok" v={String(decision.forgetting_ok ?? "—")} />
          </div>
        </Card>
      </div>
    </ViewShell>
  );
}
