import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { ArrowRight } from "lucide-react";
import { api, type Card as CardT, type Item } from "../api";
import { AREAS, ago, day, resume } from "../format";
import { ItemList, Location } from "../items";
import { STATUS, TYPE, isOpen, tone, type ItemType } from "../types";
import { AreaDot, Badge, Card, CopyButton, Empty, ErrorBox, Progress, Section, Skeleton, Tabs } from "../ui";

export default function Project() {
  const { slug = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "overview";
  const [p, setP] = useState<CardT | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.project(slug).then(setP).catch((e) => setError(String(e))), [slug]);
  useEffect(() => { load(); }, [load]);

  if (error) return <ErrorBox error={error} />;
  if (!p) return <Skeleton rows={6} />;

  const of = (t: ItemType) => p.items.filter((i) => i.type === t);
  const todos = of("todo");
  const userTodos = todos.filter((i) => i.owner === "user" && isOpen(i.status));
  const claudeTodos = todos.filter((i) => i.owner !== "user" && isOpen(i.status));
  const closedTodos = todos.filter((i) => !isOpen(i.status));
  const log: Item[] = [...of("decision"), ...of("finding"), ...of("note")].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const tabs = [
    { id: "overview", label: "Обзор" },
    { id: "todos", label: "Задачи", count: userTodos.length + claudeTodos.length },
    { id: "artifacts", label: "Артефакты", count: of("artifact").length },
    { id: "log", label: "Решения", count: log.length },
    { id: "chats", label: "Чаты", count: p.sessions.length },
    { id: "history", label: "История" },
  ];

  return (
    <div className="space-y-5">
      <div className="space-y-3">
        <div className="flex items-center gap-2 text-xs text-muted">
          <AreaDot area={p.area} />{AREAS[p.area] ?? p.area}
          {p.status !== "active" && <Badge>{p.status === "paused" ? "на паузе" : p.status === "done" ? "завершён" : p.status}</Badge>}
          <span>· обновлён {ago(p.updated_at)}</span>
        </div>
        <h1 className="text-2xl font-semibold tracking-tight">{p.title}</h1>
        {p.summary && <p className="text-sm text-muted">{p.summary}</p>}
        <Progress value={p.progress} />
        {p.next_step && (
          <div className="flex items-start gap-3 rounded-2xl bg-accent/8 px-4 py-3 ring-1 ring-accent/20">
            <ArrowRight size={18} className="mt-0.5 shrink-0 text-accent" />
            <div><div className="text-xs font-medium text-accent">Следующий шаг</div><div className="text-[15px]">{p.next_step}</div></div>
          </div>
        )}
      </div>

      {userTodos.length > 0 && (
        <Card className="space-y-1 border-transparent bg-amber-bg text-amber-fg">
          <h2 className="text-sm font-medium">Ждёт тебя</h2>
          <ItemList items={userTodos} onChange={load} hideOwner />
        </Card>
      )}

      <Tabs tabs={tabs} value={tab} onChange={(id) => setParams({ tab: id }, { replace: true })} />

      {tab === "overview" && (
        <div className="grid gap-6 md:grid-cols-2">
          {of("milestone").length > 0 && <Section title="Этапы"><ItemList items={of("milestone")} onChange={load} /></Section>}
          {of("feature").length > 0 && <Section title="Фичи"><ItemList items={of("feature")} /></Section>}
          {of("plan").length > 0 && <Section title="Планы"><ItemList items={of("plan")} /></Section>}
          {claudeTodos.length > 0 && <Section title="Задачи Claude"><ItemList items={claudeTodos.slice(0, 8)} onChange={load} /></Section>}
          {log.length > 0 && <Section title="Последние решения и находки"><ItemList items={log.slice(0, 5)} /></Section>}
          {p.items.length === 0 && <Empty>Пока пусто.</Empty>}
        </div>
      )}

      {tab === "todos" && (
        <div className="space-y-6">
          <Section title="Тебе"><ItemList items={userTodos} onChange={load} empty="Ничего." /></Section>
          <Section title="Claude"><ItemList items={claudeTodos} onChange={load} empty="Ничего." /></Section>
          {closedTodos.length > 0 && (
            <details>
              <summary className="cursor-pointer text-sm text-muted">Готово и отменено ({closedTodos.length})</summary>
              <ItemList items={closedTodos} onChange={load} />
            </details>
          )}
        </div>
      )}

      {tab === "artifacts" && (
        <div className="grid gap-3 sm:grid-cols-2">
          {of("artifact").length === 0 && <Empty>Артефактов нет.</Empty>}
          {of("artifact").map((a) => (
            <Card key={a.id} className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <Link to={`/i/${a.id}`} className="font-medium hover:text-accent">{a.title}</Link>
                <Badge tone={tone(a.status)}>{STATUS[a.status]}</Badge>
              </div>
              {a.body && <p className="line-clamp-2 text-sm text-muted">{a.body}</p>}
              <Location item={a} />
            </Card>
          ))}
        </div>
      )}

      {tab === "log" && (
        <div className="space-y-3">
          {log.length === 0 && <Empty>Решений и находок пока нет.</Empty>}
          {log.map((i) => (
            <Card key={i.id} className={`space-y-1 border-l-4 ${i.type === "decision" ? "border-l-accent" : i.type === "finding" ? "border-l-ok" : ""}`}>
              <div className="text-xs text-muted">{TYPE[i.type].label} · {day(i.created_at)}</div>
              <Link to={`/i/${i.id}`} className="font-medium hover:text-accent">{i.title}</Link>
              {i.body && <p className="whitespace-pre-wrap text-sm text-muted">{i.body}</p>}
              <Location item={i} />
            </Card>
          ))}
        </div>
      )}

      {tab === "chats" && (
        <div className="space-y-2">
          {p.sessions.length === 0 && <Empty>Чатов пока нет.</Empty>}
          {p.sessions.map((s) => (
            <Card key={s.id} className="space-y-1.5">
              <div className="flex items-center justify-between gap-2">
                <Link to={`/s/${s.id}`} className="min-w-0 truncate hover:text-accent">
                  {s.title || s.first_prompt || s.id.slice(0, 8)} <span className="text-xs text-muted">· {ago(s.ended_at ?? s.started_at)}</span>
                </Link>
                <CopyButton text={resume(s)} />
              </div>
              {s.items.length > 0 && (
                <div className="flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">
                  {s.items.slice(0, 6).map((i) => (
                    <Link key={i.id} to={`/i/${i.id}`} className="hover:text-accent">{TYPE[i.type].label}: {i.title}</Link>
                  ))}
                  {s.items.length > 6 && <span>и ещё {s.items.length - 6}</span>}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {tab === "history" && (
        <div className="space-y-1.5 text-sm">
          {p.events.length === 0 && <Empty>Истории пока нет.</Empty>}
          {p.events.map((e) => (
            <div key={e.id} className="flex gap-3">
              <span className="w-16 shrink-0 text-xs text-muted">{day(e.ts)}</span>
              {e.item_id ? <Link to={`/i/${e.item_id}`} className="hover:text-accent">{e.text}</Link> : <span className="text-muted">{e.text}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
