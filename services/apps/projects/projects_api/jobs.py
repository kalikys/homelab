"""Job applications: platforms, contacts, applications, cover letters, attachments, and the letter queue."""
import re
import sqlite3
import statistics
import unicodedata
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import AfterValidator, BaseModel, Field
from typing import Annotated

from .db import CommitRoute, get_db, now

router = APIRouter(prefix="/api/jobs", route_class=CommitRoute)

SCHEMA = """
CREATE TABLE IF NOT EXISTS platform(
  slug TEXT PRIMARY KEY, name TEXT NOT NULL, url TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL DEFAULT 'other',
  notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS contact(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL, company TEXT NOT NULL DEFAULT '', role TEXT NOT NULL DEFAULT '',
  email TEXT NOT NULL DEFAULT '', phone TEXT NOT NULL DEFAULT '', telegram TEXT NOT NULL DEFAULT '',
  linkedin TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS application(
  id INTEGER PRIMARY KEY, company TEXT NOT NULL, title TEXT NOT NULL, url TEXT NOT NULL DEFAULT '',
  platform TEXT REFERENCES platform(slug) ON DELETE SET NULL, origin TEXT NOT NULL DEFAULT 'outbound',
  contact_id INTEGER REFERENCES contact(id) ON DELETE SET NULL,
  location TEXT NOT NULL DEFAULT '', work_format TEXT NOT NULL DEFAULT '', salary TEXT NOT NULL DEFAULT '',
  fit INTEGER, vacancy_text TEXT NOT NULL DEFAULT '', vacancy_id TEXT, notes TEXT NOT NULL DEFAULT '',
  status TEXT NOT NULL, applied_at TEXT, next_action_at TEXT, next_action TEXT NOT NULL DEFAULT '',
  replied_at TEXT, interview_at TEXT, uid TEXT UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS letter(
  id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL REFERENCES application(id) ON DELETE CASCADE,
  lang TEXT NOT NULL DEFAULT 'en', body TEXT NOT NULL DEFAULT '', status TEXT NOT NULL DEFAULT 'ready',
  wish TEXT NOT NULL DEFAULT '', error TEXT, sent INTEGER NOT NULL DEFAULT 0, source TEXT NOT NULL DEFAULT 'manual',
  requested_at TEXT, claimed_at TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS letter_version(
  id INTEGER PRIMARY KEY, letter_id INTEGER NOT NULL REFERENCES letter(id) ON DELETE CASCADE,
  body TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS attachment(
  id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL REFERENCES application(id) ON DELETE CASCADE,
  name TEXT NOT NULL, mime TEXT NOT NULL, size INTEGER NOT NULL, path TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS job_event(
  id INTEGER PRIMARY KEY, application_id INTEGER NOT NULL REFERENCES application(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, text TEXT NOT NULL, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS application_status ON application(status, next_action_at);
CREATE INDEX IF NOT EXISTS letter_app ON letter(application_id);
CREATE INDEX IF NOT EXISTS letter_queue ON letter(status, id);
CREATE INDEX IF NOT EXISTS job_event_app ON job_event(application_id, at);
"""

PLATFORMS = [
    ("hirify", "Hirify", "https://hirify.me", "board"), ("profesia", "Profesia", "https://www.profesia.sk", "board"),
    ("linkedin", "LinkedIn", "https://www.linkedin.com/jobs", "social"),
    ("smartrecruiters", "SmartRecruiters", "https://jobs.smartrecruiters.com", "ats"),
    ("himalayas", "Himalayas", "https://himalayas.app", "board"),
    ("weworkremotely", "We Work Remotely", "https://weworkremotely.com", "board"),
    ("remotive", "Remotive", "https://remotive.com", "board"), ("company-site", "Сайт компании", "", "direct"),
    ("recruiter", "Рекрутер", "", "recruiter"), ("email", "Email", "", "direct"), ("telegram", "Telegram", "", "social"),
]

Status = Literal["draft", "inbound", "sent", "replied", "interview", "offer", "rejected", "declined", "silent"]
STATUS_LABELS = {"draft": "готовлю", "inbound": "HR написала", "sent": "отправил", "replied": "ответили",
                 "interview": "интервью", "offer": "оффер", "rejected": "отказ", "declined": "сам отказался",
                 "silent": "тишина"}
