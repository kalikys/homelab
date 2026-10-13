import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { BellRing, FileCheck2, Inbox, Paperclip, Plus, Search } from "lucide-react";
import { motion } from "motion/react";
import { agoShort, day } from "../format";
import { Card, Empty, ErrorBox, Section, Skeleton } from "../ui";
import { jobs, type Application, type Platform, type Summary } from "./api";
import { CLOSED, NEXT, STAGES, STATUS, dueLabel, plusDays, type Status } from "./model";
import { Dot, Fit, Flash, Ghost, inputCls, useFlash } from "./ui";

const WEEK_GOAL = 5;

export function AppRow({ a, right }: { a: Application; right?: ReactNode }) {
  return (
    <motion.div layout initial={{ opacity: 0 }} animate={{ opacity: 1 }}
      className="group flex items-center gap-3 rounded-xl px-3 py-2.5 transition hover:bg-hover">
      <Dot status={a.status} />
      <Link to={`/jobs/a/${a.id}`} className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium">{a.company}</span>
          {a.origin === "inbound" && <span title="HR написала сама"><Inbox size={13} className="shrink-0 text-[var(--s-inbound)]" /></span>}
        </div>
        <div className="truncate text-xs text-muted">
          {a.title}{a.platform_name ? ` · ${a.platform_name}` : ""}{a.contact_name ? ` · ${a.contact_name}` : ""}
        </div>
      </Link>
      {right ?? (
        <div className="flex shrink-0 items-center gap-3 text-xs text-muted">
          <Fit value={a.fit} />
          {a.letter_sent > 0 && <span title="есть отправленное письмо"><FileCheck2 size={14} /></span>}
          {a.files_count > 0 && <span title="есть файлы"><Paperclip size={13} /></span>}
          <span className="hidden w-12 text-right tabular-nums sm:block">{agoShort(a.updated_at)}</span>
        </div>
      )}
    </motion.div>
  );
}

function WeekGoal({ n }: { n: number }) {
  const pct = Math.min(100, Math.round((100 * n) / WEEK_GOAL));
  return (
    <div className="flex items-center gap-2 text-xs text-muted" title="Цель: 5–10 откликов в неделю">
      <div className="h-1.5 w-20 overflow-hidden rounded-full bg-line">
        <motion.div className="h-full rounded-full bg-ok" initial={{ width: 0 }} animate={{ width: `${pct}%` }} transition={{ duration: 0.6 }} />
      </div>
      <span className="tabular-nums">{n} из {WEEK_GOAL} за неделю</span>
    </div>
  );
}

type Filter = "active" | "closed" | "all" | Status;

