import { useCallback, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { Check, ExternalLink, FileText, Pause, Play, Undo2, X } from "lucide-react";
import { motion } from "motion/react";
import { agoShort, day } from "../format";
import { Badge, Card, CopyButton, Empty, ErrorBox, Section, Skeleton, Tabs } from "../ui";
import { safeHref } from "./model";
import { Fit, Flash, Ghost, useFlash } from "./ui";

const LOADED = Date.now();

// ---------- API (projects_api/autopilot.py)

type Counts = { sent: number; manual: number; manual_done: number; failed: number; skipped: number; queued: number; events: Record<string, number> };
type Stats = {
  days: number; today: Counts; period: Counts; series: { date: string; sent: number; auto: number; mine: number; manual: number; skipped: number }[];
  channels: Record<string, number>; skip_reasons: [string, number][];
  funnel: { sent: number; replied: number; interview: number; offer: number; rejected: number };
  manual_open: number; meta: Record<string, string>;
};
type Vacancy = {
  vid: string; date: string; at: string; score: number | null; reason: string; lang: string; title: string; company: string;
  url: string; source: string; status: "queued" | "sent" | "manual" | "failed" | "skipped"; channel: string; detail: string;
  letter: string; subject: string; answers: string; application_id: number | null; has_cv: number; has_letter?: number; has_letter_ru?: number; has_letter_en?: number; tg_handle?: string; tg_ru?: string; tg_en?: string; letter_ru?: string; letter_en?: string; manual_done_at: string | null; dismissed_at?: string | null; country?: string; visa?: string; salary?: string; salary_note?: string;
  app_status: string | null;
};
type ApEvent = { key: string; at: string; date: string; kind: string; channel: string; company: string; summary: string; application_id: number | null };

async function call<T>(method: string, path: string): Promise<T> {
  const r = await fetch(path, { method });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error ?? r.statusText);
  return r.json();
}
const ap = {
  stats: (days: number) => call<Stats>("GET", `/api/autopilot/stats?days=${days}`),
  list: (days: number) => call<Vacancy[]>("GET", `/api/autopilot/vacancies?days=${days}`),
  mine: () => call<Vacancy[]>("GET", "/api/autopilot/mine"),
  // the whole manual queue, any age: the windowed list is capped at 300 and skipped rows crowd it out
  queue: () => call<Vacancy[]>("GET", "/api/autopilot/vacancies?status=manual&days=3650&limit=1000"),
  events: (days: number) => call<ApEvent[]>("GET", `/api/autopilot/events?days=${days}`),
  done: (vid: string) => call<Vacancy>("POST", `/api/autopilot/vacancies/${encodeURIComponent(vid)}/done`),
  undone: (vid: string) => call<Vacancy>("POST", `/api/autopilot/vacancies/${encodeURIComponent(vid)}/undone`),
  dismiss: (vid: string) => call<Vacancy>("POST", `/api/autopilot/vacancies/${encodeURIComponent(vid)}/dismiss`),
  restore: (vid: string) => call<Vacancy>("POST", `/api/autopilot/vacancies/${encodeURIComponent(vid)}/restore`),
};

// ---------- labels

const CHANNEL: Record<string, string> = {
  hirify: "Hirify", email: "Email", ats: "Форма ATS", link: "Сайт", telegram: "Telegram", linkedin: "LinkedIn", reveal: "Hirify",
};
const channelLabel = (c: string) => {
  const [kind, host] = c.split(":");
  if (kind === "ats" && host) return host.includes("greenhouse") ? "Greenhouse" : host.includes("lever") ? "Lever" : host.includes("ashby") ? "Ashby" : "Форма ATS";
  return CHANNEL[kind] ?? (c || "—");
};
const KIND: Record<string, { label: string; tone: "ok" | "accent" | "amber" | "muted" }> = {
  offer: { label: "Оффер", tone: "ok" }, interview: { label: "Интервью", tone: "ok" }, question: { label: "Вопрос", tone: "accent" },
  rejection: { label: "Отказ", tone: "muted" }, other: { label: "Ответ", tone: "muted" },
};
const plural = (n: number, one: string, few: string, many: string) => {
  const m10 = n % 10, m100 = n % 100;
  return m10 === 1 && m100 !== 11 ? one : m10 >= 2 && m10 <= 4 && (m100 < 12 || m100 > 14) ? few : many;
};