FINAL = {"offer", "rejected", "declined"}
NEXT_DAYS = {"sent": 7, "inbound": 3, "replied": 3}
ANSWERED = {"replied", "interview", "offer", "rejected"}

CLAIM_STALE = timedelta(minutes=4)  # worker gives claude 3 minutes
PENDING_TIMEOUT = timedelta(minutes=10)
MAX_FILE = 15 * 1024 * 1024
MIME = {"pdf": "application/pdf", "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "txt": "text/plain; charset=utf-8", "md": "text/markdown; charset=utf-8", "html": "text/plain; charset=utf-8",
        "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg", "webp": "image/webp"}
INLINE = {"png", "jpg", "jpeg", "webp"}


# ---------- models

def http_url(v: str | None) -> str | None:
    """Links are rendered as <a href>: only http(s), so a javascript: or data: URL can never run."""
    if v is None or v.strip() == "":
        return v.strip() if v is not None else None
    v = v.strip()
    if not re.match(r"^https?://", v, re.I):
        raise ValueError("url must start with http:// or https://")
    return v


Url = Annotated[str, AfterValidator(http_url)]
OptUrl = Annotated[str | None, AfterValidator(http_url)]


class PlatformIn(BaseModel):
    slug: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")
    name: str = Field(min_length=1)
    url: Url = ""
    kind: Literal["board", "ats", "social", "direct", "recruiter", "other"] = "other"
    notes: str = ""


class PlatformPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    url: OptUrl = None
    kind: Literal["board", "ats", "social", "direct", "recruiter", "other"] | None = None
    notes: str | None = None


class ContactIn(BaseModel):
    name: str = Field(min_length=1)
    company: str = ""
    role: str = ""
    email: str = ""
    phone: str = ""
    telegram: str = ""
    linkedin: str = ""
    notes: str = ""


class ContactPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1)
    company: str | None = None
    role: str | None = None
    email: str | None = None
    phone: str | None = None
    telegram: str | None = None
    linkedin: str | None = None
    notes: str | None = None


class GenerateIn(BaseModel):
    lang: str = Field(default="en", min_length=2, max_length=12)
    wish: str = ""


class ApplicationIn(BaseModel):
    company: str = Field(min_length=1)
    title: str = Field(min_length=1)
    url: Url = ""
    platform: str | None = None
    origin: Literal["outbound", "inbound"] = "outbound"
    contact_id: int | None = None
    contact: ContactIn | None = None
    location: str = ""
    work_format: str = ""
    salary: str = ""
    fit: int | None = Field(default=None, ge=1, le=5)
    vacancy_text: str = ""
    vacancy_id: str | None = Field(default=None, pattern=r"^\d{1,12}$")
    notes: str = ""
    status: Status | None = None
    applied_at: str | None = None
    next_action_at: str | None = None
    next_action: str = ""
    uid: str | None = None
    generate: GenerateIn | None = None


class ApplicationPatch(BaseModel):
    company: str | None = Field(default=None, min_length=1)
    title: str | None = Field(default=None, min_length=1)
    url: OptUrl = None
    platform: str | None = None
    origin: Literal["outbound", "inbound"] | None = None
    contact_id: int | None = None
    location: str | None = None
    work_format: str | None = None
    salary: str | None = None
    fit: int | None = Field(default=None, ge=1, le=5)
    vacancy_text: str | None = None
    vacancy_id: str | None = Field(default=None, pattern=r"^\d{1,12}$")
    notes: str | None = None
    status: Status | None = None
    applied_at: str | None = None
    next_action_at: str | None = None
    next_action: str | None = None
    note: str | None = None  # free text for the history entry, not stored on the application


class LetterIn(BaseModel):
    lang: str = Field(default="en", min_length=2, max_length=12)
    body: str = Field(min_length=1)
    sent: bool = False
    source: Literal["manual", "imported", "generated"] = "manual"


class LetterPatch(BaseModel):
    lang: str | None = Field(default=None, min_length=2, max_length=12)
    body: str | None = Field(default=None, min_length=1)
    sent: bool | None = None


class DoneIn(BaseModel):
    body: str = Field(min_length=1)


class FailedIn(BaseModel):
    error: str = Field(min_length=1)


# ---------- helpers

def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def days_from_today(n: int) -> str:
    return (datetime.now(timezone.utc).date() + timedelta(days=n)).isoformat()


