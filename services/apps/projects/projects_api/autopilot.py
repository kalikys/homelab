"""Application autopilot (jobwatch on VM 220): its vacancy ledger, inbox events and daily stats.

jobwatch/dashsync.py pushes the ledger here after every run (POST /api/autopilot/sync, idempotent).
Every application the autopilot sent is also kept in the common pool (table application): sync finds it
by the jobwatch uid or creates it, attaches the letter that went out (marked sent) and the tailored CV.
"""
import re
import unicodedata
import shutil
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .db import CommitRoute, get_db, now
from .jobs import days_from_today, http_url, log, resolve_platform

router = APIRouter(prefix="/api/autopilot", route_class=CommitRoute)

SCHEMA = """
CREATE TABLE IF NOT EXISTS ap_vacancy(
  vid TEXT PRIMARY KEY, date TEXT NOT NULL DEFAULT '', at TEXT NOT NULL DEFAULT '', score INTEGER,
  reason TEXT NOT NULL DEFAULT '', lang TEXT NOT NULL DEFAULT '', title TEXT NOT NULL DEFAULT '',
  company TEXT NOT NULL DEFAULT '', url TEXT NOT NULL DEFAULT '', source TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL DEFAULT 'queued', channel TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '',
  letter TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '', answers TEXT NOT NULL DEFAULT '',
  application_id INTEGER REFERENCES application(id) ON DELETE SET NULL, has_cv INTEGER NOT NULL DEFAULT 0,
  manual_done_at TEXT, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS ap_event(
  key TEXT PRIMARY KEY, at TEXT NOT NULL DEFAULT '', date TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'other',
  channel TEXT NOT NULL DEFAULT '', company TEXT NOT NULL DEFAULT '', summary TEXT NOT NULL DEFAULT '',
  record_id TEXT, application_id INTEGER REFERENCES application(id) ON DELETE SET NULL);
CREATE TABLE IF NOT EXISTS ap_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ap_vacancy_date ON ap_vacancy(date, status);
CREATE INDEX IF NOT EXISTS ap_event_date ON ap_event(date, kind);
"""

STATUSES = {"queued", "sent", "manual", "failed", "skipped", "duplicate"}


