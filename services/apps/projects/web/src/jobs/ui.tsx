import { useEffect, useLayoutEffect, useRef, useState, type ButtonHTMLAttributes, type KeyboardEvent as ReactKeyboardEvent, type ReactNode, type TextareaHTMLAttributes } from "react";
import { Check, ChevronDown } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { ALL, CLOSED, STATUS, type Status } from "./model";

export const Primary = ({ className = "", ...p }: ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button {...p} className={`inline-flex items-center justify-center gap-1.5 rounded-xl bg-accent px-3.5 py-2 text-sm font-medium text-white shadow-sm transition hover:brightness-110 active:scale-[.97] disabled:opacity-50 disabled:active:scale-100 ${className}`} />
);

export const Ghost = ({ className = "", ...p }: ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button {...p} className={`inline-flex items-center gap-1.5 rounded-lg px-2 py-1 text-sm text-muted transition hover:bg-hover hover:text-fg disabled:opacity-50 ${className}`} />
);

export const Dot = ({ status, size = 8 }: { status: Status; size?: number }) => (
  <span className="inline-block shrink-0 rounded-full" style={{ width: size, height: size, background: STATUS[status].color }} />
);

export const StatusBadge = ({ status }: { status: Status }) => (
  <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line px-2 py-0.5 text-xs">
    <Dot status={status} size={7} />{STATUS[status].label}
  </span>
);

function useOutside(open: boolean, close: () => void) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) close(); };
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") close(); };
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => { document.removeEventListener("mousedown", onDown); document.removeEventListener("keydown", onKey); };
  }, [open, close]);
  return ref;
}

/** Current status as a pill; a click opens the full list. */
export function StatusMenu({ value, onChange }: { value: Status; onChange: (s: Status) => void }) {
  const [open, setOpen] = useState(false);
  const ref = useOutside(open, () => setOpen(false));
  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen(!open)} aria-haspopup="listbox" aria-expanded={open}
        className="inline-flex items-center gap-2 rounded-full border border-line bg-card py-1 pl-2.5 pr-2 text-sm font-medium transition hover:bg-hover">
        <Dot status={value} />{STATUS[value].label}<ChevronDown size={14} className="text-muted" />
      </button>
      <AnimatePresence>
        {open && (
          <motion.ul role="listbox" initial={{ opacity: 0, y: -4 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: -4 }}
            transition={{ duration: 0.12 }}
            className="absolute left-0 z-30 mt-1.5 w-52 rounded-xl border border-line bg-card p-1 shadow-lg">
            {ALL.map((s) => (
              <li key={s}>
                {s === CLOSED[0] && <div className="my-1 border-t border-line" />}
                <button role="option" aria-selected={s === value} onClick={() => { setOpen(false); if (s !== value) onChange(s); }}
                  className="flex w-full items-center gap-2 rounded-lg px-2 py-1.5 text-left text-sm hover:bg-hover">
                  <Dot status={s} /><span className="flex-1">{STATUS[s].label}</span>
                  {s === value && <Check size={14} className="text-accent" />}
                </button>
              </li>
            ))}
          </motion.ul>
        )}
      </AnimatePresence>
    </div>
  );
}

/** Fit 1–5 as dots; clickable when onChange is given (a click on the current value clears it). */
export function Fit({ value, onChange }: { value: number | null; onChange?: (v: number | null) => void }) {
  if (!onChange && value === null) return null;
  return (
    <span className="inline-flex items-center gap-0.5" title={value ? `Подходит на ${value}/5` : "Оценка не стоит"}>
      {[1, 2, 3, 4, 5].map((n) => {
        const on = value !== null && n <= value;
        const dot = <span className={`block size-1.5 rounded-full ${on ? "bg-ok" : "bg-line"}`} />;
        return onChange
          ? <button key={n} aria-label={`${n} из 5`} onClick={() => onChange(n === value ? null : n)} className="grid size-4 place-items-center rounded hover:bg-hover">{dot}</button>
          : <span key={n}>{dot}</span>;
      })}
    </span>
  );
}

export function AutoTextarea({ className = "", ...p }: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  const ref = useRef<HTMLTextAreaElement>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight + 2}px`;
  }, [p.value]);
  return <textarea ref={ref} rows={3} {...p}
    className={`w-full resize-none rounded-xl border border-line bg-card px-3 py-2 text-sm leading-relaxed outline-none transition placeholder:text-muted focus:border-accent focus:ring-4 focus:ring-accent/10 ${className}`} />;
}

export const inputCls = "w-full rounded-xl border border-line bg-card px-3 py-2 text-sm outline-none transition placeholder:text-muted focus:border-accent focus:ring-4 focus:ring-accent/10";

export const Label = ({ label, children, hint, className = "" }: { label: string; children: ReactNode; hint?: string; className?: string }) => (
  <label className={`block space-y-1 ${className}`}>
    <span className="text-xs font-medium text-muted">{label}</span>
    {children}
    {hint && <span className="block text-[11px] text-muted">{hint}</span>}
  </label>
);

/**
 * A value that turns into an input on click and saves on Enter or blur; Esc cancels.
 * Shows the placeholder in muted text when empty so every field is visibly editable.
 */
export function Editable({ value, onSave, placeholder = "добавить", type = "text", display, multiline, className = "text-sm" }: {
  value: string; onSave: (v: string) => Promise<unknown> | void; placeholder?: string; type?: string;
  display?: ReactNode; multiline?: boolean; className?: string;
}) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  useEffect(() => { if (!editing) setDraft(value); }, [value, editing]);

  async function commit() {
    setEditing(false);
    if (draft.trim() !== value.trim()) await onSave(draft.trim());
  }

  if (editing) {
    const common = {
      autoFocus: true, value: draft, onBlur: commit,
      onChange: (e: { target: { value: string } }) => setDraft(e.target.value),
      onKeyDown: (e: ReactKeyboardEvent) => {
        if (e.key === "Escape") { setDraft(value); setEditing(false); }
        if (e.key === "Enter" && (!multiline || e.metaKey || e.ctrlKey)) { e.preventDefault(); commit(); }
      },
    };
    return multiline ? <AutoTextarea {...common} /> : <input type={type} {...common} className={`${inputCls} py-1 ${className}`} />;
  }
  return (
    <button onClick={() => setEditing(true)} title="Изменить"
      className={`-mx-1.5 block w-[calc(100%+0.75rem)] rounded-lg px-1.5 py-0.5 text-left transition hover:bg-hover ${className} ${value ? "" : "text-muted"} ${multiline ? "whitespace-pre-wrap" : "truncate"}`}>
      {value ? (display ?? value) : placeholder}
    </button>
  );
}

/** A short-lived confirmation line ("Сохранено") for actions without a visible result. */
export function useFlash(): [string, (msg: string) => void] {
  const [msg, setMsg] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  return [msg, (m: string) => { setMsg(m); clearTimeout(timer.current); timer.current = setTimeout(() => setMsg(""), 1800); }];
}

export const Flash = ({ msg }: { msg: string }) => (
  <AnimatePresence>
    {msg && (
      <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }}
        className="fixed inset-x-0 bottom-20 z-40 mx-auto w-fit rounded-full bg-fg px-4 py-2 text-sm text-bg shadow-lg md:bottom-6">
        {msg}
      </motion.div>
    )}
  </AnimatePresence>
);
