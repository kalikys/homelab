import { useEffect, useState } from "react";
import { Link, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { FolderKanban, Inbox, MessagesSquare, Search, Sun } from "lucide-react";
import { api, type Project } from "./api";
import { AREAS } from "./format";
import { AreaDot, Ring } from "./ui";
import Home from "./pages/Home";
import ProjectPage from "./pages/Project";
import ItemPage from "./pages/Item";
import Waits from "./pages/Waits";
import Sessions from "./pages/Sessions";
import SessionPage from "./pages/Session";
import SearchPage from "./pages/Search";

type Counts = { waits: number; unsorted: number };

function useShell() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [counts, setCounts] = useState<Counts>({ waits: 0, unsorted: 0 });
  const loc = useLocation();
  useEffect(() => {
    Promise.all([api.projects(), api.userTodos(), api.unsorted()])
      .then(([p, w, s]) => { setProjects(p); setCounts({ waits: w.length, unsorted: s.length }); })
      .catch(() => {});
  }, [loc.pathname]);
  return { projects, counts };
}

const navItem = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition ${isActive ? "bg-hover font-medium text-fg" : "text-muted hover:bg-hover hover:text-fg"}`;

const Count = ({ n, tone }: { n: number; tone?: "amber" }) =>
  n ? <span className={`ml-auto text-xs tabular-nums ${tone === "amber" ? "font-medium text-amber-fg" : "text-muted"}`}>{n}</span> : null;

function Sidebar({ projects, counts }: { projects: Project[]; counts: Counts }) {
  const active = projects.filter((p) => p.status === "active" || p.status === "paused");
  const areas = [...new Set(active.map((p) => p.area))];
  return (
    <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col gap-5 overflow-y-auto border-r border-line bg-panel px-3 py-5 md:flex">
      <Link to="/" className="flex items-center gap-2 px-2.5 text-[15px] font-semibold"><FolderKanban size={18} className="text-accent" />Проекты</Link>
      <nav className="space-y-0.5">
        <NavLink to="/" end className={navItem}><Sun size={16} />Сегодня</NavLink>
        <NavLink to="/waits" className={navItem}><Inbox size={16} />Ждёт тебя<Count n={counts.waits} tone="amber" /></NavLink>
        <NavLink to="/sessions" className={navItem}><MessagesSquare size={16} />Неразобранные<Count n={counts.unsorted} /></NavLink>
        <NavLink to="/search" className={navItem}><Search size={16} />Поиск<kbd className="ml-auto text-[10px] text-muted">⌘K</kbd></NavLink>
      </nav>
      {areas.map((a) => (
        <div key={a} className="space-y-0.5">
          <div className="px-2.5 pb-1 text-[11px] font-semibold uppercase tracking-wide text-muted">{AREAS[a] ?? a}</div>
          {active.filter((p) => p.area === a).map((p) => (
            <NavLink key={p.slug} to={`/p/${p.slug}`} className={navItem}>
              <AreaDot area={p.area} /><span className="min-w-0 flex-1 truncate">{p.title}</span><Ring value={p.progress} size={14} />
            </NavLink>
          ))}
        </div>
      ))}
    </aside>
  );
}

function MobileTabs({ counts }: { counts: Counts }) {
  const tab = ({ isActive }: { isActive: boolean }) =>
    `relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] ${isActive ? "text-accent" : "text-muted"}`;
  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-panel/90 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
      <NavLink to="/" end className={tab}><Sun size={20} />Сегодня</NavLink>
      <NavLink to="/waits" className={tab}><Inbox size={20} />Ждёт
        {counts.waits > 0 && <span className="absolute right-[28%] top-1 rounded-full bg-amber-fg px-1 text-[9px] font-semibold text-bg">{counts.waits}</span>}
      </NavLink>
      <NavLink to="/sessions" className={tab}><MessagesSquare size={20} />Чаты</NavLink>
      <NavLink to="/search" className={tab}><Search size={20} />Поиск</NavLink>
    </nav>
  );
}

export default function App() {
  const shell = useShell();
  const navigate = useNavigate();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); navigate("/search"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  return (
    <div className="flex min-h-dvh">
      <Sidebar {...shell} />
      <main className="min-w-0 flex-1">
        <div className="mx-auto max-w-4xl px-4 pb-24 pt-6 md:px-8 md:pb-12 md:pt-8">
          <Routes>
            <Route path="/" element={<Home projects={shell.projects} />} />
            <Route path="/p/:slug" element={<ProjectPage />} />
            <Route path="/i/:id" element={<ItemPage />} />
            <Route path="/s/:id" element={<SessionPage />} />
            <Route path="/waits" element={<Waits />} />
            <Route path="/sessions" element={<Sessions />} />
            <Route path="/search" element={<SearchPage />} />
          </Routes>
        </div>
      </main>
      <MobileTabs counts={shell.counts} />
    </div>
  );
}