export default function Funnel() {
  const [params, setParams] = useSearchParams();
  const filter = (params.get("f") as Filter) || "active";
  const [q, setQ] = useState(params.get("q") ?? "");
  const [platform, setPlatform] = useState(params.get("p") ?? "");
  const [apps, setApps] = useState<Application[] | null>(null);
  const [summary, setSummary] = useState<Summary | null>(null);
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [error, setError] = useState("");
  const [flash, setFlash] = useFlash();
  const seq = useRef(0);

  const load = useCallback(() => {
    const n = ++seq.current;
    Promise.all([jobs.list({ q, platform }), jobs.summary()])
      .then(([a, s]) => { if (n === seq.current) { setApps(a); setSummary(s); setError(""); } })
      .catch((e) => setError(String(e)));
  }, [q, platform]);

  useEffect(() => { const t = setTimeout(load, q ? 200 : 0); return () => clearTimeout(t); }, [load, q]);
  useEffect(() => { jobs.platforms().then(setPlatforms).catch(() => {}); }, []);

  const setFilter = (f: Filter) => {
    const next = new URLSearchParams(params);
    if (f === "active") next.delete("f"); else next.set("f", f);
    setParams(next, { replace: true });
  };

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const a of apps ?? []) c[a.status] = (c[a.status] ?? 0) + 1;
    return c;
  }, [apps]);
  const closedCount = CLOSED.reduce((n, s) => n + (counts[s] ?? 0), 0);
  const activeCount = (apps?.length ?? 0) - closedCount;

  const shown = (apps ?? []).filter((a) =>
    filter === "all" ? true : filter === "active" ? !CLOSED.includes(a.status) : filter === "closed" ? CLOSED.includes(a.status) : a.status === filter);

  async function quick(a: Application, body: Parameters<typeof jobs.patch>[1], msg: string) {
    try { await jobs.patch(a.id, body); setFlash(msg); load(); } catch (e) { setFlash(`Не сохранилось: ${e}`); }
  }

  const waiting = (counts.sent ?? 0);

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Отклики</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
            {summary && <WeekGoal n={summary.sent_this_week} />}
            {waiting > 0 && <span>{waiting} ждут ответа</span>}
            {summary && summary.letters_pending > 0 && <span className="text-accent">{summary.letters_pending === 1 ? "письмо пишется…" : `${summary.letters_pending} письма пишутся…`}</span>}
          </div>
        </div>
        <Link to="/jobs/new" className="hidden items-center gap-1.5 rounded-xl md:inline-flex bg-accent px-3.5 py-2 text-sm font-medium text-white shadow-sm transition hover:brightness-110 active:scale-[.97]">
          <Plus size={16} />Новый отклик
        </Link>
      </header>

      {error && <ErrorBox error={error} />}

      {summary && summary.due.length > 0 && (
        <Section title={`Пора напомнить · ${summary.due.length}`}>
          <Card className="border-l-4 border-l-amber-fg/60 p-1.5">
            {summary.due.map((a) => (
              <AppRow key={a.id} a={a} right={
                <div className="flex shrink-0 items-center gap-1">
                  <span className="mr-1 hidden text-xs text-amber-fg sm:inline">
                    <BellRing size={12} className="mr-1 inline" />{a.next_action || "напомнить"} · {dueLabel(a.next_action_at)}
                  </span>
                  {NEXT[a.status] && (
                    <Ghost onClick={() => quick(a, { status: NEXT[a.status] }, `${a.company}: ${STATUS[NEXT[a.status]!].label.toLowerCase()}`)}>
                      {STATUS[NEXT[a.status]!].label}
                    </Ghost>
                  )}
                  <Ghost title="Напомнить через неделю" onClick={() => quick(a, { next_action_at: plusDays(7) }, `Напомню ${day(plusDays(7))}`)}>+7 дн</Ghost>
                </div>
              } />
            ))}
          </Card>
        </Section>
      )}

      <section className="space-y-3">
        <div className="-mx-4 flex gap-1.5 overflow-x-auto px-4 pb-1 [scrollbar-width:none]">
          <Chip on={filter === "active"} onClick={() => setFilter("active")} label="В работе" n={activeCount} />
          {STAGES.map((s) => (
            <Chip key={s} on={filter === s} onClick={() => setFilter(s)} label={STATUS[s].label} n={counts[s] ?? 0} status={s} />
          ))}
          <Chip on={filter === "closed"} onClick={() => setFilter("closed")} label="Закрытые" n={closedCount} />
        </div>
        <div className="flex gap-2">
          <div className="relative min-w-0 flex-1">
            <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Компания, должность, контакт…" className={`${inputCls} pl-9`} />
          </div>
          <select value={platform} onChange={(e) => setPlatform(e.target.value)} className="w-40 shrink-0 rounded-xl border border-line bg-card px-3 py-2 text-sm outline-none focus:border-accent sm:w-48" aria-label="Платформа">
            <option value="">Все платформы</option>
            {platforms.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
          </select>
        </div>

        {apps === null ? <Skeleton /> : shown.length === 0 ? (
          <Card><Empty>{apps.length === 0 && !q && !platform
            ? <>Откликов пока нет. <Link to="/jobs/new" className="text-accent hover:underline">Добавить первый</Link></>
            : "Здесь пусто."}</Empty></Card>
        ) : (
          <Card className="p-1.5">{shown.map((a) => <AppRow key={a.id} a={a} />)}</Card>
        )}
      </section>
      <Flash msg={flash} />
    </div>
  );
}

function Chip({ on, onClick, label, n, status }: { on: boolean; onClick: () => void; label: string; n: number; status?: Status }) {
  return (
    <button onClick={onClick}
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-3 py-1 text-sm transition ${on ? "border-fg bg-fg text-bg" : "border-line bg-card text-fg hover:bg-hover"} ${n === 0 && !on ? "opacity-50" : ""}`}>
      {status && <Dot status={status} size={7} />}{label}<span className={`tabular-nums text-xs ${on ? "opacity-70" : "text-muted"}`}>{n}</span>
    </button>
  );
}