/** Where to send a manual item: links and Telegram handles found in `detail`; the other parts are its reason. */
const TG_HANDLE = /^@?([A-Za-z][A-Za-z0-9_]{4,31})$/;
function destinations(v: Vacancy): { href?: string; text: string }[] {
  const out: { href?: string; text: string }[] = [];
  for (const raw of v.detail.split(" · ")) {
    const p = raw.trim();
    const href = /^https?:\/\//i.test(p) ? safeHref(p) : undefined;
    const tg = TG_HANDLE.exec(p);
    if (href) out.push({ href, text: new URL(href).host });
    else if (tg) out.push({ href: `https://t.me/${tg[1]}`, text: `@${tg[1]}` });
    else if (p) out.push({ text: p });
  }
  return out.length ? out : [{ text: "контакт не найден" }];
}

// ---------- pieces

function Tile({ label, value, sub, tone }: { label: string; value: number | string; sub?: string; tone?: "amber" }) {
  return (
    <Card className={`p-3.5 ${tone === "amber" && value ? "border-transparent bg-amber-bg" : ""}`}>
      <div className={`text-xs ${tone === "amber" && value ? "text-amber-fg" : "text-muted"}`}>{label}</div>
      <div className={`mt-1 text-2xl font-semibold tabular-nums tracking-tight ${tone === "amber" && value ? "text-amber-fg" : ""}`}>{value}</div>
      {sub && <div className="mt-0.5 text-xs text-muted">{sub}</div>}
    </Card>
  );
}

/** Applications sent per day: one series, so one hue and no legend; every bar has a hover tooltip. */
function DailyChart({ series }: { series: Stats["series"] }) {
  const [hover, setHover] = useState<number | null>(null);
  const max = Math.max(1, ...series.map((s) => s.sent));
  const h = 112;
  const step = Math.ceil(series.length / 6);
  const h_ = hover !== null ? series[hover] : null;
  return (
    <Card className="p-4">
      <div className="mb-3 flex items-baseline justify-between gap-3">
        <span className="text-sm font-medium">Отправлено по дням</span>
        <span className="h-4 text-xs tabular-nums text-muted">
          {h_ ? `${day(h_.date)}: отправлено ${h_.sent} (автопилот ${h_.auto}, ты ${h_.mine}) · передано тебе ${h_.manual} · отсеяно ${h_.skipped}` : `максимум ${max} в день`}
        </span>
      </div>
      <div className="relative" style={{ height: h }} onMouseLeave={() => setHover(null)}>
        <div className="absolute inset-x-0 top-0 border-t border-dashed border-line" />
        <div className="absolute inset-x-0 bottom-0 border-t border-line" />
        <div className="absolute inset-0 flex items-end gap-[2px]">
          {series.map((s, i) => (
            <div key={s.date} className="flex h-full flex-1 items-end" onMouseEnter={() => setHover(i)}
              title={`${day(s.date)}: отправлено ${s.sent} (автопилот ${s.auto}, ты ${s.mine})`}>
              <motion.div className="w-full rounded-t-[4px]"
                style={{ background: "var(--accent)", opacity: hover === null || hover === i ? 1 : 0.45 }}
                initial={{ height: 0 }} animate={{ height: s.sent ? Math.max(3, (s.sent / max) * (h - 4)) : 0 }}
                transition={{ duration: 0.4, delay: i * 0.008 }} />
            </div>
          ))}
        </div>
      </div>
      <div className="mt-1.5 flex gap-[2px] text-[10px] tabular-nums text-muted">
        {series.map((s, i) => <span key={s.date} className="flex-1 text-center">{i % step === 0 || i === series.length - 1 ? day(s.date) : ""}</span>)}
      </div>
    </Card>
  );
}

function Funnel({ f }: { f: Stats["funnel"] }) {
  const steps = [["Отправлено", f.sent], ["Ответили", f.replied], ["Интервью", f.interview], ["Оффер", f.offer]] as const;
  return (
    <Card className="p-4">
      <div className="mb-3 text-sm font-medium">Воронка</div>
      <div className="space-y-2">
        {steps.map(([label, n]) => {
          const pct = f.sent ? Math.round((100 * n) / f.sent) : 0;
          return (
            <div key={label} className="flex items-center gap-3 text-sm">
              <span className="w-24 shrink-0 text-muted">{label}</span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-line">
                <motion.div className="h-full rounded-full bg-ok" initial={{ width: 0 }} animate={{ width: `${f.sent ? Math.max(n ? 2 : 0, pct) : 0}%` }} transition={{ duration: 0.5 }} />
              </div>
              <span className="w-16 shrink-0 text-right tabular-nums">{n}{label !== "Отправлено" && f.sent ? <span className="text-muted"> · {pct}%</span> : null}</span>
            </div>
          );
        })}
      </div>
      {f.rejected > 0 && <div className="mt-2 text-xs text-muted">отказов: {f.rejected}</div>}
    </Card>
  );
}

