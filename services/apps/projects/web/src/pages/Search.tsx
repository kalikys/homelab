import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Search as SearchIcon } from "lucide-react";
import { api, type SearchGroup } from "../api";
import { TYPE, type ItemType } from "../types";
import { Card, Empty } from "../ui";

export default function SearchPage() {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchGroup[] | null>(null);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  const seq = useRef(0);

  useEffect(() => { input.current?.focus(); }, []);
  useEffect(() => {
    if (!q.trim()) { setHits(null); return; }
    const n = ++seq.current;
    const t = setTimeout(() => api.search(q)
      .then((r) => { if (n === seq.current) { setHits(r); setError(""); } })
      .catch((e) => setError(String(e))), 200);
    return () => clearTimeout(t);
  }, [q]);

  return (
    <div className="space-y-5">
      <div className="relative">
        <SearchIcon size={18} className="absolute left-3.5 top-1/2 -translate-y-1/2 text-muted" />
        <input ref={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="Решения, находки, файлы, задачи…"
          className="w-full rounded-2xl border border-line bg-card py-3 pl-11 pr-4 text-base outline-none transition placeholder:text-muted focus:border-accent focus:ring-4 focus:ring-accent/10" />
      </div>
      {error && <p className="text-sm text-amber-fg">{error}</p>}
      {hits === null && <Empty>Ищет по названиям, описаниям и путям во всех проектах.</Empty>}
      {hits?.length === 0 && <Empty>Ничего не нашлось.</Empty>}
      {hits?.map((g) => (
        <Card key={g.project} className="space-y-1.5">
          <Link to={`/p/${g.project}`} className="font-medium hover:text-accent">{g.title}</Link>
          <ul className="space-y-1 text-sm">
            {g.hits.slice(0, 8).map((h) => {
              const Icon = TYPE[h.type as ItemType]?.icon;
              return (
                <li key={`${h.type}-${h.id}`} className="flex items-center gap-2">
                  {Icon && <Icon size={14} className="shrink-0 text-muted" />}
                  {h.type === "project" ? <span className="truncate text-muted">{h.text}</span>
                    : <Link to={`/i/${h.id}`} className="truncate hover:text-accent">{h.text}</Link>}
                </li>
              );
            })}
          </ul>
        </Card>
      ))}
    </div>
  );
}
