import { useCallback, useEffect, useState, type ReactNode } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { ArrowLeft, ExternalLink, GitPullRequest, Plus, Search, Trash2 } from "lucide-react";
import { day } from "../format";
import { Card, Empty, Skeleton } from "../ui";
import { safeHref } from "../jobs/model";
import { Editable, Flash, Ghost, Primary, inputCls, useFlash } from "../jobs/ui";
import { OUT_ORDER, OUT_STATE, outreach, type OutState, type OutSummary, type StepStatus, type Target, type TargetDetail, type TargetIn } from "./api";
import LiveFeed, { LogBox, StepChip, StepStrip } from "./Live";

const REMOTE: Record<Target["remote"], string> = { yes: "удалёнка", no: "без удалёнки", unknown: "удалёнка ?" };

export const StateChip = ({ s, n, active, onClick }: { s: OutState; n?: number; active?: boolean; onClick?: () => void }) => (
  <button type="button" onClick={onClick} aria-pressed={active}
    className={`inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs transition ${active ? "border-accent bg-accent/10 font-medium" : "border-line hover:bg-hover"}`}>
    <span className="inline-block size-[7px] rounded-full" style={{ background: OUT_STATE[s].color }} />
    {OUT_STATE[s].label}{n !== undefined && <span className="tabular-nums text-muted">{n}</span>}
  </button>
);

function Row({ t }: { t: Target }) {
  const pr = safeHref(t.pr_url);
  return (
    <Link to={`/jobs/outreach/${t.id}`} className="grid grid-cols-[1fr_auto] items-center gap-3 rounded-xl px-3 py-2.5 transition hover:bg-hover md:grid-cols-[14rem_1fr_7rem_6rem]">
      <div className="min-w-0">
        <div className="truncate font-medium">{t.company}</div>
        <div className="truncate text-xs text-muted">{REMOTE[t.remote]}{t.repos ? ` · ${t.repos.split("\n")[0]}` : ""}</div>
        <div className="mt-1 md:hidden"><StepStrip t={t} /></div>
      </div>
      <div className="hidden min-w-0 md:block">
        {t.last_step ? (
          <div className="flex min-w-0 items-center gap-2">
            <StepChip step={t.last_step.step} status={t.last_step.status} />
            <span className="min-w-0 truncate text-sm text-muted">{t.last_step.text}</span>
          </div>
        ) : <div className="truncate text-sm text-muted">{t.next_step || t.finding || "—"}</div>}
        <div className="mt-1"><StepStrip t={t} /></div>
      </div>
      <div className="hidden md:block"><StateChip s={t.pr_state} /></div>
      <div className="flex items-center justify-end gap-2 text-xs text-muted">
        {pr && <GitPullRequest size={13} className="text-accent" />}
        <span className="md:hidden"><StateChip s={t.pr_state} /></span>
        <span className="hidden md:inline">{t.contacted_at ? `письмо ${day(t.contacted_at)}` : day(t.updated_at)}</span>
      </div>
    </Link>
  );
}

function AddForm({ onDone }: { onDone: (t: Target) => void }) {
  const [company, setCompany] = useState("");
  const [repo, setRepo] = useState("");
  const [busy, setBusy] = useState(false);
  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!company.trim()) return;
    setBusy(true);
    try { onDone(await outreach.create({ company: company.trim(), repos: repo.trim() })); } finally { setBusy(false); }
  }
  return (
    <form onSubmit={submit} className="flex flex-col gap-2 md:flex-row">
      <input className={inputCls} placeholder="Компания" value={company} onChange={(e) => setCompany(e.target.value)} autoFocus />
      <input className={inputCls} placeholder="owner/repo (необязательно)" value={repo} onChange={(e) => setRepo(e.target.value)} />
      <Primary type="submit" disabled={busy || !company.trim()}>Добавить</Primary>
    </form>
  );
}

