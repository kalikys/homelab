import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { ChevronDown, ExternalLink, Radio } from "lucide-react";
import { agoShort } from "../format";
import { Card, Empty } from "../ui";
import { safeHref } from "../jobs/model";
import { STATUS_STYLE, STEP_LABEL, STEP_ORDER, outreach, type FeedEvent, type StepStatus, type Target } from "./api";

const POLL_MS = 4000;

/** A step name with its status colour; a spinner-like pulse while it is running. */
export function StepChip({ step, status }: { step: string; status: StepStatus }) {
  const s = STATUS_STYLE[status];
  return (
    <span className="inline-flex shrink-0 items-center gap-1.5 rounded-full border border-line px-2 py-0.5 text-[11px]">
      <span className={`inline-block size-[7px] rounded-full ${status === "running" ? "animate-pulse" : ""}`} style={{ background: s.color }} />
      {STEP_LABEL[step] ?? step}
      <span className="text-muted">{s.label}</span>
    </span>
  );
}

/** clone → reproduce → fix → test → policy → pr-text → ready, coloured by the latest status of each step. */
export function StepStrip({ t }: { t: Target }) {
  const steps = t.steps ?? {};
  if (!Object.keys(steps).length) return null;
  return (
    <div className="flex items-center gap-0.5" aria-label="Прогресс">
      {STEP_ORDER.map((name) => {
        const st = steps[name] as StepStatus | undefined;
        return (
          <span key={name} title={`${STEP_LABEL[name]}: ${st ? STATUS_STYLE[st].label : "ещё нет"}`}
            className={`h-1.5 w-3.5 rounded-full ${st === "running" ? "animate-pulse" : ""}`}
            style={{ background: st ? STATUS_STYLE[st].color : "var(--color-line, #e5e2db)" }} />
        );
      })}
    </div>
  );
}

/** A log excerpt, collapsed until clicked. */
export function LogBox({ log }: { log: string }) {
  const [open, setOpen] = useState(false);
  if (!log) return null;
  return (
    <div className="mt-1">
      <button type="button" onClick={() => setOpen(!open)} className="inline-flex items-center gap-1 text-[11px] text-muted hover:text-fg">
        <ChevronDown size={12} className={`transition ${open ? "rotate-180" : ""}`} />лог
      </button>
      {open && <pre className="mt-1 max-h-64 overflow-auto rounded-lg bg-hover p-2 text-[11px] leading-snug whitespace-pre-wrap break-all">{log}</pre>}
    </div>
  );
}

function FeedRow({ e }: { e: FeedEvent }) {
  const href = safeHref(e.url);
  return (
    <li className="py-2">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <Link to={`/jobs/outreach/${e.target_id}`} className="text-sm font-medium hover:text-accent">{e.company}</Link>
        {e.kind === "step" && e.step && e.status ? <StepChip step={e.step} status={e.status} />
          : <span className="text-[11px] text-muted">{e.kind}</span>}
        <span className="ml-auto text-[11px] tabular-nums text-muted">{agoShort(e.created_at)}</span>
      </div>
      <div className="mt-0.5 flex items-start gap-1.5 text-sm text-muted">
        <span className="min-w-0 break-words">{e.text}</span>
        {href && <a href={href} target="_blank" rel="noreferrer" className="mt-0.5 shrink-0 hover:text-accent"><ExternalLink size={12} /></a>}
      </div>
      <LogBox log={e.log} />
    </li>
  );
}

/** Live feed of the campaign: newest first, polled every few seconds while the tab is visible. */
export default function LiveFeed({ onActivity }: { onActivity?: () => void }) {
  const [items, setItems] = useState<FeedEvent[] | null>(null);
  const last = useRef(0);
  const loaded = useRef(false);
  useEffect(() => {
    let stop = false;
    async function tick() {
      if (document.hidden) return;
      try {
        const fresh = await outreach.events(last.current || undefined);
        if (stop) return;
        if (fresh.length) {
          last.current = fresh[0].id;
          setItems((v) => [...fresh, ...(v ?? [])].slice(0, 80));
          if (loaded.current) onActivity?.(); // new events after the first load: refresh the list
        } else {
          setItems((v) => v ?? []);
        }
        loaded.current = true;
      } catch { if (!stop) setItems((v) => v ?? []); }
    }
    tick();
    const t = setInterval(tick, POLL_MS);
    return () => { stop = true; clearInterval(t); };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const running = items?.some((e) => e.status === "running" && Date.now() - Date.parse(e.created_at) < 10 * 60_000);
  return (
    <Card>
      <div className="mb-1 flex items-center gap-2 text-xs font-medium text-muted">
        <Radio size={13} className={running ? "animate-pulse text-accent" : ""} />Лайв
        <span className="font-normal">обновляется каждые {POLL_MS / 1000} с</span>
      </div>
      {items === null ? <Empty>Загрузка…</Empty> : items.length === 0
        ? <Empty>Пока тихо. Шаги приходят через pj outreach step.</Empty>
        : <ol className="divide-y divide-line">{items.map((e) => <FeedRow key={e.id} e={e} />)}</ol>}
    </Card>
  );
}
