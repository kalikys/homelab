import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .db import CommitRoute, get_db, item_rows, now, require_project, touch
from .model import LABELS, STATUS_LABELS, check_status, default_status, done_status, finished, location_kind

router = APIRouter(prefix="/api", route_class=CommitRoute)

ItemType = Literal["feature", "milestone", "plan", "todo", "artifact", "decision", "finding", "note"]
Owner = Literal["claude", "user"]
RelKind = Literal["implements", "produced", "depends_on", "relates"]


class ItemIn(BaseModel):
    type: ItemType
    title: str = Field(min_length=1)
    body: str = ""
    status: str | None = None
    owner: Owner | None = None
    location: str | None = None
    parent_id: int | None = None
    uid: str | None = None
    session_id: str | None = None
    ts: str | None = None


class ItemPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1)
    body: str | None = None
    status: str | None = None
    owner: Owner | None = None
    location: str | None = None
    parent_id: int | None = None
    position: int | None = None
    session_id: str | None = None


class SessionRef(BaseModel):
    session_id: str | None = None


class RelationIn(BaseModel):
    to_id: int
    kind: RelKind


def get_item(conn: sqlite3.Connection, iid: int) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM item WHERE id=?", (iid,)).fetchone()
    if row is None:
        raise HTTPException(404, f"item not found: {iid}")
    return row


def small(row) -> dict:
    return {k: row[k] for k in ("id", "type", "title", "status", "project")}


def describe(row) -> str:
    return f"{LABELS[row['type']]} «{row['title']}»"


def log(conn, project: str, kind: str, text: str, item=None, session_id: str | None = None, ts: str | None = None):
    conn.execute(
        "INSERT INTO event(project,item_id,item_type,session_id,ts,kind,text) VALUES(?,?,?,?,?,?,?)",
        (project, item["id"] if item else None, item["type"] if item else None, session_id, ts or now(), kind, text))


def link_session(conn, session_id: str | None, item, role: str, ts: str) -> None:
    if not session_id:
        return
    # Stub row so the current chat shows up before its SessionEnd hook runs.
    conn.execute("INSERT OR IGNORE INTO session(id, project, started_at) VALUES(?,?,?)",
                 (session_id, item["project"], ts))
    conn.execute("UPDATE session SET project=? WHERE id=? AND project IS NULL", (item["project"], session_id))
    conn.execute("INSERT OR IGNORE INTO session_item(session_id,item_id,role,ts) VALUES(?,?,?,?)",
                 (session_id, item["id"], role, ts))


def check_parent(conn, project: str, parent_id: int, self_id: int | None = None) -> None:
    if parent_id == self_id:
        raise HTTPException(400, "an item cannot be its own parent")
    p = conn.execute("SELECT project FROM item WHERE id=?", (parent_id,)).fetchone()
    if p is None:
        raise HTTPException(400, f"parent not found: {parent_id}")
    if p["project"] != project:
        raise HTTPException(400, "parent must be in the same project")


@router.post("/projects/{slug}/items", status_code=201)
def create_item(slug: str, body: ItemIn, response: Response, conn: sqlite3.Connection = Depends(get_db)):
    require_project(conn, slug)
    if body.uid:
        old = conn.execute("SELECT * FROM item WHERE uid=?", (body.uid,)).fetchone()
        if old is not None:
            response.status_code = 200
            return item_rows(conn, [old])[0]
    status = body.status or default_status(body.type)
    check_status(body.type, status)
    if body.owner and body.type != "todo":
        raise HTTPException(400, "owner is only for todos")
    owner = (body.owner or "claude") if body.type == "todo" else None
    if body.parent_id is not None:
        check_parent(conn, slug, body.parent_id)
    ts = body.ts or now()
    pos = conn.execute("SELECT COALESCE(MAX(position)+1, 0) FROM item WHERE project=? AND type=?",
                       (slug, body.type)).fetchone()[0]
    cur = conn.execute(
        "INSERT INTO item(project,type,title,body,status,owner,location,location_kind,parent_id,position,uid,"
        "created_at,updated_at,done_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (slug, body.type, body.title, body.body, status, owner, body.location, location_kind(body.location),
         body.parent_id, pos, body.uid, ts, ts, ts if finished(status) else None))
    row = get_item(conn, cur.lastrowid)
    log(conn, slug, "created", describe(row), row, body.session_id, ts)
    link_session(conn, body.session_id, row, "created", ts)
    touch(conn, slug, ts)
    return item_rows(conn, [row])[0]


