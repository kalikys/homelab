"""Outreach: the fix-PR campaign. One target per company: what we would fix in its public repos, the PR, and the contact."""
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .db import CommitRoute, get_db, now
from .jobs import OptUrl, Url

router = APIRouter(prefix="/api/outreach", route_class=CommitRoute)

SCHEMA = """
CREATE TABLE IF NOT EXISTS outreach_target(
  id INTEGER PRIMARY KEY, company TEXT NOT NULL, url TEXT NOT NULL DEFAULT '', careers_url TEXT NOT NULL DEFAULT '',
  remote TEXT NOT NULL DEFAULT 'unknown', why TEXT NOT NULL DEFAULT '', repos TEXT NOT NULL DEFAULT '',
  finding TEXT NOT NULL DEFAULT '', pr_url TEXT NOT NULL DEFAULT '', pr_state TEXT NOT NULL DEFAULT 'idea',
  contact_role TEXT NOT NULL DEFAULT '', contacted_at TEXT, reply TEXT NOT NULL DEFAULT '',
  next_step TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '', uid TEXT UNIQUE,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS outreach_event(
  id INTEGER PRIMARY KEY, target_id INTEGER NOT NULL REFERENCES outreach_target(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, text TEXT NOT NULL, at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS outreach_state ON outreach_target(pr_state, updated_at);
CREATE INDEX IF NOT EXISTS outreach_event_target ON outreach_event(target_id, at);
"""

# Columns added later for the live step feed; ALTER is idempotent through migrate().
EVENT_COLUMNS = {"step": "TEXT", "status": "TEXT", "url": "TEXT NOT NULL DEFAULT ''", "log": "TEXT NOT NULL DEFAULT ''"}
STEP_ORDER = ["clone", "reproduce", "fix", "test", "policy-check", "pr-text", "ready"]
LOG_MAX = 4096


