import { useCallback, useEffect, useRef, useState } from "react";
import { MessageSquare, Play, RefreshCw, Send, Server, Square } from "lucide-react";
import { api, errorMessage } from "../api";
import type { ChatResponse, ForgeStatus, PlaygroundStatus } from "../types";
import {
  Button, Card, CardHeader, Empty, ErrorBanner, Field, Input, KV, Pill, Select,
  Spinner, Textarea, cx, fmt,
} from "../components/ui";

type Message = { role: "user" | "assistant"; text: string; meta?: string };
type Sample = { ok: boolean; text?: string; error?: string; matches: boolean; tok_s?: number };
type ProbeResult = {
  greedy: ChatResponse;
  target: string;
  samples: Sample[];
  n: number;
  matches: number;
  temperature: number;
  agreement: number | null;
  wilson: [number, number];
  at: string;
};
type ServerInfo = {
  running?: boolean; starting?: boolean; models?: string[]; tail?: string[];
  port?: number; pid?: number;
};

export function PlaygroundView() {
  const [pg, setPg] = useState<PlaygroundStatus | null>(null);
  const [forge, setForge] = useState<ForgeStatus | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [endpointUrl, setEndpointUrl] = useState("");
  const [kind, setKind] = useState("");
  const [model, setModel] = useState("");
  const [system, setSystem] = useState("");
  const [temperature, setTemperature] = useState(0.0);
  const [maxTokens, setMaxTokens] = useState(512);
  const [messages, setMessages] = useState<Message[]>([]);
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState("");
  const [probe, setProbe] = useState<ProbeResult | null>(null);
  const [port, setPort] = useState(8080);
  const [serverModel, setServerModel] = useState("");
  const [serverAdapter, setServerAdapter] = useState("");
  const [server, setServer] = useState<ServerInfo | null>(null);
  const chatRef = useRef<HTMLDivElement | null>(null);

  const load = useCallback(async () => {
    setLoading(true); setError("");
    try {
      const [p, f] = await Promise.all([
        api.get<PlaygroundStatus>("/api/playground/status"),
        api.get<ForgeStatus>("/api/forge/status"),
      ]);
      setPg(p); setForge(f);
      const first = p.endpoints?.[0];
      setEndpointUrl((v) => v || first?.url || "");
      setKind((v) => v || first?.kind || "");
      setModel((v) => v || first?.models?.[0] || "");
      setServerModel((v) => v || f.models?.[0]?.id || "");
      setServer((p.servers?.[String(port)] as ServerInfo | undefined) || null);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setLoading(false);
    }
  }, [port]);

  useEffect(() => { load(); }, [load]);

  const loadServer = useCallback(async (p = port) => {
    try {
      const d = await api.get<{ server: ServerInfo }>(`/api/playground/server?port=${p}`);
      setServer(d.server);
      return d.server;
    } catch (e) {
      setError(errorMessage(e));
      return null;
    }
  }, [port]);

  useEffect(() => {
    if (!server?.starting) return;
    const t = setInterval(() => loadServer(port), 2500);
    return () => clearInterval(t);
  }, [server?.starting, loadServer, port]);

  useEffect(() => {
    if (chatRef.current) chatRef.current.scrollTop = chatRef.current.scrollHeight;
  }, [messages]);

  const endpoints = pg?.endpoints || [];
  const selected = endpoints.find((e) => e.url === endpointUrl);
  const models = selected?.models || [];
  const usingServer = server?.running && endpointUrl === `http://127.0.0.1:${port}`;

  const chooseEndpoint = (url: string) => {
    setEndpointUrl(url);
    const e = endpoints.find((x) => x.url === url);
    setKind(e?.kind || "");
    setModel(e?.models?.[0] || "");
  };

  const useLocalServer = () => {
    setEndpointUrl(`http://127.0.0.1:${port}`);
    setKind("openai");
    setModel(server?.models?.[0] || serverModel || "");
  };

  const startServer = async () => {
    setBusy("server-start"); setError("");
    try {
      const d = await api.post<{ result: { ok?: boolean; reason?: string; port?: number } }>(
        "/api/playground/server/start",
        { model: serverModel, adapter_path: serverAdapter || null, port },
      );
      if (d.result?.ok === false) setError(d.result.reason || "server refused to start");
      else { await loadServer(port); setServer((s) => ({ ...(s || {}), starting: true, port })); }
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const stopServer = async () => {
    setBusy("server-stop"); setError("");
    try {
      const d = await api.post<{ result: { ok?: boolean; reason?: string } }>(
        "/api/playground/server/stop", { port },
      );
      if (d.result?.ok === false) setError(d.result.reason || "no server to stop");
      await loadServer(port);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  const send = async () => {
    const text = prompt.trim();
    if (!text) return;
    setMessages((m) => [...m, { role: "user", text }]);
    setPrompt("");
    setBusy("chat");
    try {
      const r = await api.post<ChatResponse>("/api/playground/chat", {
        prompt: text, system, model, endpoint: endpointUrl, kind,
        temperature, max_tokens: maxTokens,
      });
      setMessages((m) => [...m, {
        role: "assistant", text: r.text || "(empty response)",
        meta: `${r.endpoint || "—"} · ${r.model || "—"} · ${r.wall_ms ?? "?"} ms` +
          (r.tok_s ? ` · ${r.tok_s} tok/s` : ""),
      }]);
    } catch (e) {
      setMessages((m) => [...m, { role: "assistant", text: `⚠ ${errorMessage(e)}`, meta: "not sent — no server replied" }]);
    } finally {
      setBusy("");
    }
  };

  const runProbe = async () => {
    const text = prompt.trim() || messages.filter((m) => m.role === "user").slice(-1)[0]?.text || "";
    if (!text) { setError("Type a prompt first."); return; }
    setBusy("probe"); setError(""); setProbe(null);
    try {
      const r = await api.post<ProbeResult>("/api/playground/probe", {
        prompt: text, system, n: 6, temperature: 0.3,
        model, endpoint: endpointUrl, kind, max_tokens: maxTokens,
      });
      setProbe(r);
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="flex h-full min-h-0">
      <aside className="hidden w-[310px] shrink-0 flex-col gap-3 overflow-y-auto border-r border-line bg-[#0b1117] p-4 md:flex">
        <div>
          <h1 className="text-sm font-semibold">Playground</h1>
          <p className="mt-1 text-[11px] leading-relaxed text-dim">
            Real local inference only. No server, no reply.
          </p>
        </div>

        <Card>
          <CardHeader title="Endpoint" subtitle={`${endpoints.length} reachable`} right={
            <button onClick={load} className="text-dim hover:text-fg"><RefreshCw size={13} /></button>
          } />
          <div className="space-y-2.5 p-3">
            <Field label="server">
              <Select value={endpointUrl} onChange={(e) => chooseEndpoint(e.target.value)}>
                <option value="">{endpoints.length ? "select an endpoint" : "none reachable"}</option>
                {endpoints.map((e) => <option key={e.url} value={e.url}>{e.label} · {e.kind}</option>)}
              </Select>
            </Field>
            <Field label="model">
              {models.length ? (
                <Select value={model} onChange={(e) => setModel(e.target.value)}>
                  {models.map((m) => <option key={m} value={m}>{m}</option>)}
                </Select>
              ) : <Input value={model} onChange={(e) => setModel(e.target.value)} placeholder="model id" />}
            </Field>
            {!endpoints.length && (
              <div className="rounded-lg border border-warn/35 bg-warn/10 px-2.5 py-2 text-[10.5px] text-warn">
                No local inference server found. Start one below, or run Ollama.
              </div>
            )}
          </div>
        </Card>

        <Card>
          <CardHeader title="mlx_lm.server" subtitle="Load a base + optional adapter" right={<Server size={14} className="text-dim" />} />
          <div className="space-y-2.5 p-3">
            <Field label="base model">
              <Select value={serverModel} onChange={(e) => setServerModel(e.target.value)}>
                {(forge?.models || []).map((m) => <option key={m.id} value={m.id}>{m.label}</option>)}
              </Select>
            </Field>
            <Field label="adapter (optional)">
              <Select value={serverAdapter} onChange={(e) => setServerAdapter(e.target.value)}>
                <option value="">base only</option>
                {(forge?.adapters || []).map((a) => <option key={a.path} value={a.path}>{a.name}</option>)}
              </Select>
            </Field>
            <Field label="port">
              <Input type="number" value={port} onChange={(e) => setPort(Number(e.target.value))} />
            </Field>
            <div className="flex gap-1.5">
              <Button variant="primary" size="sm" onClick={startServer} disabled={!!busy}>
                <Play size={12} /> Start
              </Button>
              <Button variant="danger" size="sm" onClick={stopServer} disabled={!!busy}>
                <Square size={12} /> Stop
              </Button>
              <Button size="sm" onClick={() => loadServer(port)}>Status</Button>
            </div>
            {server && (
              <div className="rounded-lg border border-line bg-[#0b1219] px-2.5 py-2 text-[10.5px]">
                <div className="flex items-center gap-1.5">
                  <Pill tone={server.running ? "ok" : server.starting ? "warn" : "neutral"}>
                    {server.running ? "running" : server.starting ? "starting" : "stopped"}
                  </Pill>
                  <span className="mono text-dim">:{port}</span>
                </div>
                {server.models?.length ? <div className="mono mt-1 truncate text-muted">{server.models.join(", ")}</div> : null}
                {server.tail?.length ? <div className="mono mt-1 whitespace-pre-wrap text-[9.5px] text-dim">{server.tail.slice(-4).join("\n")}</div> : null}
                {server.running && !usingServer && (
                  <Button size="sm" className="mt-2 w-full" onClick={useLocalServer}>Use this server</Button>
                )}
              </div>
            )}
          </div>
        </Card>
      </aside>

      <section className="flex min-w-0 flex-1 flex-col">
        <div className="flex items-start justify-between gap-3 border-b border-line bg-panel/40 px-5 py-4">
          <div>
            <h2 className="flex items-center gap-2 text-sm font-semibold"><MessageSquare size={15} className="text-accent" /> Chat</h2>
            <p className="mt-1 text-[11px] text-dim">Replies come from a real local server. If none answers, the UI says so.</p>
          </div>
          <div className="flex items-center gap-1.5">
            <Button size="sm" onClick={() => setMessages([])}>Clear</Button>
          </div>
        </div>

        {error && <div className="px-5 pt-3"><ErrorBanner error={error} onRetry={() => setError("")} /></div>}

        <div ref={chatRef} className="min-h-0 flex-1 overflow-y-auto px-5 py-4">
          {!messages.length ? (
            <Empty title="No messages yet" detail="Pick an endpoint on the left. If none is reachable, start an mlx_lm.server." />
          ) : (
            <div className="mx-auto flex max-w-3xl flex-col gap-3">
              {messages.map((m, i) => (
                <div key={i} className={cx("max-w-[88%] rounded-xl border px-3.5 py-2.5",
                  m.role === "user" ? "self-end border-accent/30 bg-accent/10" : "self-start border-line bg-panel")}>
                  <div className="whitespace-pre-wrap text-[12px] leading-relaxed text-fg">{m.text}</div>
                  {m.meta && <div className="mono mt-1 text-[9.5px] text-dim">{m.meta}</div>}
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="shrink-0 border-t border-line bg-panel/60 p-4">
          <div className="mb-2 grid gap-2 sm:grid-cols-2">
            <Field label="system prompt">
              <Textarea rows={2} value={system} onChange={(e) => setSystem(e.target.value)} placeholder="optional" />
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Field label="temperature"><Input type="number" step="0.1" value={temperature} onChange={(e) => setTemperature(Number(e.target.value))} /></Field>
              <Field label="max tokens"><Input type="number" value={maxTokens} onChange={(e) => setMaxTokens(Number(e.target.value))} /></Field>
            </div>
          </div>
          <div className="flex gap-2">
            <Textarea rows={2} value={prompt} onChange={(e) => setPrompt(e.target.value)} placeholder="Ask something…" className="flex-1" />
            <div className="flex flex-col gap-1.5">
              <Button variant="primary" onClick={send} disabled={busy === "chat" || !prompt.trim()}>
                {busy === "chat" ? <Spinner label="" /> : <Send size={13} />} Send
              </Button>
              <Button onClick={runProbe} disabled={busy === "probe"}>Probe</Button>
            </div>
          </div>
        </div>
      </section>

      <aside className="hidden w-[380px] shrink-0 flex-col gap-3 overflow-y-auto border-l border-line bg-[#0b1117] p-4 xl:flex">
        <Card className="flex-1">
          <CardHeader title="Robustness probe" subtitle="1 greedy + 6 at temp 0.3" />
          {probe ? (
            <div className="space-y-3 p-3">
              <div className="grid grid-cols-2 gap-2">
                <div className="rounded-lg border border-line bg-[#0b1219] px-2.5 py-2">
                  <div className="text-[9.5px] uppercase tracking-[0.08em] text-dim">agreement</div>
                  <div className="text-lg font-semibold num">{probe.agreement == null ? "—" : `${(probe.agreement * 100).toFixed(0)}%`}</div>
                  <div className="text-[10px] text-dim">{probe.matches}/{probe.n} samples match greedy</div>
                </div>
                <div className="rounded-lg border border-line bg-[#0b1219] px-2.5 py-2">
                  <div className="text-[9.5px] uppercase tracking-[0.08em] text-dim">Wilson 95%</div>
                  <div className="mono text-[11px] text-muted">[{fmt(probe.wilson?.[0], 2)}, {fmt(probe.wilson?.[1], 2)}]</div>
                  <div className="text-[10px] text-dim">observed, not a model score</div>
                </div>
              </div>
              <div className="rounded-lg border border-line bg-[#0b1219] px-2.5 py-2">
                <div className="text-[9.5px] uppercase tracking-[0.08em] text-dim">greedy</div>
                <div className="mt-1 max-h-[150px] overflow-auto whitespace-pre-wrap text-[11px] text-muted">{probe.greedy?.text || "—"}</div>
              </div>
              <div className="space-y-1.5">
                {probe.samples.map((s, i) => (
                  <div key={i} className="rounded-lg border border-line bg-[#0b1219] px-2.5 py-2">
                    <div className="flex items-center justify-between">
                      <span className="text-[10px] text-dim">sample {i + 1}</span>
                      <Pill tone={s.matches ? "ok" : s.ok ? "warn" : "err"}>{s.matches ? "match" : s.ok ? "diff" : "error"}</Pill>
                    </div>
                    <div className="mt-1 max-h-[100px] overflow-auto whitespace-pre-wrap text-[10.5px] text-muted">{s.text || s.error || "—"}</div>
                  </div>
                ))}
              </div>
              <div className="text-[10px] text-dim">at {probe.at}</div>
            </div>
          ) : (
            <Empty title="No probe yet" detail="Type a prompt, then click Probe. The greedy answer is the comparison target." />
          )}
        </Card>

        <Card>
          <CardHeader title="Server" subtitle="Status is probed, never assumed" />
          <div className="space-y-1.5 p-3">
            <KV k="endpoint" v={endpointUrl || "—"} mono />
            <KV k="kind" v={kind || "—"} mono />
            <KV k="model" v={model || "—"} mono />
            <KV k="server" v={server?.running ? "running" : server?.starting ? "starting" : "stopped"} />
          </div>
        </Card>
      </aside>
    </div>
  );
}
