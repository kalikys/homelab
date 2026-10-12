import { useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";
import { motion } from "motion/react";

export const Card = ({ children, className = "" }: { children: ReactNode; className?: string }) => (
  <div className={`rounded-2xl border border-line bg-card p-4 shadow-[0_1px_2px_rgba(0,0,0,0.04)] ${className}`}>{children}</div>
);

export const Badge = ({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "amber" | "accent" | "ok" }) => {
  const t = {
    muted: "text-muted bg-hover", amber: "bg-amber-bg text-amber-fg",
    accent: "text-accent bg-accent/10", ok: "text-ok bg-ok/10",
  }[tone];
  return <span className={`inline-flex shrink-0 items-center rounded-md px-1.5 py-0.5 text-[11px] font-medium ${t}`}>{children}</span>;
};

export const Button = ({ className = "", ...p }: ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button {...p} className={`inline-flex items-center gap-1.5 rounded-lg border border-line bg-card px-3 py-1.5 text-sm transition hover:bg-hover active:scale-[.97] ${className}`} />
);

export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => (
  <input {...p} className={`w-full rounded-xl border border-line bg-card px-3 py-2 text-sm outline-none transition placeholder:text-muted focus:border-accent focus:ring-4 focus:ring-accent/10 ${p.className ?? ""}`} />
);

/** Progress as a small ring (Linear-style); null renders nothing. */
export function Ring({ value, size = 18 }: { value: number | null; size?: number }) {
  if (value === null) return null;
  const r = (size - 3) / 2, c = 2 * Math.PI * r;
  const color = value >= 100 ? "var(--ok)" : "var(--accent)";
  return (
    <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="shrink-0 -rotate-90" aria-label={`${value}%`}>
      <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--line)" strokeWidth="2.5" />
      <motion.circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke={color} strokeWidth="2.5" strokeLinecap="round"
        strokeDasharray={c} initial={{ strokeDashoffset: c }} animate={{ strokeDashoffset: c * (1 - value / 100) }}
        transition={{ duration: 0.6, ease: "easeOut" }} />
    </svg>
  );
}

export const Progress = ({ value }: { value: number | null }) =>
  value === null ? null : (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line">
        <motion.div className="h-full rounded-full" style={{ background: value >= 100 ? "var(--ok)" : "var(--accent)" }}
          initial={{ width: 0 }} animate={{ width: `${value}%` }} transition={{ duration: 0.6, ease: "easeOut" }} />
      </div>
      <span className="w-9 text-right text-xs tabular-nums text-muted">{value}%</span>
    </div>
  );

export const AreaDot = ({ area }: { area: string }) => (
  <span className="inline-block size-2 shrink-0 rounded-full" style={{ background: `var(--a-${area}, var(--a-other))` }} />
);

// navigator.clipboard exists only on https/localhost; the dashboard is also opened as http://192.168.1.10:8790.
async function copy(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* fall through */ }
  const ta = document.createElement("textarea");
  ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
  document.body.appendChild(ta); ta.select();
  let ok = false;
  try { ok = document.execCommand("copy"); } catch { ok = false; }
  ta.remove();
  return ok;
}

export function CopyButton({ text, label, title }: { text: string; label?: string; title?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button title={title ?? text} className="px-2 py-1 text-xs"
      onClick={async (e) => {
        e.preventDefault(); e.stopPropagation();
        if (await copy(text)) { setDone(true); setTimeout(() => setDone(false), 1200); }
        else window.prompt("Скопируй вручную:", text);
      }}>
      {done ? <Check size={14} className="text-ok" /> : <Copy size={14} />}{done ? "Скопировано" : label}
    </Button>
  );
}

export const Section = ({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) => (
  <section className="space-y-2">
    <div className="flex items-center justify-between">
      <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</h2>{action}
    </div>
    {children}
  </section>
);

export function Tabs({ tabs, value, onChange }: { tabs: { id: string; label: string; count?: number }[]; value: string; onChange: (id: string) => void }) {
  return (
    <div className="-mx-4 flex gap-1 overflow-x-auto border-b border-line px-4 [scrollbar-width:none]">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={`relative shrink-0 px-3 py-2.5 text-sm transition ${value === t.id ? "text-fg" : "text-muted hover:text-fg"}`}>
          {t.label}{t.count ? <span className="ml-1 text-xs text-muted">{t.count}</span> : null}
          {value === t.id && <motion.span layoutId="tab-underline" className="absolute inset-x-2 -bottom-px h-0.5 rounded-full bg-accent" />}
        </button>
      ))}
    </div>
  );
}

export const Empty = ({ children }: { children: ReactNode }) => <p className="py-6 text-center text-sm text-muted">{children}</p>;

export const Skeleton = ({ rows = 4 }: { rows?: number }) => (
  <div className="space-y-2">
    {Array.from({ length: rows }, (_, i) => <div key={i} className="h-12 animate-pulse rounded-xl bg-hover" />)}
  </div>
);

export const ErrorBox = ({ error }: { error: string }) => (
  <Card className="border-transparent bg-amber-bg text-sm text-amber-fg">Сервис недоступен: {error}</Card>
);
