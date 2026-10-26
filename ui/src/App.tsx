import { useEffect, useState } from "react";
import type { LucideIcon } from "lucide-react";
import {
  Activity, Database, Flame, FlaskConical, LayoutDashboard, Layers3,
  ListChecks, MessageSquare,
} from "lucide-react";
import { api, errorMessage } from "./api";
import type { ForgeStatus } from "./types";
import { cx, Pill } from "./components/ui";
import { OverviewView } from "./views/OverviewView";
import { DataView } from "./views/DataView";
import { TrainView } from "./views/TrainView";
import { SkillsView } from "./views/SkillsView";
import { RsiView } from "./views/RsiView";
import { PlaygroundView } from "./views/PlaygroundView";
import { TelemetryView } from "./views/TelemetryView";
import { JobsView } from "./views/JobsView";

type View =
  | "overview" | "data" | "train" | "jobs" | "skills" | "rsi" | "playground" | "telemetry";

const NAV: { group: string; items: { id: View; label: string; icon: LucideIcon }[] }[] = [
  {
    group: "Workbench",
    items: [
      { id: "overview", label: "Overview", icon: LayoutDashboard },
      { id: "data", label: "Data", icon: Database },
      { id: "train", label: "Train", icon: Flame },
      { id: "jobs", label: "Jobs", icon: ListChecks },
    ],
  },
  {
    group: "Intelligence",
    items: [
      { id: "skills", label: "Skills", icon: Layers3 },
      { id: "rsi", label: "RSI", icon: FlaskConical },
      { id: "playground", label: "Playground", icon: MessageSquare },
    ],
  },
  {
    group: "Observability",
    items: [{ id: "telemetry", label: "Telemetry", icon: Activity }],
  },
];

const ALL = NAV.flatMap((g) => g.items);
const LABEL = Object.fromEntries(ALL.map((i) => [i.id, i.label])) as Record<View, string>;

export default function App() {
  const [view, setView] = useState<View>(() => {
    const saved = localStorage.getItem("skillforge.view") as View | null;
    return saved && ALL.some((i) => i.id === saved) ? saved : "overview";
  });
  const [engine, setEngine] = useState<{ ok: boolean; forge?: ForgeStatus; error?: string }>({ ok: false });

  const go = (v: View) => {
    setView(v);
    localStorage.setItem("skillforge.view", v);
  };

  const loadEngine = async () => {
    try {
      const health = await api.get<{ ok: boolean }>("/api/health");
      if (!health.ok) throw new Error("engine health check failed");
      const forge = await api.get<ForgeStatus>("/api/forge/status");
      setEngine({ ok: true, forge });
    } catch (e) {
      setEngine({ ok: false, error: errorMessage(e) });
    }
  };

  useEffect(() => {
    loadEngine();
    const t = setInterval(loadEngine, 30000);
    return () => clearInterval(t);
  }, []);

  const forge = engine.forge;
  const lora = forge?.mlx?.lora_cli;

  return (
    <div className="flex h-screen overflow-hidden bg-bg text-fg">
      <aside className="hidden w-[250px] shrink-0 flex-col border-r border-line bg-[#0b1117] lg:flex">
        <div className="flex items-center gap-2.5 px-5 py-5">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg border border-accent/30 bg-accent/10">
            <Layers3 size={16} className="text-accent" />
          </div>
          <div>
            <div className="text-sm font-semibold tracking-tight">SkillForge</div>
            <div className="text-[10px] uppercase tracking-[0.14em] text-dim">Forge-RSI workbench</div>
          </div>
        </div>

        <nav className="flex-1 space-y-5 px-3 py-1">
          {NAV.map((group) => (
            <div key={group.group}>
              <div className="px-2 pb-1.5 text-[9.5px] font-semibold uppercase tracking-[0.14em] text-dim">
                {group.group}
              </div>
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const active = view === item.id;
                  return (
                    <button
                      key={item.id}
                      onClick={() => go(item.id)}
                      className={cx(
                        "flex w-full items-center gap-2.5 rounded-lg border px-2.5 py-2 text-left text-[12.5px] transition-colors",
                        active
                          ? "border-accent/25 bg-accent/10 text-accent"
                          : "border-transparent text-muted hover:bg-elevated/50 hover:text-fg",
                      )}
                    >
                      <Icon size={15} className={active ? "text-accent" : "text-dim"} />
                      <span className="font-medium">{item.label}</span>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>

        <div className="m-3 rounded-xl border border-line bg-panel px-3 py-3">
          <div className="flex items-center justify-between">
            <span className="text-[10px] font-semibold uppercase tracking-[0.1em] text-dim">Local engine</span>
            <span className={cx(
              "h-2 w-2 rounded-full",
              engine.ok ? "bg-ok" : "bg-err pulse-dot",
            )} />
          </div>
          {engine.ok ? (
            <div className="mt-2 space-y-1 text-[11px] text-muted">
              <div className="flex justify-between"><span>mlx_lm</span><span className="mono">{forge?.mlx?.mlx_lm || "—"}</span></div>
              <div className="flex justify-between">
                <span>lora cli</span>
                <span className={lora ? "text-ok" : "text-err"}>{lora ? "found" : "missing"}</span>
              </div>
              <div className="flex justify-between"><span>models</span><span className="mono">{forge?.models?.length ?? 0}</span></div>
            </div>
          ) : (
            <div className="mt-2 text-[11px] text-err">
              offline
              <div className="mt-0.5 text-[10px] text-dim">run ./sf serve</div>
            </div>
          )}
        </div>
      </aside>

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-12 shrink-0 items-center justify-between gap-3 border-b border-line bg-panel/60 px-4 lg:px-6">
          <div className="flex min-w-0 items-center gap-2 text-[11px] text-dim">
            <span className="hidden sm:inline">SkillForge</span>
            <span className="hidden text-line sm:inline">/</span>
            <span className="truncate text-muted">{LABEL[view]}</span>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={view}
              onChange={(e) => go(e.target.value as View)}
              className="rounded-lg border border-line bg-[#0b1219] px-2 py-1.5 text-[11px] text-muted lg:hidden"
            >
              {ALL.map((i) => <option key={i.id} value={i.id}>{i.label}</option>)}
            </select>
            <Pill tone={engine.ok ? "ok" : "err"}>{engine.ok ? "local" : "offline"}</Pill>
            {engine.error && <span className="hidden max-w-[360px] truncate text-[10px] text-dim xl:inline">{engine.error}</span>}
          </div>
        </header>

        <main className="min-h-0 flex-1 overflow-hidden">
          {view === "overview" && <OverviewView />}
          {view === "data" && <DataView />}
          {view === "train" && <TrainView />}
          {view === "jobs" && <JobsView />}
          {view === "skills" && <SkillsView />}
          {view === "rsi" && <RsiView />}
          {view === "playground" && <PlaygroundView />}
          {view === "telemetry" && <TelemetryView />}
        </main>
      </div>
    </div>
  );
}