type Lang = "ru" | "en";
const LANGS: Lang[] = ["ru", "en"];
const hasBoth = (v: Vacancy) => !!(v.letter_ru && v.letter_en);
/** The texts of a card in one language; falls back to the letter as it was written. */
function texts(v: Vacancy, lang: Lang | null) {
  if (!lang) return { letter: v.letter, tg: v.tg_ru || v.tg_en || "", pdf: v.has_letter ? "letter" : null };
  return {
    letter: (lang === "ru" ? v.letter_ru : v.letter_en) || v.letter,
    tg: (lang === "ru" ? v.tg_ru : v.tg_en) || "",
    pdf: (lang === "ru" ? v.has_letter_ru : v.has_letter_en) ? `letter_${lang}` : v.has_letter ? "letter" : null,
  };
}
const block = "whitespace-pre-wrap rounded-xl bg-hover/60 p-3 text-sm leading-relaxed";

function LangSwitch({ value, onChange }: { value: Lang; onChange: (l: Lang) => void }) {
  return (
    <div className="inline-flex rounded-lg border border-line bg-card p-0.5 text-xs" role="group" aria-label="Язык текстов">
      {LANGS.map((l) => (
        <button key={l} onClick={() => onChange(l)} aria-pressed={value === l}
          className={`rounded-md px-2 py-0.5 font-medium transition ${value === l ? "bg-accent text-white" : "text-muted hover:text-fg"}`}>
          {l.toUpperCase()}
        </button>
      ))}
    </div>
  );
}

function Letter({ v, lang = null }: { v: Vacancy; lang?: Lang | null }) {
  if (!v.letter) return null;
  const t = texts(v, lang);
  return (
    <details className="group mt-2">
      <summary className="cursor-pointer list-none text-xs text-muted hover:text-fg">
        <FileText size={12} className="mr-1 inline" />письмо<span className="group-open:hidden"> · показать</span>
      </summary>
      <div className="mt-2 space-y-2">
        <p className={block}>{t.letter}</p>
        {v.answers && <p className={block}>{v.answers}</p>}
        {t.tg && <><div className="text-xs text-muted">Привет в Telegram @{v.tg_handle}</div><p className={block}>{t.tg}</p></>}
      </div>
    </details>
  );
}

const fileBtn = "inline-flex items-center gap-1.5 rounded-lg border border-line bg-card px-2 py-1 text-xs transition hover:bg-hover";

// ---------- company country filter (2026-11-08)

const NO_COUNTRY = "не указана";
const countryOf = (v: Vacancy) => v.country?.trim() || NO_COUNTRY;
type SortKey = "time" | "score" | "country";
const SORTS: [SortKey, string][] = [["time", "новые"], ["score", "оценка"], ["country", "страна"]];

function ordered(list: Vacancy[], key: SortKey, country: string, visaOnly = false): Vacancy[] {
  const out = list.filter((v) => (!country || countryOf(v) === country) && (!visaOnly || v.visa === "yes"));
  const time = (v: Vacancy) => v.at || v.date || "";
  const byKey = (a: Vacancy, b: Vacancy) =>
    key === "score" ? (b.score ?? 0) - (a.score ?? 0) || time(b).localeCompare(time(a))
      : key === "country" ? countryOf(a).localeCompare(countryOf(b), "ru") || (b.score ?? 0) - (a.score ?? 0)
        : time(b).localeCompare(time(a));
  // sent-by-hand manual cards always sink to the bottom
  return out.sort((a, b) => Number(!!a.manual_done_at) - Number(!!b.manual_done_at) || byKey(a, b));
}

function CountryBar({ items, value, onChange, sort, onSort, visaOnly, onVisa }: {
  items: Vacancy[]; value: string; onChange: (c: string) => void; sort: SortKey; onSort: (k: SortKey) => void;
  visaOnly: boolean; onVisa: (on: boolean) => void;
}) {
  const visaCount = items.filter((v) => v.visa === "yes").length;
  const counts = new Map<string, number>();
  for (const v of items) counts.set(countryOf(v), (counts.get(countryOf(v)) ?? 0) + 1);
  if (value && !counts.has(value)) counts.set(value, 0);
  const list = [...counts.entries()].sort((a, b) =>
    Number(a[0] === NO_COUNTRY) - Number(b[0] === NO_COUNTRY) || b[1] - a[1] || a[0].localeCompare(b[0], "ru"));
  const chip = (active: boolean) => `rounded-full border px-2.5 py-0.5 transition ${active
    ? "border-accent bg-accent text-white" : "border-line hover:bg-hover"}`;
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
      <div className="flex flex-wrap items-center gap-1.5">
        <button className={chip(!value)} onClick={() => onChange("")}>Все страны <span className="tabular-nums opacity-70">{items.length}</span></button>
        {list.map(([c, n]) => (
          <button key={c} className={chip(value === c)} onClick={() => onChange(value === c ? "" : c)}>
            {c} <span className="tabular-nums opacity-70">{n}</span></button>
        ))}
      </div>
      <div className="flex items-center gap-1 text-muted">
        {visaCount > 0 && <button className={`${chip(visaOnly)} mr-2`} onClick={() => onVisa(!visaOnly)}
          title="Работодатель прямо пишет, что спонсирует рабочую визу">с визой <span className="tabular-nums opacity-70">{visaCount}</span></button>}
        <span>сортировка:</span>
        {SORTS.map(([k, label]) => (
          <button key={k} onClick={() => onSort(k)}
            className={`rounded-md px-1.5 py-0.5 ${sort === k ? "bg-hover text-fg" : "hover:text-fg"}`}>{label}</button>
        ))}
      </div>
    </div>
  );
}

