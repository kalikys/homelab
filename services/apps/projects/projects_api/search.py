import sqlite3

from fastapi import APIRouter, Depends

from .db import get_db

router = APIRouter(prefix="/api")

QUERIES = [
    "SELECT slug AS project, slug AS id, 'project' AS type,"
    " title || CASE WHEN summary!='' THEN ' — ' || summary ELSE '' END AS text, updated_at AS ts"
    " FROM project WHERE ulower(title || ' ' || summary || ' ' || next_step) LIKE ? ESCAPE '\\'",
    "SELECT project, id, type, title || CASE WHEN body!='' THEN ' — ' || body ELSE '' END AS text, updated_at AS ts"
    " FROM item WHERE ulower(title || ' ' || body || ' ' || COALESCE(location, '')) LIKE ? ESCAPE '\\'",
]


def _like(q: str) -> str:
    q = q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{q}%"


@router.get("/search")
def search(q: str = "", conn: sqlite3.Connection = Depends(get_db)):
    q = q.strip()
    if not q:
        return []
    titles = {r[0]: r[1] for r in conn.execute("SELECT slug, title FROM project")}
    groups: dict[str, dict] = {}
    for sql in QUERIES:
        for row in conn.execute(sql + " LIMIT 200", (_like(q),)):
            g = groups.setdefault(row["project"], {"project": row["project"], "title": titles.get(row["project"], ""), "hits": []})
            g["hits"].append({"type": row["type"], "id": row["id"], "text": row["text"][:200], "ts": row["ts"]})
    out = list(groups.values())
    for g in out:
        g["hits"].sort(key=lambda h: h["ts"] or "", reverse=True)
    out.sort(key=lambda g: g["hits"][0]["ts"] or "", reverse=True)
    return out
