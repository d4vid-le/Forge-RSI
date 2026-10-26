import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from "react";
import type { Summary } from "../types";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

export function Card({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("rounded-xl border border-line bg-panel", className)}>{children}</div>;
}

export function CardHeader({
  title, subtitle, right,
}: { title: string; subtitle?: string; right?: ReactNode }) {
  return (
    <div className="flex items-start justify-between gap-4 border-b border-line px-4 py-3">
      <div className="min-w-0">
        <div className="text-[11px] font-semibold uppercase tracking-[0.08em] text-dim">{title}</div>
        {subtitle && <div className="mt-0.5 text-xs text-muted">{subtitle}</div>}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}

export function ViewShell({ children, className }: { children: ReactNode; className?: string }) {
  return <div className={cx("h-full overflow-y-auto p-5 lg:p-6", className)}>{children}</div>;
}

export function PageHeader({
  title, subtitle, actions,
}: { title: string; subtitle?: string; actions?: ReactNode }) {
  return (
    <div className="flex flex-wrap items-start justify-between gap-3 pb-5">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-fg">{title}</h1>
        {subtitle && <p className="mt-1 max-w-3xl text-sm text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  );
}

type Tone = "neutral" | "ok" | "err" | "warn" | "accent" | "violet";

export function Pill({ children, tone = "neutral", className }: {
  children: ReactNode; tone?: Tone; className?: string;
}) {
  const tones: Record<Tone, string> = {
    neutral: "border-line bg-elevated/50 text-muted",
    ok: "border-ok/40 bg-ok/10 text-ok",
    err: "border-err/40 bg-err/10 text-err",
    warn: "border-warn/40 bg-warn/10 text-warn",
    accent: "border-accent/40 bg-accent/10 text-accent",
    violet: "border-accent2/40 bg-accent2/10 text-accent2",
  };
  return (
    <span className={cx(
      "inline-flex items-center rounded-full border px-2 py-0.5 text-[10.5px] font-semibold",
      tones[tone], className,
    )}>{children}</span>
  );
}

export function Button({
  children, variant = "ghost", size = "md", className, ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "ghost" | "danger" | "success" | "quiet";
  size?: "sm" | "md";
}) {
  const variants = {
    primary: "bg-accent text-[#07111b] hover:bg-accent/90 border-accent",
    ghost: "bg-elevated/60 text-fg hover:bg-elevated border-line",
    danger: "bg-err/10 text-err hover:bg-err/15 border-err/35",
    success: "bg-ok/10 text-ok hover:bg-ok/15 border-ok/35",
    quiet: "bg-transparent text-muted hover:text-fg hover:bg-elevated/60 border-transparent",
  };
  const sizes = { sm: "px-2.5 py-1 text-[11px]", md: "px-3 py-1.5 text-xs" };
  return (
    <button
      {...rest}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-lg border font-medium transition-colors",
        "disabled:cursor-not-allowed disabled:opacity-40",
        variants[variant], sizes[size], className,
      )}
    >{children}</button>
  );
}

export function Input({ className, ...rest }: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...rest} className={cx(
    "w-full rounded-lg border border-line bg-[#0b1219] px-3 py-2 text-xs text-fg",
    "placeholder:text-dim focus:border-accent focus:outline-none", className,
  )} />;
}

export function Select({ className, children, ...rest }: SelectHTMLAttributes<HTMLSelectElement>) {
  return <select {...rest} className={cx(
    "w-full rounded-lg border border-line bg-[#0b1219] px-2.5 py-2 text-xs text-fg",
    "focus:border-accent focus:outline-none", className,
  )}>{children}</select>;
}

export function Textarea({ className, ...rest }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...rest} className={cx(
    "w-full rounded-lg border border-line bg-[#0b1219] px-3 py-2 text-xs text-fg",
    "placeholder:text-dim focus:border-accent focus:outline-none", className,
  )} />;
}

export function Field({ label, hint, children }: {
  label: string; hint?: string; children: ReactNode;
}) {
  return (
    <label className="block">
      <div className="mb-1 text-[10px] font-semibold uppercase tracking-[0.07em] text-dim">{label}</div>
      {children}
      {hint && <div className="mt-1 text-[10.5px] text-dim">{hint}</div>}
    </label>
  );
}

export function Stat({ label, value, note, tone }: {
  label: string; value: ReactNode; note?: ReactNode; tone?: Tone;
}) {
  const toneClass = tone === "ok" ? "text-ok" : tone === "err" ? "text-err"
    : tone === "warn" ? "text-warn" : tone === "accent" ? "text-accent" : "text-fg";
  return (
    <Card className="px-4 py-3.5">
      <div className="text-[10px] font-semibold uppercase tracking-[0.08em] text-dim">{label}</div>
      <div className={cx("mt-1 text-2xl font-semibold tracking-tight num", toneClass)}>{value}</div>
      {note && <div className="mt-0.5 text-[11px] text-muted">{note}</div>}
    </Card>
  );
}

export function Empty({ title, detail, children }: {
  title: string; detail?: string; children?: ReactNode;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-14 text-center">
      <div className="text-sm font-medium text-muted">{title}</div>
      {detail && <div className="mt-1 max-w-md text-xs text-dim">{detail}</div>}
      {children && <div className="mt-4">{children}</div>}
    </div>
  );
}

export function ErrorBanner({ error, onRetry }: { error: string; onRetry?: () => void }) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-err/35 bg-err/10 px-4 py-3 text-xs text-err">
      <span className="min-w-0 break-words">{error}</span>
      {onRetry && <Button variant="danger" size="sm" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function Spinner({ label }: { label?: string }) {
  return (
    <div className="flex items-center gap-2 text-xs text-muted">
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-line border-t-accent" />
      {label || "Loading…"}
    </div>
  );
}

export function KV({ k, v, mono }: { k: string; v: ReactNode; mono?: boolean }) {
  return (
    <div className="flex items-start justify-between gap-3 border-b border-line/60 py-1.5 text-[11.5px] last:border-0">
      <span className="text-dim">{k}</span>
      <span className={cx("text-right text-muted", mono && "mono")}>{v}</span>
    </div>
  );
}

export function Score({ s }: { s?: Summary }) {
  if (!s || s.passed == null || s.n == null) return <span className="text-dim">—</span>;
  const pct = s.score != null ? s.score : s.passed / s.n;
  const tone = pct >= 1 ? "text-ok" : pct >= 0.8 ? "text-fg" : "text-warn";
  return <span className={cx("num", tone)}><strong>{s.passed}</strong>/{s.n}</span>;
}

export function Sparkline({ values, height = 56 }: { values: number[]; height?: number }) {
  if (!values.length) return <div className="h-14 rounded-lg border border-line bg-[#0b1219]" />;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values.map((v, i) => {
    const x = values.length === 1 ? 0 : (i / (values.length - 1)) * 298;
    const y = 52 - ((v - min) / span) * 44;
    return `${x},${y}`;
  }).join(" ");
  return (
    <svg viewBox="0 0 300 60" preserveAspectRatio="none"
      className="w-full rounded-lg border border-line bg-[#0b1219]" style={{ height }}>
      <polyline fill="none" stroke="#6ea8fe" strokeWidth="2" points={pts} />
    </svg>
  );
}

export function fmt(n: number | null | undefined, digits = 2): string {
  return n == null || Number.isNaN(n) ? "—" : Number(n).toFixed(digits);
}

export function dateLabel(iso?: string | null): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleString();
}