def ago(delta: timedelta) -> str:
    return (datetime.now(timezone.utc) - delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def seed(conn: sqlite3.Connection) -> None:
    ts = now()
    conn.executemany("INSERT OR IGNORE INTO platform(slug,name,url,kind,created_at) VALUES(?,?,?,?,?)",
                     [(*p, ts) for p in PLATFORMS])


def slugify(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:40] or "other"


def resolve_platform(conn, value: str | None) -> str | None:
    """Accept a slug or a display name; unknown platforms are created so the user is never blocked."""
    if not value:
        return None
    row = conn.execute("SELECT slug FROM platform WHERE slug=? OR ulower(name)=?", (value, value.lower())).fetchone()
    if row:
        return row["slug"]
    slug = slugify(value)
    conn.execute("INSERT OR IGNORE INTO platform(slug,name,created_at) VALUES(?,?,?)", (slug, value, now()))
    return slug


def log(conn, app_id: int, kind: str, text: str) -> None:
    conn.execute("INSERT INTO job_event(application_id,kind,text,at) VALUES(?,?,?,?)", (app_id, kind, text, now()))


def get_app(conn, aid: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM application WHERE id=?", (aid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"application not found: {aid}")
    return row


def get_letter(conn, lid: int) -> sqlite3.Row:
    expire(conn)
    row = conn.execute("SELECT * FROM letter WHERE id=?", (lid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"letter not found: {lid}")
    return row


def get_contact(conn, cid: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM contact WHERE id=?", (cid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"contact not found: {cid}")
    return row


APP_LIST = """
SELECT a.*, p.name AS platform_name, c.name AS contact_name,
  (SELECT COUNT(*) FROM letter l WHERE l.application_id=a.id) AS letters_count,
  (SELECT COUNT(*) FROM letter l WHERE l.application_id=a.id AND l.sent=1) AS letter_sent,
  (SELECT COUNT(*) FROM attachment f WHERE f.application_id=a.id) AS files_count
FROM application a LEFT JOIN platform p ON p.slug=a.platform LEFT JOIN contact c ON c.id=a.contact_id
"""


def app_json(conn, aid: int) -> dict:
    return dict(conn.execute(APP_LIST + " WHERE a.id=?", (aid,)).fetchone())


def letter_json(row) -> dict:
    d = dict(row)
    d["sent"] = bool(d["sent"])
    return d


def expire(conn) -> None:
    conn.execute("UPDATE letter SET status='failed', error='Не дождались генерации за 10 минут', updated_at=?"
                 " WHERE status='pending' AND requested_at < ?", (now(), ago(PENDING_TIMEOUT)))


def status_fields(old: dict | None, new_status: str, explicit: dict) -> dict:
    """Dates that follow a status change, unless the caller set them explicitly."""
    out: dict = {}
    if new_status in FINAL:
        out["next_action_at"] = None
    elif new_status in NEXT_DAYS:
        out["next_action_at"] = days_from_today(NEXT_DAYS[new_status])
    if new_status in ("sent", "inbound") and not (old and old["applied_at"]):
        out["applied_at"] = today()
    if new_status in ANSWERED and not (old and old["replied_at"]):
        out["replied_at"] = now()
    if new_status in ("interview", "offer") and not (old and old["interview_at"]):
        out["interview_at"] = now()
    return {k: v for k, v in out.items() if k not in explicit}


def find_or_create_contact(conn, c: ContactIn) -> int:
    if c.email:
        row = conn.execute("SELECT id FROM contact WHERE ulower(email)=?", (c.email.lower(),)).fetchone()
        if row:
            return row["id"]
    else:
        row = conn.execute("SELECT id FROM contact WHERE ulower(name)=? AND ulower(company)=?",
                           (c.name.lower(), c.company.lower())).fetchone()
        if row:
            return row["id"]
    ts = now()
    cur = conn.execute(
        "INSERT INTO contact(name,company,role,email,phone,telegram,linkedin,notes,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)", (*c.model_dump().values(), ts, ts))
    return cur.lastrowid


def queue_letter(conn, aid: int, g: GenerateIn) -> int:
    ts = now()
    cur = conn.execute(
        "INSERT INTO letter(application_id,lang,status,wish,source,requested_at,created_at,updated_at)"
        " VALUES(?,?,'pending',?,'generated',?,?,?)", (aid, g.lang, g.wish, ts, ts, ts))
    log(conn, aid, "letter", f"Запрошено письмо ({g.lang})" + (f": {g.wish}" if g.wish else ""))
    return cur.lastrowid


# ---------- platforms

def platform_stats(conn) -> dict[str, dict]:
    stats: dict[str, dict] = {}
    rows = conn.execute("SELECT platform, origin, status, applied_at, replied_at, interview_at FROM application")
    delays: dict[str, list[float]] = {}
    for r in rows:
        s = stats.setdefault(r["platform"], {"sent": 0, "inbound": 0, "replied": 0, "interviews": 0, "offers": 0})
        if r["origin"] == "inbound":
            s["inbound"] += 1
        elif r["status"] != "draft":
            s["sent"] += 1
            if r["replied_at"]:
                s["replied"] += 1
                if r["applied_at"]:
                    d = (datetime.fromisoformat(r["replied_at"].replace("Z", "+00:00")).date()
                         - datetime.fromisoformat(r["applied_at"]).date()).days
                    delays.setdefault(r["platform"], []).append(max(d, 0))
        if r["interview_at"]:
            s["interviews"] += 1
        if r["status"] == "offer":
            s["offers"] += 1
    for slug, s in stats.items():
        s["reply_rate"] = round(100 * s["replied"] / s["sent"]) if s["sent"] else None
        s["median_reply_days"] = statistics.median(delays[slug]) if slug in delays else None
    return stats


@router.get("/platforms")
def list_platforms(conn: sqlite3.Connection = Depends(get_db)):
    stats = platform_stats(conn)
    empty = {"sent": 0, "inbound": 0, "replied": 0, "interviews": 0, "offers": 0, "reply_rate": None, "median_reply_days": None}
    rows = conn.execute("SELECT * FROM platform ORDER BY name")
    out = [dict(r) | {"stats": stats.get(r["slug"], empty)} for r in rows]
    return sorted(out, key=lambda p: (-(p["stats"]["sent"] + p["stats"]["inbound"]), p["name"].lower()))


@router.post("/platforms", status_code=201)
def create_platform(body: PlatformIn, conn: sqlite3.Connection = Depends(get_db)):
    if conn.execute("SELECT 1 FROM platform WHERE slug=?", (body.slug,)).fetchone():
        raise HTTPException(409, f"platform exists: {body.slug}")
    conn.execute("INSERT INTO platform(slug,name,url,kind,notes,created_at) VALUES(?,?,?,?,?,?)",
                 (body.slug, body.name, body.url, body.kind, body.notes, now()))
    return dict(conn.execute("SELECT * FROM platform WHERE slug=?", (body.slug,)).fetchone())


@router.patch("/platforms/{slug}")
def patch_platform(slug: str, body: PlatformPatch, conn: sqlite3.Connection = Depends(get_db)):
    if not conn.execute("SELECT 1 FROM platform WHERE slug=?", (slug,)).fetchone():
        raise HTTPException(404, f"platform not found: {slug}")
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    if any(v is None for v in fields.values()):
        raise HTTPException(400, "fields may not be null")
    if fields:
        conn.execute(f"UPDATE platform SET {', '.join(f'{k}=?' for k in fields)} WHERE slug=?", (*fields.values(), slug))
    return dict(conn.execute("SELECT * FROM platform WHERE slug=?", (slug,)).fetchone())


# ---------- contacts

@router.get("/contacts")
def list_contacts(conn: sqlite3.Connection = Depends(get_db)):
    return [dict(r) for r in conn.execute(
        "SELECT c.*, (SELECT COUNT(*) FROM application a WHERE a.contact_id=c.id) AS applications_count"
        " FROM contact c ORDER BY c.updated_at DESC, c.id DESC")]


@router.post("/contacts", status_code=201)
def create_contact(body: ContactIn, conn: sqlite3.Connection = Depends(get_db)):
    ts = now()
    cur = conn.execute(
        "INSERT INTO contact(name,company,role,email,phone,telegram,linkedin,notes,created_at,updated_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)", (*body.model_dump().values(), ts, ts))
    return dict(get_contact(conn, cur.lastrowid))


@router.get("/contacts/{cid}")
def contact_detail(cid: int, conn: sqlite3.Connection = Depends(get_db)):
    d = dict(get_contact(conn, cid))
    d["applications"] = [dict(r) for r in conn.execute(APP_LIST + " WHERE a.contact_id=? ORDER BY a.id DESC", (cid,))]
    return d


@router.patch("/contacts/{cid}")
def patch_contact(cid: int, body: ContactPatch, conn: sqlite3.Connection = Depends(get_db)):
    get_contact(conn, cid)
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    if any(v is None for v in fields.values()):
        raise HTTPException(400, "fields may not be null")
    if fields:
        fields["updated_at"] = now()
        conn.execute(f"UPDATE contact SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), cid))
    return dict(get_contact(conn, cid))


@router.delete("/contacts/{cid}", status_code=204)
def delete_contact(cid: int, conn: sqlite3.Connection = Depends(get_db)):
    get_contact(conn, cid)
    conn.execute("DELETE FROM contact WHERE id=?", (cid,))
    return Response(status_code=204)


# ---------- applications

@router.get("/applications")
def list_applications(status: str | None = None, platform: str | None = None, origin: str | None = None,
                      q: str | None = None, conn: sqlite3.Connection = Depends(get_db)):
    where, args = [], []
    for col, val in (("a.status", status), ("a.platform", platform), ("a.origin", origin)):
        if val:
            where.append(f"{col}=?")
            args.append(val)
    if q and q.strip():
        like = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        where.append("(" + " OR ".join(f"ulower({c}) LIKE ? ESCAPE '\\'" for c in
                                      ("a.company", "a.title", "a.notes", "a.location", "COALESCE(c.name,'')")) + ")")
        args += [like] * 5
    sql = APP_LIST + (" WHERE " + " AND ".join(where) if where else "")
    return [dict(r) for r in conn.execute(sql + " ORDER BY a.updated_at DESC, a.id DESC", args)]


@router.post("/applications", status_code=201)
def create_application(body: ApplicationIn, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    if body.uid:
        old = conn.execute("SELECT id FROM application WHERE uid=?", (body.uid,)).fetchone()
        if old:
            response.status_code = 200
            return app_json(conn, old["id"])
    status = body.status or ("inbound" if body.origin == "inbound" else "sent")
    contact_id = body.contact_id
    if contact_id is not None:
        get_contact(conn, contact_id)
    elif body.contact:
        contact_id = find_or_create_contact(conn, body.contact)
    explicit = {k for k in ("applied_at", "next_action_at") if getattr(body, k) is not None}
    dates = {"applied_at": body.applied_at, "next_action_at": body.next_action_at, "replied_at": None, "interview_at": None}
    dates |= status_fields(None, status, explicit)
    ts = now()
    cur = conn.execute(
        "INSERT INTO application(company,title,url,platform,origin,contact_id,location,work_format,salary,fit,"
        "vacancy_text,vacancy_id,notes,status,applied_at,next_action_at,next_action,replied_at,interview_at,uid,"
        "created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (body.company, body.title, body.url, resolve_platform(conn, body.platform), body.origin, contact_id,
         body.location, body.work_format, body.salary, body.fit, body.vacancy_text, body.vacancy_id, body.notes,
         status, dates["applied_at"], dates["next_action_at"], body.next_action, dates["replied_at"],
         dates["interview_at"], body.uid, ts, ts))
    aid = cur.lastrowid
    log(conn, aid, "created", ("HR написала сама" if body.origin == "inbound" else "Отклик создан")
        + f" · {STATUS_LABELS[status]}")
    if body.generate:
        queue_letter(conn, aid, body.generate)
    return app_json(conn, aid)


@router.get("/applications/{aid}")
def application_detail(aid: int, conn: sqlite3.Connection = Depends(get_db)):
    get_app(conn, aid)
    expire(conn)
    d = app_json(conn, aid)
    c = conn.execute("SELECT * FROM contact WHERE id=?", (d["contact_id"],)).fetchone() if d["contact_id"] else None
    d["contact"] = dict(c) if c else None
    d["letters"] = [letter_json(r) for r in conn.execute(
        "SELECT * FROM letter WHERE application_id=? ORDER BY id", (aid,))]
    d["attachments"] = [{k: r[k] for k in ("id", "name", "mime", "size", "created_at")} for r in conn.execute(
        "SELECT * FROM attachment WHERE application_id=? ORDER BY id", (aid,))]
    d["events"] = [dict(r) for r in conn.execute(
        "SELECT * FROM job_event WHERE application_id=? ORDER BY at DESC, id DESC", (aid,))]
    return d


EDIT_LABELS = {"company": "компания", "title": "должность", "url": "ссылка", "platform": "платформа",
               "contact_id": "контакт", "location": "локация", "work_format": "формат", "salary": "зарплата",
               "fit": "оценка", "vacancy_text": "текст вакансии", "vacancy_id": "id вакансии", "notes": "заметки",
               "applied_at": "дата отклика", "next_action_at": "дата следующего шага", "next_action": "следующий шаг",
               "origin": "источник"}


@router.patch("/applications/{aid}")
def patch_application(aid: int, body: ApplicationPatch, conn: sqlite3.Connection = Depends(get_db)):
    row = get_app(conn, aid)
    fields = {k: getattr(body, k) for k in body.model_fields_set if k != "note"}
    nullable = {"contact_id", "fit", "vacancy_id", "applied_at", "next_action_at", "platform"}
    for k, v in fields.items():
        if v is None and k not in nullable:
            raise HTTPException(400, f"{k}: may not be null")
    if "platform" in fields:
        fields["platform"] = resolve_platform(conn, fields["platform"])
    if fields.get("contact_id") is not None:
        get_contact(conn, fields["contact_id"])
    changed = {k: v for k, v in fields.items() if row[k] != v}
    if "status" in changed:
        changed |= status_fields(dict(row), changed["status"], set(fields))
        log(conn, aid, "status", f"{STATUS_LABELS[row['status']]} → {STATUS_LABELS[changed['status']]}"
            + (f": {body.note}" if body.note else ""))
    elif body.note:
        log(conn, aid, "note", body.note)
    edited = [EDIT_LABELS[k] for k in changed if k in EDIT_LABELS and k in fields]
    if edited and "status" not in changed:
        log(conn, aid, "edited", "Изменено: " + ", ".join(edited))
    if changed:
        changed["updated_at"] = now()
        conn.execute(f"UPDATE application SET {', '.join(f'{k}=?' for k in changed)} WHERE id=?", (*changed.values(), aid))
    return app_json(conn, aid)


@router.delete("/applications/{aid}", status_code=204)
def delete_application(aid: int, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    get_app(conn, aid)
    conn.execute("DELETE FROM application WHERE id=?", (aid,))
    folder = files_root(request) / str(aid)
    if folder.is_dir():
        for f in folder.iterdir():
            f.unlink(missing_ok=True)
        folder.rmdir()
    return Response(status_code=204)


@router.get("/summary")
def summary(conn: sqlite3.Connection = Depends(get_db)):
    final = ",".join(f"'{s}'" for s in FINAL)
    due = conn.execute(APP_LIST + f" WHERE a.next_action_at IS NOT NULL AND a.next_action_at<=? AND a.status NOT IN ({final})"
                       " ORDER BY a.next_action_at, a.id", (today(),))
    silent = conn.execute(APP_LIST + " WHERE a.status='sent' AND a.updated_at<? ORDER BY a.updated_at",
                          (ago(timedelta(days=14)),))
    counts = {s: 0 for s in STATUS_LABELS}
    for r in conn.execute("SELECT status, COUNT(*) n FROM application GROUP BY status"):
        counts[r["status"]] = r["n"]
    week = conn.execute("SELECT COUNT(*) FROM application WHERE origin='outbound' AND applied_at>=?",
                        (days_from_today(-6),)).fetchone()[0]
    pending = conn.execute("SELECT COUNT(*) FROM letter WHERE status='pending'").fetchone()[0]
    return {"due": [dict(r) for r in due], "silent": [dict(r) for r in silent], "counts": counts,
            "sent_this_week": week, "letters_pending": pending}


# ---------- letters

@router.post("/applications/{aid}/letters", status_code=201)
def create_letter(aid: int, body: LetterIn, conn: sqlite3.Connection = Depends(get_db)):
    get_app(conn, aid)
    ts = now()
    if body.sent:
        conn.execute("UPDATE letter SET sent=0 WHERE application_id=?", (aid,))
    cur = conn.execute(
        "INSERT INTO letter(application_id,lang,body,status,sent,source,created_at,updated_at) VALUES(?,?,?,'ready',?,?,?,?)",
        (aid, body.lang, body.body, int(body.sent), body.source, ts, ts))
    log(conn, aid, "letter", f"Добавлено письмо ({body.lang})")
    return letter_json(get_letter(conn, cur.lastrowid))


@router.post("/applications/{aid}/letters/generate", status_code=201)
def generate_letter(aid: int, body: GenerateIn, conn: sqlite3.Connection = Depends(get_db)):
    get_app(conn, aid)
    return letter_json(get_letter(conn, queue_letter(conn, aid, body)))


@router.get("/letters/{lid}")
def letter_detail(lid: int, conn: sqlite3.Connection = Depends(get_db)):
    d = letter_json(get_letter(conn, lid))
    d["versions"] = [dict(r) for r in conn.execute(
        "SELECT id, body, created_at FROM letter_version WHERE letter_id=? ORDER BY id DESC", (lid,))]
    return d


@router.patch("/letters/{lid}")
def patch_letter(lid: int, body: LetterPatch, conn: sqlite3.Connection = Depends(get_db)):
    row = get_letter(conn, lid)
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    if any(v is None for v in fields.values()):
        raise HTTPException(400, "fields may not be null")
    if "body" in fields and row["status"] == "pending":
        raise HTTPException(409, "letter is still being generated")
    ts = now()
    if "body" in fields and fields["body"] != row["body"]:
        if row["body"]:
            conn.execute("INSERT INTO letter_version(letter_id,body,created_at) VALUES(?,?,?)", (lid, row["body"], ts))
        log(conn, row["application_id"], "letter", f"Письмо ({row['lang']}) перезаписано")
        fields["status"], fields["error"] = "ready", None
    if fields.get("sent"):
        conn.execute("UPDATE letter SET sent=0 WHERE application_id=? AND id!=?", (row["application_id"], lid))
        log(conn, row["application_id"], "letter", f"Письмо ({fields.get('lang', row['lang'])}) отмечено как отправленное")
    if "sent" in fields:
        fields["sent"] = int(fields["sent"])
    if fields:
        fields["updated_at"] = ts
        conn.execute(f"UPDATE letter SET {', '.join(f'{k}=?' for k in fields)} WHERE id=?", (*fields.values(), lid))
    return letter_json(get_letter(conn, lid))


@router.delete("/letters/{lid}", status_code=204)
def delete_letter(lid: int, conn: sqlite3.Connection = Depends(get_db)):
    row = get_letter(conn, lid)
    conn.execute("DELETE FROM letter WHERE id=?", (lid,))
    log(conn, row["application_id"], "letter", f"Письмо ({row['lang']}) удалено")
    return Response(status_code=204)


@router.post("/letters/{lid}/retry")
def retry_letter(lid: int, conn: sqlite3.Connection = Depends(get_db)):
    row = get_letter(conn, lid)
    if row["status"] != "failed":
        raise HTTPException(409, "only a failed letter can be retried")
    ts = now()
    conn.execute("UPDATE letter SET status='pending', error=NULL, requested_at=?, claimed_at=NULL, updated_at=? WHERE id=?",
                 (ts, ts, lid))
    return letter_json(get_letter(conn, lid))


# ---------- queue (letter worker on VM 220)

@router.post("/queue/claim")
def claim(conn: sqlite3.Connection = Depends(get_db)):
    expire(conn)
    # One statement: SQLite takes the write lock for it, so two workers never get the same letter.
    row = conn.execute(
        "UPDATE letter SET claimed_at=? WHERE id=(SELECT id FROM letter WHERE status='pending'"
        " AND (claimed_at IS NULL OR claimed_at<?) ORDER BY id LIMIT 1) RETURNING *",
        (now(), ago(CLAIM_STALE))).fetchone()
    if row is None:
        return Response(status_code=204)
    letter = letter_json(row)
    conn.commit()
    app = dict(get_app(conn, row["application_id"]))
    c = conn.execute("SELECT * FROM contact WHERE id=?", (app["contact_id"],)).fetchone() if app["contact_id"] else None
    app["contact"] = dict(c) if c else None
    previous = [{"lang": r["lang"], "body": r["body"], "title": r["title"]} for r in conn.execute(
        "SELECT l.lang, l.body, a.title FROM letter l JOIN application a ON a.id=l.application_id"
        " WHERE ulower(a.company)=ulower(?) AND l.status='ready' AND l.id!=? ORDER BY l.id DESC LIMIT 5",
        (app["company"], row["id"]))]
    return {"letter": letter, "application": app, "previous_letters": previous}


@router.post("/queue/{lid}/done")
def queue_done(lid: int, body: DoneIn, conn: sqlite3.Connection = Depends(get_db)):
    row = get_letter(conn, lid)
    if row["status"] != "pending":
        raise HTTPException(409, f"letter is {row['status']}")
    conn.execute("UPDATE letter SET body=?, status='ready', error=NULL, updated_at=? WHERE id=?", (body.body, now(), lid))
    log(conn, row["application_id"], "letter", f"Письмо ({row['lang']}) готово")
    return letter_json(get_letter(conn, lid))


@router.post("/queue/{lid}/failed")
def queue_failed(lid: int, body: FailedIn, conn: sqlite3.Connection = Depends(get_db)):
    row = get_letter(conn, lid)
    if row["status"] != "pending":
        raise HTTPException(409, f"letter is {row['status']}")
    conn.execute("UPDATE letter SET status='failed', error=?, updated_at=? WHERE id=?", (body.error[:500], now(), lid))
    return letter_json(get_letter(conn, lid))


# ---------- attachments

def files_root(request: Request) -> Path:
    return Path(request.app.state.files_dir)


def safe_name(name: str) -> tuple[str, str]:
    base = re.split(r"[\\/]", name.replace("\x00", ""))[-1]
    base = re.sub(r"[^\w.\- ()]+", "_", base).strip(" .")[:120]
    ext = base.rsplit(".", 1)[-1].lower() if "." in base else ""
    if not base or ext not in MIME:
        raise HTTPException(400, f"file type not allowed: {ext or 'none'} (pdf, docx, txt, md, html, png, jpg, webp)")
    return base, ext


@router.put("/applications/{aid}/files", status_code=201)
async def upload_file(aid: int, name: str, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    get_app(conn, aid)
    base, ext = safe_name(name)
    declared = request.headers.get("content-length")
    if declared and declared.isdigit() and int(declared) > MAX_FILE:
        raise HTTPException(413, "file is larger than 15 MB")
    # Read in chunks and stop at the limit: a chunked upload has no Content-Length to check up front.
    buf = bytearray()
    async for chunk in request.stream():
        buf += chunk
        if len(buf) > MAX_FILE:
            raise HTTPException(413, "file is larger than 15 MB")
    data = bytes(buf)
    if not data:
        raise HTTPException(400, "empty file")
    cur = conn.execute("INSERT INTO attachment(application_id,name,mime,size,path,created_at) VALUES(?,?,?,?,'',?)",
                       (aid, base, MIME[ext], len(data), now()))
    fid = cur.lastrowid
    folder = files_root(request) / str(aid)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{fid}.{ext}"
    path.write_bytes(data)
    conn.execute("UPDATE attachment SET path=? WHERE id=?", (str(path.relative_to(files_root(request))), fid))
    log(conn, aid, "attachment", f"Прикреплён файл «{base}»")
    return {"id": fid, "name": base, "mime": MIME[ext], "size": len(data)}


def get_file(conn, fid: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM attachment WHERE id=?", (fid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"file not found: {fid}")
    return row


@router.get("/files/{fid}")
def download_file(fid: int, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    row = get_file(conn, fid)
    path = files_root(request) / row["path"]
    if not path.is_file():
        raise HTTPException(404, "file is missing on disk")
    ext = row["name"].rsplit(".", 1)[-1].lower()
    return FileResponse(path, media_type=row["mime"], filename=row["name"],
                        content_disposition_type="inline" if ext in INLINE else "attachment",
                        headers={"X-Content-Type-Options": "nosniff"})


@router.delete("/files/{fid}", status_code=204)
def delete_file(fid: int, request: Request, conn: sqlite3.Connection = Depends(get_db)):
    row = get_file(conn, fid)
    (files_root(request) / row["path"]).unlink(missing_ok=True)
    conn.execute("DELETE FROM attachment WHERE id=?", (fid,))
    log(conn, row["application_id"], "attachment", f"Удалён файл «{row['name']}»")
    return Response(status_code=204)
