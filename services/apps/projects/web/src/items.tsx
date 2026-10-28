import { useState } from "react";
import { Link } from "react-router-dom";
import { ExternalLink, MessageSquare } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { api, type Item } from "./api";
import { STATUS, TYPE, isOpen, tone } from "./types";
import { Badge, CopyButton, Ring } from "./ui";

export function Location({ item }: { item: { location: string | null; location_kind: string | null } }) {
  if (!item.location) return null;
  if (item.location_kind === "path")
    return <CopyButton text={item.location} label={item.location.split("/").slice(-2).join("/")} />;
  return (
    <a href={item.location} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-accent hover:underline">
      <ExternalLink size={12} />{item.location.replace(/^https?:\/\//, "").slice(0, 48)}
    </a>
  );
}

/** A round checkbox that ticks with a small spring. */
function Check({ checked, onToggle, label }: { checked: boolean; onToggle: () => void; label: string }) {
  return (
    <button role="checkbox" aria-checked={checked} aria-label={label} onClick={(e) => { e.preventDefault(); onToggle(); }}
      className={`grid size-[18px] shrink-0 place-items-center rounded-full border-[1.5px] transition ${checked ? "border-ok bg-ok" : "border-muted/60 hover:border-accent"}`}>
      <AnimatePresence>
        {checked && (
          <motion.svg key="t" viewBox="0 0 12 12" className="size-2.5" initial={{ scale: 0 }} animate={{ scale: 1 }} exit={{ scale: 0 }}
            transition={{ type: "spring", stiffness: 500, damping: 25 }}>
            <path d="M2.5 6.2 5 8.5 9.5 3.5" fill="none" stroke="white" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
          </motion.svg>
        )}
      </AnimatePresence>
    </button>
  );
}

// The one way an item is shown in a list. Todos and milestones get a checkbox, everything else its type icon.
export function ItemRow({ item, onChange, withProject, hideOwner }: { item: Item; onChange?: () => void; withProject?: boolean; hideOwner?: boolean }) {
  const Icon = TYPE[item.type].icon;
  const checkable = item.type === "todo" || item.type === "milestone";
  const [done, setDone] = useState(item.status === "done");
  const closed = checkable ? done : !isOpen(item.status) && item.status !== "logged";

  async function toggle() {
    const next = !done;
    setDone(next);
    try {
      await api.patchItem(item.id, { status: next ? "done" : "open" });
      setTimeout(() => onChange?.(), 450); // let the tick play before the row moves
    } catch (e) {
      setDone(!next);
      alert(`Не сохранилось: ${e}`);
    }
  }

  return (
    <motion.div layout initial={{ opacity: 0, y: 4 }} animate={{ opacity: 1, y: 0 }}
      className="group flex items-center gap-3 rounded-lg px-2 py-2 text-sm hover:bg-hover">
      {checkable ? <Check checked={done} onToggle={toggle} label={item.title} />
        : <Icon size={16} className="shrink-0 text-muted" aria-label={TYPE[item.type].label} />}
      <Link to={`/i/${item.id}`} className={`min-w-0 flex-1 truncate transition ${closed ? (checkable ? "text-muted line-through" : "text-muted") : ""}`}>
        {item.title}
      </Link>
      {withProject && item.project_title && <span className="hidden max-w-[40%] truncate text-xs text-muted sm:inline">{item.project_title}</span>}
      {item.type === "todo" && item.owner === "user" && !withProject && !hideOwner && <Badge tone="amber">тебе</Badge>}
      {item.progress !== null && <Ring value={item.progress} size={16} />}
      {!checkable && item.status !== "logged" && <Badge tone={tone(item.status)}>{STATUS[item.status] ?? item.status}</Badge>}
      {item.session_count > 0 && (
        <span className="flex shrink-0 items-center gap-0.5 text-xs text-muted" title="чатов"><MessageSquare size={12} />{item.session_count}</span>
      )}
    </motion.div>
  );
}

export const ItemList = ({ items, onChange, empty, withProject, hideOwner }: { items: Item[]; onChange?: () => void; empty?: string; withProject?: boolean; hideOwner?: boolean }) =>
  items.length ? (
    <div className="-mx-2">{items.map((i) => <ItemRow key={i.id} item={i} onChange={onChange} withProject={withProject} hideOwner={hideOwner} />)}</div>
  ) : empty ? <p className="py-2 text-sm text-muted">{empty}</p> : null;
