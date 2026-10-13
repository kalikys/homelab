import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Circle, History, PenLine, RotateCcw, Sparkles, Trash2 } from "lucide-react";
import { AnimatePresence, motion } from "motion/react";
import { ago, day } from "../format";
import { Card, CopyButton } from "../ui";
import { jobs, type ApplicationDetail, type Letter } from "./api";
import { LANGS } from "./model";
import { AutoTextarea, Ghost, Primary, inputCls } from "./ui";

const SOURCE: Record<Letter["source"], string> = { generated: "Claude", manual: "вручную", imported: "импорт" };
const words = (s: string) => (s.trim() ? s.trim().split(/\s+/).length : 0);

function LangPicker({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  return (
    <div className="inline-flex rounded-xl border border-line bg-hover/50 p-0.5" role="radiogroup" aria-label="Язык письма">
      {LANGS.map((l) => (
        <button key={l.id} role="radio" aria-checked={value === l.id} onClick={() => onChange(l.id)}
          className={`relative rounded-lg px-2.5 py-1 text-xs font-medium transition ${value === l.id ? "text-fg" : "text-muted hover:text-fg"}`}>
          {value === l.id && <motion.span layoutId="lang-pill" className="absolute inset-0 rounded-lg bg-card shadow-sm" />}
          <span className="relative">{l.id.toUpperCase()}</span>
        </button>
      ))}
    </div>
  );
}

/** Guess the vacancy language so the default is usually right. */
function guessLang(text: string): string {
  if (/[а-яё]/i.test(text)) return "ru";
  if (/[áäčďéíĺľňóôŕšťúýž]/i.test(text)) return "sk";
  if (/\b(und|wir|sie|für|mit)\b/i.test(text)) return "de";
  return "en";
}

function Composer({ app, onDone, onCancel }: { app: ApplicationDetail; onDone: () => void; onCancel?: () => void }) {
  const [mode, setMode] = useState<"generate" | "manual">("generate");
  const [lang, setLang] = useState(() => guessLang(app.vacancy_text));
  const [wish, setWish] = useState("");
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setBusy(true); setError("");
    try {
      if (mode === "generate") await jobs.generate(app.id, { lang, wish });
      else await jobs.addLetter(app.id, { lang, body });
      setWish(""); setBody(""); onDone();
    } catch (e) { setError(String(e)); } finally { setBusy(false); }
  }

  return (
    <Card className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex gap-1">
          <Ghost onClick={() => setMode("generate")} className={mode === "generate" ? "bg-hover text-fg" : ""}><Sparkles size={14} />Сгенерировать</Ghost>
          <Ghost onClick={() => setMode("manual")} className={mode === "manual" ? "bg-hover text-fg" : ""}><PenLine size={14} />Вставить своё</Ghost>
        </div>
        <LangPicker value={lang} onChange={setLang} />
      </div>
      {mode === "generate" ? (
        <>
          <input value={wish} onChange={(e) => setWish(e.target.value)} onKeyDown={(e) => e.key === "Enter" && !busy && submit()}
            placeholder="Пожелание, если есть: короче, упомянуть релокацию в Košice, без шутки…" className={inputCls} />
          {!app.vacancy_text.trim() && (
            <p className="flex items-center gap-1.5 text-xs text-amber-fg">
              <AlertTriangle size={13} />Текста вакансии нет: письмо выйдет общим. Вставь его в блок «Вакансия» ниже.
            </p>
          )}
        </>
      ) : (
        <AutoTextarea value={body} onChange={(e) => setBody(e.target.value)} placeholder="Текст письма" className="min-h-28" />
      )}
      {error && <p className="text-xs text-amber-fg">{error}</p>}
      <div className="flex items-center justify-end gap-2">
        {onCancel && <Ghost onClick={onCancel}>Отмена</Ghost>}
        <Primary onClick={submit} disabled={busy || (mode === "manual" && !body.trim())}>
          {mode === "generate" ? <><Sparkles size={15} />Написать письмо</> : "Сохранить письмо"}
        </Primary>
      </div>
    </Card>
  );
}

function Pending({ l }: { l: Letter }) {
  return (
    <div className="space-y-3 py-1">
      <div className="flex items-center gap-2 text-sm text-accent">
        <motion.span animate={{ rotate: 360 }} transition={{ repeat: Infinity, duration: 2.4, ease: "linear" }}><Sparkles size={15} /></motion.span>
        Claude пишет письмо… обычно 30–60 секунд
      </div>
      {l.wish && <p className="text-xs text-muted">Пожелание: {l.wish}</p>}
      <div className="space-y-2">
        {[92, 100, 78, 96, 54].map((w, i) => (
          <motion.div key={i} className="h-2.5 rounded-full bg-hover" style={{ width: `${w}%` }}
            animate={{ opacity: [0.5, 1, 0.5] }} transition={{ repeat: Infinity, duration: 1.6, delay: i * 0.12 }} />
        ))}
      </div>
    </div>
  );
}

