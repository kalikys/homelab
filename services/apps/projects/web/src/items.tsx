import { Link } from "react-router-dom";
import { ExternalLink, MessageSquare } from "lucide-react";
import { api, type Item } from "./api";
import { STATUS, TYPE, isOpen, tone } from "./types";
import { Badge, CopyButton } from "./ui";

export function Location({ item }: { item: { location: string | null; location_kind: string | null } }) {
  if (!item.location) return null;
  if (item.location_kind === "path")
    return <CopyButton text={item.location} label={item.location.split("/").slice(-2).join("/")} />;
  return (
    <a href={item.location} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-accent">
      <ExternalLink size={12} />{item.location.replace(/^https?:\/\//, "").slice(0, 48)}
    </a>
  );
}

// The one way an item is shown in a list. Todos and milestones get a checkbox, everything else its type icon.
export function ItemRow({ item, onChange, withProject }: { item: Item; onChange?: () => void; withProject?: boolean }) {
  const Icon = TYPE[item.type].icon;
  const checkable = item.type === "todo" || item.type === "milestone";
  const closed = !isOpen(item.status) && item.status !== "logged";
  return (
    <div className="flex items-center gap-2 py-1.5 text-sm">
      {checkable ? (
        <input type="checkbox" className="shrink-0" checked={item.status === "done"} aria-label={item.title}
          onChange={(e) => api.patchItem(item.id, { status: e.target.checked ? "done" : "open" }).then(onChange)} />
      ) : (
        <Icon size={15} className="shrink-0 text-muted" aria-label={TYPE[item.type].label} />
      )}
      <Link to={`/i/${item.id}`} className={`min-w-0 flex-1 truncate hover:text-accent ${closed ? "text-muted line-through" : ""}`}>
        {item.title}
        {withProject && item.project_title && <span className="ml-2 text-xs text-muted">{item.project_title}</span>}
      </Link>
      {item.type === "todo" && item.owner === "user" && !withProject && <Badge tone="amber">тебе</Badge>}
      {item.progress !== null && <span className="text-xs tabular-nums text-muted">{item.progress}%</span>}
      {!checkable && item.status !== "logged" && <Badge tone={tone(item.status)}>{STATUS[item.status] ?? item.status}</Badge>}
      {item.session_count > 0 && (
        <span className="flex shrink-0 items-center gap-0.5 text-xs text-muted" title="чатов"><MessageSquare size={12} />{item.session_count}</span>
      )}
    </div>
  );
}

export const ItemList = ({ items, onChange, empty, withProject }: { items: Item[]; onChange?: () => void; empty?: string; withProject?: boolean }) =>
  items.length ? (
    <div className="divide-y divide-line">{items.map((i) => <ItemRow key={i.id} item={i} onChange={onChange} withProject={withProject} />)}</div>
  ) : empty ? <p className="py-2 text-sm text-muted">{empty}</p> : null;
