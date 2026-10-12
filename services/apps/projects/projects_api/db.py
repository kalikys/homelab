import json
import sqlite3
from datetime import datetime, timezone

from fastapi import HTTPException, Request

SCHEMA = """
CREATE TABLE IF NOT EXISTS project(
  slug TEXT PRIMARY KEY, title TEXT NOT NULL, area TEXT NOT NULL DEFAULT 'other',
  status TEXT NOT NULL DEFAULT 'active', summary TEXT NOT NULL DEFAULT '', next_step TEXT NOT NULL DEFAULT '',
  progress_override INTEGER, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS item(
  id INTEGER PRIMARY KEY, project TEXT NOT NULL REFERENCES project(slug) ON DELETE CASCADE,
  type TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', status TEXT NOT NULL,
  owner TEXT, location TEXT, location_kind TEXT,
  parent_id INTEGER REFERENCES item(id) ON DELETE SET NULL, position INTEGER NOT NULL DEFAULT 0,
  uid TEXT UNIQUE, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, done_at TEXT);
CREATE TABLE IF NOT EXISTS relation(
  from_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  to_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  kind TEXT NOT NULL, PRIMARY KEY(from_id, to_id, kind));
CREATE TABLE IF NOT EXISTS event(
  id INTEGER PRIMARY KEY, project TEXT NOT NULL REFERENCES project(slug) ON DELETE CASCADE,
  item_id INTEGER REFERENCES item(id) ON DELETE SET NULL, item_type TEXT, session_id TEXT,
  ts TEXT NOT NULL, kind TEXT NOT NULL, text TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS session(
  id TEXT PRIMARY KEY, project TEXT REFERENCES project(slug) ON DELETE SET NULL,
  title TEXT NOT NULL DEFAULT '', cwd TEXT NOT NULL DEFAULT '', first_prompt TEXT NOT NULL DEFAULT '',
  started_at TEXT, ended_at TEXT, user_turns INTEGER NOT NULL DEFAULT 0,
  files_changed TEXT NOT NULL DEFAULT '[]', transcript_path TEXT NOT NULL DEFAULT '');
CREATE TABLE IF NOT EXISTS session_item(
  session_id TEXT NOT NULL, item_id INTEGER NOT NULL REFERENCES item(id) ON DELETE CASCADE,
  role TEXT NOT NULL, ts TEXT NOT NULL, PRIMARY KEY(session_id, item_id, role));
CREATE TABLE IF NOT EXISTS path_map(
  prefix TEXT PRIMARY KEY, project TEXT NOT NULL REFERENCES project(slug) ON DELETE CASCADE);
CREATE INDEX IF NOT EXISTS item_project ON item(project, type, position);
CREATE INDEX IF NOT EXISTS item_parent ON item(parent_id);
CREATE INDEX IF NOT EXISTS event_project_ts ON event(project, ts);
CREATE INDEX IF NOT EXISTS event_item ON event(item_id);
CREATE INDEX IF NOT EXISTS session_item_item ON session_item(item_id);
CREATE INDEX IF NOT EXISTS session_project ON session(project, ended_at);
"""


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    # SQLite's own lower()/LIKE fold only ASCII; search needs Cyrillic too.
    conn.create_function("ulower", 1, lambda s: s.lower() if isinstance(s, str) else s, deterministic=True)
    return conn


def init(path: str) -> None:
    conn = connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.close()


def get_db(request: Request):
    conn = connect(request.app.state.db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def require_project(conn: sqlite3.Connection, slug: str) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM project WHERE slug=?", (slug,)).fetchone()
    if row is None:
        raise HTTPException(404, f"project not found: {slug}")
    return row


def touch(conn: sqlite3.Connection, slug: str, ts: str | None = None) -> None:
    conn.execute("UPDATE project SET updated_at=max(updated_at, ?) WHERE slug=?", (ts or now(), slug))


def progress(override: int | None, done: int | None, total: int | None) -> int | None:
    if override is not None:
        return override
    if not total:
        return None
    return round(100 * (done or 0) / total)


def item_rows(conn: sqlite3.Connection, rows) -> list[dict]:
    rows = list(rows)
    if not rows:
        return []
    ids = [r["id"] for r in rows]
    q = ",".join("?" * len(ids))
    kids = {r[0]: (r[1], r[2]) for r in conn.execute(
        f"SELECT parent_id, SUM(status='done'), SUM(status!='dropped') FROM item"
        f" WHERE type='todo' AND parent_id IN ({q}) GROUP BY parent_id", ids)}
    chats = {r[0]: r[1] for r in conn.execute(
        f"SELECT item_id, COUNT(DISTINCT session_id) FROM session_item WHERE item_id IN ({q}) GROUP BY item_id", ids)}
    out = []
    for r in rows:
        d = dict(r)
        k = kids.get(r["id"])
        d["progress"] = progress(None, k[0], k[1]) if k and r["type"] in ("feature", "plan") else None
        d["session_count"] = chats.get(r["id"], 0)
        out.append(d)
    return out


def session_json(row: sqlite3.Row) -> dict:
    return {**dict(row), "files_changed": json.loads(row["files_changed"])}