/** The campaign list: one row per company, filtered by PR state. */
export default function Outreach() {
  const [params, setParams] = useSearchParams();
  const state = (params.get("s") as OutState | null) ?? undefined;
  const [q, setQ] = useState("");
  const [list, setList] = useState<Target[] | null>(null);
  const [summary, setSummary] = useState<OutSummary | null>(null);
  const [adding, setAdding] = useState(false);
  const navigate = useNavigate();
  const load = useCallback(() => {
    outreach.list(state, q.trim() || undefined).then(setList).catch(() => setList([]));
    outreach.summary().then(setSummary).catch(() => {});
  }, [state, q]);
  useEffect(() => { load(); }, [load]);
  const setState = (s?: OutState) => setParams(s && s !== state ? { s } : {});

  return (
    <div className="space-y-5">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Fix-PR кампания</h1>
          <p className="text-sm text-muted">
            Компании, которым чиним публичные репозитории. Письмо руководителю — только после merge.
            {summary && <> Писали: {summary.contacted}, ответили: {summary.replied}.</>}
          </p>
        </div>
        <Primary onClick={() => setAdding(!adding)}><Plus size={16} />Компания</Primary>
      </header>
      {adding && <Card><AddForm onDone={(t) => navigate(`/jobs/outreach/${t.id}`)} /></Card>}
      <div className="flex flex-wrap items-center gap-2">
        {OUT_ORDER.map((s) => <StateChip key={s} s={s} n={summary?.counts[s]} active={state === s} onClick={() => setState(s)} />)}
        <label className="relative ml-auto w-full md:w-60">
          <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted" />
          <input className={`${inputCls} pl-8`} placeholder="Поиск" value={q} onChange={(e) => setQ(e.target.value)} />
        </label>
      </div>
      <div className="grid gap-5 xl:grid-cols-[1fr_22rem]">
        <Card className="p-1">
          {list === null ? <Skeleton rows={4} /> : list.length === 0
            ? <Empty>{state || q ? "Ничего не нашлось." : "Пока пусто. Добавь компанию или: pj outreach add <компания>"}</Empty>
            : list.map((t) => <Row key={t.id} t={t} />)}
        </Card>
        <div className="xl:sticky xl:top-4 xl:self-start"><LiveFeed onActivity={load} /></div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[7.5rem_1fr] items-start gap-2 py-0.5">
      <dt className="pt-0.5 text-xs text-muted">{label}</dt><dd className="min-w-0">{children}</dd>
    </div>
  );
}

const selectCls = "-mx-1.5 cursor-pointer rounded-lg bg-transparent px-1 py-0.5 text-sm outline-none transition hover:bg-hover focus:bg-hover";

