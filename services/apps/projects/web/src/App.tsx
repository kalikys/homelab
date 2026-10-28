import { useEffect, useState } from "react";
import { Link, NavLink, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { Briefcase, FolderKanban, Inbox, MessagesSquare, Search, Sun } from "lucide-react";
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
import Funnel from "./jobs/Funnel";
import ApplicationPage from "./jobs/Application";
import NewApplication from "./jobs/NewApplication";
import Contacts from "./jobs/Contacts";
import Platforms from "./jobs/Platforms";
import { JobsNav, JobsTabs, useJobsSummary } from "./jobs/Shell";
import type { Summary } from "./jobs/api";

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

/** "Проекты | Отклики": two dashboards in one app, each with its own navigation. */
function SectionSwitch({ jobsMode }: { jobsMode: boolean }) {
  const seg = (on: boolean) =>
    `flex flex-1 items-center justify-center gap-1.5 rounded-lg py-1.5 text-sm transition ${on ? "bg-card font-medium shadow-sm" : "text-muted hover:text-fg"}`;
  return (
    <div className="flex rounded-xl border border-line bg-hover/60 p-0.5">
      <Link to="/" className={seg(!jobsMode)}><FolderKanban size={15} className={jobsMode ? "" : "text-accent"} />Проекты</Link>
      <Link to="/jobs" className={seg(jobsMode)}><Briefcase size={15} className={jobsMode ? "text-accent" : ""} />Отклики</Link>
    </div>
  );
}

function Sidebar({ projects, counts, jobsMode, summary }: { projects: Project[]; counts: Counts; jobsMode: boolean; summary: Summary | null }) {
  const active = projects.filter((p) => p.status === "active" || p.status === "paused");
  const areas = [...new Set(active.map((p) => p.area))];
  return (
    <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col gap-5 overflow-y-auto border-r border-line bg-panel px-3 py-5 md:flex">
      <SectionSwitch jobsMode={jobsMode} />
      {jobsMode ? <JobsNav summary={summary} /> : <ProjectsNav active={active} areas={areas} counts={counts} />}
    </aside>
  );
}

function ProjectsNav({ active, areas, counts }: { active: Project[]; areas: string[]; counts: Counts }) {
  return (
    <>
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
    </>
  );
}

function MobileTabs({ counts, jobsMode, summary }: { counts: Counts; jobsMode: boolean; summary: Summary | null }) {
  const tab = ({ isActive }: { isActive: boolean }) =>
    `relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] ${isActive ? "text-accent" : "text-muted"}`;
  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-panel/90 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
      {jobsMode ? <JobsTabs summary={summary} /> : <>
      <NavLink to="/" end className={tab}><Sun size={20} />Сегодня</NavLink>
      <NavLink to="/waits" className={tab}><Inbox size={20} />Ждёт
        {counts.waits > 0 && <span className="absolute right-[28%] top-1 rounded-full bg-amber-fg px-1 text-[9px] font-semibold text-bg">{counts.waits}</span>}
      </NavLink>
      <NavLink to="/sessions" className={tab}><MessagesSquare size={20} />Чаты</NavLink>
      <NavLink to="/search" className={tab}><Search size={20} />Поиск</NavLink>
      </>}
    </nav>
  );
}

/** On phones the section switch lives in a slim top bar, since the sidebar is hidden. */
function MobileSwitch({ jobsMode }: { jobsMode: boolean }) {
  return <div className="sticky top-0 z-20 border-b border-line bg-panel/90 px-4 py-2 backdrop-blur md:hidden"><SectionSwitch jobsMode={jobsMode} /></div>;
}

// jobs.home.kalik8s.ru opens the applications dashboard directly.
const jobsHost = typeof location !== "undefined" && location.host.startsWith("jobs.");

export default function App() {
  const shell = useShell();
  const navigate = useNavigate();
  const loc = useLocation();
  const jobsMode = loc.pathname.startsWith("/jobs");
  const summary = useJobsSummary();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); navigate("/search"); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [navigate]);

  return (
    <div className="flex min-h-dvh">
      <Sidebar {...shell} jobsMode={jobsMode} summary={summary} />
      <main className="min-w-0 flex-1">
        <MobileSwitch jobsMode={jobsMode} />
        <div className={`mx-auto px-4 pb-24 pt-6 md:px-8 md:pb-12 md:pt-8 ${jobsMode ? "max-w-6xl" : "max-w-4xl"}`}>
          <Routes>
            <Route path="/" element={jobsHost ? <Navigate to="/jobs" replace /> : <Home projects={shell.projects} />} />
            <Route path="/jobs" element={<Funnel />} />
            <Route path="/jobs/new" element={<NewApplication />} />
            <Route path="/jobs/a/:id" element={<ApplicationPage />} />
            <Route path="/jobs/contacts" element={<Contacts />} />
            <Route path="/jobs/platforms" element={<Platforms />} />
            <Route path="/p/:slug" element={<ProjectPage />} />
            <Route path="/i/:id" element={<ItemPage />} />
            <Route path="/s/:id" element={<SessionPage />} />
            <Route path="/waits" element={<Waits />} />
            <Route path="/sessions" element={<Sessions />} />
            <Route path="/search" element={<SearchPage />} />
          </Routes>
        </div>
      </main>
      <MobileTabs counts={shell.counts} jobsMode={jobsMode} summary={summary} />
    </div>
  );
}
