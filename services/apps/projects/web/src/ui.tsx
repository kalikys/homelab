import { useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";

export const Card = ({ children, className = "" }: { children: ReactNode; className?: string }) => (
  <div className={`rounded-xl border border-line bg-card p-4 ${className}`}>{children}</div>
);

export const Badge = ({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "amber" | "accent" | "ok" }) => {
  const t = {
    muted: "text-muted border-line", amber: "bg-amber-bg text-amber-fg border-transparent",
    accent: "text-accent border-accent/40", ok: "text-ok border-ok/40",
  }[tone];
  return <span className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs ${t}`}>{children}</span>;
};

export const Button = ({ className = "", ...p }: ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button {...p} className={`inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm transition hover:bg-line/50 active:scale-[.98] ${className}`} />
);

export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => (
  <input {...p} className={`w-full rounded-lg border border-line bg-card px-3 py-2 text-sm outline-none focus:border-accent ${p.className ?? ""}`} />
);

export const Progress = ({ value }: { value: number | null }) =>
  value === null ? null : (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-line">
        <div className="h-1.5 rounded-full bg-accent transition-all" style={{ width: `${value}%` }} />
      </div>
      <span className="w-9 text-right text-xs tabular-nums text-muted">{value}%</span>
    </div>
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

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button title={text} className="px-2 py-1 text-xs"
      onClick={async (e) => {
        e.preventDefault();
        if (await copy(text)) { setDone(true); setTimeout(() => setDone(false), 1200); }
        else window.prompt("Скопируй вручную:", text);
      }}>
      {done ? <Check size={14} /> : <Copy size={14} />}{label}
    </Button>
  );
}

export const Section = ({ title, children }: { title: string; children: ReactNode }) => (
  <section className="space-y-1"><h2 className="text-sm font-medium text-muted">{title}</h2>{children}</section>
);

export function Tabs({ tabs, value, onChange }: { tabs: { id: string; label: string; count?: number }[]; value: string; onChange: (id: string) => void }) {
  return (
    <div className="-mx-4 flex gap-1 overflow-x-auto border-b border-line px-4">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={`shrink-0 border-b-2 px-3 py-2 text-sm ${value === t.id ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg"}`}>
          {t.label}{t.count ? <span className="ml-1 text-xs text-muted">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export const Empty = ({ children }: { children: ReactNode }) => <p className="py-2 text-sm text-muted">{children}</p>;