def apply_patch(conn, row, fields: dict, session_id: str | None):
    if "status" in fields:
        check_status(row["type"], fields["status"])
    for col in ("title", "body"):
        if col in fields and fields[col] is None:
            raise HTTPException(400, f"{col}: may not be null")
    if "owner" in fields:
        if row["type"] != "todo":
            raise HTTPException(400, "owner is only for todos")
        if fields["owner"] is None:
            raise HTTPException(400, "owner: may not be null")
    if "location" in fields:
        fields["location_kind"] = location_kind(fields["location"])
    if fields.get("parent_id") is not None:
        check_parent(conn, row["project"], fields["parent_id"], row["id"])
    if not fields:
        return row
    ts = now()
    status_changed = "status" in fields and fields["status"] != row["status"]
    if status_changed:
        fields["done_at"] = ts if finished(fields["status"]) else None
    edited = set(fields) - {"position", "location_kind", "status", "done_at"}
    fields["updated_at"] = ts
    sets = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE item SET {sets} WHERE id=?", (*fields.values(), row["id"]))
    new = get_item(conn, row["id"])
    if status_changed:
        log(conn, row["project"], "status",
            f"{describe(new)}: {STATUS_LABELS[row['status']]} → {STATUS_LABELS[new['status']]}", new, session_id, ts)
    elif edited:
        log(conn, row["project"], "edited", f"{describe(new)}: изменено ({', '.join(sorted(edited))})", new, session_id, ts)
    link_session(conn, session_id, new, "updated", ts)
    touch(conn, row["project"], ts)
    return new


@router.get("/items/{iid}")
def item_detail(iid: int, conn: sqlite3.Connection = Depends(get_db)):
    row = get_item(conn, iid)
    d = item_rows(conn, [row])[0]
    parent = conn.execute("SELECT * FROM item WHERE id=?", (row["parent_id"],)).fetchone() if row["parent_id"] else None
    d["parent"] = small(parent) if parent else None
    d["children"] = item_rows(conn, conn.execute(
        "SELECT * FROM item WHERE parent_id=? ORDER BY type, position, id", (iid,)))
    rels = []
    for direction, sql in (("out", "SELECT r.kind, i.* FROM relation r JOIN item i ON i.id=r.to_id WHERE r.from_id=?"),
                           ("in", "SELECT r.kind, i.* FROM relation r JOIN item i ON i.id=r.from_id WHERE r.to_id=?")):
        for r in conn.execute(sql + " ORDER BY i.id", (iid,)):
            rels.append({"direction": direction, "kind": r["kind"], "item": small(r)})
    d["relations"] = rels
    chats: dict[str, dict] = {}
    for r in conn.execute(
            "SELECT si.role, s.id, s.title, s.first_prompt, s.cwd, s.started_at, s.ended_at FROM session_item si"
            " JOIN session s ON s.id=si.session_id WHERE si.item_id=? ORDER BY si.ts DESC", (iid,)):
        c = chats.setdefault(r["id"], {k: r[k] for k in ("id", "title", "first_prompt", "cwd", "started_at", "ended_at")} | {"roles": []})
        c["roles"].append(r["role"])
    d["sessions"] = list(chats.values())
    d["events"] = [dict(e) for e in conn.execute("SELECT * FROM event WHERE item_id=? ORDER BY ts DESC, id DESC", (iid,))]
    return d


@router.patch("/items/{iid}")
def patch_item(iid: int, body: ItemPatch, conn: sqlite3.Connection = Depends(get_db)):
    row = get_item(conn, iid)
    fields = {k: getattr(body, k) for k in body.model_fields_set if k != "session_id"}
    return item_rows(conn, [apply_patch(conn, row, fields, body.session_id)])[0]


@router.post("/items/{iid}/done")
def mark_done(iid: int, body: SessionRef, conn: sqlite3.Connection = Depends(get_db)):
    row = get_item(conn, iid)
    return item_rows(conn, [apply_patch(conn, row, {"status": done_status(row["type"])}, body.session_id)])[0]


@router.delete("/items/{iid}", status_code=204)
def delete_item(iid: int, conn: sqlite3.Connection = Depends(get_db)):
    row = get_item(conn, iid)
    conn.execute("DELETE FROM item WHERE id=?", (iid,))
    log(conn, row["project"], "deleted", f"{describe(row)}: удалено")
    touch(conn, row["project"])
    return Response(status_code=204)


@router.post("/items/{iid}/relations", status_code=201)
def add_relation(iid: int, body: RelationIn, conn: sqlite3.Connection = Depends(get_db)):
    a = get_item(conn, iid)
    get_item(conn, body.to_id)
    if iid == body.to_id:
        raise HTTPException(400, "an item cannot relate to itself")
    conn.execute("INSERT OR IGNORE INTO relation(from_id,to_id,kind) VALUES(?,?,?)", (iid, body.to_id, body.kind))
    touch(conn, a["project"])
    return {"from_id": iid, "to_id": body.to_id, "kind": body.kind}


@router.delete("/items/{iid}/relations/{kind}/{to_id}", status_code=204)
def delete_relation(iid: int, kind: str, to_id: int, conn: sqlite3.Connection = Depends(get_db)):
    get_item(conn, iid)
    conn.execute("DELETE FROM relation WHERE from_id=? AND to_id=? AND kind=?", (iid, to_id, kind))
    return Response(status_code=204)


@router.get("/todos")
def list_todos(owner: str | None = None, project: str | None = None, conn: sqlite3.Connection = Depends(get_db)):
    sql = ("SELECT item.*, project.title AS project_title FROM item JOIN project ON project.slug=item.project"
           " WHERE item.type='todo' AND item.status IN ('open','doing')")
    args: list = []
    if owner:
        sql += " AND item.owner=?"
        args.append(owner)
    if project:
        sql += " AND item.project=?"
        args.append(project)
    return item_rows(conn, conn.execute(sql + " ORDER BY item.created_at, item.id", args))
