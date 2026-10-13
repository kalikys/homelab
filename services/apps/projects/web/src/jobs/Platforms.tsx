import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowRight, ExternalLink, Plus } from "lucide-react";
import { motion } from "motion/react";
import { Card, Empty, Skeleton } from "../ui";
import { jobs, type Platform } from "./api";
import { safeHref } from "./model";
import { Editable, Ghost, Label, Primary, inputCls } from "./ui";

const KIND: Record<string, string> = { board: "доска вакансий", ats: "система найма", social: "соцсеть", direct: "напрямую", recruiter: "через рекрутера", other: "другое" };

const slugify = (s: string) => s.toLowerCase().normalize("NFKD").replace(/[^\w\s-]/g, "").trim().replace(/[\s_]+/g, "-").replace(/[^a-z0-9-]/g, "").slice(0, 40);

function Stat({ n, label, accent }: { n: number | string; label: string; accent?: boolean }) {
  return (
    <div>
      <div className={`text-lg font-semibold tabular-nums ${accent ? "text-ok" : ""}`}>{n}</div>
      <div className="text-[11px] text-muted">{label}</div>
    </div>
  );
}

function PlatformCard({ p, onChange }: { p: Platform; onChange: () => void }) {
  const s = p.stats;
  const used = s.sent + s.inbound > 0;
  return (
    <motion.div layout initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }}>
      <Card className={`h-full space-y-3 ${used ? "" : "opacity-70"}`}>
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-1.5 font-medium">
              {p.name}
              {safeHref(p.url) && <a href={safeHref(p.url)} target="_blank" rel="noreferrer" className="text-muted hover:text-accent" title={p.url}><ExternalLink size={13} /></a>}
            </div>
            <div className="text-xs text-muted">{KIND[p.kind] ?? p.kind}</div>
          </div>
          {used && <Link to={`/jobs?p=${p.slug}&f=all`} className="inline-flex shrink-0 items-center gap-0.5 text-xs text-accent hover:underline">отклики<ArrowRight size={12} /></Link>}
        </div>
        {used ? (
          <>
            <div className="grid grid-cols-4 gap-2">
              <Stat n={s.sent} label="отправил" />
              <Stat n={s.reply_rate === null ? "—" : `${s.reply_rate}%`} label="ответили" />
              <Stat n={s.interviews} label="интервью" />
              <Stat n={s.offers} label="офферы" accent={s.offers > 0} />
            </div>
            {s.reply_rate !== null && (
              <div className="h-1.5 overflow-hidden rounded-full bg-line">
                <motion.div className="h-full rounded-full bg-[var(--s-replied)]" initial={{ width: 0 }} animate={{ width: `${s.reply_rate}%` }} transition={{ duration: 0.6 }} />
              </div>
            )}
            <div className="text-xs text-muted">
              {s.inbound > 0 && <>{s.inbound} входящих · </>}
              {s.median_reply_days !== null ? <>отвечают примерно за {s.median_reply_days} дн</> : "ответов пока нет"}
            </div>
          </>
        ) : <p className="text-sm text-muted">Откликов отсюда пока нет.</p>}
        <div className="border-t border-line pt-2">
          <Editable value={p.notes} multiline placeholder="Заметки: как заходить, что работает (пароли сюда не пиши)"
            onSave={(v) => jobs.patchPlatform(p.slug, { notes: v }).then(onChange)} />
        </div>
      </Card>
    </motion.div>
  );
}

export default function Platforms() {
  const [list, setList] = useState<Platform[] | null>(null);
  const [adding, setAdding] = useState(false);
  const [name, setName] = useState("");
  const [url, setUrl] = useState("");
  const [kind, setKind] = useState("board");
  const [error, setError] = useState("");

  const load = useCallback(() => jobs.platforms().then(setList).catch(() => setList([])), []);
  useEffect(() => { load(); }, [load]);

  async function add() {
    setError("");
    try {
      await jobs.createPlatform({ slug: slugify(name) || `p-${Date.now()}`, name: name.trim(), url: url.trim(), kind });
      setName(""); setUrl(""); setAdding(false); load();
    } catch (e) { setError(String(e)); }
  }

  const totals = (list ?? []).reduce((t, p) => ({ sent: t.sent + p.stats.sent, replied: t.replied + p.stats.replied }), { sent: 0, replied: 0 });

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Платформы</h1>
          <p className="mt-1 text-sm text-muted">
            Где откликаешься и где отвечают{totals.sent > 0 && <> · всего {totals.sent} отправлено, ответили {Math.round((100 * totals.replied) / totals.sent)}%</>}
          </p>
        </div>
        <Primary onClick={() => setAdding(true)}><Plus size={16} />Добавить</Primary>
      </header>

      {adding && (
        <Card className="space-y-3">
          <div className="grid gap-3 sm:grid-cols-3">
            <Label label="Название *"><input autoFocus value={name} onChange={(e) => setName(e.target.value)} placeholder="Djinni" className={inputCls} /></Label>
            <Label label="Ссылка"><input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://djinni.co" className={inputCls} /></Label>
            <Label label="Тип">
              <select value={kind} onChange={(e) => setKind(e.target.value)} className={inputCls}>
                {Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            </Label>
          </div>
          {error && <p className="text-xs text-amber-fg">{error}</p>}
          <div className="flex justify-end gap-2"><Ghost onClick={() => setAdding(false)}>Отмена</Ghost><Primary disabled={!name.trim()} onClick={add}>Сохранить</Primary></div>
        </Card>
      )}

      {list === null ? <Skeleton /> : list.length === 0 ? <Empty>Платформ нет.</Empty> : (
        <div className="grid gap-3 sm:grid-cols-2">{list.map((p) => <PlatformCard key={p.slug} p={p} onChange={load} />)}</div>
      )}
    </div>
  );
}