def migrate(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    have = {r["name"] if isinstance(r, sqlite3.Row) else r[1] for r in conn.execute("PRAGMA table_info(outreach_event)")}
    for col, decl in EVENT_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE outreach_event ADD COLUMN {col} {decl}")

State = Literal["idea", "prepared", "opened", "merged", "closed"]
STATE_LABELS = {"idea": "идея", "prepared": "PR готов", "opened": "PR открыт", "merged": "PR принят", "closed": "закрыт"}
Remote = Literal["yes", "no", "unknown"]
StepStatus = Literal["running", "ok", "fail", "skip"]
STEP_LABELS = {"running": "идёт", "ok": "готово", "fail": "ошибка", "skip": "пропуск"}
DATE = r"^\d{4}-\d{2}-\d{2}$"

EDIT_LABELS = {"company": "компания", "url": "сайт", "careers_url": "вакансии", "remote": "удалёнка", "why": "почему",
               "repos": "репозитории", "finding": "что чиним", "pr_url": "PR", "contact_role": "кому писать",
               "contacted_at": "дата письма", "reply": "ответ", "next_step": "следующий шаг", "notes": "заметки"}


class TargetIn(BaseModel):
    company: str = Field(min_length=1)
    url: Url = ""
    careers_url: Url = ""
    remote: Remote = "unknown"
    why: str = ""
    repos: str = ""
    finding: str = ""
    pr_url: Url = ""
    pr_state: State = "idea"
    contact_role: str = ""
    contacted_at: str | None = Field(default=None, pattern=DATE)
    reply: str = ""
    next_step: str = ""
    notes: str = ""
    uid: str | None = None


class TargetPatch(BaseModel):
    company: str | None = Field(default=None, min_length=1)
    url: OptUrl = None
    careers_url: OptUrl = None
    remote: Remote | None = None
    why: str | None = None
    repos: str | None = None
    finding: str | None = None
    pr_url: OptUrl = None
    pr_state: State | None = None
    contact_role: str | None = None
    contacted_at: str | None = Field(default=None, pattern=DATE)
    reply: str | None = None
    next_step: str | None = None
    notes: str | None = None
    note: str | None = None  # goes to the event log only


class StepIn(BaseModel):
    step: str = Field(pattern=r"^[a-z][a-z0-9-]{0,23}$")
    status: StepStatus
    text: str = Field(min_length=1, max_length=500)
    url: Url = ""
    log: str = ""


def log(conn: sqlite3.Connection, tid: int, kind: str, text: str, **extra) -> int:
    cols = ["target_id", "kind", "text", "at", *extra]
    cur = conn.execute(f"INSERT INTO outreach_event({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                       (tid, kind, text, now(), *extra.values()))
    return cur.lastrowid


def get_target(conn: sqlite3.Connection, tid: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM outreach_target WHERE id=?", (tid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"outreach target not found: {tid}")
    return row


def target_json(row: sqlite3.Row, steps: dict | None = None) -> dict:
    d = dict(row)
    d["state_label"] = STATE_LABELS[d["pr_state"]]
    if steps is not None:
        mine = steps.get(d["id"], [])
        d["steps"] = {s["step"]: s["status"] for s in mine}  # latest status per step
        d["last_step"] = mine[-1] if mine else None
    return d


def steps_by_target(conn: sqlite3.Connection, ids: list[int]) -> dict[int, list[dict]]:
    """Step events per target in time order (the latest one per step name wins in target_json)."""
    out: dict[int, list[dict]] = {}
    if not ids:
        return out
    q = ("SELECT id, target_id, step, status, text, url, at FROM outreach_event WHERE kind='step' AND target_id IN ("
         + ",".join("?" * len(ids)) + ") ORDER BY at, id")
    for r in conn.execute(q, ids):
        out.setdefault(r["target_id"], []).append(dict(r))
    return out


@router.get("/targets")
def list_targets(state: State | None = None, q: str | None = None, conn: sqlite3.Connection = Depends(get_db)):
    where, args = [], []
    if state:
        where.append("pr_state=?")
        args.append(state)
    if q and q.strip():
        like = "%" + q.strip().lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
        cols = ("company", "why", "repos", "finding", "notes")
        where.append("(" + " OR ".join(f"ulower({c}) LIKE ? ESCAPE '\\'" for c in cols) + ")")
        args += [like] * len(cols)
    sql = "SELECT * FROM outreach_target" + (" WHERE " + " AND ".join(where) if where else "")
    rows = conn.execute(sql + " ORDER BY updated_at DESC, id DESC", args).fetchall()
    steps = steps_by_target(conn, [r["id"] for r in rows])
    return [target_json(r, steps) for r in rows]


@router.post("/targets", status_code=201)
def create_target(body: TargetIn, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    if body.uid:
        old = conn.execute("SELECT * FROM outreach_target WHERE uid=?", (body.uid,)).fetchone()
        if old:
            response.status_code = 200
            return target_json(old)
    ts = now()
    fields = body.model_dump()
    cols = list(fields) + ["created_at", "updated_at"]
    cur = conn.execute(f"INSERT INTO outreach_target({','.join(cols)}) VALUES({','.join('?' * len(cols))})",
                       (*fields.values(), ts, ts))
    log(conn, cur.lastrowid, "created", f"Добавлено · {STATE_LABELS[body.pr_state]}")
    return target_json(get_target(conn, cur.lastrowid))


@router.get("/targets/{tid}")
def target_detail(tid: int, conn: sqlite3.Connection = Depends(get_db)):
    d = target_json(get_target(conn, tid), steps_by_target(conn, [tid]))
    d["events"] = [dict(r) for r in conn.execute(
        "SELECT * FROM outreach_event WHERE target_id=? ORDER BY at DESC, id DESC", (tid,))]
    return d


@router.patch("/targets/{tid}")
def patch_target(tid: int, body: TargetPatch, conn: sqlite3.Connection = Depends(get_db)):
    row = get_target(conn, tid)
    fields = {k: getattr(body, k) for k in body.model_fields_set if k != "note"}
    for k, v in fields.items():
        if v is None and k != "contacted_at":
            raise HTTPException(400, f"{k}: may not be null")
    changed = {k: v for k, v in fields.items() if row[k] != v}
    if "pr_state" in changed:
        log(conn, tid, "state", f"{STATE_LABELS[row['pr_state']]} → {STATE_LABELS[changed['pr_state']]}"
            + (f": {body.note}" if body.note else ""))
    elif body.note:
        log(conn, tid, "note", body.note)
    edited = [EDIT_LABELS[k] for k in changed if k in EDIT_LABELS]
    if edited:
        log(conn, tid, "edited", "Изменено: " + ", ".join(edited))
    if changed:
        changed["updated_at"] = now()
        conn.execute(f"UPDATE outreach_target SET {', '.join(f'{k}=?' for k in changed)} WHERE id=?",
                     (*changed.values(), tid))
    return target_json(get_target(conn, tid))


@router.post("/targets/{tid}/steps", status_code=201)
def add_step(tid: int, body: StepIn, conn: sqlite3.Connection = Depends(get_db)):
    """Live progress from whoever is working on the fix: clone, reproduce, fix, test, policy-check, pr-text, ready."""
    get_target(conn, tid)
    eid = log(conn, tid, "step", body.text, step=body.step, status=body.status, url=body.url,
              log=body.log[-LOG_MAX:])
    conn.execute("UPDATE outreach_target SET updated_at=? WHERE id=?", (now(), tid))
    return event_json(conn.execute(EVENT_SQL + " WHERE e.id=?", (eid,)).fetchone())


EVENT_SQL = ("SELECT e.id, e.target_id, t.company, e.kind, e.text, e.step, e.status, e.url, e.log, e.at AS created_at "
             "FROM outreach_event e JOIN outreach_target t ON t.id = e.target_id")


def event_json(r: sqlite3.Row) -> dict:
    d = dict(r)
    d["status_label"] = STEP_LABELS.get(d["status"] or "", "")
    return d


@router.get("/events")
def events(since: str | None = None, limit: int = 50, conn: sqlite3.Connection = Depends(get_db)):
    """Newest events across all targets. since = an event id (only newer ones) or an ISO time."""
    limit = max(1, min(limit, 200))
    where, args = "", []
    if since:
        if since.isdigit():
            where, args = " WHERE e.id > ?", [int(since)]
        else:
            where, args = " WHERE e.at > ?", [since]
    rows = conn.execute(EVENT_SQL + where + " ORDER BY e.id DESC LIMIT ?", (*args, limit))
    return [event_json(r) for r in rows]


@router.delete("/targets/{tid}", status_code=204)
def delete_target(tid: int, conn: sqlite3.Connection = Depends(get_db)):
    get_target(conn, tid)
    conn.execute("DELETE FROM outreach_target WHERE id=?", (tid,))
    return Response(status_code=204)


@router.get("/summary")
def summary(conn: sqlite3.Connection = Depends(get_db)):
    counts = {s: 0 for s in STATE_LABELS}
    for r in conn.execute("SELECT pr_state, COUNT(*) n FROM outreach_target GROUP BY pr_state"):
        counts[r["pr_state"]] = r["n"]
    contacted = conn.execute("SELECT COUNT(*) FROM outreach_target WHERE contacted_at IS NOT NULL").fetchone()[0]
    replied = conn.execute("SELECT COUNT(*) FROM outreach_target WHERE reply!=''").fetchone()[0]
    return {"counts": counts, "contacted": contacted, "replied": replied}
