import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type ItemDetail } from "../api";
import { ago, day, resume } from "../format";
import { ItemList, Location } from "../items";
import { REL, ROLE, STATUS, STATUSES, TYPE } from "../types";
import { Card, CopyButton, Empty, Progress, Section } from "../ui";

const select = "rounded-lg border border-line bg-card px-2 py-1 text-sm";

export default function ItemPage() {
  const { id = "" } = useParams();
  const [it, setIt] = useState<ItemDetail | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.item(Number(id)).then(setIt).catch((e) => setError(String(e))), [id]);
  useEffect(() => { load(); }, [load]);

  if (error) return <Card className="text-sm text-amber-fg">{error}</Card>;
  if (!it) return <Empty>Загрузка…</Empty>;
  const Icon = TYPE[it.type].icon;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-1.5 text-sm text-muted">
          <Icon size={16} />{TYPE[it.type].label} · <Link to={`/p/${it.project}`} className="hover:text-accent">{it.project}</Link>
          {it.parent && <> · в <Link to={`/i/${it.parent.id}`} className="hover:text-accent">{it.parent.title}</Link></>}
        </div>
        <h1 className="text-2xl font-semibold">{it.title}</h1>
        <div className="flex flex-wrap items-center gap-2">
          {STATUSES[it.type].length > 1 && (
            <select className={select} value={it.status} onChange={(e) => api.patchItem(it.id, { status: e.target.value }).then(load)}>
              {STATUSES[it.type].map((s) => <option key={s} value={s}>{STATUS[s]}</option>)}
            </select>
          )}
          {it.type === "todo" && (
            <select className={select} value={it.owner ?? "claude"} onChange={(e) => api.patchItem(it.id, { owner: e.target.value }).then(load)}>
              <option value="claude">делает Claude</option>
              <option value="user">делаешь ты</option>
            </select>
          )}
          <Location item={it} />
          <span className="text-xs text-muted">создано {day(it.created_at)}</span>
        </div>
        <Progress value={it.progress} />
      </div>

      {it.body && <Card><p className="whitespace-pre-wrap text-sm">{it.body}</p></Card>}

      <div className="grid gap-6 md:grid-cols-2">
        {it.children.length > 0 && <Section title="Внутри"><ItemList items={it.children} onChange={load} /></Section>}
        {it.relations.length > 0 && (
          <Section title="Связи">
            {it.relations.map((r) => (
              <div key={`${r.direction}-${r.kind}-${r.item.id}`} className="flex items-center gap-2 py-1 text-sm">
                <span className="shrink-0 text-muted">{REL[r.direction][r.kind] ?? r.kind}</span>
                <Link to={`/i/${r.item.id}`} className="truncate hover:text-accent">{r.item.title}</Link>
                {r.item.project !== it.project && <span className="text-xs text-muted">{r.item.project}</span>}
              </div>
            ))}
          </Section>
        )}
        {it.sessions.length > 0 && (
          <Section title="Чаты">
            {it.sessions.map((s) => (
              <div key={s.id} className="flex items-center justify-between gap-2 py-1 text-sm">
                <Link to={`/s/${s.id}`} className="min-w-0 truncate hover:text-accent">
                  {s.title || s.first_prompt || s.id.slice(0, 8)}
                  <span className="text-xs text-muted"> · {s.roles.map((r) => ROLE[r] ?? r).join(", ")} · {ago(s.ended_at ?? s.started_at)}</span>
                </Link>
                <CopyButton text={resume(s)} />
              </div>
            ))}
          </Section>
        )}
        {it.events.length > 0 && (
          <Section title="История">
            {it.events.map((e) => (
              <div key={e.id} className="flex gap-3 py-0.5 text-sm">
                <span className="w-16 shrink-0 text-xs text-muted">{day(e.ts)}</span><span>{e.text}</span>
              </div>
            ))}
          </Section>
        )}
      </div>
    </div>
  );
}
