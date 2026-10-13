import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .db import CommitRoute, get_db, item_rows, now, progress, require_project, session_json, touch

router = APIRouter(prefix="/api", route_class=CommitRoute)

Area = Literal["youtube", "sites", "infra", "jobs", "crypto", "research", "other"]
Status = Literal["active", "paused", "done", "dropped"]
SLUG = r"^[a-z0-9][a-z0-9-]{0,62}$"


class ProjectIn(BaseModel):
    slug: str = Field(pattern=SLUG)
    title: str = Field(min_length=1)
    area: Area = "other"
    status: Status = "active"
    summary: str = ""
    next_step: str = ""
    milestones: list[str] = []
    ts: str | None = None  # historic imports (seed): when the project was last active


class ProjectPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    area: Area | None = None
    status: Status | None = None
    summary: str | None = None
    next_step: str | None = None
    progress_override: int | None = Field(default=None, ge=0, le=100)


def project_json(conn: sqlite3.Connection, row: sqlite3.Row) -> dict:
    slug = row["slug"]
    ms = conn.execute(
        "SELECT SUM(status='done'), COUNT(*) FROM item WHERE project=? AND type='milestone'", (slug,)).fetchone()
    td = conn.execute(
        "SELECT SUM(owner='user'), SUM(owner='claude') FROM item"
        " WHERE project=? AND type='todo' AND status IN ('open','doing')", (slug,)).fetchone()
    d = dict(row)
    d["progress"] = progress(row["progress_override"], ms[0], ms[1])
    d["open_user_todos"] = td[0] or 0
    d["open_todos"] = td[1] or 0
    return d


@router.get("/health")
def health():
    return {"ok": True}


@router.get("/projects")
def list_projects(conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute("SELECT * FROM project ORDER BY updated_at DESC, slug").fetchall()
    return [project_json(conn, r) for r in rows]


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, conn: sqlite3.Connection = Depends(get_db)):
    ts = body.ts or now()
    try:
        conn.execute(
            "INSERT INTO project(slug,title,area,status,summary,next_step,created_at,updated_at)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (body.slug, body.title, body.area, body.status, body.summary, body.next_step, ts, ts),
        )
    except sqlite3.IntegrityError:
        raise HTTPException(409, f"project exists: {body.slug}")
    for i, title in enumerate(body.milestones):
        conn.execute(
            "INSERT INTO item(project,type,title,status,position,created_at,updated_at)"
            " VALUES(?,'milestone',?,'open',?,?,?)", (body.slug, title, i, ts, ts))
    return project_json(conn, require_project(conn, body.slug))


@router.get("/projects/{slug}")
def get_project(slug: str, conn: sqlite3.Connection = Depends(get_db)):
    d = project_json(conn, require_project(conn, slug))
    d["items"] = item_rows(conn, conn.execute(
        "SELECT * FROM item WHERE project=? ORDER BY type, position, id", (slug,)))
    d["events"] = [dict(r) for r in conn.execute(
        "SELECT * FROM event WHERE project=? ORDER BY ts DESC, id DESC LIMIT 100", (slug,))]
    d["sessions"] = [session_json(r) for r in conn.execute(
        "SELECT * FROM session WHERE project=? OR id IN"
        " (SELECT si.session_id FROM session_item si JOIN item i ON i.id=si.item_id WHERE i.project=?)"
        " ORDER BY COALESCE(ended_at, started_at, '') DESC LIMIT 50", (slug, slug))]
    touched: dict[str, dict[int, dict]] = {}
    for r in conn.execute(
            "SELECT si.session_id, si.role, i.id, i.type, i.title, i.status, i.project FROM session_item si"
            " JOIN item i ON i.id=si.item_id WHERE i.project=? ORDER BY si.ts, i.id", (slug,)):
        it = touched.setdefault(r["session_id"], {}).setdefault(
            r["id"], {k: r[k] for k in ("id", "type", "title", "status", "project")} | {"roles": []})
        it["roles"].append(r["role"])
    for s in d["sessions"]:
        s["items"] = list(touched.get(s["id"], {}).values())
    return d


@router.patch("/projects/{slug}")
def patch_project(slug: str, body: ProjectPatch, conn: sqlite3.Connection = Depends(get_db)):
    require_project(conn, slug)
    fields = {k: getattr(body, k) for k in body.model_fields_set}
    for col in ("title", "area", "status", "summary", "next_step"):
        if col in fields and fields[col] is None:
            raise HTTPException(400, f"{col}: may not be null")
    if fields:
        sets = ", ".join(f"{k}=?" for k in fields)
        conn.execute(f"UPDATE project SET {sets} WHERE slug=?", (*fields.values(), slug))
    touch(conn, slug)
    return project_json(conn, require_project(conn, slug))


@router.delete("/projects/{slug}", status_code=204)
def delete_project(slug: str, conn: sqlite3.Connection = Depends(get_db)):
    require_project(conn, slug)
    conn.execute("DELETE FROM project WHERE slug=?", (slug,))
    return Response(status_code=204)
