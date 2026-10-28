import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { AtSign, Linkedin, Mail, Phone, Send, UserPlus, X } from "lucide-react";
import { Card } from "../ui";
import { jobs, type Contact, type ContactIn } from "./api";
import { Editable, Ghost, Label, Primary, inputCls } from "./ui";

const tgLink = (t: string) => `https://t.me/${t.replace(/^@/, "").replace(/^https?:\/\/t\.me\//, "")}`;
// A bare "linkedin.com/in/x" gets https://; any other scheme (javascript:, data:) is forced into a harmless https URL.
const httpLink = (u: string) => (/^https?:\/\//i.test(u) ? u : `https://${u.replace(/^[a-z][\w+.-]*:/i, "")}`);

export const CONTACT_FIELDS: { key: keyof ContactIn; label: string; placeholder: string; type?: string }[] = [
  { key: "role", label: "Роль", placeholder: "Recruiter, HR, CTO" },
  { key: "email", label: "Email", placeholder: "name@company.com", type: "email" },
  { key: "phone", label: "Телефон", placeholder: "+995 …", type: "tel" },
  { key: "telegram", label: "Telegram", placeholder: "@username" },
  { key: "linkedin", label: "LinkedIn", placeholder: "linkedin.com/in/…" },
];

/** Quick links: one tap to write or call. */
export function ContactLinks({ c }: { c: Contact }) {
  const links = [
    c.email && { href: `mailto:${c.email}`, icon: Mail, label: c.email },
    c.phone && { href: `tel:${c.phone.replace(/\s/g, "")}`, icon: Phone, label: c.phone },
    c.telegram && { href: tgLink(c.telegram), icon: Send, label: c.telegram },
    c.linkedin && { href: httpLink(c.linkedin), icon: Linkedin, label: "LinkedIn" },
  ].filter(Boolean) as { href: string; icon: typeof Mail; label: string }[];
  if (!links.length) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {links.map((l) => (
        <a key={l.href} href={l.href} target="_blank" rel="noreferrer"
          className="inline-flex max-w-full items-center gap-1 truncate rounded-lg border border-line px-2 py-1 text-xs transition hover:border-accent hover:text-accent">
          <l.icon size={12} className="shrink-0" /><span className="truncate">{l.label}</span>
        </a>
      ))}
    </div>
  );
}

export function ContactForm({ value, onChange, autoFocus }: { value: ContactIn; onChange: (c: ContactIn) => void; autoFocus?: boolean }) {
  return (
    <div className="grid gap-3 sm:grid-cols-2">
      <Label label="Имя *"><input autoFocus={autoFocus} value={value.name} onChange={(e) => onChange({ ...value, name: e.target.value })} placeholder="Как зовут" className={inputCls} /></Label>
      {CONTACT_FIELDS.map((f) => (
        <Label key={f.key} label={f.label}>
          <input type={f.type ?? "text"} value={(value[f.key] as string) ?? ""} placeholder={f.placeholder}
            onChange={(e) => onChange({ ...value, [f.key]: e.target.value })} className={inputCls} />
        </Label>
      ))}
    </div>
  );
}

/** The contact block on an application: show, edit in place, pick another or add one. */
export function ContactCard({ appId, company, contact, onChange }: { appId: number; company: string; contact: Contact | null; onChange: () => void }) {
  const [mode, setMode] = useState<"view" | "pick" | "new">("view");
  const [all, setAll] = useState<Contact[]>([]);
  const [draft, setDraft] = useState<ContactIn>({ name: "", company });
  const [error, setError] = useState("");

  useEffect(() => { if (mode === "pick") jobs.contacts().then(setAll).catch(() => {}); }, [mode]);

  async function link(id: number | null) {
    try { await jobs.patch(appId, { contact_id: id }); setMode("view"); onChange(); } catch (e) { setError(String(e)); }
  }
  async function create() {
    try { const c = await jobs.createContact({ ...draft, company: draft.company || company }); await link(c.id); setDraft({ name: "", company }); }
    catch (e) { setError(String(e)); }
  }
  const save = (key: keyof ContactIn) => async (v: string) => { if (contact) await jobs.patchContact(contact.id, { [key]: v }).then(onChange); };

  return (
    <Card className="space-y-3">
      <div className="flex items-center justify-between">
        <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Контакт</h3>
        {contact && mode === "view" && <Ghost className="text-xs" title="Отвязать контакт" onClick={() => link(null)}><X size={13} /></Ghost>}
      </div>

      {contact && mode === "view" && (
        <div className="space-y-2">
          <div>
            <Link to={`/jobs/contacts?c=${contact.id}`} className="font-medium hover:text-accent">{contact.name}</Link>
            {(contact.role || contact.company) && <div className="text-xs text-muted">{[contact.role, contact.company].filter(Boolean).join(" · ")}</div>}
          </div>
          <ContactLinks c={contact} />
          <details className="group text-sm">
            <summary className="cursor-pointer list-none text-xs text-muted hover:text-fg">Изменить контакт</summary>
            <dl className="mt-2 space-y-1">
              {CONTACT_FIELDS.map((f) => (
                <div key={f.key} className="grid grid-cols-[5.5rem_1fr] items-center gap-2">
                  <dt className="text-xs text-muted">{f.label}</dt>
                  <dd className="min-w-0"><Editable value={(contact[f.key as keyof Contact] as string) ?? ""} onSave={save(f.key)} placeholder={f.placeholder} type={f.type} /></dd>
                </div>
              ))}
            </dl>
          </details>
        </div>
      )}

      {!contact && mode === "view" && (
        <div className="flex flex-wrap gap-2">
          <Ghost onClick={() => setMode("new")} className="border border-dashed border-line"><UserPlus size={14} />Добавить контакт</Ghost>
          <Ghost onClick={() => setMode("pick")}><AtSign size={14} />Выбрать из сохранённых</Ghost>
        </div>
      )}

      {mode === "pick" && (
        <div className="space-y-2">
          {all.length === 0 ? <p className="text-sm text-muted">Сохранённых контактов нет.</p> : (
            <div className="max-h-56 space-y-0.5 overflow-y-auto">
              {all.map((c) => (
                <button key={c.id} onClick={() => link(c.id)} className="block w-full rounded-lg px-2 py-1.5 text-left text-sm hover:bg-hover">
                  {c.name} <span className="text-xs text-muted">{[c.role, c.company].filter(Boolean).join(" · ")}</span>
                </button>
              ))}
            </div>
          )}
          <div className="flex justify-end gap-2"><Ghost onClick={() => setMode("new")}>Новый</Ghost><Ghost onClick={() => setMode("view")}>Отмена</Ghost></div>
        </div>
      )}

      {mode === "new" && (
        <div className="space-y-3">
          <ContactForm value={draft} onChange={setDraft} autoFocus />
          <div className="flex justify-end gap-2">
            <Ghost onClick={() => setMode("view")}>Отмена</Ghost>
            <Primary onClick={create} disabled={!draft.name.trim()}>Сохранить контакт</Primary>
          </div>
        </div>
      )}
      {error && <p className="text-xs text-amber-fg">{error}</p>}
    </Card>
  );
}