// Ledger "at" is Tbilisi local time ("2026-11-08 20:52"); manual_done_at is UTC ISO.
function when(s: string | null | undefined): string {
  if (!s) return "";
  const d = new Date(s.includes("T") ? s : s.replace(" ", "T") + "+04:00");
  return isNaN(+d) ? "" : d.toLocaleString("ru", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

function ManualCard({ v, onDone, onUndo, onDismiss }: { v: Vacancy; onDone: () => void; onUndo: () => void; onDismiss: () => void }) {
  const dests = destinations(v);
  const done = !!v.manual_done_at;
  const [lang, setLang] = useState<Lang>(v.lang === "ru" ? "ru" : "en");
  const active = hasBoth(v) ? lang : null;
  const t = texts(v, active);
  // ?t= per page load: CVs are rebuilt in place, a cached PDF must not hide the new one (2026-11-12)
  const file = (kind: string) => `/api/autopilot/vacancies/${encodeURIComponent(v.vid)}/${kind}?t=${LOADED}`;
  return (
    <motion.div layout initial={{ opacity: 0 }} animate={{ opacity: done ? 0.55 : 1 }}>
      <Card className="p-4">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-2">
              <span className="truncate font-medium">{v.company || "компания не указана"}</span>
              <Fit value={v.score} />
            </div>
            <div className="truncate text-sm text-muted">{v.title}</div>
            <div className="mt-1.5 text-xs text-muted">
              {v.country ? `${v.country} · ` : ""}{v.visa === "yes" ? "виза ✓ · " : ""}{channelLabel(v.channel)}
              {dests.map((d, i) => <span key={i}> · {d.href
                ? <a href={d.href} target="_blank" rel="noreferrer" className="text-accent hover:underline">{d.text}<ExternalLink size={11} className="ml-0.5 inline" /></a>
                : d.text}</span>)}
              {safeHref(v.url) && !dests.some((d) => d.href === safeHref(v.url)) && <> · <a href={safeHref(v.url)} target="_blank" rel="noreferrer" className="text-accent hover:underline">вакансия<ExternalLink size={11} className="ml-0.5 inline" /></a></>}
            </div>
            <div className="mt-1 text-xs text-muted">
              Автопилот передал тебе {when(v.at) || day(v.date)}
              {done && <> · <span className="text-accent">ты отправил {when(v.manual_done_at)}</span></>}
            </div>
            {v.reason && <div className="mt-1 text-xs text-muted" title="Почему такая оценка; приоритет и −1 — по данным вакансии">
              <span>Оценка: </span>{v.reason}</div>}
            {v.salary && <div className="mt-1 text-xs" title="Что указать, если форма спрашивает зарплатные ожидания">
              <span className="text-muted">Вилка для формы: </span><span className="font-medium">{v.salary}</span>
              {v.salary_note && <span className="text-muted"> · {v.salary_note}</span>}
            </div>}
          </div>
          <div className="flex shrink-0 flex-wrap items-center gap-1.5">
            {active && <LangSwitch value={lang} onChange={setLang} />}
            {t.tg && <CopyButton text={t.tg} label="Привет TG" title={`Первое сообщение для @${v.tg_handle}`} />}
            {t.letter && <CopyButton text={t.letter} label="Письмо" title="Скопировать письмо" />}
            {v.salary && <CopyButton text={v.salary} label="Вилка" title="Скопировать зарплатные ожидания для формы" />}
            {v.has_cv ? <a href={file("cv")} target="_blank" rel="noreferrer" className={fileBtn}><FileText size={14} />CV</a> : null}
            {t.pdf ? <a href={file(t.pdf)} target="_blank" rel="noreferrer" title="Сопроводительное письмо в PDF" className={fileBtn}>
              <FileText size={14} />Письмо PDF</a> : null}
            {!done && <Ghost onClick={onDismiss} title="Вакансия закрыта или неинтересна: убрать из списка"><X size={14} />Убрать</Ghost>}
            {done
              ? <Ghost onClick={onUndo} title="Вернуть в очередь"><Undo2 size={14} />Отправлено</Ghost>
              : <button onClick={onDone}
                  className="inline-flex items-center gap-1.5 rounded-lg bg-accent px-2.5 py-1 text-xs font-medium text-white shadow-sm transition hover:brightness-110 active:scale-[.97]">
                  <Check size={14} />Отправил</button>}
          </div>
        </div>
        <Letter v={v} lang={active} />
      </Card>
    </motion.div>
  );
}

function SentRow({ v }: { v: Vacancy }) {
  return (
    <div className="rounded-xl px-3 py-2.5 transition hover:bg-hover">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          {v.application_id
            ? <Link to={`/jobs/a/${v.application_id}`} className="truncate text-sm font-medium hover:underline">{v.company || "—"}</Link>
            : <span className="truncate text-sm font-medium">{v.company || "—"}</span>}
          <div className="truncate text-xs text-muted">{v.title}</div>
          <div className="text-xs text-muted">{v.country ? `${v.country} · ` : ""}{v.visa === "yes" ? "виза ✓ · " : ""}Автопилот откликнулся {when(v.at) || day(v.date)}</div>
        </div>
        <Badge>{channelLabel(v.channel)}</Badge>
        <Fit value={v.score} />
      </div>
      <Letter v={v} />
    </div>
  );
}

// ---------- what I sent by hand

const APP_STATUS: Record<string, { label: string; tone: "ok" | "accent" | "amber" | "muted" }> = {
  sent: { label: "ждём ответа", tone: "muted" }, interview: { label: "интервью", tone: "ok" }, offer: { label: "оффер", tone: "ok" },
  rejected: { label: "отказ", tone: "amber" }, silent: { label: "молчат", tone: "muted" }, inbound: { label: "написали", tone: "accent" },
};

/** Where the application actually went: the ATS or site behind the apply link, not the board that found it. */
function whereTo(v: Vacancy): { label: string; href?: string } {
  const d = destinations(v).find((x) => x.href) ?? (safeHref(v.url) ? { href: safeHref(v.url), text: "" } : undefined);
  const href = d?.href;
  const host = href ? new URL(href).host.replace(/^www\./, "") : "";
  const known: [RegExp, string][] = [[/greenhouse/, "Greenhouse"], [/ashbyhq/, "Ashby"], [/lever\.co/, "Lever"], [/workable/, "Workable"],
    [/smartrecruiters/, "SmartRecruiters"], [/teamtailor/, "Teamtailor"], [/t\.me/, "Telegram"], [/linkedin/, "LinkedIn"],
    [/hirify/, "Hirify → сайт"], [/himalayas/, "Himalayas → сайт"], [/jobicy/, "Jobicy → сайт"], [/getmatch/, "getmatch"], [/4dayweek/, "4dayweek → сайт"]];
  if (v.channel === "telegram") return { label: "Telegram", href };
  for (const [re, label] of known) if (re.test(host)) return { label, href };
  return { label: host || channelLabel(v.channel), href };
}

function Bars({ title, rows }: { title: string; rows: [string, number][] }) {
  const top = rows[0]?.[1] ?? 1;
  return (
    <Card className="space-y-1.5 p-4">
      <div className="mb-1 text-xs text-muted">{title}</div>
      {rows.map(([k, n]) => (
        <div key={k} className="flex items-center gap-3 text-sm" title={`${k}: ${n}`}>
          <span className="w-36 shrink-0 truncate">{k}</span>
          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line"><div className="h-full rounded-full bg-accent" style={{ width: `${(100 * n) / top}%` }} /></div>
          <span className="w-6 shrink-0 text-right tabular-nums">{n}</span>
        </div>
      ))}
    </Card>
  );
}

const countBy = (items: Vacancy[], key: (v: Vacancy) => string): [string, number][] => {
  const m = new Map<string, number>();
  for (const v of items) m.set(key(v), (m.get(key(v)) ?? 0) + 1);
  return [...m.entries()].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0], "ru"));
};