/** One company: fields edit in place, state changes and notes go to the history. */
export function TargetPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const [t, setT] = useState<TargetDetail | null>(null);
  const [error, setError] = useState("");
  const [note, setNote] = useState("");
  const [flash, setFlash] = useFlash();
  const load = useCallback(() => { outreach.get(Number(id)).then(setT).catch((e) => setError(String(e.message ?? e))); }, [id]);
  useEffect(() => { load(); }, [load]);
  // Live timeline: refresh every 4 s, but never while a field is being edited.
  useEffect(() => {
    const timer = setInterval(() => {
      const el = document.activeElement;
      const editing = el && ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName);
      if (!document.hidden && !editing) load();
    }, 4000);
    return () => clearInterval(timer);
  }, [load]);
  if (error) return <Empty>{error}</Empty>;
  if (!t) return <Skeleton rows={6} />;

  const save = (body: TargetIn) => outreach.patch(t.id, body).then(() => { setFlash("Сохранено"); load(); })
    .catch((e) => setFlash(String(e.message ?? e)));
  const text = (key: keyof TargetIn, label: string, placeholder?: string, multiline?: boolean) => (
    <Field label={label}><Editable value={(t[key as keyof Target] as string) ?? ""} onSave={(v) => save({ [key]: v })}
      placeholder={placeholder} multiline={multiline} /></Field>
  );
  const link = (key: "url" | "careers_url" | "pr_url", label: string) => {
    const href = safeHref(t[key]);
    return (
      <Field label={label}>
        <div className="flex items-center gap-1.5">
          <div className="min-w-0 flex-1"><Editable value={t[key]} onSave={(v) => save({ [key]: v })} placeholder="https://…" /></div>
          {href && <a href={href} target="_blank" rel="noreferrer" className="text-muted hover:text-accent"><ExternalLink size={13} /></a>}
        </div>
      </Field>
    );
  };

  return (
    <div className="space-y-5">
      <Link to="/jobs/outreach" className="inline-flex items-center gap-1 text-sm text-muted hover:text-fg"><ArrowLeft size={14} />Кампания</Link>
      <header className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">{t.company}</h1>
          <div className="mt-1"><StepStrip t={t} /></div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {OUT_ORDER.map((s) => <StateChip key={s} s={s} active={t.pr_state === s} onClick={() => s !== t.pr_state && save({ pr_state: s })} />)}
        </div>
      </header>
      <div className="grid gap-5 md:grid-cols-[1fr_18rem]">
        <Card>
          <dl className="space-y-1">
            {text("company", "Компания")}
            {link("url", "Сайт")}
            {link("careers_url", "Вакансии")}
            <Field label="Удалёнка">
              <select className={selectCls} value={t.remote} onChange={(e) => save({ remote: e.target.value as Target["remote"] })}>
                <option value="yes">да</option><option value="no">нет</option><option value="unknown">неизвестно</option>
              </select>
            </Field>
            {text("why", "Почему они", "чем интересна компания")}
            {text("repos", "Репозитории", "owner/repo, по строке", true)}
            {text("finding", "Что чиним", "конкретная проблема и фикс", true)}
            {link("pr_url", "PR")}
            {text("contact_role", "Кому писать", "роль, например Head of Platform")}
            <Field label="Письмо">
              <input type="date" className={`${inputCls} w-auto py-1`} value={t.contacted_at ?? ""}
                onChange={(e) => save({ contacted_at: e.target.value || null })} />
            </Field>
            {text("reply", "Ответ", "что ответили", true)}
            {text("next_step", "Следующий шаг")}
            {text("notes", "Заметки", "", true)}
          </dl>
        </Card>
        <div className="space-y-3">
          <Card className="space-y-2">
            <div className="text-xs font-medium text-muted">Запись в историю</div>
            <textarea className={`${inputCls} min-h-16`} value={note} onChange={(e) => setNote(e.target.value)} placeholder="что произошло" />
            <Primary className="w-full" disabled={!note.trim()} onClick={() => save({ note: note.trim() }).then(() => setNote(""))}>Записать</Primary>
          </Card>
          <Card>
            <div className="mb-2 text-xs font-medium text-muted">История</div>
            {t.events.length === 0 ? <Empty>Пусто</Empty> : (
              <ol className="space-y-2">
                {t.events.map((e) => (
                  <li key={e.id} className="text-sm">
                    <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted">
                      {new Date(e.at).toLocaleString("ru", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" })}
                      {e.kind === "step" && e.step && e.status && <StepChip step={e.step} status={e.status as StepStatus} />}
                    </div>
                    <div className="flex items-start gap-1.5">
                      <span className="min-w-0 break-words">{e.text}</span>
                      {safeHref(e.url ?? "") && <a href={safeHref(e.url ?? "")} target="_blank" rel="noreferrer" className="mt-0.5 shrink-0 text-muted hover:text-accent"><ExternalLink size={12} /></a>}
                    </div>
                    <LogBox log={e.log ?? ""} />
                  </li>
                ))}
              </ol>
            )}
          </Card>
          <Ghost className="text-xs" onClick={() => confirm(`Удалить ${t.company} из кампании?`) && outreach.remove(t.id).then(() => navigate("/jobs/outreach"))}>
            <Trash2 size={13} />Удалить
          </Ghost>
        </div>
      </div>
      <Flash msg={flash} />
    </div>
  );
}
