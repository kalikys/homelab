import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, BellRing, ExternalLink, Inbox, Trash2 } from "lucide-react";
import { day } from "../format";
import { Card, Empty } from "../ui";
import { jobs, type ApplicationDetail, type ApplicationIn, type Platform } from "./api";
import { ContactCard } from "./Contact";
import Files from "./Files";
import Letters from "./Letters";
import { FORMATS, NEXT, STATUS, dueLabel, daysUntil, formatLabel, safeHref, type Status } from "./model";
import { Editable, Fit, Flash, Ghost, Primary, StatusMenu, useFlash } from "./ui";

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[6.5rem_1fr] items-center gap-2 py-0.5">
      <dt className="text-xs text-muted">{label}</dt><dd className="min-w-0">{children}</dd>
    </div>
  );
}

const selectCls = "-mx-1.5 w-[calc(100%+0.75rem)] cursor-pointer rounded-lg bg-transparent px-1 py-0.5 text-sm outline-none transition hover:bg-hover focus:bg-hover";

export default function ApplicationPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [a, setA] = useState<ApplicationDetail | null>(null);
  const [platforms, setPlatforms] = useState<Platform[]>([]);
  const [error, setError] = useState("");
  const [flash, setFlash] = useFlash();

  const load = useCallback(() => jobs.get(Number(id)).then(setA).catch((e) => setError(String(e))), [id]);
  useEffect(() => { load(); jobs.platforms().then(setPlatforms).catch(() => {}); }, [load]);

  if (error) return <Card className="text-sm text-amber-fg">{error}</Card>;
  if (!a) return <Empty>Загрузка…</Empty>;

  const patch = async (body: Partial<ApplicationIn>, msg = "Сохранено") => {
    try { await jobs.patch(a.id, body); setFlash(msg); await load(); } catch (e) { setFlash(`Не сохранилось: ${e}`); }
  };
  const field = (key: keyof ApplicationIn) => (v: string) => patch({ [key]: v });
  const next = NEXT[a.status];
  const overdue = (daysUntil(a.next_action_at) ?? 1) <= 0;

  return (
    <div className="space-y-6">
      <Link to="/jobs" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><ArrowLeft size={15} />Отклики</Link>

      <header className="space-y-3">
        <div className="space-y-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-muted">
            {a.origin === "inbound" && <span className="inline-flex items-center gap-1 text-[var(--s-inbound)]"><Inbox size={14} />HR написала сама</span>}
            {a.platform_name && <span>{a.platform_name}</span>}
            {a.applied_at && <span>· {a.origin === "inbound" ? "написали" : "отправил"} {day(a.applied_at)}</span>}
          </div>
          <h1><Editable value={a.company} onSave={field("company")} className="text-2xl font-semibold tracking-tight" /></h1>
          <Editable value={a.title} onSave={field("title")} className="text-lg text-muted" />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <StatusMenu value={a.status} onChange={(s: Status) => patch({ status: s }, `Статус: ${STATUS[s].label.toLowerCase()}`)} />
          {next && (
            <Primary onClick={() => patch({ status: next }, `Статус: ${STATUS[next].label.toLowerCase()}`)} className="py-1.5">
              {a.origin === "inbound" && next === "replied" ? "Я ответил" : STATUS[next].label}<ArrowRight size={15} />
            </Primary>
          )}
          {safeHref(a.url) && (
            <a href={safeHref(a.url)} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-sm text-accent hover:bg-hover">
              <ExternalLink size={14} />Вакансия
            </a>
          )}
        </div>

        {!["offer", "rejected", "declined"].includes(a.status) && (
          <div className={`flex flex-wrap items-center gap-x-3 gap-y-2 rounded-xl px-3 py-2 text-sm ${overdue && a.next_action_at ? "bg-amber-bg text-amber-fg" : "bg-hover/60"}`}>
            <BellRing size={15} className="shrink-0" />
            <div className="min-w-40 flex-1"><Editable value={a.next_action} onSave={field("next_action")} placeholder="Следующий шаг: написать follow-up, подготовиться к созвону…" /></div>
            <label className="flex items-center gap-2 text-xs">
              {a.next_action_at ? dueLabel(a.next_action_at) : "без даты"}
              <input type="date" value={a.next_action_at ?? ""} onChange={(e) => patch({ next_action_at: e.target.value || null }, "Дата напоминания сохранена")}
                className="rounded-lg border border-line bg-card px-2 py-1 text-xs text-fg" aria-label="Дата напоминания" />
            </label>
          </div>
        )}
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="min-w-0 space-y-8">
          <Letters app={a} onChange={load} />

          <section className="space-y-2">
            <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Вакансия</h2>
            <Card>
              <Editable value={a.vacancy_text} onSave={field("vacancy_text")} multiline
                placeholder="Вставь сюда описание вакансии: по нему Claude пишет письмо. ⌘Enter, чтобы сохранить." />
            </Card>
          </section>
        </div>

        <aside className="space-y-4">
          <Card>
            <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">Детали</h3>
            <dl>
              <Row label="Ссылка"><Editable value={a.url} onSave={field("url")} placeholder="указать" display={a.url.replace(/^https?:\/\/(www\.)?/, "")} /></Row>
              <Row label="Платформа">
                <select value={a.platform ?? ""} onChange={(e) => patch({ platform: e.target.value || null })} className={selectCls}>
                  <option value="">не указана</option>
                  {platforms.map((p) => <option key={p.slug} value={p.slug}>{p.name}</option>)}
                </select>
              </Row>
              <Row label="Локация"><Editable value={a.location} onSave={field("location")} placeholder="указать" /></Row>
              <Row label="Формат">
                <select value={a.work_format} onChange={(e) => patch({ work_format: e.target.value })} className={selectCls}>
                  <option value="">не указан</option>
                  {FORMATS.map((f) => <option key={f.id} value={f.id}>{f.label}</option>)}
                  {a.work_format && !FORMATS.some((f) => f.id === a.work_format) && <option value={a.work_format}>{formatLabel(a.work_format)}</option>}
                </select>
              </Row>
              <Row label="Зарплата"><Editable value={a.salary} onSave={field("salary")} placeholder="указать" /></Row>
              <Row label="Подходит"><Fit value={a.fit} onChange={(v) => patch({ fit: v })} /></Row>
              <Row label="Дата отклика">
                <input type="date" value={a.applied_at ?? ""} onChange={(e) => patch({ applied_at: e.target.value || null })}
                  className="-mx-1 rounded-lg bg-transparent px-1 py-0.5 text-sm hover:bg-hover" />
              </Row>
            </dl>
          </Card>

          <ContactCard appId={a.id} company={a.company} contact={a.contact} onChange={load} />

          <Card className="space-y-2">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Файлы</h3>
            <Files appId={a.id} files={a.attachments} onChange={load} />
          </Card>

          <Card className="space-y-1">
            <h3 className="text-xs font-semibold uppercase tracking-wide text-muted">Заметки</h3>
            <Editable value={a.notes} onSave={field("notes")} multiline placeholder="Что важно помнить: вопросы, впечатления, условия" />
          </Card>

          <details className="group">
            <summary className="cursor-pointer list-none text-xs font-semibold uppercase tracking-wide text-muted hover:text-fg">
              История · {a.events.length}
            </summary>
            <ol className="mt-2 space-y-1.5 border-l border-line pl-3 text-sm">
              {a.events.map((e) => (
                <li key={e.id}><span className="mr-2 text-xs text-muted">{day(e.at)}</span>{e.text}</li>
              ))}
            </ol>
          </details>

          <Ghost className="text-xs" onClick={async () => {
            if (!confirm(`Удалить отклик в ${a.company} вместе с письмами и файлами?`)) return;
            await jobs.remove(a.id); navigate("/jobs");
          }}><Trash2 size={13} />Удалить отклик</Ghost>
        </aside>
      </div>
      <Flash msg={flash} />
    </div>
  );
}