function MineView({ items, onUndo }: { items: Vacancy[]; onUndo: (v: Vacancy) => void }) {
  if (!items.length) return <Empty>Ты пока ничего не отправил сам. Нажми «Отправил» на карточке в «Отправь сам».</Empty>;
  const weekAgo = new Date(Date.now() - 7 * 864e5).toISOString();
  const week = items.filter((v) => (v.manual_done_at ?? "") >= weekAgo).length;
  const answered = items.filter((v) => v.app_status && v.app_status !== "sent").length;
  const interviews = items.filter((v) => v.app_status === "interview" || v.app_status === "offer").length;
  const byDay = new Map<string, Vacancy[]>();
  for (const v of items) {
    const d = (v.manual_done_at ?? "").slice(0, 10);
    byDay.set(d, [...(byDay.get(d) ?? []), v]);
  }
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tile label="Отправил сам" value={items.length} sub={`с ${day(items[items.length - 1].manual_done_at!.slice(0, 10))}`} />
        <Tile label="За 7 дней" value={week} />
        <Tile label="Ответили" value={answered} sub={items.length ? `${Math.round((100 * answered) / items.length)}%` : undefined} />
        <Tile label="Интервью" value={interviews} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Bars title="Куда ушёл отклик" rows={countBy(items, (v) => whereTo(v).label)} />
        <Bars title="Страна компании" rows={countBy(items, (v) => v.country?.trim() || "не указана")} />
      </div>
      {[...byDay.entries()].map(([d, list]) => (
        <section key={d} className="space-y-1">
          <div className="px-1 text-xs text-muted">{day(d)} · {list.length} {plural(list.length, "отклик", "отклика", "откликов")}</div>
          <Card className="p-1.5">
            {list.map((v) => {
              const w = whereTo(v);
              const st = APP_STATUS[v.app_status ?? "sent"] ?? APP_STATUS.sent;
              return (
                <div key={v.vid} className="group flex flex-wrap items-center gap-x-3 gap-y-1 rounded-xl px-3 py-2 hover:bg-hover">
                  <div className="min-w-0 flex-1">
                    {v.application_id
                      ? <Link to={`/jobs/a/${v.application_id}`} className="text-sm font-medium hover:underline">{v.company || "—"}</Link>
                      : <span className="text-sm font-medium">{v.company || "—"}</span>}
                    <span className="text-sm text-muted"> · {v.title}</span>
                    <div className="text-xs text-muted">
                      {v.country ? `${v.country} · ` : ""}
                      {w.href ? <a href={w.href} target="_blank" rel="noreferrer" className="text-accent hover:underline">{w.label}<ExternalLink size={11} className="ml-0.5 inline" /></a> : w.label}
                      {v.manual_done_at ? ` · ${when(v.manual_done_at)}` : ""}
                    </div>
                  </div>
                  <Badge tone={st.tone}>{st.label}</Badge>
                  <Fit value={v.score} />
                  <Ghost onClick={() => onUndo(v)} title="Не отправлял: вернуть в очередь"><Undo2 size={14} /></Ghost>
                </div>
              );
            })}
          </Card>
        </section>
      ))}
    </div>
  );
}

