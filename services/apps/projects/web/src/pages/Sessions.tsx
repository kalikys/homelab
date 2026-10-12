import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Project, type Session } from "../api";
import { ago, resume } from "../format";
import { Card, CopyButton, Empty } from "../ui";

export default function Sessions() {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [remember, setRemember] = useState(false);
  const load = () => api.unsorted().then(setSessions);
  useEffect(() => { load(); api.projects().then(setProjects); }, []);

  async function attach(s: Session, slug: string) {
    await api.attach(s.id, slug);
    if (remember && s.cwd) await api.addPathMap(s.cwd, slug).catch((e) => alert(String(e)));
    load();
  }

  if (!sessions) return <Empty>Загрузка…</Empty>;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Неразобранные чаты</h1>
        <label className="flex items-center gap-1.5 text-sm text-muted">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> запомнить папку за проектом
        </label>
      </div>
      {sessions.length === 0 && <Empty>Всё разобрано.</Empty>}
      {sessions.map((s) => (
        <Card key={s.id} className="space-y-2">
          <div className="flex items-start justify-between gap-2">
            <Link to={`/s/${s.id}`} className="font-medium hover:text-accent">{s.title || s.first_prompt.slice(0, 120) || s.id}</Link>
            <span className="shrink-0 text-xs text-muted">{ago(s.ended_at ?? s.started_at)}</span>
          </div>
          {s.title && s.first_prompt && <p className="line-clamp-2 text-sm text-muted">{s.first_prompt}</p>}
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <span className="truncate">{s.cwd}</span><span>· {s.user_turns} сообщ.</span>
            <CopyButton text={resume(s)} />
          </div>
          <select defaultValue="" onChange={(e) => e.target.value && attach(s, e.target.value)}
            className="w-full rounded-lg border border-line bg-card px-3 py-2 text-sm">
            <option value="" disabled>Привязать к проекту…</option>
            {projects.map((p) => <option key={p.slug} value={p.slug}>{p.title}</option>)}
          </select>
        </Card>
      ))}
    </div>
  );
}