def migrate(conn) -> None:
    """Columns added after the first release (2026-10-19): the formatted cover letter PDF."""
    cols = {r[1] for r in conn.execute("PRAGMA table_info(ap_vacancy)")}
    if "has_letter" not in cols:
        conn.execute("ALTER TABLE ap_vacancy ADD COLUMN has_letter INTEGER NOT NULL DEFAULT 0")
    # Telegram hello in two languages for manual items with a recruiter's handle (2026-10-19).
    for col in ("tg_handle", "tg_ru", "tg_en", "letter_ru", "letter_en"):
        if col not in cols:
            conn.execute(f"ALTER TABLE ap_vacancy ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
    # cover letter PDF per language, for the language switch on a manual card (2026-10-20)
    # Kalik removed a stale item from the manual queue (2026-10-20); jobwatch learns it from the sync answer.
    if "dismissed_at" not in cols:
        conn.execute("ALTER TABLE ap_vacancy ADD COLUMN dismissed_at TEXT")
    for col in ("has_letter_ru", "has_letter_en"):
        if col not in cols:
            conn.execute(f"ALTER TABLE ap_vacancy ADD COLUMN {col} INTEGER NOT NULL DEFAULT 0")
    # company country, for the country filter on the autopilot page (2026-11-08)
    if "country" not in cols:
        conn.execute("ALTER TABLE ap_vacancy ADD COLUMN country TEXT NOT NULL DEFAULT ''")
    # visa sponsorship stated by the employer: yes / no / '' (2026-11-09)
    if "visa" not in cols:
        conn.execute("ALTER TABLE ap_vacancy ADD COLUMN visa TEXT NOT NULL DEFAULT ''")
    # salary to name in an application form for a manual item, and why (2026-11-12)
    for col in ("salary", "salary_note"):
        if col not in cols:
            conn.execute(f"ALTER TABLE ap_vacancy ADD COLUMN {col} TEXT NOT NULL DEFAULT ''")
KINDS = {"interview", "rejection", "question", "offer", "other"}
VID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
# Platforms of the common pool for each autopilot channel.
ATS = {"greenhouse": ("greenhouse", "Greenhouse"), "lever": ("lever", "Lever"), "ashby": ("ashby", "Ashby")}
SKIP_BUCKETS = [
    ("нет продакшен-облака", r"aws|gcp|azure|облак|eks|gke|aks"),
    ("lead / principal", r"lead|head|principal|staff|руковод|тимлид"),
    ("язык", r"немец|словац|german|slovak|чешск|польск|c1\b|язык"),
    ("география", r"сша|\bus\b|usa|только из|only|регион|страна|eu work|резидент|граждан|location"),
    ("оплата", r"зарплат|оплат|волонт|руб|ниже"),
    ("не тот профиль", r"devsecops|appsec|тестир|qa\b|аналит|frontend|backend|java|\.net|разработ"),
    ("стек", r"kafka|argocd|windows|vmware|active directory|openstack|go\b|golang"),
]


class VacancyIn(BaseModel):
    vid: str = Field(pattern=VID.pattern)
    date: str = ""
    at: str = ""
    score: int | None = None
    reason: str = ""
    lang: str = ""
    title: str = ""
    company: str = ""
    url: str = ""
    source: str = ""
    status: str = "queued"
    channel: str = ""
    detail: str = ""
    letter: str = ""
    subject: str = ""
    answers: str = ""
    tg_handle: str = ""
    tg_ru: str = ""
    tg_en: str = ""
    letter_ru: str = ""
    letter_en: str = ""
    country: str = ""
    visa: str = ""
    salary: str = ""
    salary_note: str = ""
    app_uid: str | None = None  # uid of the jobwatch application record (jobwatch:<id>) when it exists


class EventIn(BaseModel):
    key: str = Field(min_length=1, max_length=300)
    at: str = ""
    date: str = ""
    kind: str = "other"
    channel: str = ""
    company: str = ""
    summary: str = ""
    record_id: str | None = None
    app_uid: str | None = None


class SyncIn(BaseModel):
    vacancies: list[VacancyIn] = []
    events: list[EventIn] = []
    meta: dict[str, str] = {}


# ---------- helpers

def files_dir(request: Request) -> Path:
    path = Path(request.app.state.files_dir) / "autopilot"
    path.mkdir(parents=True, exist_ok=True)
    return path


KINDS_OF_FILE = {"cv": ("{vid}.pdf", "CV"), "letter": ("{vid}.letter.pdf", "Cover-Letter"),
                 "letter_ru": ("{vid}.letter.ru.pdf", "Cover-Letter-RU"),
                 "letter_en": ("{vid}.letter.en.pdf", "Cover-Letter-EN")}
HAS_FILE = {"cv": "has_cv", "letter": "has_letter", "letter_ru": "has_letter_ru", "letter_en": "has_letter_en"}
POOL_FILES = ("cv", "letter")  # what went to the employer; language copies stay on the manual card


def file_path(request: Request, vid: str, kind: str = "cv") -> Path:
    if not VID.match(vid) or kind not in KINDS_OF_FILE:
        raise HTTPException(400, "bad vacancy id or file kind")
    return files_dir(request) / KINDS_OF_FILE[kind][0].format(vid=vid)


def cv_path(request: Request, vid: str) -> Path:
    return file_path(request, vid, "cv")


def file_name(company: str, kind: str) -> str:
    """Kalislav-Smirnov-CV-Logos.pdf: the name employers and Kalik see."""
    slug = re.sub(r"[^A-Za-z0-9]+", "-", unicodedata.normalize("NFKD", company or "").encode("ascii", "ignore")
                  .decode()).strip("-")[:40] or "Company"
    return f"Kalislav-Smirnov-{KINDS_OF_FILE[kind][1]}-{slug}.pdf"


def platform_for(conn, v: VacancyIn | sqlite3.Row) -> str | None:
    channel = (v["channel"] if isinstance(v, sqlite3.Row) else v.channel) or ""
    source = (v["source"] if isinstance(v, sqlite3.Row) else v.source) or ""
    c = channel.lower()
    if c.startswith("ats"):
        for key, (slug, name) in ATS.items():
            if key in c:
                conn.execute("INSERT OR IGNORE INTO platform(slug,name,url,kind,created_at) VALUES(?,?,?,?,?)",
                             (slug, name, "", "ats", now()))
                return slug
        if "smartrecruiters" in c:
            return "smartrecruiters"
        return resolve_platform(conn, "company-site")
    if c in ("hirify", "email", "telegram", "linkedin"):
        return c
    if c == "link":
        return "company-site"
    return resolve_platform(conn, source) if source else None


def clean_url(url: str) -> str:
    try:
        return http_url(url) or ""
    except ValueError:
        return ""


def ensure_application(conn, v, uid: str | None, status: str = "sent") -> int:
    """The application of the common pool for a vacancy the autopilot (or Kalik, by hand) sent."""
    row = None
    for u in filter(None, [uid, f"autopilot:{v['vid']}"]):
        row = conn.execute("SELECT id FROM application WHERE uid=?", (u,)).fetchone()
        if row:
            break
    vacancy_id = v["vid"] if str(v["vid"]).isdigit() else None
    if row is None and vacancy_id:
        row = conn.execute("SELECT id FROM application WHERE vacancy_id=? ORDER BY id LIMIT 1", (vacancy_id,)).fetchone()
    platform = platform_for(conn, v)
    ts = now()
    if row is None:
        applied = v["date"] or ts[:10]
        cur = conn.execute(
            "INSERT INTO application(company,title,url,platform,origin,fit,vacancy_id,notes,status,applied_at,"
            "next_action_at,uid,created_at,updated_at) VALUES(?,?,?,?,'outbound',?,?,?,?,?,?,?,?,?)",
            (v["company"] or "компания не указана", v["title"] or "?", clean_url(v["url"]), platform,
             v["score"] if v["score"] and 1 <= v["score"] <= 5 else None, vacancy_id,
             f"Автопилот: {v['channel']}", status, applied,
             (datetime.fromisoformat(applied) + timedelta(days=7)).date().isoformat() if len(applied) == 10 else None,
             uid or f"autopilot:{v['vid']}", ts, ts))
        aid = cur.lastrowid
        log(conn, aid, "created", "Отклик автопилота" if status == "sent" else "Отправлено вручную из очереди автопилота")
        return aid
    aid = row["id"]
    # Mirrored records come without the real channel and score: fill what is empty, never overwrite edits.
    conn.execute("UPDATE application SET platform=CASE WHEN platform IS NULL OR platform IN ('hirify','email') "
                 "AND ?<>'' THEN ? ELSE platform END, fit=COALESCE(fit, ?), updated_at=? WHERE id=?",
                 (platform or "", platform, v["score"] if v["score"] and 1 <= v["score"] <= 5 else None, ts, aid))
    return aid


def ensure_letter(conn, aid: int, v) -> None:
    body = (v["letter"] or "").strip()
    if not body:
        return
    if conn.execute("SELECT 1 FROM letter WHERE application_id=? AND body=?", (aid, body)).fetchone():
        return
    ts = now()
    conn.execute("UPDATE letter SET sent=0 WHERE application_id=?", (aid,))
    conn.execute("INSERT INTO letter(application_id,lang,body,status,sent,source,created_at,updated_at) "
                 "VALUES(?,?,?,'ready',1,'generated',?,?)", (aid, (v["lang"] or "en")[:12], body, ts, ts))
    log(conn, aid, "letter", "Письмо автопилота (ушло)")


def ensure_cv(conn, request: Request, aid: int, vid: str) -> None:
    """Attaches the tailored CV and the cover letter PDF of this vacancy to the application, once each."""
    v = conn.execute("SELECT company FROM ap_vacancy WHERE vid=?", (vid,)).fetchone()
    company = v["company"] if v else ""
    for kind in POOL_FILES:
        src = file_path(request, vid, kind)
        name = file_name(company, kind)
        if not src.is_file() or conn.execute("SELECT 1 FROM attachment WHERE application_id=? AND name=?",
                                             (aid, name)).fetchone():
            continue
        cur = conn.execute("INSERT INTO attachment(application_id,name,mime,size,path,created_at) VALUES(?,?,?,?,'',?)",
                           (aid, name, "application/pdf", src.stat().st_size, now()))
        root = Path(request.app.state.files_dir)
        folder = root / str(aid)
        folder.mkdir(parents=True, exist_ok=True)
        dst = folder / f"{cur.lastrowid}.pdf"
        shutil.copyfile(src, dst)
        conn.execute("UPDATE attachment SET path=? WHERE id=?", (str(dst.relative_to(root)), cur.lastrowid))


def link_to_pool(conn, request: Request, vid: str, uid: str | None, status: str = "sent") -> int:
    v = conn.execute("SELECT * FROM ap_vacancy WHERE vid=?", (vid,)).fetchone()
    aid = ensure_application(conn, v, uid, status)
    ensure_letter(conn, aid, v)
    ensure_cv(conn, request, aid, vid)
    conn.execute("UPDATE ap_vacancy SET application_id=? WHERE vid=?", (aid, vid))
    return aid


def bucket(reason: str) -> str:
    r = (reason or "").lower()
    for name, pattern in SKIP_BUCKETS:
        if re.search(pattern, r):
            return name
    return "другое"


def vacancy_json(row) -> dict:
    d = dict(row)
    d["url"] = clean_url(d["url"])
    return d


# ---------- sync from jobwatch

@router.post("/sync")
def sync(body: SyncIn, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    ts = now()
    for v in body.vacancies:
        status = v.status if v.status in STATUSES else "queued"
        conn.execute(
            "INSERT INTO ap_vacancy(vid,date,at,score,reason,lang,title,company,url,source,status,channel,detail,letter,"
            "subject,answers,tg_handle,tg_ru,tg_en,letter_ru,letter_en,country,visa,salary,salary_note,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(vid) DO UPDATE SET "
            "date=excluded.date, at=excluded.at, score=excluded.score, reason=excluded.reason, lang=excluded.lang, "
            "title=excluded.title, company=excluded.company, url=excluded.url, source=excluded.source, "
            "status=excluded.status, channel=excluded.channel, detail=excluded.detail, letter=excluded.letter, "
            "subject=excluded.subject, answers=excluded.answers, tg_handle=excluded.tg_handle, tg_ru=excluded.tg_ru, "
            "tg_en=excluded.tg_en, letter_ru=excluded.letter_ru, letter_en=excluded.letter_en, country=excluded.country, visa=excluded.visa, salary=excluded.salary, salary_note=excluded.salary_note, updated_at=excluded.updated_at",
            (v.vid, v.date, v.at, v.score, v.reason[:500], v.lang[:12], v.title[:300], v.company[:200], v.url[:1000],
             v.source[:40], status, v.channel[:80], v.detail[:1000], v.letter[:10000], v.subject[:300],
             v.answers[:10000], v.tg_handle[:64], v.tg_ru[:3000], v.tg_en[:3000], v.letter_ru[:10000], v.letter_en[:10000], v.country[:60], v.visa[:8], v.salary[:200], v.salary_note[:300], ts))
        if status == "sent":
            link_to_pool(conn, request, v.vid, v.app_uid)
    for e in body.events:
        aid = None
        if e.app_uid:
            row = conn.execute("SELECT id FROM application WHERE uid=?", (e.app_uid,)).fetchone()
            aid = row["id"] if row else None
        conn.execute(
            "INSERT INTO ap_event(key,at,date,kind,channel,company,summary,record_id,application_id) VALUES(?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET kind=excluded.kind, summary=excluded.summary, company=excluded.company, "
            "application_id=COALESCE(excluded.application_id, ap_event.application_id)",
            (e.key, e.at, e.date or e.at[:10], e.kind if e.kind in KINDS else "other", e.channel[:40], e.company[:200],
             e.summary[:1000], e.record_id, aid))
    for k, val in body.meta.items():
        conn.execute("INSERT INTO ap_meta(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET "
                     "value=excluded.value, updated_at=excluded.updated_at", (k[:60], str(val)[:2000], ts))
    conn.execute("INSERT INTO ap_meta(key,value,updated_at) VALUES('synced_at',?,?) ON CONFLICT(key) DO UPDATE SET "
                 "value=excluded.value, updated_at=excluded.updated_at", (ts, ts))
    need_cv = [r["vid"] for r in conn.execute(
        "SELECT vid FROM ap_vacancy WHERE has_cv=0 AND status IN ('sent','manual')")]
    need_letter = [r["vid"] for r in conn.execute(
        "SELECT vid FROM ap_vacancy WHERE has_letter=0 AND status IN ('sent','manual') AND letter != ''")]
    dismissed = [r["vid"] for r in conn.execute("SELECT vid FROM ap_vacancy WHERE dismissed_at IS NOT NULL")]
    need_lang = {f"need_letter_{lang}": [r["vid"] for r in conn.execute(
        f"SELECT vid FROM ap_vacancy WHERE has_letter_{lang}=0 AND status='manual' AND letter_{lang} != ''")]
        for lang in ("ru", "en")}
    return {"vacancies": len(body.vacancies), "events": len(body.events), "need_cv": need_cv,
            "need_letter": need_letter, **need_lang, "dismissed": dismissed}


@router.put("/vacancies/{vid}/{kind}", status_code=201)
async def upload_file(vid: str, kind: str, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """kind = cv | letter | letter_ru | letter_en: the tailored CV or a formatted cover letter, all PDF."""
    path = file_path(request, vid, kind)
    row = conn.execute("SELECT application_id FROM ap_vacancy WHERE vid=?", (vid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"vacancy not found: {vid}")
    data = await request.body()
    if not data.startswith(b"%PDF") or len(data) > 15 * 1024 * 1024:
        raise HTTPException(400, "expected a PDF up to 15 MB")
    path.write_bytes(data)
    conn.execute(f"UPDATE ap_vacancy SET {HAS_FILE[kind]}=1 WHERE vid=?", (vid,))
    if row["application_id"]:
        ensure_cv(conn, request, row["application_id"], vid)
    return {"vid": vid, "kind": kind, "size": len(data)}


@router.get("/vacancies/{vid}/{kind}")
def download_file(vid: str, kind: str, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    path = file_path(request, vid, kind)
    if not path.is_file():
        raise HTTPException(404, f"no {kind} for this vacancy")
    row = conn.execute("SELECT company FROM ap_vacancy WHERE vid=?", (vid,)).fetchone()
    return FileResponse(path, media_type="application/pdf", filename=file_name(row["company"] if row else "", kind),
                        content_disposition_type="inline", headers={"X-Content-Type-Options": "nosniff",
                                                                  "Cache-Control": "no-cache"})  # CVs get rebuilt in place


@router.post("/vacancies/{vid}/done")
def manual_done(vid: str, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    """Kalik sent a manual-queue application himself: it joins the common pool as sent."""
    row = conn.execute("SELECT * FROM ap_vacancy WHERE vid=?", (vid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"vacancy not found: {vid}")
    aid = link_to_pool(conn, request, vid, None)
    conn.execute("UPDATE ap_vacancy SET manual_done_at=? WHERE vid=?", (now(), vid))
    return vacancy_json(conn.execute("SELECT * FROM ap_vacancy WHERE vid=?", (vid,)).fetchone()) | {"application_id": aid}


@router.post("/vacancies/{vid}/dismiss")
def dismiss(vid: str, conn: sqlite3.Connection = Depends(get_db)):
    """The vacancy is gone or no longer interesting: off the manual queue, here and in jobwatch."""
    if conn.execute("UPDATE ap_vacancy SET dismissed_at=? WHERE vid=?", (now(), vid)).rowcount == 0:
        raise HTTPException(404, f"vacancy not found: {vid}")
    return vacancy_json(conn.execute("SELECT * FROM ap_vacancy WHERE vid=?", (vid,)).fetchone())


@router.post("/vacancies/{vid}/restore")
def restore(vid: str, conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("UPDATE ap_vacancy SET dismissed_at=NULL WHERE vid=?", (vid,)).rowcount == 0:
        raise HTTPException(404, f"vacancy not found: {vid}")
    return vacancy_json(conn.execute("SELECT * FROM ap_vacancy WHERE vid=?", (vid,)).fetchone())


@router.post("/vacancies/{vid}/undone")
def manual_undone(vid: str, conn: sqlite3.Connection = Depends(get_db)):
    conn.execute("UPDATE ap_vacancy SET manual_done_at=NULL WHERE vid=?", (vid,))
    row = conn.execute("SELECT * FROM ap_vacancy WHERE vid=?", (vid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"vacancy not found: {vid}")
    return vacancy_json(row)


# ---------- read

@router.get("/vacancies")
def list_vacancies(status: str | None = None, q: str | None = None, days: int = 30, limit: int = 300,
                   conn: sqlite3.Connection = Depends(get_db)):
    sql = ("SELECT v.*, a.status AS app_status FROM ap_vacancy v LEFT JOIN application a ON a.id=v.application_id "
           "WHERE v.date>=?")
    args: list = [days_from_today(-max(0, days - 1))]
    if status:
        sql += " AND v.status=?"
        args.append(status)
    if q:
        sql += " AND (ulower(v.company) LIKE ? OR ulower(v.title) LIKE ?)"
        args += [f"%{q.lower()}%"] * 2
    sql += " ORDER BY v.date DESC, v.at DESC, v.score DESC LIMIT ?"
    args.append(min(max(limit, 1), 1000))
    return [vacancy_json(r) for r in conn.execute(sql, args)]


@router.get("/mine")
def list_mine(conn: sqlite3.Connection = Depends(get_db)):
    """Everything Kalik sent by hand from the manual queue, all time, newest first, with the pool status."""
    sql = ("SELECT v.*, a.status AS app_status FROM ap_vacancy v LEFT JOIN application a ON a.id=v.application_id "
           "WHERE v.manual_done_at IS NOT NULL ORDER BY v.manual_done_at DESC")
    return [vacancy_json(r) for r in conn.execute(sql)]


@router.get("/events")
def list_events(days: int = 30, conn: sqlite3.Connection = Depends(get_db)):
    order = "CASE kind WHEN 'offer' THEN 0 WHEN 'interview' THEN 1 WHEN 'question' THEN 2 WHEN 'rejection' THEN 3 ELSE 4 END"
    return [dict(r) for r in conn.execute(
        f"SELECT * FROM ap_event WHERE date>=? ORDER BY {order}, at DESC", (days_from_today(-max(0, days - 1)),))]


@router.get("/stats")
def stats(days: int = 30, conn: sqlite3.Connection = Depends(get_db)):
    days = min(max(days, 1), 365)
    since = days_from_today(-(days - 1))
    today = days_from_today(0)
    rows = conn.execute("SELECT date, CASE WHEN dismissed_at IS NOT NULL THEN 'skipped' ELSE status END AS status, "
                        "channel, reason, manual_done_at FROM ap_vacancy WHERE date>=?",
                        (since,)).fetchall()

    def count(rs):
        out = {"sent": 0, "manual": 0, "manual_done": 0, "failed": 0, "skipped": 0, "queued": 0}
        for r in rs:
            out[r["status"]] = out.get(r["status"], 0) + 1
            if r["status"] == "manual" and r["manual_done_at"]:
                out["manual_done"] += 1
        return out

    series = []
    start = datetime.fromisoformat(since).date()
    by_date: dict[str, list] = {}
    for r in rows:
        by_date.setdefault(r["date"], []).append(r)
    # Bars count what actually went out that day: the autopilot's own sends (by the day it found and sent them)
    # plus the handed-over ones Kalik marked as sent, by the day he marked them, whenever they were found.
    mine: dict[str, int] = {}
    for r in conn.execute("SELECT substr(manual_done_at,1,10) AS d, count(*) AS n FROM ap_vacancy "
                          "WHERE manual_done_at IS NOT NULL AND manual_done_at>=? GROUP BY 1", (since,)):
        mine[r["d"]] = r["n"]
    for i in range(days):
        d = (start + timedelta(days=i)).isoformat()
        c = count(by_date.get(d, []))
        auto, own = c["sent"], mine.get(d, 0)
        series.append({"date": d, "sent": auto + own, "auto": auto, "mine": own,
                       "manual": c["manual"], "skipped": c["skipped"]})

    channels: dict[str, int] = {}
    for r in rows:
        if r["status"] == "sent":
            ch = (r["channel"] or "?").split(":")[0]
            channels[ch] = channels.get(ch, 0) + 1
    reasons: dict[str, int] = {}
    for r in rows:
        if r["status"] == "skipped":
            b = bucket(r["reason"])
            reasons[b] = reasons.get(b, 0) + 1

    # Funnel of what was sent, from the common pool (statuses there move with replies).
    funnel = {"sent": 0, "replied": 0, "interview": 0, "offer": 0, "rejected": 0}
    for r in conn.execute("SELECT a.status FROM ap_vacancy v JOIN application a ON a.id=v.application_id "
                          "WHERE v.date>=? AND (v.status='sent' OR v.manual_done_at IS NOT NULL)", (since,)):
        funnel["sent"] += 1
        s = r["status"]
        if s in ("replied", "interview", "offer", "rejected"):
            funnel["replied"] += 1
        if s in ("interview", "offer"):
            funnel["interview"] += 1
        if s == "offer":
            funnel["offer"] += 1
        if s == "rejected":
            funnel["rejected"] += 1
    events: dict[str, int] = {}
    events_today: dict[str, int] = {}
    for r in conn.execute("SELECT date, kind FROM ap_event WHERE date>=?", (since,)):
        events[r["kind"]] = events.get(r["kind"], 0) + 1
        if r["date"] == today:
            events_today[r["kind"]] = events_today.get(r["kind"], 0) + 1
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM ap_meta")}
    queue = conn.execute("SELECT COUNT(*) FROM ap_vacancy WHERE status='manual' AND manual_done_at IS NULL "
                         "AND dismissed_at IS NULL").fetchone()[0]
    return {
        "days": days, "today": count(by_date.get(today, [])) | {"events": events_today},
        "period": count(rows) | {"events": events}, "series": series, "channels": channels,
        "skip_reasons": sorted(([k, v] for k, v in reasons.items()), key=lambda kv: -kv[1]),
        "funnel": funnel, "manual_open": queue, "meta": meta,
    }
