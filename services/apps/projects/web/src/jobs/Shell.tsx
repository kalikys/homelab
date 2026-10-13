import { useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Building2, Inbox, LayoutList, Plus, Users } from "lucide-react";
import { jobs, type Summary } from "./api";

export function useJobsSummary() {
  const [s, setS] = useState<Summary | null>(null);
  const loc = useLocation();
  useEffect(() => { jobs.summary().then(setS).catch(() => {}); }, [loc.pathname]);
  return s;
}

const navItem = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition ${isActive ? "bg-hover font-medium text-fg" : "text-muted hover:bg-hover hover:text-fg"}`;

export function JobsNav({ summary }: { summary: Summary | null }) {
  const c = summary?.counts;
  const open = c ? c.draft + c.inbound + c.sent + c.replied + c.interview + c.offer : 0;
  return (
    <>
      <NavLink to="/jobs/new"
        className="flex items-center justify-center gap-1.5 rounded-xl bg-accent px-3 py-2 text-sm font-medium text-white shadow-sm transition hover:brightness-110 active:scale-[.98]">
        <Plus size={16} />Новый отклик
      </NavLink>
      <nav className="space-y-0.5">
        <NavLink to="/jobs" end className={navItem}><LayoutList size={16} />Отклики
          {open > 0 && <span className="ml-auto text-xs tabular-nums text-muted">{open}</span>}
        </NavLink>
        <NavLink to="/jobs/contacts" className={navItem}><Users size={16} />Контакты</NavLink>
        <NavLink to="/jobs/platforms" className={navItem}><Building2 size={16} />Платформы</NavLink>
      </nav>
      {summary && summary.due.length > 0 && (
        <NavLink to="/jobs" className="rounded-xl bg-amber-bg px-3 py-2.5 text-xs text-amber-fg">
          <Inbox size={13} className="mr-1 inline" />{summary.due.length} пора напомнить
        </NavLink>
      )}
    </>
  );
}

export function JobsTabs({ summary }: { summary: Summary | null }) {
  const tab = ({ isActive }: { isActive: boolean }) =>
    `relative flex flex-1 flex-col items-center gap-0.5 py-2 text-[11px] ${isActive ? "text-accent" : "text-muted"}`;
  return (
    <>
      <NavLink to="/jobs" end className={tab}><LayoutList size={20} />Отклики
        {summary && summary.due.length > 0 && <span className="absolute right-[26%] top-1 rounded-full bg-amber-fg px-1 text-[9px] font-semibold text-bg">{summary.due.length}</span>}
      </NavLink>
      <NavLink to="/jobs/new" className={tab}>
        <span className="-mt-0.5 grid size-7 place-items-center rounded-full bg-accent text-white"><Plus size={18} /></span>Новый
      </NavLink>
      <NavLink to="/jobs/contacts" className={tab}><Users size={20} />Контакты</NavLink>
      <NavLink to="/jobs/platforms" className={tab}><Building2 size={20} />Платформы</NavLink>
    </>
  );
}