// ---------- page

type Tab = "manual" | "mine" | "sent" | "events" | "skipped" | "failed";

export default function Autopilot() {
  const [days, setDays] = useState(7);
  const [stats, setStats] = useState<Stats | null>(null);
  const [list, setList] = useState<Vacancy[] | null>(null);
  const [mine, setMine] = useState<Vacancy[]>([]);
  const [events, setEvents] = useState<ApEvent[]>([]);
  const [tab, setTab] = useState<Tab>("manual");
  const [country, setCountry] = useState("");
  const [sort, setSort] = useState<SortKey>("score");
  const [visaOnly, setVisaOnly] = useState(false);
  const [error, setError] = useState("");
  const [flash, setFlash] = useFlash();

  const load = useCallback(() => {
    ap.mine().then(setMine).catch(() => {});
    Promise.all([ap.stats(days), ap.list(Math.max(days, 30)), ap.events(days), ap.queue()])
      .then(([s, l, e, q]) => {
        const seen = new Set(l.map((v) => v.vid));
        setStats(s); setList([...l, ...q.filter((v) => !seen.has(v.vid))]); setEvents(e); setError("");
      })
      .catch((e) => setError(String(e)));
  }, [days]);
  useEffect(() => { load(); }, [load]);

  const groups = useMemo(() => {
    const g: Record<Tab, Vacancy[]> = { manual: [], mine: [], sent: [], events: [], skipped: [], failed: [] };
    for (const v of list ?? []) {
      if (v.dismissed_at) g.skipped.push(v);
      else if (v.manual_done_at) continue;
      else if (v.status === "manual") g.manual.push(v);
      else if (v.status === "sent") g.sent.push(v);
      else if (v.status === "skipped") g.skipped.push(v);
      else if (v.status === "failed") g.failed.push(v);
    }
    return g;
  }, [list]);
  const shown = useMemo(() => {
    const out = {} as Record<Tab, Vacancy[]>;
    for (const k of Object.keys(groups) as Tab[]) out[k] = ordered(groups[k], sort, country, visaOnly);
    return out;
  }, [groups, sort, country, visaOnly]);

  async function dismiss(v: Vacancy, off: boolean) {
    try { await (off ? ap.dismiss(v.vid) : ap.restore(v.vid)); setFlash(off ? `Убрал ${v.company || "вакансию"}, вернуть можно в «Отсеяно»` : "Вернул в очередь"); load(); }
    catch (e) { setFlash(`Не сохранилось: ${e}`); }
  }

  async function mark(v: Vacancy, done: boolean) {
    try { await (done ? ap.done(v.vid) : ap.undone(v.vid)); setFlash(done ? "Записал в отклики" : "Вернул в очередь"); load(); }
    catch (e) { setFlash(`Не сохранилось: ${e}`); }
  }

  const meta = stats?.meta ?? {};
  const paused = meta.paused === "1";
  const t = stats?.today;
  const p = stats?.period;
  const openManual = shown.manual.length;

  return (
    <div className="space-y-8">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Автопилот</h1>
          <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-sm text-muted">
            {stats && <span className={`inline-flex items-center gap-1.5 ${paused ? "text-amber-fg" : "text-ok"}`}>
              {paused ? <Pause size={14} /> : <Play size={14} />}{paused ? "на паузе (/resume в боте)" : "работает"}</span>}
            {meta.synced_at && <span>обновлено {agoShort(meta.synced_at)} назад</span>}
            {meta.hirify_apply && <span>hirify: откликов {meta.hirify_apply}, раскрытий {meta.hirify_reveal}</span>}
          </div>
        </div>
        <div className="flex rounded-xl border border-line bg-hover/60 p-0.5 text-sm">
          {[1, 7, 30].map((d) => (
            <button key={d} onClick={() => setDays(d)}
              className={`rounded-lg px-3 py-1 transition ${days === d ? "bg-card font-medium shadow-sm" : "text-muted hover:text-fg"}`}>
              {d === 1 ? "Сегодня" : `${d} дней`}
            </button>
          ))}
        </div>
      </header>

      {error && <ErrorBox error={error} />}
      {!stats && !error && <Skeleton rows={3} />}

      {stats && t && p && (
        <>
          <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
            <Tile label="Отправлено" value={p.sent} sub={days > 1 ? `сегодня ${t.sent}` : undefined} />
            <Tile label="Ответы" value={Object.values(p.events).reduce((a, b) => a + b, 0)}
              sub={p.events.rejection ? `из них отказов ${p.events.rejection}` : undefined} />
            <Tile label="Интервью" value={(p.events.interview ?? 0) + (p.events.offer ?? 0)} sub={p.events.offer ? `офферов ${p.events.offer}` : undefined} />
            <Tile label="Отправь сам" value={stats.manual_open} tone="amber"
              sub={stats.manual_open ? plural(stats.manual_open, "ссылка ждёт", "ссылки ждут", "ссылок ждут") : "очередь пуста"} />
          </div>

          <div className="grid gap-3 md:grid-cols-[1.6fr_1fr]">
            {days > 1 ? <DailyChart series={stats.series} /> : (
              <Card className="p-4 text-sm">
                <div className="mb-2 font-medium">Сегодня</div>
                <div className="space-y-1 text-muted">
                  <div>оценено вакансий: <span className="tabular-nums text-fg">{t.sent + t.manual + t.skipped + t.failed + t.queued}</span></div>
                  <div>отсеяно: <span className="tabular-nums text-fg">{t.skipped}</span> · ошибки: <span className="tabular-nums text-fg">{t.failed}</span> · в очереди: <span className="tabular-nums text-fg">{t.queued}</span></div>
                </div>
              </Card>
            )}
            <Funnel f={stats.funnel} />
          </div>

          {Object.keys(stats.channels).length > 0 && (
            <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
              <span>Каналы:</span>
              {Object.entries(stats.channels).sort((a, b) => b[1] - a[1]).map(([c, n]) => (
                <span key={c} className="rounded-full border border-line px-2.5 py-0.5"><span className="text-fg">{channelLabel(c)}</span> <span className="tabular-nums">{n}</span></span>
              ))}
            </div>
          )}
        </>
      )}

      {list && (
        <div className="space-y-4">
          <Tabs value={tab} onChange={(id) => setTab(id as Tab)} tabs={[
            { id: "manual", label: "Отправь сам", count: openManual },
            { id: "mine", label: "Отправил сам", count: mine.length },
            { id: "sent", label: "Отправлено автопилотом", count: shown.sent.length },
            { id: "events", label: "Ответы", count: events.length },
            { id: "skipped", label: "Отсеяно", count: shown.skipped.length },
            ...(groups.failed.length ? [{ id: "failed", label: "Ошибки", count: shown.failed.length }] : []),
          ]} />

          {tab !== "events" && tab !== "mine" && groups[tab].length > 0 && (
            <CountryBar items={groups[tab]} value={country} onChange={setCountry} sort={sort} onSort={setSort}
              visaOnly={visaOnly} onVisa={setVisaOnly} />
          )}

          {tab === "manual" && (shown.manual.length ? (
            <div className="space-y-3">
              <p className="text-sm text-muted">Сюда попадает то, что автопилот не может отправить сам: сайт компании, LinkedIn, Telegram. Письмо и CV готовы, после отправки нажми «Отправил» — отклик попадёт в общий список.</p>
              {shown.manual.map((v) => <ManualCard key={v.vid} v={v} onDone={() => mark(v, true)} onUndo={() => mark(v, false)} onDismiss={() => dismiss(v, true)} />)}
            </div>
          ) : <Empty>Ручная очередь пуста.</Empty>)}

          {tab === "mine" && <MineView items={mine} onUndo={(v) => mark(v, false)} />}

          {tab === "sent" && (shown.sent.length
            ? <Card className="p-1.5">{shown.sent.map((v) => <SentRow key={v.vid} v={v} />)}</Card>
            : <Empty>Пока ничего не отправлено.</Empty>)}

          {tab === "events" && (events.length ? (
            <Card className="p-1.5">
              {events.map((e) => (
                <div key={e.key} className="flex items-start gap-3 rounded-xl px-3 py-2.5 hover:bg-hover">
                  <Badge tone={KIND[e.kind]?.tone ?? "muted"}>{KIND[e.kind]?.label ?? e.kind}</Badge>
                  <div className="min-w-0 flex-1">
                    {e.application_id
                      ? <Link to={`/jobs/a/${e.application_id}`} className="text-sm font-medium hover:underline">{e.company || "—"}</Link>
                      : <span className="text-sm font-medium">{e.company || "—"}</span>}
                    <div className="text-sm text-muted">{e.summary}</div>
                  </div>
                  <span className="shrink-0 text-xs tabular-nums text-muted">{e.at ? `${day(e.at.slice(0, 10))} ${e.at.slice(11, 16)}` : ""}</span>
                </div>
              ))}
            </Card>
          ) : <Empty>Ответов пока нет. Приглашения приходят в Telegram сразу.</Empty>)}

          {tab === "skipped" && (shown.skipped.length ? (
            <div className="space-y-3">
              {stats && stats.skip_reasons.length > 0 && (
                <Section title="Почему отсеяно">
                  <Card className="space-y-1.5 p-4">
                    {stats.skip_reasons.map(([r, n]) => {
                      const top = stats.skip_reasons[0][1];
                      return (
                        <div key={r} className="flex items-center gap-3 text-sm" title={`${r}: ${n}`}>
                          <span className="w-40 shrink-0 truncate">{r}</span>
                          <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-line"><div className="h-full rounded-full bg-[var(--s-closed)]" style={{ width: `${(100 * n) / top}%` }} /></div>
                          <span className="w-8 text-right tabular-nums text-muted">{n}</span>
                        </div>
                      );
                    })}
                  </Card>
                </Section>
              )}
              <Card className="p-1.5">
                {shown.skipped.map((v) => (
                  <div key={v.vid} className="flex items-center gap-3 rounded-xl px-3 py-2 hover:bg-hover">
                    <div className="min-w-0 flex-1">
                      {safeHref(v.url)
                        ? <a href={safeHref(v.url)} target="_blank" rel="noreferrer" className="truncate text-sm hover:underline">{v.company || "—"} · {v.title}</a>
                        : <span className="truncate text-sm">{v.company || "—"} · {v.title}</span>}
                      <div className="truncate text-xs text-muted">{v.dismissed_at ? "Убрал вручную: неактуально" : v.reason}</div>
                    </div>
                    {v.dismissed_at && <Ghost onClick={() => dismiss(v, false)} title="Вернуть в «Отправь сам»"><Undo2 size={14} />Вернуть</Ghost>}
                    <span className="shrink-0 text-xs tabular-nums text-muted">{v.score}/5</span>
                  </div>
                ))}
              </Card>
            </div>
          ) : <Empty>Ничего не отсеяно.</Empty>)}

          {tab === "failed" && (
            <Card className="p-1.5">
              {shown.failed.map((v) => (
                <div key={v.vid} className="rounded-xl px-3 py-2 hover:bg-hover">
                  <div className="truncate text-sm">{v.company || "—"} · {v.title}</div>
                  <div className="break-words text-xs text-muted">{v.detail}</div>
                </div>
              ))}
            </Card>
          )}
        </div>
      )}
      <Flash msg={flash} />
    </div>
  );
}
