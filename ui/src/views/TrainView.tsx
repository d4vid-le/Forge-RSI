import { useCallback, useEffect, useState } from "react";
import { Cpu, Flame, Play, RefreshCw, ShieldCheck, Square } from "lucide-react";
import { api, errorMessage } from "../api";
import type { ForgeRun, ForgeStatus, Session } from "../types";
import {
  Button, Card, CardHeader, Empty, ErrorBanner, Field, Input, KV, Pill, Select,
  Sparkline, Spinner, ViewShell, cx, dateLabel, fmt,
} from "../components/ui";

type Prepared = { train: number; valid: number; est_tokens: number; run_dir: string };
type Preview = {
  cmdline?: string;
  lora_config?: string;
  run_dir?: string;
  adapter_path?: string;
  checks?: {
    mlx_ok?: boolean; model_ok?: boolean; model?: string;
    train_rows?: number; valid_rows?: number; running?: boolean;
  };
};
type Lock = {
  verified?: boolean | null;
  files?: { file: string; status: string; expected?: string }[];
  note?: string;
  model?: string;
};

export function TrainView() {
  const [forge, setForge] = useState<ForgeStatus | null>(null);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [model, setModel] = useState("");
  const [sessionId, setSessionId] = useState("");
  const [include, setInclude] = useState("accepted");
  const [runName, setRunName] = useState("skill_run_1");
  const [validRatio, setValidRatio] = useState(0.05);
  const [seed, setSeed] = useState(0);
  const [maxSeq, setMaxSeq] = useState(2048);
  const [allowFlagged, setAllowFlagged] = useState(false);
  const [rank, setRank] = useState(8);
  const [alpha, setAlpha] = useState(16);
  const [layers, setLayers] = useState(6);
  const [lr, setLr] = useState(0.0001);
  const [iters, setIters] = useState(100);
  const [batch, setBatch] = useState(1);
  const [grad, setGrad] = useState(4);
  const [saveEvery, setSaveEvery] = useState(50);
  const [maskPrompt, setMaskPrompt] = useState(true);
  const [gradCheckpoint, setGradCheckpoint] = useState(false);
  const [lock, setLock] = useState<Lock | null>(null);
  const [prepared, setPrepared] = useState<Prepared | null>(null);
  const [preview, setPreview] = useState<Preview | null>(null);
  const [run, setRun] = useState<ForgeRun | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [f, s] = await Promise.all([
        api.get<ForgeStatus>("/api/forge/status"),
        api.get<{ sessions: Session[] }>("/api/sessions"),
      ]);
      setForge(f);
      setSessions(s.sessions || []);
      setModel((m) => m || f.models?.[0]?.id || "");
      setSessionId((sid) => sid || s.sessions?.[0]?.id || "");
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, []);

  const loadLock = useCallback(async (verify = false) => {
    if (!model) return;
    setLock(null);
    try {
      const d = await api.get<{ lock: Lock }>(
        `/api/forge/base-lock?model=${encodeURIComponent(model)}&verify=${verify ? 1 : 0}`,
      );
      setLock(d.lock);
    } catch (e) {
      setLock({ note: errorMessage(e) });
    }
  }, [model]);

  const refreshRun = useCallback(async (name: string) => {
    if (!name) return;
    try {
      const d = await api.get<{ run: ForgeRun }>(`/api/forge/run?name=${encodeURIComponent(name)}`);
      setRun(d.run);
      if (d.run.status !== "running") {
        const f = await api.get<ForgeStatus>("/api/forge/status");
        setForge(f);
      }
    } catch (e) {
      setError(errorMessage(e));
    }
  }, []);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { if (model) loadLock(false); }, [model, loadLock]);
  useEffect(() => {
    if (!run?.name || run.status !== "running") return;
    const t = setInterval(() => refreshRun(run.name), 2500);
    return () => clearInterval(t);
  }, [run?.name, run?.status, refreshRun]);

  const body = () => ({
    run_name: runName.trim(), model,
    rank, alpha, num_layers: layers, learning_rate: lr, iters,
    batch_size: batch, grad_accum: grad, save_every: saveEvery,
    max_seq_length: maxSeq, mask_prompt: maskPrompt,
    grad_checkpoint: gradCheckpoint, seed,
  });

  const prepare = async () => {
    if (!sessionId || !runName.trim()) { setNotice("Pick a session and a run name."); return; }
    setBusy("prepare"); setError(""); setNotice("");
    try {
      const d = await api.post<Prepared & { run_dir: string }>("/api/forge/prepare", {
        session: sessionId, run_name: runName.trim(), include,
        valid_ratio: validRatio, seed, max_tokens: maxSeq, allow_flagged: allowFlagged,
      });
      setPrepared(d);
      setNotice(`prepared ${d.train} train / ${d.valid} valid rows`);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const dryRun = async () => {
    setBusy("preview"); setError(""); setNotice("");
    try {
      const d = await api.post<{ preview: Preview }>("/api/forge/train", { ...body(), dry_run: true });
      setPreview(d.preview);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const start = async () => {
    setBusy("start"); setError(""); setNotice("");
    try {
      const d = await api.post<{ run: ForgeRun }>("/api/forge/train", body());
      setRun(d.run);
      setNotice("training started");
      await refreshRun(d.run.name);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const stop = async () => {
    const name = run?.name || runName.trim();
    setBusy("stop");
    try {
      await api.post("/api/forge/stop", { run_name: name });
      setNotice("stop requested");
      await refreshRun(name);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const lora = forge?.mlx?.lora_cli;
  const running = run?.status === "running";

  return (
    <div className="flex h-full min-h-0">
      <aside className="hidden w-[300px] shrink-0 flex-col gap-3 overflow-y-auto border-r border-line bg-[#0b1117] p-4 md:flex">
        <div>
          <h1 className="text-sm font-semibold">Train</h1>
          <p className="mt-1 text-[11px] leading-relaxed text-dim">
            Real <span className="mono">mlx_lm.lora</span>. The base is frozen; the adapter is a candidate.
          </p>
        </div>

        <Card>
          <CardHeader title="Environment" subtitle="Live checks, no simulation" />
          <div className="p-3">
            <KV k="mlx" v={forge?.mlx?.mlx || "missing"} mono />
            <KV k="mlx_lm" v={forge?.mlx?.mlx_lm || "missing"} mono />
            <KV k="lora cli" v={lora ? "found" : "MISSING"} mono />
            <KV k="python" v={forge?.mlx?.python || "—"} mono />
            {!lora && (
              <div className="mt-2 rounded-lg border border-err/35 bg-err/10 px-2.5 py-2 text-[10.5px] text-err">
                Start the server with the MLX bin on PATH. Training is disabled, not simulated.
              </div>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Base model (R1)" subtitle="Frozen; checksum-verified" />
          <div className="space-y-2 p-3">
            <Select value={model} onChange={(e) => setModel(e.target.value)}>
              {(forge?.models || []).map((m) => (
                <option key={m.id} value={m.id}>{m.label} · {m.size_gb} GB</option>
              ))}
            </Select>
            <div className="flex gap-1.5">
              <Button size="sm" onClick={() => loadLock(false)}>Check</Button>
              <Button size="sm" onClick={() => loadLock(true)} disabled={!model}>Verify checksums</Button>
            </div>
            {lock && (
              <div className={cx(
                "rounded-lg border px-2.5 py-2 text-[10.5px]",
                lock.verified === true ? "border-ok/35 bg-ok/10 text-ok" :
                  lock.verified === false ? "border-err/35 bg-err/10 text-err" :
                    "border-line bg-[#0b1219] text-muted",
              )}>
                {lock.verified === true ? "base lock verified — all files match" :
                  lock.verified === false ? "MISMATCH — do not train" :
                    lock.note || (lock.files?.length ? "lock inventory loaded" : "no recorded lock")}
              </div>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="Adapters" subtitle="Nested Le-Gates adapters are discovered" />
          <div className="max-h-[240px] overflow-auto p-2">
            {(forge?.adapters || []).map((a) => (
              <div key={a.path} className="border-b border-line/60 px-1.5 py-1.5 last:border-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="mono truncate text-[11px] text-fg">{a.name}</span>
                  <Pill tone={a.format === "mlx_lm" ? "ok" : "warn"}>{a.format}</Pill>
                </div>
                <div className="mt-0.5 text-[10px] text-dim">{a.size_mb} MB · rank {a.rank ?? "?"}/{a.scale ?? "?"}</div>
              </div>
            ))}
            {!forge?.adapters?.length && <div className="p-3 text-center text-[11px] text-dim">none</div>}
          </div>
        </Card>
      </aside>

      <section className="min-w-0 flex-1 overflow-y-auto p-5 lg:p-6">
        <div className="flex flex-wrap items-start justify-between gap-3 pb-4">
          <div>
            <h2 className="text-lg font-semibold tracking-tight">Forge a skill adapter</h2>
            <p className="mt-1 text-sm text-muted">Prepare a gated dataset, preview the exact command, then run real MLX training.</p>
          </div>
          <div className="flex items-center gap-2">
            <Pill tone={lora ? "ok" : "err"}>{lora ? "engine ready" : "engine blocked"}</Pill>
            <Button size="sm" onClick={load}><RefreshCw size={12} /> Refresh</Button>
          </div>
        </div>

        {(error || notice) && (
          <div className="mb-4">
            {error ? <ErrorBanner error={error} onRetry={load} /> :
              <div className="rounded-lg border border-ok/30 bg-ok/10 px-3 py-2 text-[11px] text-ok">{notice}</div>}
          </div>
        )}

        {loading && <Spinner label="Loading Forge…" />}

        <div className="grid gap-4 xl:grid-cols-2">
          <Card>
            <CardHeader title="1 · Dataset" subtitle="Only reviewed rows; hard gates enforced" />
            <div className="grid gap-3 p-4 sm:grid-cols-2">
              <Field label="from session">
                <Select value={sessionId} onChange={(e) => setSessionId(e.target.value)}>
                  {sessions.map((s) => <option key={s.id} value={s.id}>{s.name || s.id}</option>)}
                </Select>
              </Field>
              <Field label="include">
                <Select value={include} onChange={(e) => setInclude(e.target.value)}>
                  <option value="accepted">accepted + edited</option>
                  <option value="clean">clean</option>
                  <option value="all">all</option>
                </Select>
              </Field>
              <Field label="run name">
                <Input value={runName} onChange={(e) => setRunName(e.target.value)} />
              </Field>
              <Field label="valid ratio">
                <Input type="number" step="0.01" value={validRatio} onChange={(e) => setValidRatio(Number(e.target.value))} />
              </Field>
              <Field label="max seq length">
                <Input type="number" value={maxSeq} onChange={(e) => setMaxSeq(Number(e.target.value))} />
              </Field>
              <Field label="seed">
                <Input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
              </Field>
              <label className="flex items-center gap-2 text-[11px] text-muted">
                <input type="checkbox" checked={allowFlagged} onChange={(e) => setAllowFlagged(e.target.checked)} />
                allow gated rows
              </label>
              <div className="flex items-end">
                <Button variant="primary" className="w-full" onClick={prepare} disabled={busy === "prepare" || !sessionId}>
                  {busy === "prepare" ? "Preparing…" : "Prepare train/valid"}
                </Button>
              </div>
            </div>
            {prepared && (
              <div className="mx-4 mb-4 rounded-lg border border-ok/30 bg-ok/10 px-3 py-2 text-[11px] text-ok">
                train {prepared.train} · valid {prepared.valid} · {prepared.est_tokens.toLocaleString()} est tokens
                <div className="mono mt-1 break-all text-[10px] text-dim">{prepared.run_dir}</div>
              </div>
            )}
          </Card>

          <Card>
            <CardHeader title="2 · LoRA config" subtitle="Scale is derived: α / rank" />
            <div className="grid gap-3 p-4 sm:grid-cols-2">
              <Field label="rank (R6: 8)"><Input type="number" value={rank} onChange={(e) => setRank(Number(e.target.value))} /></Field>
              <Field label="alpha"><Input type="number" value={alpha} onChange={(e) => setAlpha(Number(e.target.value))} /></Field>
              <Field label="layers (last N)"><Input type="number" value={layers} onChange={(e) => setLayers(Number(e.target.value))} /></Field>
              <Field label="learning rate"><Input type="number" step="0.00001" value={lr} onChange={(e) => setLr(Number(e.target.value))} /></Field>
              <Field label="iters"><Input type="number" value={iters} onChange={(e) => setIters(Number(e.target.value))} /></Field>
              <Field label="batch size"><Input type="number" value={batch} onChange={(e) => setBatch(Number(e.target.value))} /></Field>
              <Field label="grad accumulation"><Input type="number" value={grad} onChange={(e) => setGrad(Number(e.target.value))} /></Field>
              <Field label="save every"><Input type="number" value={saveEvery} onChange={(e) => setSaveEvery(Number(e.target.value))} /></Field>
              <label className="flex items-center gap-2 text-[11px] text-muted">
                <input type="checkbox" checked={maskPrompt} onChange={(e) => setMaskPrompt(e.target.checked)} /> mask prompt
              </label>
              <label className="flex items-center gap-2 text-[11px] text-muted">
                <input type="checkbox" checked={gradCheckpoint} onChange={(e) => setGradCheckpoint(e.target.checked)} /> grad checkpoint
              </label>
            </div>
            <div className="flex flex-wrap gap-1.5 border-t border-line px-4 py-3">
              <Button size="sm" onClick={dryRun} disabled={busy === "preview"}>
                <ShieldCheck size={12} /> Preview command
              </Button>
              {running ? (
                <Button size="sm" variant="danger" onClick={stop} disabled={busy === "stop"}>
                  <Square size={12} /> Stop
                </Button>
              ) : (
                <Button size="sm" variant="primary" onClick={start} disabled={busy === "start" || !prepared || !lora}>
                  <Play size={12} /> Start training
                </Button>
              )}
              <span className="ml-auto self-center text-[10px] text-dim">scale <span className="mono">{fmt(alpha / rank, 3)}</span></span>
            </div>
          </Card>
        </div>

        <Card className="mt-4">
          <CardHeader title="Command + checks" subtitle="Nothing starts until this is legible" />
          <pre className="mono max-h-[300px] overflow-auto whitespace-pre-wrap px-4 py-3 text-[11px] leading-relaxed text-muted">
            {preview?.cmdline
              ? `$ ${preview.cmdline}\n\n--- lora_config.yaml\n${preview.lora_config || ""}\n--- checks\n` +
                `  mlx_lm.lora   ${preview.checks?.mlx_ok ? "found" : "MISSING -> refused"}\n` +
                `  model         ${preview.checks?.model_ok ? "ok" : "NOT FOUND"}  ${preview.checks?.model || ""}\n` +
                `  train.jsonl   ${preview.checks?.train_rows ?? 0} rows\n` +
                `  valid.jsonl   ${preview.checks?.valid_rows ?? 0} rows\n` +
                `  already run?  ${preview.checks?.running ? "YES" : "no"}\n` +
                `  adapter out   ${preview.adapter_path || ""}\n`
              : "Click “Preview command” to print the exact argv, YAML, and gate checks."}
          </pre>
        </Card>
        <div className="mt-4 grid gap-4 xl:grid-cols-2">
        <Card>
          <CardHeader title="Runs" subtitle="Real mlx_lm runs on disk" right={
            <button onClick={load} className="text-dim hover:text-fg"><RefreshCw size={13} /></button>
          } />
          <div className="max-h-[220px] overflow-auto p-2">
            {(forge?.runs || []).map((r) => (
              <button key={r.name} onClick={() => { setRunName(r.name); refreshRun(r.name); }}
                className={cx(
                  "mb-1 block w-full rounded-lg border px-2.5 py-2 text-left",
                  run?.name === r.name ? "border-accent/30 bg-accent/10" : "border-transparent hover:bg-elevated/50",
                )}>
                <div className="flex items-center justify-between gap-2">
                  <span className="mono truncate text-[11px] text-fg">{r.name}</span>
                  <Pill tone={r.status === "running" ? "warn" : r.status === "finished" ? "ok" : "neutral"}>{r.status || "?"}</Pill>
                </div>
                <div className="mt-0.5 text-[10px] text-dim">
                  {r.data?.train ?? 0}/{r.data?.valid ?? 0} rows · last loss {r.last_train?.loss != null ? r.last_train.loss.toFixed(3) : "—"}
                </div>
              </button>
            ))}
            {!forge?.runs?.length && <div className="p-3 text-center text-[11px] text-dim">none yet</div>}
          </div>
        </Card>

        <Card className="flex-1">
          <CardHeader title="Live run" subtitle={run?.name || "no run selected"} />
          {run ? (
            <div className="space-y-3 p-3">
              <div className="flex items-center gap-2">
                <Pill tone={run.status === "running" ? "warn" : run.status === "finished" ? "ok" : run.status === "failed" ? "err" : "neutral"}>
                  {run.status || "?"}
                </Pill>
                <span className="mono truncate text-[10px] text-dim">{run.adapter_path || ""}</span>
              </div>
              <Sparkline values={(run.train || []).map((t) => t.loss)} />
              <div className="grid grid-cols-2 gap-x-3">
                <KV k="iteration" v={run.last_train?.iter ?? "—"} mono />
                <KV k="train loss" v={run.last_train?.loss != null ? run.last_train.loss.toFixed(4) : "—"} mono />
                <KV k="val loss" v={run.last_val?.loss != null ? run.last_val.loss.toFixed(4) : "—"} mono />
                <KV k="tok/s" v={run.last_train?.tok_sec != null ? run.last_train.tok_sec.toFixed(1) : "—"} mono />
              </div>
              <pre className="mono max-h-[220px] overflow-auto whitespace-pre-wrap rounded-lg border border-line bg-[#0b1219] p-2.5 text-[10.5px] text-muted">
                {(run.tail || []).join("\n") || "waiting for output…"}
              </pre>
            </div>
          ) : <Empty title="No run selected" detail="Start a run or pick one from the list." />}
        </Card>
        </div>
      </section>
    </div>
  );
}
