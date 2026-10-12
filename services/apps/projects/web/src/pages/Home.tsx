import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Project, type SearchGroup } from "../api";
import { AREAS, ago, isStale } from "../format";
import { TYPE, type ItemType } from "../types";
import { Badge, Card, Empty, Input, Progress } from "../ui";

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [waits, setWaits] = useState(0);
  const [unsorted, setUnsorted] = useState(0);
  const [area, setArea] = useState("all");
  const [showClosed, setShowClosed] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchGroup[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.projects(), api.userTodos(), api.unsorted()])
      .then(([p, w, s]) => { setProjects(p); setWaits(w.length); setUnsorted(s.length); })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!q.trim()) { setHits(null); return; }
    const t = setTimeout(() => api.search(q).then(setHits), 250);
    return () => clearTimeout(t);
  }, [q]);

  const shown = useMemo(() => projects.filter((p) =>
    (area === "all" || p.area === area) && (showClosed || p.status === "active" || p.status === "paused")), [projects, area, showClosed]);
  const areas = useMemo(() => [...new Set(projects.map((p) => p.area))], [projects]);

  return (
    <div className="space-y-5">
      {error && <Card className="text-sm text-amber-fg">Сервис недоступен: {error}</Card>}
      {(waits > 0 || unsorted > 0) && (
        <div className="flex flex-wrap gap-2 text-sm">
          {waits > 0 && <Link to="/waits"><Badge tone="amber">Ждёт тебя: {waits}</Badge></Link>}
          {unsorted > 0 && <Link to="/sessions"><Badge>Неразобранные чаты: {unsorted}</Badge></Link>}
        </div>
      )}
      <Input placeholder="Поиск по решениям, находкам, файлам…" value={q} onChange={(e) => setQ(e.target.value)} />

      {hits ? (
        <div className="space-y-3">
          {hits.length === 0 && <Empty>Ничего не нашлось.</Empty>}
          {hits.map((g) => (
            <Card key={g.project}>
              <Link to={`/p/${g.project}`} className="font-medium hover:text-accent">{g.title}</Link>
              <ul className="mt-2 space-y-1 text-sm">
                {g.hits.slice(0, 6).map((h) => (
                  <li key={`${h.type}-${h.id}`} className="truncate">
                    <span className="text-muted">{TYPE[h.type as ItemType]?.label ?? "Проект"}: </span>
                    {h.type === "project" ? h.text : <Link to={`/i/${h.id}`} className="hover:text-accent">{h.text}</Link>}
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {["all", ...areas].map((a) => (
              <button key={a} onClick={() => setArea(a)}
                className={`rounded-full px-3 py-1 ${area === a ? "bg-fg text-bg" : "text-muted hover:text-fg"}`}>
                {a === "all" ? "Все" : AREAS[a] ?? a}
              </button>
            ))}
            <label className="ml-auto flex items-center gap-1.5 text-muted">
              <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} /> завершённые
            </label>
          </div>
          {shown.length === 0 && !error && <Empty>Проектов пока нет — их создаёт Claude через pj.</Empty>}
          <div className="grid gap-3 sm:grid-cols-2">
            {shown.map((p) => (
              <Link key={p.slug} to={`/p/${p.slug}`}>
                <Card className={`h-full space-y-2 transition hover:border-accent/50 ${isStale(p) ? "opacity-60" : ""}`}>
                  <div className="flex items-start justify-between gap-2">
                    <h2 className="font-medium leading-snug">{p.title}</h2>
                    <span className="shrink-0 text-xs text-muted">{ago(p.updated_at)}</span>
                  </div>
                  <Progress value={p.progress} />
                  {p.next_step && <p className="text-sm"><span className="text-muted">Дальше: </span>{p.next_step}</p>}
                  <div className="flex flex-wrap gap-1.5">
                    <Badge>{AREAS[p.area] ?? p.area}</Badge>
                    {p.status === "paused" && <Badge>на паузе</Badge>}
                    {isStale(p) && <Badge>заброшен</Badge>}
                    {p.open_user_todos > 0 && <Badge tone="amber">ждёт тебя: {p.open_user_todos}</Badge>}
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