function Versions({ id, onRestore }: { id: number; onRestore: (body: string) => void }) {
  const [list, setList] = useState<{ id: number; body: string; created_at: string }[] | null>(null);
  useEffect(() => { jobs.letter(id).then((l) => setList(l.versions)).catch(() => setList([])); }, [id]);
  if (list === null) return <p className="text-xs text-muted">Загрузка…</p>;
  if (list.length === 0) return <p className="text-xs text-muted">Письмо не переписывали.</p>;
  return (
    <div className="space-y-2">
      {list.map((v) => (
        <div key={v.id} className="rounded-xl border border-line bg-hover/40 p-3">
          <div className="mb-1.5 flex items-center justify-between text-xs text-muted">
            <span>до правки {day(v.created_at)}, {ago(v.created_at)}</span>
            <Ghost className="text-xs" onClick={() => onRestore(v.body)}><RotateCcw size={12} />Вернуть эту</Ghost>
          </div>
          <p className="line-clamp-4 whitespace-pre-wrap text-xs">{v.body}</p>
        </div>
      ))}
    </div>
  );
}

function LetterCard({ l, onChange }: { l: Letter; onChange: () => void }) {
  const [draft, setDraft] = useState(l.body);
  const [showVersions, setShowVersions] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => setDraft(l.body), [l.body]);
  const dirty = draft !== l.body;

  async function run(p: Promise<unknown>) {
    setError("");
    try { await p; onChange(); } catch (e) { setError(String(e)); }
  }
  const save = () => dirty && draft.trim() && run(jobs.patchLetter(l.id, { body: draft }));

  return (
    <motion.div layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
      <Card className={`space-y-3 ${l.sent ? "border-ok/50" : ""}`}>
        <div className="flex flex-wrap items-center gap-2">
          <span className="rounded-md bg-hover px-1.5 py-0.5 text-[11px] font-semibold tracking-wide">{l.lang.toUpperCase()}</span>
          <span className="text-xs text-muted">{SOURCE[l.source]} · {ago(l.updated_at)}</span>
          <div className="ml-auto flex items-center gap-1">
            {l.status === "ready" && (
              <>
                <button onClick={() => run(jobs.patchLetter(l.id, { sent: !l.sent }))}
                  title={l.sent ? "Это письмо ушло работодателю" : "Отметить, что отправил именно это письмо"}
                  className={`inline-flex items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium transition ${l.sent ? "bg-ok/10 text-ok" : "text-muted hover:bg-hover hover:text-fg"}`}>
                  {l.sent ? <CheckCircle2 size={14} /> : <Circle size={14} />}{l.sent ? "Ушло" : "Отправил это"}
                </button>
                <CopyButton text={draft} label="Копировать" title="Скопировать текст письма" />
                <Ghost title="Предыдущие версии" onClick={() => setShowVersions(!showVersions)}><History size={14} /></Ghost>
              </>
            )}
            <Ghost title="Удалить письмо" onClick={() => confirm("Удалить это письмо?") && run(jobs.removeLetter(l.id))}><Trash2 size={14} /></Ghost>
          </div>
        </div>

        {l.status === "pending" && <Pending l={l} />}
        {l.status === "failed" && (
          <div className="flex flex-wrap items-center gap-3 rounded-xl bg-amber-bg px-3 py-2.5 text-sm text-amber-fg">
            <AlertTriangle size={15} /><span className="flex-1">Не получилось: {l.error}</span>
            <Primary className="py-1.5" onClick={() => run(jobs.retry(l.id))}><RotateCcw size={14} />Повторить</Primary>
          </div>
        )}
        {l.status === "ready" && (
          <>
            <AutoTextarea value={draft} onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => { if ((e.metaKey || e.ctrlKey) && (e.key === "s" || e.key === "Enter")) { e.preventDefault(); save(); } }}
              className="border-transparent bg-transparent px-0 hover:border-line focus:px-3" />
            <div className="flex items-center justify-between gap-2 text-xs text-muted">
              <span>{words(draft)} слов</span>
              <AnimatePresence>
                {dirty && (
                  <motion.div initial={{ opacity: 0 }} animate={{ opacity: 1 }} exit={{ opacity: 0 }} className="flex items-center gap-2">
                    <span className="hidden sm:inline">⌘S</span>
                    <Ghost onClick={() => setDraft(l.body)}>Отменить</Ghost>
                    <Primary className="py-1.5" onClick={save}>Сохранить</Primary>
                  </motion.div>
                )}
              </AnimatePresence>
            </div>
          </>
        )}
        {error && <p className="text-xs text-amber-fg">{error}</p>}
        {showVersions && <Versions id={l.id} onRestore={(b) => run(jobs.patchLetter(l.id, { body: b }).then(() => setShowVersions(false)))} />}
      </Card>
    </motion.div>
  );
}

export default function Letters({ app, onChange }: { app: ApplicationDetail; onChange: () => void }) {
  const [composing, setComposing] = useState(false);
  const pending = app.letters.some((l) => l.status === "pending");

  // Poll while Claude is writing; the worker on VM 220 usually needs 30–60 s.
  useEffect(() => {
    if (!pending) return;
    const t = setInterval(onChange, 3000);
    return () => clearInterval(t);
  }, [pending, onChange]);

  const letters = [...app.letters].sort((a, b) => Number(b.sent) - Number(a.sent) || b.id - a.id);

  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-xs font-semibold uppercase tracking-wide text-muted">Сопроводительные</h2>
        {letters.length > 0 && !composing && (
          <Ghost onClick={() => setComposing(true)} className="text-accent hover:text-accent"><Sparkles size={14} />Ещё письмо</Ghost>
        )}
      </div>
      {(letters.length === 0 || composing) && (
        <Composer app={app} onDone={() => { setComposing(false); onChange(); }} onCancel={letters.length ? () => setComposing(false) : undefined} />
      )}
      {letters.map((l) => <LetterCard key={l.id} l={l} onChange={onChange} />)}
    </section>
  );
}
