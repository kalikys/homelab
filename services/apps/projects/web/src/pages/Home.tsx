import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, Play } from "lucide-react";
import { motion } from "motion/react";
import { api, type Card as CardT, type Item, type Project } from "../api";
import { ago, agoShort, isStale, resume } from "../format";
import { ItemList } from "../items";
import { AreaDot, Badge, Card, CopyButton, Empty, ErrorBox, Ring, Section, Skeleton } from "../ui";

function ProjectRow({ p }: { p: Project }) {
  return (
    <Link to={`/p/${p.slug}`}
      className={`flex items-center gap-3 rounded-xl px-3 py-2.5 transition hover:bg-hover ${isStale(p) ? "opacity-60" : ""}`}>
      <AreaDot area={p.area} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-sm font-medium">{p.title}</span>
          {p.open_user_todos > 0 && <span title="ждёт тебя"><Badge tone="amber">{p.open_user_todos}</Badge></span>}
          {isStale(p) && <Badge>давно не трогали</Badge>}
        </div>
        {p.next_step && <div className="truncate text-xs text-muted">{p.next_step}</div>}
      </div>
      <Ring value={p.progress} />
      <span className="hidden w-14 shrink-0 text-right text-xs tabular-nums text-muted sm:block">{agoShort(p.updated_at)}</span>
    </Link>
  );
}

function ContinueCard({ p }: { p: CardT }) {
  const chat = p.sessions[0];
  return (
    <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
      <Card className="flex h-full flex-col gap-3 transition hover:border-accent/40">
        <Link to={`/p/${p.slug}`} className="flex items-center gap-2">
          <AreaDot area={p.area} />
          <span className="flex-1 font-medium leading-snug">{p.title}</span>
          <Ring value={p.progress} size={22} />
        </Link>
        <p className="line-clamp-2 flex-1 text-sm text-muted">{p.next_step || "Следующий шаг не записан"}</p>
        <div className="flex items-center justify-between gap-2 text-xs text-muted">
          <span>{ago(p.updated_at)}</span>
          {chat && <span className="whitespace-nowrap"><CopyButton text={resume(chat)} label="Чат" title={`claude --resume: ${chat.title || chat.id}`} /></span>}
        </div>
      </Card>
    </motion.div>
  );
}

export default function Home({ projects }: { projects: Project[] }) {
  const [waits, setWaits] = useState<Item[] | null>(null);
  const [recent, setRecent] = useState<CardT[]>([]);
  const [error, setError] = useState("");

  const loadWaits = useCallback(() => api.userTodos().then(setWaits).catch((e) => setError(String(e))), []);
  useEffect(() => { loadWaits(); }, [loadWaits]);

  const active = useMemo(() => projects.filter((p) => p.status === "active"), [projects]);
  const paused = useMemo(() => projects.filter((p) => p.status === "paused"), [projects]);
  const closed = useMemo(() => projects.filter((p) => p.status === "done" || p.status === "dropped"), [projects]);

  useEffect(() => {
    const top = active.slice(0, 3);
    if (!top.length) return;
    Promise.all(top.map((p) => api.project(p.slug))).then(setRecent).catch(() => {});
  }, [active]);

  const today = new Date().toLocaleDateString("ru", { weekday: "long", day: "numeric", month: "long" });

  return (
    <div className="space-y-9">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Сегодня</h1>
        <p className="mt-1 text-sm text-muted first-letter:uppercase">
          {today} · {active.length} в работе{waits && waits.length > 0 ? ` · ${waits.length} ждут тебя` : ""}
        </p>
      </header>

      {error && <ErrorBox error={error} />}

      <Section title="Ждёт тебя" action={waits && waits.length > 5 && (
        <Link to="/waits" className="flex items-center gap-1 text-xs text-accent hover:underline">все {waits.length}<ArrowRight size={12} /></Link>
      )}>
        {waits === null ? <Skeleton rows={3} /> : waits.length === 0 ? (
          <Card><Empty>Ничего не ждёт — можно работать.</Empty></Card>
        ) : (
          <Card className="border-l-4 border-l-amber-fg/60 py-2"><ItemList items={waits.slice(0, 5)} onChange={loadWaits} withProject /></Card>
        )}
      </Section>

      {recent.length > 0 && (
        <Section title="Продолжить">
          <div className="grid gap-3 sm:grid-cols-3">{recent.map((p) => <ContinueCard key={p.slug} p={p} />)}</div>
        </Section>
      )}

      <Section title={`В работе · ${active.length}`}>
        {projects.length === 0 && !error ? <Skeleton /> : (
          <Card className="p-1.5">{active.map((p) => <ProjectRow key={p.slug} p={p} />)}</Card>
        )}
      </Section>

      {paused.length > 0 && (
        <Section title={`На паузе · ${paused.length}`}>
          <Card className="p-1.5">{paused.map((p) => <ProjectRow key={p.slug} p={p} />)}</Card>
        </Section>
      )}

      {closed.length > 0 && (
        <details className="group">
          <summary className="flex cursor-pointer list-none items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
            <Play size={10} className="transition group-open:rotate-90" />Завершённые · {closed.length}
          </summary>
          <Card className="mt-2 p-1.5">{closed.map((p) => <ProjectRow key={p.slug} p={p} />)}</Card>
        </details>
      )}
    </div>
  );
}
