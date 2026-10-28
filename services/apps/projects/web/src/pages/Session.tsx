import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type SessionDetail } from "../api";
import { ago, resume } from "../format";
import { ROLE, STATUS, TYPE } from "../types";
import { Card, CopyButton, Empty, Section } from "../ui";

export default function SessionPage() {
  const { id = "" } = useParams();
  const [s, setS] = useState<SessionDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.session(id).then(setS).catch((e) => setError(String(e))); }, [id]);
  if (error) return <Card className="text-sm text-amber-fg">{error}</Card>;
  if (!s) return <Empty>Загрузка…</Empty>;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="text-sm text-muted">
          Чат · {ago(s.ended_at ?? s.started_at)}{s.project && <> · <Link to={`/p/${s.project}`} className="hover:text-accent">{s.project}</Link></>}
        </div>
        <h1 className="text-2xl font-semibold">{s.title || s.first_prompt.slice(0, 80) || s.id}</h1>
        {s.first_prompt && <p className="text-sm text-muted">{s.first_prompt}</p>}
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <span className="truncate">{s.cwd}</span><span>· {s.user_turns} сообщ.</span><CopyButton text={resume(s)} label="resume" />
        </div>
      </div>
      <Section title="Что создано и изменено">
        {s.items.length === 0 && <Empty>Этот чат ничего не записал в дашборд.</Empty>}
        {s.items.map((i) => {
          const Icon = TYPE[i.type].icon;
          return (
            <div key={i.id} className="flex items-center gap-2 py-1 text-sm">
              <Icon size={15} className="shrink-0 text-muted" />
              <Link to={`/i/${i.id}`} className="min-w-0 flex-1 truncate hover:text-accent">{i.title}</Link>
              <span className="shrink-0 text-xs text-muted">{STATUS[i.status]} · {i.roles.map((r) => ROLE[r] ?? r).join(", ")}</span>
            </div>
          );
        })}
      </Section>
      {s.files_changed.length > 0 && (
        <details className="rounded-xl border border-line bg-card p-4">
          <summary className="cursor-pointer text-sm text-muted">Изменённые файлы ({s.files_changed.length})</summary>
          <ul className="mt-2 space-y-1 text-xs">{s.files_changed.map((f) => <li key={f} className="truncate">{f}</li>)}</ul>
        </details>
      )}
    </div>
  );
}
