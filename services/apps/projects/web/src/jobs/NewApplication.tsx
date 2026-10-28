import { useEffect, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { ArrowLeft, Inbox, Send, Sparkles } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { Card } from "../ui";
import { jobs, type ApplicationIn, type Contact, type ContactIn, type Platform } from "./api";
import { ContactForm } from "./Contact";
import { DropZone, FileRow } from "./Files";
import { FORMATS, LANGS, STATUS, type Status } from "./model";
import { AutoTextarea, Label, Primary, inputCls } from "./ui";

type Mode = "outbound" | "inbound";

function Tile({ on, onClick, icon: Icon, title, text }: { on: boolean; onClick: () => void; icon: typeof Send; title: string; text: string }) {
  return (
    <button onClick={onClick}
      className={`flex flex-1 items-start gap-3 rounded-2xl border p-4 text-left transition ${on ? "border-accent bg-accent/5 ring-4 ring-accent/10" : "border-line bg-card hover:border-accent/50"}`}>
      <span className={`grid size-9 shrink-0 place-items-center rounded-xl ${on ? "bg-accent text-white" : "bg-hover text-muted"}`}><Icon size={18} /></span>
      <span><span className="block font-medium">{title}</span><span className="block text-sm text-muted">{text}</span></span>
    </button>
  );
}

function Segmented<T extends string>({ value, options, onChange }: { value: T; options: { id: T; label: string }[]; onChange: (v: T) => void }) {
  return (
    <div className="inline-flex flex-wrap rounded-xl border border-line bg-hover/50 p-0.5">
      {options.map((o) => (
        <button key={o.id} type="button" onClick={() => onChange(o.id)}
          className={`rounded-lg px-3 py-1.5 text-sm transition ${value === o.id ? "bg-card font-medium shadow-sm" : "text-muted hover:text-fg"}`}>{o.label}</button>
      ))}
    </div>
  );
}

const STATUS_OPTIONS: Record<Mode, Status[]> = { outbound: ["sent", "draft"], inbound: ["inbound", "replied", "interview"] };

export default function NewApplication() {
  const navigate = useNavigate();
  const [params] = useSearchParams();
  const [mode, setMode] = useState<Mode | null>((params.get("mode") as Mode) || null);
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [contacts, setContacts] = useState<Contact[]>([]);
  const [form, setForm] = useState<ApplicationIn>({ company: "", title: "", url: "", platform: "", location: "", work_format: "", salary: "", vacancy_text: "", notes: "" });
  const [status, setStatus] = useState<Status>("sent");
  const [contactId, setContactId] = useState<number | "new">("new");
  const [contact, setContact] = useState<ContactIn>({ name: "" });
  const [customPlatform, setCustomPlatform] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [generate, setGenerate] = useState(false);
  const [lang, setLang] = useState("en");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    jobs.platforms().then(setPlatforms).catch(() => {});
    jobs.contacts().then(setContacts).catch(() => {});
  }, []);
  useEffect(() => { if (mode) setStatus(STATUS_OPTIONS[mode][0]); }, [mode]);
  useEffect(() => { setGenerate(status === "draft"); }, [status]);

  const set = (k: keyof ApplicationIn) => (e: { target: { value: string } }) => setForm({ ...form, [k]: e.target.value });
  const contactOk = mode !== "inbound" || contactId !== "new" || contact.name.trim();
  const ready = form.company.trim() && form.title.trim() && contactOk;

  async function submit() {
    if (!mode || !ready) return;
    setBusy(true); setError("");
    try {
      const platform = form.platform === "__other" ? customPlatform.trim() : form.platform;
      const body: ApplicationIn = { ...form, platform: platform || null, origin: mode, status };
      if (contactId !== "new") body.contact_id = contactId;
      else if (contact.name.trim()) body.contact = { ...contact, company: contact.company || form.company };
      if (generate) body.generate = { lang, wish: "" };
      const a = await jobs.create(body);
      for (const f of files) await jobs.upload(a.id, f).catch(() => {});
      navigate(`/jobs/a/${a.id}`);
    } catch (e) { setError(String(e)); setBusy(false); }
  }

  const contactBlock = (
    <section className="space-y-3">
      <h2 className="text-sm font-semibold">{mode === "inbound" ? "Кто написал" : "Контакт (если есть)"}</h2>
      {contacts.length > 0 && (
        <select value={contactId} onChange={(e) => setContactId(e.target.value === "new" ? "new" : Number(e.target.value))} className={inputCls}>
          <option value="new">Новый контакт</option>
          {contacts.map((c) => <option key={c.id} value={c.id}>{c.name}{c.company ? ` · ${c.company}` : ""}</option>)}
        </select>
      )}
      {contactId === "new" && <ContactForm value={contact} onChange={setContact} autoFocus={mode === "inbound"} />}
    </section>
  );

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <Link to="/jobs" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><ArrowLeft size={15} />Отклики</Link>
      <h1 className="text-2xl font-semibold tracking-tight">Новый отклик</h1>

      <div className="flex flex-col gap-3 sm:flex-row">
        <Tile on={mode === "outbound"} onClick={() => setMode("outbound")} icon={Send} title="Я откликаюсь" text="Нашёл вакансию: отправил или собираюсь" />
        <Tile on={mode === "inbound"} onClick={() => setMode("inbound")} icon={Inbox} title="HR написала сама" text="Сохраню контакт, вакансию и что ответил" />
      </div>

      <AnimatePresence mode="wait">
        {mode && (
          <motion.div key={mode} initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0 }}>
            <Card className="space-y-7 p-5">
              {mode === "inbound" && contactBlock}

              <section className="space-y-3">
                <h2 className="text-sm font-semibold">Вакансия</h2>
                <div className="grid gap-3 sm:grid-cols-2">
                  <Label label="Компания *"><input autoFocus={mode === "outbound"} value={form.company} onChange={set("company")} placeholder="Например, Deutsche Telekom" className={inputCls} /></Label>
                  <Label label="Должность *"><input value={form.title} onChange={set("title")} placeholder="Например, DevOps Engineer" className={inputCls} /></Label>
                  <Label label="Ссылка" className="sm:col-span-2"><input value={form.url} onChange={set("url")} placeholder="https://…" className={inputCls} /></Label>
                  <Label label={mode === "inbound" ? "Где написали" : "Платформа"}>
                    <select value={form.platform ?? ""} onChange={set("platform")} className={inputCls}>
                      <option value="">не указана</option>
                      {platforms.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
                      <option value="__other">Другая…</option>
                    </select>
                  </Label>
                  {form.platform === "__other"
                    ? <Label label="Название платформы"><input value={customPlatform} onChange={(e) => setCustomPlatform(e.target.value)} placeholder="Djinni" className={inputCls} /></Label>
                    : <Label label="Формат">
                        <select value={form.work_format} onChange={set("work_format")} className={inputCls}>
                          <option value="">не указан</option>
                          {FORMATS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
                        </select>
                      </Label>}
                  <Label label="Локация"><input value={form.location} onChange={set("location")} placeholder="Košice / remote" className={inputCls} /></Label>
                  <Label label="Зарплата"><input value={form.salary} onChange={set("salary")} placeholder="€3500 gross" className={inputCls} /></Label>
                </div>
                <Label label="Текст вакансии" hint="Нужен, чтобы письмо было про эту вакансию, а не общим.">
                  <AutoTextarea value={form.vacancy_text} onChange={set("vacancy_text")} placeholder="Вставь описание целиком" className="min-h-24" />
                </Label>
                <div className="space-y-1.5">
                  {files.map((f, i) => <FileRow key={i} f={{ name: f.name, size: f.size, mime: f.type }} onRemove={() => setFiles(files.filter((_, j) => j !== i))} />)}
                  <DropZone onFiles={(l) => setFiles([...files, ...l])} compact />
                </div>
              </section>

              {mode === "outbound" && contactBlock}

              <section className="space-y-3">
                <h2 className="text-sm font-semibold">Статус</h2>
                <Segmented value={status} onChange={setStatus}
                  options={STATUS_OPTIONS[mode].map((s) => ({ id: s, label: s === "replied" && mode === "inbound" ? "Я ответил" : STATUS[s].label }))} />
                <label className="flex flex-wrap items-center gap-2 text-sm">
                  <input type="checkbox" checked={generate} onChange={(e) => setGenerate(e.target.checked)} />
                  <Sparkles size={14} className="text-accent" />Сразу написать сопроводительное
                  {generate && (
                    <select value={lang} onChange={(e) => setLang(e.target.value)} className="rounded-lg border border-line bg-card px-2 py-0.5 text-sm">
                      {LANGS.map((l) => <option key={l.id} value={l.id}>{l.label}</option>)}
                    </select>
                  )}
                </label>
                <Label label="Заметка"><input value={form.notes} onChange={set("notes")} placeholder="Например: просили ответить до пятницы" className={inputCls} /></Label>
              </section>

              {error && <p className="text-sm text-amber-fg">{error}</p>}
              <div className="flex items-center justify-end gap-3">
                {!ready && <span className="text-xs text-muted">{!contactOk ? "Укажи, кто написал" : "Нужны компания и должность"}</span>}
                <Primary onClick={submit} disabled={!ready || busy} className="px-5">{busy ? "Сохраняю…" : "Сохранить отклик"}</Primary>
              </div>
            </Card>
          </motion.div>
        )}
      </AnimatePresence>
    </div>
  );
}
