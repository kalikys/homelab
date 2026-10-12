import json
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from .db import get_db, require_project, session_json, touch

router = APIRouter(prefix="/api")


class SessionIn(BaseModel):
    id: str = Field(min_length=1)
    title: str = ""
    cwd: str = ""
    first_prompt: str = ""
    started_at: str | None = None
    ended_at: str | None = None
    user_turns: int = 0
    files_changed: list[str] = []
    transcript_path: str = ""
    project: str | None = None


class SessionPatch(BaseModel):
    project: str | None


class PathMapIn(BaseModel):
    prefix: str = Field(min_length=1)
    project: str


def _norm(path: str) -> str:
    return path.rstrip("/") or "/"


def resolve(conn: sqlite3.Connection, cwd: str) -> str | None:
    cwd = _norm(cwd)
    best = None
    for row in conn.execute("SELECT prefix, project FROM path_map"):
        p = row["prefix"]
        if (cwd == p or cwd.startswith(p + "/")) and (best is None or len(p) > len(best[0])):
            best = (p, row["project"])
    return best[1] if best else None


def _get(conn, sid: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM session WHERE id=?", (sid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"session not found: {sid}")
    return row


@router.post("/sessions")
def upsert_session(body: SessionIn, conn: sqlite3.Connection = Depends(get_db)):
    project = body.project
    if project is not None:
        require_project(conn, project)
    elif body.cwd:
        project = resolve(conn, body.cwd)
    conn.execute(
        "INSERT INTO session(id,project,title,cwd,first_prompt,started_at,ended_at,user_turns,files_changed,transcript_path)"
        " VALUES(?,?,?,?,?,?,?,?,?,?)"
        " ON CONFLICT(id) DO UPDATE SET"
        "  project=COALESCE(session.project, excluded.project),"
        "  title=CASE WHEN excluded.title!='' THEN excluded.title ELSE session.title END,"
        "  cwd=CASE WHEN session.cwd='' THEN excluded.cwd ELSE session.cwd END,"
        "  first_prompt=CASE WHEN session.first_prompt='' THEN excluded.first_prompt ELSE session.first_prompt END,"
        "  started_at=COALESCE(min(session.started_at, excluded.started_at), session.started_at, excluded.started_at),"
        "  ended_at=COALESCE(excluded.ended_at, session.ended_at),"
        "  user_turns=max(session.user_turns, excluded.user_turns),"
        "  files_changed=excluded.files_changed,"
        "  transcript_path=CASE WHEN excluded.transcript_path!='' THEN excluded.transcript_path ELSE session.transcript_path END",
        (body.id, project, body.title, body.cwd, body.first_prompt[:300], body.started_at, body.ended_at,
         body.user_turns, json.dumps(body.files_changed[:50], ensure_ascii=False), body.transcript_path),
    )
    row = _get(conn, body.id)
    if row["project"] and row["ended_at"]:
        touch(conn, row["project"], row["ended_at"])
    return session_json(row)


@router.get("/sessions")
def list_sessions(unsorted: int = 0, limit: int = 100, conn: sqlite3.Connection = Depends(get_db)):
    where = "WHERE project IS NULL" if unsorted else ""
    rows = conn.execute(
        f"SELECT * FROM session {where} ORDER BY COALESCE(ended_at, started_at, '') DESC LIMIT ?", (min(limit, 500),))
    return [session_json(r) for r in rows]


@router.get("/sessions/{sid}")
def session_detail(sid: str, conn: sqlite3.Connection = Depends(get_db)):
    d = session_json(_get(conn, sid))
    items: dict[int, dict] = {}
    for r in conn.execute(
            "SELECT si.role, i.id, i.type, i.title, i.status, i.project FROM session_item si"
            " JOIN item i ON i.id=si.item_id WHERE si.session_id=? ORDER BY si.ts, i.id", (sid,)):
        it = items.setdefault(r["id"], {k: r[k] for k in ("id", "type", "title", "status", "project")} | {"roles": []})
        it["roles"].append(r["role"])
    d["items"] = list(items.values())
    return d


@router.patch("/sessions/{sid}")
def patch_session(sid: str, body: SessionPatch, conn: sqlite3.Connection = Depends(get_db)):
    _get(conn, sid)
    if body.project is not None:
        require_project(conn, body.project)
    conn.execute("UPDATE session SET project=? WHERE id=?", (body.project, sid))
    row = _get(conn, sid)
    if row["project"] and row["ended_at"]:
        touch(conn, row["project"], row["ended_at"])
    return session_json(row)


@router.get("/resolve")
def resolve_route(cwd: str, conn: sqlite3.Connection = Depends(get_db)):
    return {"project": resolve(conn, cwd)}


@router.get("/path-map")
def list_path_map(conn: sqlite3.Connection = Depends(get_db)):
    return [dict(r) for r in conn.execute("SELECT * FROM path_map ORDER BY prefix")]


@router.post("/path-map", status_code=201)
def add_path_map(body: PathMapIn, conn: sqlite3.Connection = Depends(get_db)):
    require_project(conn, body.project)
    prefix = _norm(body.prefix)
    conn.execute("INSERT INTO path_map(prefix,project) VALUES(?,?)"
                 " ON CONFLICT(prefix) DO UPDATE SET project=excluded.project", (prefix, body.project))
    return {"prefix": prefix, "project": body.project}
