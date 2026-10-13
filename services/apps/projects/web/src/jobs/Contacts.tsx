import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Search, Trash2, UserPlus } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Card, Empty, Skeleton } from "../ui";
import { jobs, type Application, type Contact, type ContactIn } from "./api";
import { CONTACT_FIELDS, ContactForm, ContactLinks } from "./Contact";
import { AppRow } from "./Funnel";
import { Editable, Ghost, Primary, inputCls } from "./ui";

const initials = (n: string) => n.split(/\s+/).map((w) => w[0]).slice(0, 2).join("").toUpperCase();

function Expanded({ c, onChange }: { c: Contact; onChange: () => void }) {
  const [apps, setApps] = useState<Application[] | null>(null);
  useEffect(() => { jobs.contact(c.id).then((d) => setApps(d.applications)).catch(() => setApps([])); }, [c.id]);
  const save = (key: keyof ContactIn) => (v: string) => jobs.patchContact(c.id, { [key]: v }).then(onChange);
  return (
    <motion.div initial={{ height: 0, opacity: 0 }} animate={{ height: "auto", opacity: 1 }} exit={{ height: 0, opacity: 0 }} className="overflow-hidden">
      <div className="grid gap-4 border-t border-line px-3 pb-3 pt-3 md:grid-cols-2">
        <dl className="space-y-1">
          {([{ key: "name", label: "Имя", placeholder: "" }, { key: "company", label: "Компания", placeholder: "компания" }, ...CONTACT_FIELDS] as typeof CONTACT_FIELDS).map((f) => (
            <div key={f.key} className="grid grid-cols-[5.5rem_1fr] items-center gap-2">
              <dt className="text-xs text-muted">{f.label}</dt>
              <dd className="min-w-0"><Editable value={(c[f.key as keyof Contact] as string) ?? ""} onSave={save(f.key)} placeholder={f.placeholder || "добавить"} type={f.type} /></dd>
            </div>
          ))}
          <div className="grid grid-cols-[5.5rem_1fr] gap-2">
            <dt className="pt-0.5 text-xs text-muted">Заметки</dt>
            <dd><Editable value={c.notes} onSave={save("notes")} multiline placeholder="как познакомились, о чём договорились" /></dd>
          </div>
        </dl>
        <div className="space-y-1">
          <div className="text-xs font-medium text-muted">Отклики</div>
          {apps === null ? <Skeleton rows={1} /> : apps.length === 0 ? <p className="text-sm text-muted">Пока ни одного.</p>
            : <div className="-mx-3">{apps.map((a) => <AppRow key={a.id} a={a} />)}</div>}
          <Ghost className="mt-2 text-xs" onClick={() => confirm(`Удалить контакт ${c.name}? Отклики останутся.`) && jobs.removeContact(c.id).then(onChange)}>
            <Trash2 size={13} />Удалить контакт
          </Ghost>
        </div>
      </div>
    </motion.div>
  );
}

export default function Contacts() {
  const [params, setParams] = useSearchParams();
  const open = Number(params.get("c")) || null;
  const [list, setList] = useState<Contact[] | null>(null);
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState(false);
  const [draft, setDraft] = useState<ContactIn>({ name: "" });

  const load = useCallback(() => jobs.contacts().then(setList).catch(() => setList([])), []);
  useEffect(() => { load(); }, [load]);

  const toggle = (id: number) => setParams(open === id ? {} : { c: String(id) }, { replace: true });
  const needle = q.trim().toLowerCase();
  const shown = (list ?? []).filter((c) => !needle || [c.name, c.company, c.role, c.email, c.telegram].some((v) => v.toLowerCase().includes(needle)));

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Контакты</h1>
          <p className="mt-1 text-sm text-muted">Рекрутеры и HR, с которыми переписывался</p>
        </div>
        <Primary onClick={() => setAdding(true)}><UserPlus size={16} />Добавить</Primary>
      </header>

      {adding && (
        <Card className="space-y-3">
          <ContactForm value={draft} onChange={setDraft} autoFocus />
          <input value={draft.company ?? ""} onChange={(e) => setDraft({ ...draft, company: e.target.value })} placeholder="Компания" className={inputCls} />
          <div className="flex justify-end gap-2">
            <Ghost onClick={() => setAdding(false)}>Отмена</Ghost>
            <Primary disabled={!draft.name.trim()} onClick={async () => { await jobs.createContact(draft); setDraft({ name: "" }); setAdding(false); load(); }}>Сохранить</Primary>
          </div>
        </Card>
      )}

      <div className="relative">
        <Search size={15} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Имя, компания, email…" className={`${inputCls} pl-9`} />
      </div>

      {list === null ? <Skeleton /> : shown.length === 0 ? (
        <Card><Empty>{list.length ? "Никого не нашлось." : "Контактов пока нет. Они появятся, когда добавишь отклик «HR написала сама»."}</Empty></Card>
      ) : (
        <Card className="divide-y divide-line p-0">
          {shown.map((c) => (
            <div key={c.id}>
              <button onClick={() => toggle(c.id)} className="flex w-full items-center gap-3 px-3 py-3 text-left transition hover:bg-hover">
                <span className="grid size-9 shrink-0 place-items-center rounded-full bg-[var(--s-inbound)]/15 text-xs font-semibold text-[var(--s-inbound)]">{initials(c.name)}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium">{c.name}</span>
                  <span className="block truncate text-xs text-muted">{[c.role, c.company].filter(Boolean).join(" · ") || "—"}</span>
                </span>
                <span className="hidden sm:block" onClick={(e) => e.stopPropagation()}><ContactLinks c={c} /></span>
                {!!c.applications_count && <span className="shrink-0 text-xs text-muted">{c.applications_count} откл.</span>}
              </button>
              <AnimatePresence>{open === c.id && <Expanded c={c} onChange={load} />}</AnimatePresence>
            </div>
          ))}
        </Card>
      )}
    </div>
  );
}
