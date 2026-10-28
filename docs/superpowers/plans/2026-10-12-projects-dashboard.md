# Projects Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A LAN dashboard at `https://projects.home.kalik8s.ru` that tracks every long-running project through typed items (feature, milestone, plan, todo, artifact, decision, finding, note) linked to each other and to the Claude chats that touched them, fed by a `pj` CLI, a `SessionEnd` hook and a `project-log` skill.

**Architecture:** FastAPI + SQLite service in one container on LXC 103 `apps` (port 8790), serving a Vite/React frontend built into the image. The server owns the item rules (statuses per type, progress, auto events, chat links). `pj` is one stdlib-only Python file on the Mac; it attaches the current session id to every write, queues writes in an outbox when the server is unreachable, and doubles as the hook and the backfill/seed tool.

**Tech Stack:** Python 3.12, FastAPI 0.118.0, uvicorn 0.37.0, pydantic 2.11.9, pytest 8.4.2, httpx 0.28.1; Node 24, Vite 7.1.7, React 19.1.1, react-router-dom 7.9.3, Tailwind CSS 4.1.13, lucide-react 0.544.0; Docker compose on LXC 103; Nginx Proxy Manager REST API.

**Spec:** `docs/superpowers/specs/2026-10-12-projects-dashboard-design.md`

## Global Constraints

- Service code lives in the public `homelab` repo under `services/apps/projects/`. **No project data is committed**: `data/`, `.secrets/` are git-ignored; the seed file lives at `~/.config/pj/seed.json`.
- Port `8790` on LXC 103 (`192.168.1.10`); server path `/opt/projects`; database `/opt/projects/data/projects.db` (container `/data/projects.db`).
- Not published through the Cloudflare tunnel; no Terraform changes.
- `AUTH_MODE=none` by default; `AUTH_MODE=token` + `AUTH_TOKEN` makes every `/api/*` route except `/api/health` require `Authorization: Bearer <token>`. `pj` sends the token whenever `token` is set in `~/.config/pj/config.toml`.
- Areas: `youtube`, `sites`, `infra`, `jobs`, `crypto`, `research`, `other`. Project statuses: `active`, `paused`, `done`, `dropped`.
- Item types and statuses (first = default): feature `planned, in_progress, done, dropped`; milestone `open, done`; plan `draft, approved, in_progress, done, dropped`; todo `open, doing, done, dropped`; artifact `draft, final, published`; decision / finding / note `logged`. Finished = `done`, `final`, `published`. Todo owner `claude` (default) or `user`; other types have no owner.
- Relation kinds: `implements`, `produced`, `depends_on`, `relates`. Session link roles: `created`, `updated`. Event kinds: `created`, `status`, `edited`, `deleted` (server-written only).
- Timestamps stored as UTC ISO strings `YYYY-MM-DDTHH:MM:SSZ` (transcript timestamps keep milliseconds; both sort correctly as strings).
- Error bodies are `{"error": "<message>"}` with 400 / 404 / 409.
- `pj` never blocks or fails a Claude session: network failures → warning on stderr, request appended to the outbox, exit 0.
- UI language Russian; light + dark theme; usable at 375 px width; one obvious action per screen.
- Commits in `homelab` stage **only the files the task names** (the repo has unrelated uncommitted work). Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

**Decisions made while planning (spec is silent or this is the concrete form):**
- `pj` takes the project as `-p/--project <slug>`; without it, the project is resolved from `$PWD`.
- Search is `LIKE` over a Python `lower()` SQL function, not FTS5 (small data; substring beats tokens for paths/URLs; SQLite folds only ASCII).
- `session.title` comes from transcript `customTitle`/`aiTitle`.
- A session linked to an item before the hook ran gets a stub row (`id`, `project` of the item, `started_at` = link time).
- Item creates carry a client `uid`, so outbox replays are idempotent.

## Review Focus

1. **Cyrillic search and case** — searching `монтаж` must find `Монтаж готов`; `%`/`_` are literal. Test: `test_search_cyrillic_case_insensitive` (Task 3).
2. **Path-prefix false matches** — `/x/nodesize-old` must not resolve to the project mapped at `/x/nodesize`; nested dirs resolve to the longest mapped prefix. Test: `test_resolve_boundary_and_longest_prefix` (Task 3).
3. **Dashboard unreachable (outside home without Tailscale, LXC down)** — `pj` exits 0, queues writes in order, replays them on the next call without duplicating items. Tests: `test_offline_write_goes_to_outbox`, `test_outbox_replay_is_ordered_and_idempotent` (Task 6).
4. **Current chat vs. the later hook** — an item written during a chat links that chat at once (stub session bound to the item's project); the `SessionEnd` upsert later fills title/prompt without losing the project or the earlier `started_at`; compact summaries and tool results never count as human turns; a 50k-line transcript parses in under 3 s. Tests: `test_item_links_current_chat_and_hook_keeps_project` (Task 3), `test_parse_transcript_counts_only_human_turns`, `test_parse_large_transcript_fast` (Task 7).
5. **Backfilled old sessions must not make projects look fresh** — attaching a session that ended in August must not move `updated_at`. Test: `test_old_session_does_not_bump_updated_at` (Task 3).

---

## File Structure

```
services/apps/projects/
  .gitignore                   data/, web/node_modules/, web/dist/, .venv/, .secrets/
  README.md                    what it is, deploy, pj install
  requirements.txt             runtime deps (pinned)
  requirements-dev.txt         + pytest, httpx
  Dockerfile                   node build of web → python slim
  docker-compose.yml
  deploy.sh                    tar → LXC 103, compose up, cron, health check
  npm_proxy.py                 idempotent NPM proxy host via REST API
  backup.py                    sqlite online backup, keep 14
  projects_api/
    __init__.py
    db.py                      schema, connect, now(), touch(), progress(), item_rows(), session_json()
    model.py                   item types, statuses, labels, location kinds
    errors.py                  JSON error handlers
    projects.py                /api/projects routes
    items.py                   /api/items, /api/projects/{slug}/items, relations, todos; auto events; chat links
    sessions.py                sessions, path-map, resolve routes
    search.py                  search route
    main.py                    create_app(): routers, auth middleware, SPA
  client/
    pj.py                      the CLI (stdlib only)
    SKILL.md                   source of ~/.claude/skills/project-log/SKILL.md
  tests/
    conftest.py                app/client fixtures, live server fixture
    test_projects.py  test_items.py  test_sessions_search.py  test_auth_spa.py
    test_pj.py  test_transcript.py  fixtures/transcript.jsonl
  web/
    package.json, package-lock.json, vite.config.ts, tsconfig.json, index.html
    src/main.tsx, App.tsx, index.css, api.ts, types.ts, format.ts, ui.tsx, items.tsx
    src/pages/Home.tsx, Project.tsx, Item.tsx, Waits.tsx, Sessions.tsx, Session.tsx
```

On the Mac (outside the repo): `~/.local/bin/pj` → symlink to `client/pj.py`; `~/.config/pj/config.toml`; `~/.claude/skills/project-log/SKILL.md` (copy); `SessionEnd` hook in `~/.claude/settings.json`.

---

### Task 1: API core — schema, app factory, projects

**Files:**
- Create: `services/apps/projects/.gitignore`, `requirements.txt`, `requirements-dev.txt`, `projects_api/__init__.py`, `projects_api/db.py`, `projects_api/errors.py`, `projects_api/projects.py`, `projects_api/main.py`, `tests/conftest.py`, `tests/test_projects.py`

**Interfaces:**
- Produces: `projects_api.main.create_app(db_path: str | None = None, static_dir: str | None = None, auth_mode: str | None = None, auth_token: str | None = None) -> FastAPI`; in `projects_api.db`: `get_db` (dependency yielding `sqlite3.Connection`, commits on success), `now() -> str`, `touch(conn, slug, ts: str | None = None)` (`updated_at = max(updated_at, ts or now())`), `require_project(conn, slug) -> sqlite3.Row` (404), `progress(override, done, total) -> int | None`, `item_rows(conn, rows) -> list[dict]` (adds `progress` for feature/plan from child todos and `session_count`), `session_json(row) -> dict`. Project JSON: `{slug,title,area,status,summary,next_step,progress_override,progress,created_at,updated_at,open_user_todos,open_todos}`; card adds `items`, `events`, `sessions`.

- [ ] **Step 1: Scaffold files**

All paths below are relative to `services/apps/projects/`.

`.gitignore`:
```
data/
.secrets/
.venv/
web/node_modules/
web/dist/
__pycache__/
.pytest_cache/
```

`requirements.txt`:
```
fastapi==0.118.0
uvicorn==0.37.0
pydantic==2.11.9
```

`requirements-dev.txt`:
```
-r requirements.txt
pytest==8.4.2
httpx==0.28.1
```

`projects_api/__init__.py`: empty file.

Create the venv: `cd services/apps/projects && uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements-dev.txt`

- [ ] **Step 2: Write the failing tests**

`tests/conftest.py`:
```python
import pytest
from fastapi.testclient import TestClient

from projects_api.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), static_dir=str(tmp_path / "nostatic"))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project(client):
    r = client.post("/api/projects", json={"slug": "video02", "title": "Видео 02", "area": "youtube"})
    assert r.status_code == 201
    return r.json()
```

`tests/test_projects.py`:
```python
def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_create_and_get(client, project):
    assert project["slug"] == "video02" and project["progress"] is None
    assert project["open_user_todos"] == 0
    card = client.get("/api/projects/video02").json()
    assert card["title"] == "Видео 02"
    assert card["items"] == [] and card["events"] == [] and card["sessions"] == []


def test_create_with_milestones(client):
    r = client.post("/api/projects", json={"slug": "s1", "title": "S", "milestones": ["a", "b"]})
    assert r.json()["progress"] == 0
    items = client.get("/api/projects/s1").json()["items"]
    assert [(i["type"], i["title"], i["status"]) for i in items] == [("milestone", "a", "open"), ("milestone", "b", "open")]


def test_duplicate_slug_409(client, project):
    r = client.post("/api/projects", json={"slug": "video02", "title": "x"})
    assert r.status_code == 409 and "error" in r.json()


def test_bad_slug_400(client):
    r = client.post("/api/projects", json={"slug": "Bad Slug", "title": "x"})
    assert r.status_code == 400 and "error" in r.json()


def test_unknown_404(client):
    r = client.get("/api/projects/nope")
    assert r.status_code == 404 and r.json() == {"error": "project not found: nope"}


def test_patch_and_clear_override(client, project):
    r = client.patch("/api/projects/video02", json={"next_step": "монтаж", "progress_override": 70})
    assert r.json()["next_step"] == "монтаж" and r.json()["progress"] == 70
    r = client.patch("/api/projects/video02", json={"progress_override": None})
    assert r.json()["progress"] is None
    assert client.patch("/api/projects/video02", json={"title": None}).status_code == 400


def test_list_sorted_by_activity(client):
    client.post("/api/projects", json={"slug": "a", "title": "A"})
    client.post("/api/projects", json={"slug": "b", "title": "B"})
    client.patch("/api/projects/a", json={"summary": "touched"})
    assert client.get("/api/projects").json()[0]["slug"] == "a"


def test_delete(client, project):
    assert client.delete("/api/projects/video02").status_code == 204
    assert client.get("/api/projects/video02").status_code == 404
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd services/apps/projects && .venv/bin/pytest tests/test_projects.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'projects_api.main'`

- [ ] **Step 4: Implement**

`projects_api/db.py`:
```python
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
```

`projects_api/errors.py`:
```python
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException


def install(app: FastAPI) -> None:
    @app.exception_handler(HTTPException)
    async def http_error(_: Request, exc: HTTPException):
        return JSONResponse({"error": str(exc.detail)}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        parts = [f"{'.'.join(str(x) for x in e['loc'][1:])}: {e['msg']}" for e in exc.errors()]
        return JSONResponse({"error": "; ".join(parts) or "invalid request"}, status_code=400)
```

`projects_api/projects.py`:
```python
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .db import get_db, item_rows, now, progress, require_project, session_json, touch

router = APIRouter(prefix="/api")

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
    ts = now()
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
```

`projects_api/main.py`:
```python
import os
from pathlib import Path

from fastapi import FastAPI

from . import db, errors, projects


def create_app(db_path: str | None = None, static_dir: str | None = None,
               auth_mode: str | None = None, auth_token: str | None = None) -> FastAPI:
    app = FastAPI(title="projects", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.db_path = db_path or os.environ.get("PROJECTS_DB", "/data/projects.db")
    Path(app.state.db_path).parent.mkdir(parents=True, exist_ok=True)
    db.init(app.state.db_path)
    errors.install(app)
    app.include_router(projects.router)
    return app
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd services/apps/projects && .venv/bin/pytest tests/test_projects.py -q`
Expected: all passed, 0 failed

- [ ] **Step 6: Commit**

```bash
cd ~/prj/homeserver/homelab
git add services/apps/projects/.gitignore services/apps/projects/requirements.txt services/apps/projects/requirements-dev.txt services/apps/projects/projects_api services/apps/projects/tests
git commit -m "projects: API core, schema with typed items, projects CRUD

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Items — types, statuses, progress, relations, auto events, chat links, todos

**Files:**
- Create: `services/apps/projects/projects_api/model.py`, `services/apps/projects/projects_api/items.py`, `services/apps/projects/tests/test_items.py`
- Modify: `services/apps/projects/projects_api/main.py` (import `items`, include `items.router` after `projects.router`)

**Interfaces:**
- Consumes: Task 1 `db` helpers.
- Produces:
  - `model.TYPES: dict[str, list[str]]`, `model.LABELS`, `model.STATUS_LABELS`, `model.default_status(t)`, `model.check_status(t, s)` (400), `model.finished(s) -> bool`, `model.done_status(t) -> str`, `model.location_kind(loc: str | None) -> str | None` (`repo` for github/gitlab, `artifact` for claude.ai artifacts, `url`, `path`).
  - `items.get_item(conn, id) -> Row` (404), `items.small(row) -> {id,type,title,status,project}`, `items.link_session(conn, session_id, item_row, role, ts)` (creates the stub session).
  - Routes: `POST /api/projects/{slug}/items` (201; same `uid` → 200 with the existing item), `GET /api/items/{id}` (detail: `parent`, `children`, `relations: [{direction: "out"|"in", kind, item: small}]`, `sessions: [{id,title,first_prompt,cwd,started_at,ended_at,roles}]`, `events`), `PATCH /api/items/{id}`, `POST /api/items/{id}/done {session_id?}`, `DELETE /api/items/{id}` (204), `POST /api/items/{id}/relations {to_id, kind}` (201), `DELETE /api/items/{id}/relations/{kind}/{to_id}` (204), `GET /api/todos?owner=&project=` (open/doing todos + `project_title`, oldest first).

- [ ] **Step 1: Write the failing tests**

`tests/test_items.py`:
```python
def add(client, type_, title, slug="video02", **kw):
    r = client.post(f"/api/projects/{slug}/items", json={"type": type_, "title": title, **kw})
    assert r.status_code in (200, 201), r.json()
    return r.json()


def test_defaults_per_type(client, project):
    assert add(client, "feature", "Озвучка")["status"] == "planned"
    t = add(client, "todo", "Свести звук")
    assert t["status"] == "open" and t["owner"] == "claude"
    assert add(client, "decision", "ElevenLabs")["status"] == "logged"
    assert add(client, "feature", "Монтаж")["owner"] is None


def test_status_validated_per_type(client, project):
    r = client.post("/api/projects/video02/items", json={"type": "todo", "title": "x", "status": "published"})
    assert r.status_code == 400 and "open, doing, done, dropped" in r.json()["error"]
    assert add(client, "artifact", "Рендер", status="published")["done_at"]
    t = add(client, "todo", "y")
    assert client.patch(f"/api/items/{t['id']}", json={"status": "final"}).status_code == 400
    assert client.post("/api/projects/video02/items", json={"type": "bogus", "title": "x"}).status_code == 400


def test_owner_only_for_todo(client, project):
    r = client.post("/api/projects/video02/items", json={"type": "feature", "title": "x", "owner": "user"})
    assert r.status_code == 400
    f = add(client, "feature", "f")
    assert client.patch(f"/api/items/{f['id']}", json={"owner": "user"}).status_code == 400


def test_parent_must_be_same_project(client, project):
    client.post("/api/projects", json={"slug": "other", "title": "O"})
    f = add(client, "feature", "чужая", slug="other")
    r = client.post("/api/projects/video02/items", json={"type": "todo", "title": "x", "parent_id": f["id"]})
    assert r.status_code == 400
    mine = add(client, "feature", "своя")
    assert client.patch(f"/api/items/{mine['id']}", json={"parent_id": mine["id"]}).status_code == 400


def test_feature_progress_from_child_todos(client, project):
    f = add(client, "feature", "Озвучка")
    a = add(client, "todo", "a", parent_id=f["id"])
    add(client, "todo", "b", parent_id=f["id"])
    c = add(client, "todo", "c", parent_id=f["id"])
    client.post(f"/api/items/{a['id']}/done", json={})
    client.patch(f"/api/items/{c['id']}", json={"status": "dropped"})
    feat = next(i for i in client.get("/api/projects/video02").json()["items"] if i["id"] == f["id"])
    assert feat["progress"] == 50
    assert [ch["title"] for ch in client.get(f"/api/items/{f['id']}").json()["children"]] == ["a", "b", "c"]


def test_project_progress_from_milestones(client):
    client.post("/api/projects", json={"slug": "v", "title": "V", "milestones": ["a", "b", "c", "d"]})
    ms = client.get("/api/projects/v").json()["items"]
    client.post(f"/api/items/{ms[0]['id']}/done", json={})
    assert client.get("/api/projects/v").json()["progress"] == 25


def test_done_endpoint_per_type(client, project):
    a = add(client, "artifact", "Рендер")
    assert client.post(f"/api/items/{a['id']}/done", json={}).json()["status"] == "final"
    t = add(client, "todo", "t")
    r = client.post(f"/api/items/{t['id']}/done", json={}).json()
    assert r["status"] == "done" and r["done_at"]
    assert client.patch(f"/api/items/{t['id']}", json={"status": "open"}).json()["done_at"] is None


def test_uid_idempotent(client, project):
    a = client.post("/api/projects/video02/items", json={"type": "note", "title": "n", "uid": "u1"})
    b = client.post("/api/projects/video02/items", json={"type": "note", "title": "n", "uid": "u1"})
    assert a.status_code == 201 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    assert len(client.get("/api/projects/video02").json()["items"]) == 1


def test_auto_events(client, project):
    t = add(client, "todo", "Свести звук")
    client.post(f"/api/items/{t['id']}/done", json={})
    client.patch(f"/api/items/{t['id']}", json={"body": "готово в Reaper"})
    client.patch(f"/api/items/{t['id']}", json={"position": 5})  # no event for reordering
    ev = client.get("/api/projects/video02").json()["events"]
    assert [e["kind"] for e in ev] == ["edited", "status", "created"]
    assert ev[2]["text"] == "Задача «Свести звук»" and ev[2]["item_type"] == "todo"
    assert ev[1]["text"].endswith("открыто → готово")
    assert len(client.get(f"/api/items/{t['id']}").json()["events"]) == 3


def test_relations(client, project):
    f = add(client, "feature", "Озвучка")
    p = add(client, "plan", "План озвучки", location="/x/plan.md")
    assert client.post(f"/api/items/{p['id']}/relations", json={"to_id": f["id"], "kind": "implements"}).status_code == 201
    client.post(f"/api/items/{p['id']}/relations", json={"to_id": f["id"], "kind": "implements"})  # duplicate ignored
    rel = client.get(f"/api/items/{f['id']}").json()["relations"]
    assert rel == [{"direction": "in", "kind": "implements",
                    "item": {"id": p["id"], "type": "plan", "title": "План озвучки", "status": "draft", "project": "video02"}}]
    assert client.post(f"/api/items/{p['id']}/relations", json={"to_id": p["id"], "kind": "relates"}).status_code == 400
    assert client.post(f"/api/items/{p['id']}/relations", json={"to_id": 999, "kind": "relates"}).status_code == 404
    assert client.delete(f"/api/items/{p['id']}/relations/implements/{f['id']}").status_code == 204
    assert client.get(f"/api/items/{f['id']}").json()["relations"] == []


def test_location_kind(client, project):
    assert add(client, "artifact", "repo", location="https://github.com/kalikys/homelab")["location_kind"] == "repo"
    assert add(client, "artifact", "art", location="https://claude.ai/artifact/abc")["location_kind"] == "artifact"
    assert add(client, "artifact", "site", location="https://nodesize.kalik8s.com")["location_kind"] == "url"
    assert add(client, "artifact", "file", location="/x/v6.mp4")["location_kind"] == "path"
    assert add(client, "note", "none")["location_kind"] is None


def test_user_todos(client, project):
    add(client, "todo", "нажать Publish app", owner="user")
    done = add(client, "todo", "старое", owner="user")
    client.post(f"/api/items/{done['id']}/done", json={})
    add(client, "todo", "моё", owner="claude")
    todos = client.get("/api/todos", params={"owner": "user"}).json()
    assert [t["title"] for t in todos] == ["нажать Publish app"] and todos[0]["project_title"] == "Видео 02"
    p = client.get("/api/projects").json()[0]
    assert p["open_user_todos"] == 1 and p["open_todos"] == 1


def test_item_404_and_delete(client, project):
    assert client.get("/api/items/999").status_code == 404
    n = add(client, "note", "черновик")
    assert client.delete(f"/api/items/{n['id']}").status_code == 204
    assert client.get(f"/api/items/{n['id']}").status_code == 404
    assert client.get("/api/projects/video02").json()["events"][0]["kind"] == "deleted"


def test_session_link_on_write(client, project):
    t = add(client, "todo", "t", session_id="chat-1")
    client.post(f"/api/items/{t['id']}/done", json={"session_id": "chat-1"})
    client.patch(f"/api/items/{t['id']}", json={"title": "t2", "session_id": "chat-2"})
    sessions = client.get(f"/api/items/{t['id']}").json()["sessions"]
    assert {s["id"]: sorted(s["roles"]) for s in sessions} == {"chat-1": ["created", "updated"], "chat-2": ["updated"]}
    assert next(i for i in client.get("/api/projects/video02").json()["items"])["session_count"] == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_items.py -q`
Expected: FAIL (404/405 — routes missing).

- [ ] **Step 3: Implement**

`projects_api/model.py`:
```python
import re

from fastapi import HTTPException

# Statuses per item type; the first one is the default.
TYPES: dict[str, list[str]] = {
    "feature": ["planned", "in_progress", "done", "dropped"],
    "milestone": ["open", "done"],
    "plan": ["draft", "approved", "in_progress", "done", "dropped"],
    "todo": ["open", "doing", "done", "dropped"],
    "artifact": ["draft", "final", "published"],
    "decision": ["logged"],
    "finding": ["logged"],
    "note": ["logged"],
}
LABELS = {"feature": "Фича", "milestone": "Этап", "plan": "План", "todo": "Задача", "artifact": "Артефакт",
          "decision": "Решение", "finding": "Находка", "note": "Заметка"}
STATUS_LABELS = {"planned": "запланировано", "in_progress": "в работе", "done": "готово", "dropped": "отменено",
                 "open": "открыто", "doing": "в работе", "draft": "черновик", "approved": "утверждено",
                 "final": "финал", "published": "опубликовано", "logged": "записано"}
FINISHED = {"done", "final", "published"}


def default_status(t: str) -> str:
    return TYPES[t][0]


def check_status(t: str, s: str | None) -> None:
    if s not in TYPES[t]:
        raise HTTPException(400, f"status for {t} must be one of: {', '.join(TYPES[t])}")


def finished(s: str) -> bool:
    return s in FINISHED


def done_status(t: str) -> str:
    if t == "artifact":
        return "final"
    return "done" if "done" in TYPES[t] else TYPES[t][0]


def location_kind(loc: str | None) -> str | None:
    if not loc:
        return None
    if re.match(r"https?://(www\.)?(github|gitlab)\.com/", loc):
        return "repo"
    if re.match(r"https?://claude\.ai/(code/)?artifact/", loc):
        return "artifact"
    if re.match(r"https?://", loc):
        return "url"
    return "path"
```

`projects_api/items.py`:
```python
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from .db import get_db, item_rows, now, require_project, touch
from .model import LABELS, STATUS_LABELS, check_status, default_status, done_status, finished, location_kind

router = APIRouter(prefix="/api")

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
```

In `projects_api/main.py`: change the import to `from . import db, errors, items, projects` and add `app.include_router(items.router)` after `app.include_router(projects.router)`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests -q`
Expected: all passed, 0 failed

- [ ] **Step 5: Commit**

```bash
cd ~/prj/homeserver/homelab
git add services/apps/projects/projects_api/model.py services/apps/projects/projects_api/items.py services/apps/projects/projects_api/main.py services/apps/projects/tests/test_items.py
git commit -m "projects: typed items, relations, auto events, chat links, todos

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: Sessions, path map, resolve, search

**Files:**
- Create: `services/apps/projects/projects_api/sessions.py`, `services/apps/projects/projects_api/search.py`, `services/apps/projects/tests/test_sessions_search.py`
- Modify: `services/apps/projects/projects_api/main.py` (import and include `sessions.router`, `search.router`)

**Interfaces:**
- Consumes: Task 1 helpers, Task 2 stub sessions (`link_session`).
- Produces: `sessions.resolve(conn, cwd) -> str | None`; routes `POST /api/sessions` (upsert; body `{id, title?, cwd?, first_prompt?, started_at?, ended_at?, user_turns?, files_changed?, transcript_path?, project?}`), `GET /api/sessions?unsorted=1&limit=100`, `GET /api/sessions/{id}` (+ `items: [{id,type,title,status,project,roles}]`), `PATCH /api/sessions/{id} {project}`, `GET /api/resolve?cwd=` → `{"project": slug|null}`, `GET/POST /api/path-map`, `GET /api/search?q=` → `[{project, title, hits: [{type, id, text, ts}]}]` (`type` is `project` or the item type).

- [ ] **Step 1: Write the failing tests**

`tests/test_sessions_search.py`:
```python
def mk(client, slug, title="T"):
    assert client.post("/api/projects", json={"slug": slug, "title": title}).status_code == 201


def test_resolve_boundary_and_longest_prefix(client):
    mk(client, "home")
    mk(client, "nodesize")
    client.post("/api/path-map", json={"prefix": "/x/homeserver", "project": "home"})
    client.post("/api/path-map", json={"prefix": "/x/homeserver/nodesize/", "project": "nodesize"})
    r = lambda cwd: client.get("/api/resolve", params={"cwd": cwd}).json()["project"]
    assert r("/x/homeserver/nodesize/site") == "nodesize"
    assert r("/x/homeserver/nodesize") == "nodesize"
    assert r("/x/homeserver/nodesize-old") == "home"
    assert r("/x/homeserverx") is None


def test_path_map_unknown_project_404(client):
    assert client.post("/api/path-map", json={"prefix": "/a", "project": "nope"}).status_code == 404


def test_session_resolves_project_from_cwd(client):
    mk(client, "nodesize")
    client.post("/api/path-map", json={"prefix": "/x/nodesize", "project": "nodesize"})
    s = client.post("/api/sessions", json={"id": "s1", "cwd": "/x/nodesize/web", "first_prompt": "привет",
                                           "ended_at": "2026-10-12T10:00:00Z", "user_turns": 5}).json()
    assert s["project"] == "nodesize"
    assert client.get("/api/projects/nodesize").json()["sessions"][0]["id"] == "s1"


def test_session_upsert_keeps_first_prompt_and_project(client):
    mk(client, "a")
    client.post("/api/sessions", json={"id": "s1", "cwd": "/nowhere", "first_prompt": "первый", "user_turns": 3})
    client.patch("/api/sessions/s1", json={"project": "a"})
    s = client.post("/api/sessions", json={"id": "s1", "cwd": "/nowhere", "first_prompt": "другой",
                                           "user_turns": 9, "ended_at": "2026-10-12T11:00:00Z"}).json()
    assert s["first_prompt"] == "первый" and s["project"] == "a" and s["user_turns"] == 9


def test_item_links_current_chat_and_hook_keeps_project(client):
    mk(client, "v")
    it = client.post("/api/projects/v/items", json={"type": "todo", "title": "t", "session_id": "chat-1"}).json()
    card = client.get("/api/projects/v").json()
    assert [s["id"] for s in card["sessions"]] == ["chat-1"]
    s = client.post("/api/sessions", json={"id": "chat-1", "cwd": "/unmapped", "title": "Дашборд",
                                           "started_at": "2000-01-01T00:00:00Z", "ended_at": "2099-01-01T00:00:00Z",
                                           "user_turns": 4}).json()
    assert s["project"] == "v" and s["title"] == "Дашборд" and s["started_at"] == "2000-01-01T00:00:00Z"
    detail = client.get("/api/sessions/chat-1").json()
    assert detail["items"] == [{"id": it["id"], "type": "todo", "title": "t", "status": "open", "project": "v",
                                "roles": ["created"]}]


def test_unsorted_sessions(client):
    client.post("/api/sessions", json={"id": "s1", "cwd": "/nowhere", "ended_at": "2026-10-01T00:00:00Z"})
    client.post("/api/sessions", json={"id": "s2", "cwd": "/nowhere", "ended_at": "2026-10-02T00:00:00Z"})
    assert [s["id"] for s in client.get("/api/sessions", params={"unsorted": 1}).json()] == ["s2", "s1"]


def test_old_session_does_not_bump_updated_at(client):
    mk(client, "a")
    before = client.get("/api/projects/a").json()["updated_at"]
    client.post("/api/sessions", json={"id": "old", "project": "a", "ended_at": "2026-08-01T00:00:00Z"})
    assert client.get("/api/projects/a").json()["updated_at"] == before


def test_session_errors(client):
    assert client.post("/api/sessions", json={"id": "s", "project": "nope"}).status_code == 404
    assert client.get("/api/sessions/nope").status_code == 404


def test_search_cyrillic_case_insensitive(client):
    mk(client, "v", "Видео")
    client.post("/api/projects/v/items", json={"type": "finding", "title": "Монтаж готов", "body": "в DaVinci"})
    client.post("/api/projects/v/items", json={"type": "artifact", "title": "Рендер", "location": "/x/50%_done.mp4"})
    res = client.get("/api/search", params={"q": "монтаж"}).json()
    assert res[0]["project"] == "v" and res[0]["hits"][0]["type"] == "finding"
    assert res[0]["hits"][0]["text"].startswith("Монтаж готов")
    assert client.get("/api/search", params={"q": "davinci"}).json()[0]["hits"][0]["type"] == "finding"
    assert [h["type"] for h in client.get("/api/search", params={"q": "50%_"}).json()[0]["hits"]] == ["artifact"]
    assert client.get("/api/search", params={"q": "  "}).json() == []
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_sessions_search.py -q`
Expected: FAIL (404 on `/api/path-map`, `/api/sessions`, `/api/search`)

- [ ] **Step 3: Implement**

`projects_api/sessions.py`:
```python
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
```

`projects_api/search.py`:
```python
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
```

In `projects_api/main.py`: import line becomes `from . import db, errors, items, projects, search, sessions`; after `app.include_router(items.router)` add `app.include_router(sessions.router)` and `app.include_router(search.router)`.

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests -q`
Expected: all passed, 0 failed

- [ ] **Step 5: Commit**

```bash
cd ~/prj/homeserver/homelab
git add services/apps/projects/projects_api/sessions.py services/apps/projects/projects_api/search.py services/apps/projects/projects_api/main.py services/apps/projects/tests/test_sessions_search.py
git commit -m "projects: sessions, path map, resolve, search

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Auth hook and SPA serving

**Files:**
- Modify: `services/apps/projects/projects_api/main.py`
- Create: `services/apps/projects/tests/test_auth_spa.py`

**Interfaces:**
- Produces: `create_app(..., auth_mode="token", auth_token="t")` rejects `/api/*` (except `/api/health`) without `Authorization: Bearer t` → 401 `{"error":"unauthorized"}`. With `static_dir` containing `index.html`: `/assets/*` served as files, any other non-`/api` GET returns `index.html`. Env: `PROJECTS_DB`, `STATIC_DIR` (default `/app/static`), `AUTH_MODE` (default `none`), `AUTH_TOKEN`.

- [ ] **Step 1: Write the failing tests**

`tests/test_auth_spa.py`:
```python
from fastapi.testclient import TestClient

from projects_api.main import create_app


def test_token_mode(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), static_dir=str(tmp_path), auth_mode="token", auth_token="t")
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        r = c.get("/api/projects")
        assert r.status_code == 401 and r.json() == {"error": "unauthorized"}
        assert c.get("/api/projects", headers={"Authorization": "Bearer t"}).status_code == 200


def test_spa_fallback(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<html>spa</html>")
    app = create_app(db_path=str(tmp_path / "t.db"), static_dir=str(tmp_path))
    with TestClient(app) as c:
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert "spa" in c.get("/p/video02").text
        assert c.get("/api/nope").status_code == 404
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/pytest tests/test_auth_spa.py -q`
Expected: FAIL (401 not returned; `/p/video02` 404)

- [ ] **Step 3: Implement** — replace `projects_api/main.py` with:

```python
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, errors, items, projects, search, sessions


def create_app(db_path: str | None = None, static_dir: str | None = None,
               auth_mode: str | None = None, auth_token: str | None = None) -> FastAPI:
    app = FastAPI(title="projects", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.db_path = db_path or os.environ.get("PROJECTS_DB", "/data/projects.db")
    Path(app.state.db_path).parent.mkdir(parents=True, exist_ok=True)
    db.init(app.state.db_path)
    errors.install(app)

    # Auth is off on the LAN; AUTH_MODE=token is the switch for later.
    mode = auth_mode or os.environ.get("AUTH_MODE", "none")
    if mode == "token":
        expected = "Bearer " + (auth_token or os.environ["AUTH_TOKEN"])

        @app.middleware("http")
        async def require_token(request: Request, call_next):
            path = request.url.path
            if path.startswith("/api/") and path != "/api/health" and request.headers.get("authorization") != expected:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app.include_router(projects.router)
    app.include_router(items.router)
    app.include_router(sessions.router)
    app.include_router(search.router)

    static = Path(static_dir or os.environ.get("STATIC_DIR", "/app/static"))
    index = static / "index.html"
    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/") or not index.is_file():
            raise HTTPException(404, "not found")
        file = static / path
        if path and file.is_file() and static in file.resolve().parents:
            return FileResponse(file)
        return FileResponse(index)

    return app
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/pytest tests -q`
Expected: all passed, 0 failed

- [ ] **Step 5: Commit**

```bash
cd ~/prj/homeserver/homelab
git add services/apps/projects/projects_api/main.py services/apps/projects/tests/test_auth_spa.py
git commit -m "projects: token auth switch (off by default) and SPA serving

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Frontend

**Files:**
- Create: everything under `services/apps/projects/web/` listed in File Structure.

**Interfaces:**
- Consumes: the API from Tasks 1–3 (JSON shapes as returned there).
- Produces: `npm run build` → `web/dist/` with `index.html` + `assets/`. Routes: `/` home, `/p/:slug?tab=overview|todos|artifacts|log|chats|history`, `/i/:id` item, `/s/:id` chat, `/waits`, `/sessions`.

Design rules (from the user's feedback): one obvious action per screen, no wall of text, rare things folded. Before styling, look once at Linear's project view and GitHub Projects for density; keep cards sparse. Each item type has one icon and one way of being shown, defined in `types.ts` and `items.tsx` — pages never invent their own rendering of an item.

- [ ] **Step 1: Scaffold the package**

`web/package.json`:
```json
{
  "name": "projects-web",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc --noEmit && vite build"
  },
  "dependencies": {
    "lucide-react": "0.544.0",
    "react": "19.1.1",
    "react-dom": "19.1.1",
    "react-router-dom": "7.9.3"
  },
  "devDependencies": {
    "@tailwindcss/vite": "4.1.13",
    "@types/react": "19.1.13",
    "@types/react-dom": "19.1.9",
    "@vitejs/plugin-react": "5.0.3",
    "tailwindcss": "4.1.13",
    "typescript": "5.9.2",
    "vite": "7.1.7"
  }
}
```

`web/vite.config.ts`:
```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: { proxy: { "/api": "http://127.0.0.1:8790" } },
});
```

`web/tsconfig.json`:
```json
{
  "compilerOptions": {
    "target": "ES2022",
    "lib": ["ES2022", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "moduleResolution": "bundler",
    "jsx": "react-jsx",
    "strict": true,
    "noEmit": true,
    "skipLibCheck": true
  },
  "include": ["src"]
}
```

`web/index.html`:
```html
<!doctype html>
<html lang="ru">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Проекты</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

Run: `cd services/apps/projects/web && npm install` (creates `package-lock.json`).

- [ ] **Step 2: Styles, API client, type metadata, formatting**

`web/src/index.css`:
```css
@import "tailwindcss";

:root {
  --bg: #fafaf9; --card: #ffffff; --fg: #1c1917; --muted: #78716c; --line: #e7e5e4;
  --accent: #2563eb; --amber-bg: #fef3c7; --amber-fg: #92400e; --ok: #16a34a;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0c0a09; --card: #1c1917; --fg: #f5f5f4; --muted: #a8a29e; --line: #292524;
    --accent: #60a5fa; --amber-bg: #422006; --amber-fg: #fcd34d; --ok: #4ade80;
  }
}
@theme inline {
  --color-bg: var(--bg); --color-card: var(--card); --color-fg: var(--fg); --color-muted: var(--muted);
  --color-line: var(--line); --color-accent: var(--accent); --color-amber-bg: var(--amber-bg);
  --color-amber-fg: var(--amber-fg); --color-ok: var(--ok);
}
body { background: var(--bg); color: var(--fg); font-family: ui-sans-serif, system-ui, sans-serif; }
```

`web/src/api.ts`:
```ts
import type { ItemType } from "./types";

export type Project = {
  slug: string; title: string; area: string; status: string; summary: string; next_step: string;
  progress: number | null; progress_override: number | null; created_at: string; updated_at: string;
  open_user_todos: number; open_todos: number;
};
export type Item = {
  id: number; project: string; type: ItemType; title: string; body: string; status: string; owner: string | null;
  location: string | null; location_kind: string | null; parent_id: number | null; position: number;
  created_at: string; updated_at: string; done_at: string | null; progress: number | null; session_count: number;
  project_title?: string;
};
export type Small = { id: number; type: ItemType; title: string; status: string; project: string };
export type Ev = { id: number; item_id: number | null; item_type: string | null; session_id: string | null; ts: string; kind: string; text: string };
export type Session = {
  id: string; project: string | null; title: string; cwd: string; first_prompt: string;
  started_at: string | null; ended_at: string | null; user_turns: number; files_changed: string[];
};
export type Card = Project & { items: Item[]; events: Ev[]; sessions: Session[] };
export type ItemDetail = Item & {
  parent: Small | null; children: Item[];
  relations: { direction: "out" | "in"; kind: string; item: Small }[];
  sessions: (Pick<Session, "id" | "title" | "first_prompt" | "cwd" | "started_at" | "ended_at"> & { roles: string[] })[];
  events: Ev[];
};
export type SessionDetail = Session & { items: (Small & { roles: string[] })[] };
export type SearchGroup = { project: string; title: string; hits: { type: string; id: number | string; text: string; ts: string }[] };

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await fetch(path, {
    method, headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error ?? r.statusText);
  return r.status === 204 ? (undefined as T) : r.json();
}

export const api = {
  projects: () => call<Project[]>("GET", "/api/projects"),
  project: (slug: string) => call<Card>("GET", `/api/projects/${slug}`),
  item: (id: number) => call<ItemDetail>("GET", `/api/items/${id}`),
  patchItem: (id: number, body: { status?: string; owner?: string }) => call<Item>("PATCH", `/api/items/${id}`, body),
  userTodos: () => call<Item[]>("GET", "/api/todos?owner=user"),
  unsorted: () => call<Session[]>("GET", "/api/sessions?unsorted=1"),
  session: (id: string) => call<SessionDetail>("GET", `/api/sessions/${id}`),
  attach: (id: string, project: string) => call<Session>("PATCH", `/api/sessions/${id}`, { project }),
  addPathMap: (prefix: string, project: string) => call("POST", "/api/path-map", { prefix, project }),
  search: (q: string) => call<SearchGroup[]>("GET", `/api/search?q=${encodeURIComponent(q)}`),
};
```

`web/src/types.ts`:
```ts
import { Box, FileText, Flag, Lightbulb, ListChecks, Puzzle, Scale, StickyNote, type LucideIcon } from "lucide-react";

export type ItemType = "feature" | "milestone" | "plan" | "todo" | "artifact" | "decision" | "finding" | "note";

export const TYPE: Record<ItemType, { label: string; icon: LucideIcon }> = {
  feature: { label: "Фича", icon: Puzzle },
  milestone: { label: "Этап", icon: Flag },
  plan: { label: "План", icon: FileText },
  todo: { label: "Задача", icon: ListChecks },
  artifact: { label: "Артефакт", icon: Box },
  decision: { label: "Решение", icon: Scale },
  finding: { label: "Находка", icon: Lightbulb },
  note: { label: "Заметка", icon: StickyNote },
};

// Must match projects_api/model.py TYPES.
export const STATUSES: Record<ItemType, string[]> = {
  feature: ["planned", "in_progress", "done", "dropped"],
  milestone: ["open", "done"],
  plan: ["draft", "approved", "in_progress", "done", "dropped"],
  todo: ["open", "doing", "done", "dropped"],
  artifact: ["draft", "final", "published"],
  decision: ["logged"], finding: ["logged"], note: ["logged"],
};

export const STATUS: Record<string, string> = {
  planned: "запланировано", in_progress: "в работе", done: "готово", dropped: "отменено", open: "открыто",
  doing: "в работе", draft: "черновик", approved: "утверждено", final: "финал", published: "опубликовано", logged: "записано",
};

export const REL: Record<"out" | "in", Record<string, string>> = {
  out: { implements: "реализует", produced: "создала", depends_on: "зависит от", relates: "связано с" },
  in: { implements: "реализуется в", produced: "создан в", depends_on: "нужен для", relates: "связано с" },
};

export const ROLE: Record<string, string> = { created: "создан", updated: "изменён" };

export const isOpen = (s: string) => !["done", "dropped", "final", "published", "logged"].includes(s);

export const tone = (s: string): "ok" | "accent" | "muted" =>
  ["done", "final", "published"].includes(s) ? "ok" : ["in_progress", "doing", "approved"].includes(s) ? "accent" : "muted";
```

`web/src/format.ts`:
```ts
const rtf = new Intl.RelativeTimeFormat("ru", { numeric: "auto" });
const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 31557600], ["month", 2629800], ["week", 604800], ["day", 86400], ["hour", 3600], ["minute", 60], ["second", 1],
];

export function ago(iso: string | null | undefined): string {
  if (!iso) return "—";
  const s = (new Date(iso).getTime() - Date.now()) / 1000;
  const [unit, size] = UNITS.find(([, size]) => Math.abs(s) >= size) ?? ["second", 1];
  return rtf.format(Math.round(s / size), unit);
}

export function day(iso: string | null | undefined): string {
  return iso ? new Date(iso).toLocaleDateString("ru", { day: "numeric", month: "short" }) : "—";
}

export const isStale = (p: { status: string; updated_at: string }) =>
  p.status === "active" && Date.now() - new Date(p.updated_at).getTime() > 7 * 86400_000;

export const AREAS: Record<string, string> = {
  youtube: "YouTube", sites: "Сайты", infra: "Инфра", jobs: "Работа", crypto: "Крипто", research: "Исследования", other: "Другое",
};

export const resume = (s: { id: string; cwd: string }) => (s.cwd ? `cd ${s.cwd} && ` : "") + `claude --resume ${s.id}`;
```

- [ ] **Step 3: UI primitives and item rendering**

`web/src/ui.tsx`:
```tsx
import { useState, type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode } from "react";
import { Check, Copy } from "lucide-react";

export const Card = ({ children, className = "" }: { children: ReactNode; className?: string }) => (
  <div className={`rounded-xl border border-line bg-card p-4 ${className}`}>{children}</div>
);

export const Badge = ({ children, tone = "muted" }: { children: ReactNode; tone?: "muted" | "amber" | "accent" | "ok" }) => {
  const t = {
    muted: "text-muted border-line", amber: "bg-amber-bg text-amber-fg border-transparent",
    accent: "text-accent border-accent/40", ok: "text-ok border-ok/40",
  }[tone];
  return <span className={`inline-flex shrink-0 items-center rounded-full border px-2 py-0.5 text-xs ${t}`}>{children}</span>;
};

export const Button = ({ className = "", ...p }: ButtonHTMLAttributes<HTMLButtonElement>) => (
  <button {...p} className={`inline-flex items-center gap-1.5 rounded-lg border border-line px-3 py-1.5 text-sm transition hover:bg-line/50 active:scale-[.98] ${className}`} />
);

export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => (
  <input {...p} className={`w-full rounded-lg border border-line bg-card px-3 py-2 text-sm outline-none focus:border-accent ${p.className ?? ""}`} />
);

export const Progress = ({ value }: { value: number | null }) =>
  value === null ? null : (
    <div className="flex items-center gap-2">
      <div className="h-1.5 flex-1 rounded-full bg-line">
        <div className="h-1.5 rounded-full bg-accent transition-all" style={{ width: `${value}%` }} />
      </div>
      <span className="w-9 text-right text-xs tabular-nums text-muted">{value}%</span>
    </div>
  );

export function CopyButton({ text, label }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <Button title={text} className="px-2 py-1 text-xs"
      onClick={(e) => { e.preventDefault(); navigator.clipboard.writeText(text); setDone(true); setTimeout(() => setDone(false), 1200); }}>
      {done ? <Check size={14} /> : <Copy size={14} />}{label}
    </Button>
  );
}

export const Section = ({ title, children }: { title: string; children: ReactNode }) => (
  <section className="space-y-1"><h2 className="text-sm font-medium text-muted">{title}</h2>{children}</section>
);

export function Tabs({ tabs, value, onChange }: { tabs: { id: string; label: string; count?: number }[]; value: string; onChange: (id: string) => void }) {
  return (
    <div className="-mx-4 flex gap-1 overflow-x-auto border-b border-line px-4">
      {tabs.map((t) => (
        <button key={t.id} onClick={() => onChange(t.id)}
          className={`shrink-0 border-b-2 px-3 py-2 text-sm ${value === t.id ? "border-accent text-fg" : "border-transparent text-muted hover:text-fg"}`}>
          {t.label}{t.count ? <span className="ml-1 text-xs text-muted">{t.count}</span> : null}
        </button>
      ))}
    </div>
  );
}

export const Empty = ({ children }: { children: ReactNode }) => <p className="py-2 text-sm text-muted">{children}</p>;
```

`web/src/items.tsx`:
```tsx
import { Link } from "react-router-dom";
import { ExternalLink, MessageSquare } from "lucide-react";
import { api, type Item } from "./api";
import { STATUS, TYPE, isOpen, tone } from "./types";
import { Badge, CopyButton } from "./ui";

export function Location({ item }: { item: { location: string | null; location_kind: string | null } }) {
  if (!item.location) return null;
  if (item.location_kind === "path")
    return <CopyButton text={item.location} label={item.location.split("/").slice(-2).join("/")} />;
  return (
    <a href={item.location} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs text-accent">
      <ExternalLink size={12} />{item.location.replace(/^https?:\/\//, "").slice(0, 48)}
    </a>
  );
}

// The one way an item is shown in a list. Todos and milestones get a checkbox, everything else its type icon.
export function ItemRow({ item, onChange, withProject }: { item: Item; onChange?: () => void; withProject?: boolean }) {
  const Icon = TYPE[item.type].icon;
  const checkable = item.type === "todo" || item.type === "milestone";
  const closed = !isOpen(item.status) && item.status !== "logged";
  return (
    <div className="flex items-center gap-2 py-1.5 text-sm">
      {checkable ? (
        <input type="checkbox" className="shrink-0" checked={item.status === "done"} aria-label={item.title}
          onChange={(e) => api.patchItem(item.id, { status: e.target.checked ? "done" : "open" }).then(onChange)} />
      ) : (
        <Icon size={15} className="shrink-0 text-muted" aria-label={TYPE[item.type].label} />
      )}
      <Link to={`/i/${item.id}`} className={`min-w-0 flex-1 truncate hover:text-accent ${closed ? "text-muted line-through" : ""}`}>
        {item.title}
        {withProject && item.project_title && <span className="ml-2 text-xs text-muted">{item.project_title}</span>}
      </Link>
      {item.type === "todo" && item.owner === "user" && !withProject && <Badge tone="amber">тебе</Badge>}
      {item.progress !== null && <span className="text-xs tabular-nums text-muted">{item.progress}%</span>}
      {!checkable && item.status !== "logged" && <Badge tone={tone(item.status)}>{STATUS[item.status] ?? item.status}</Badge>}
      {item.session_count > 0 && (
        <span className="flex shrink-0 items-center gap-0.5 text-xs text-muted" title="чатов"><MessageSquare size={12} />{item.session_count}</span>
      )}
    </div>
  );
}

export const ItemList = ({ items, onChange, empty, withProject }: { items: Item[]; onChange?: () => void; empty?: string; withProject?: boolean }) =>
  items.length ? (
    <div className="divide-y divide-line">{items.map((i) => <ItemRow key={i.id} item={i} onChange={onChange} withProject={withProject} />)}</div>
  ) : empty ? <p className="py-2 text-sm text-muted">{empty}</p> : null;
```

- [ ] **Step 4: App shell and pages**

`web/src/main.tsx`:
```tsx
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode><BrowserRouter><App /></BrowserRouter></StrictMode>,
);
```

`web/src/App.tsx`:
```tsx
import { Link, Route, Routes } from "react-router-dom";
import Home from "./pages/Home";
import Project from "./pages/Project";
import ItemPage from "./pages/Item";
import Waits from "./pages/Waits";
import Sessions from "./pages/Sessions";
import SessionPage from "./pages/Session";

export default function App() {
  return (
    <div className="mx-auto max-w-5xl px-4 pb-16">
      <header className="flex items-center justify-between py-5">
        <Link to="/" className="text-lg font-semibold">Проекты</Link>
        <nav className="flex gap-4 text-sm text-muted">
          <Link to="/waits" className="hover:text-fg">Ждёт тебя</Link>
          <Link to="/sessions" className="hover:text-fg">Неразобранные</Link>
        </nav>
      </header>
      <Routes>
        <Route path="/" element={<Home />} />
        <Route path="/p/:slug" element={<Project />} />
        <Route path="/i/:id" element={<ItemPage />} />
        <Route path="/s/:id" element={<SessionPage />} />
        <Route path="/waits" element={<Waits />} />
        <Route path="/sessions" element={<Sessions />} />
      </Routes>
    </div>
  );
}
```

`web/src/pages/Home.tsx`:
```tsx
import { useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Project, type SearchGroup } from "../api";
import { AREAS, ago, isStale } from "../format";
import { TYPE, type ItemType } from "../types";
import { Badge, Card, Empty, Input, Progress } from "../ui";

export default function Home() {
  const [projects, setProjects] = useState<Project[]>([]);
  const [waits, setWaits] = useState(0);
  const [unsorted, setUnsorted] = useState(0);
  const [area, setArea] = useState("all");
  const [showClosed, setShowClosed] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<SearchGroup[] | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    Promise.all([api.projects(), api.userTodos(), api.unsorted()])
      .then(([p, w, s]) => { setProjects(p); setWaits(w.length); setUnsorted(s.length); })
      .catch((e) => setError(String(e)));
  }, []);

  useEffect(() => {
    if (!q.trim()) { setHits(null); return; }
    const t = setTimeout(() => api.search(q).then(setHits), 250);
    return () => clearTimeout(t);
  }, [q]);

  const shown = useMemo(() => projects.filter((p) =>
    (area === "all" || p.area === area) && (showClosed || p.status === "active" || p.status === "paused")), [projects, area, showClosed]);
  const areas = useMemo(() => [...new Set(projects.map((p) => p.area))], [projects]);

  return (
    <div className="space-y-5">
      {error && <Card className="text-sm text-amber-fg">Сервис недоступен: {error}</Card>}
      {(waits > 0 || unsorted > 0) && (
        <div className="flex flex-wrap gap-2 text-sm">
          {waits > 0 && <Link to="/waits"><Badge tone="amber">Ждёт тебя: {waits}</Badge></Link>}
          {unsorted > 0 && <Link to="/sessions"><Badge>Неразобранные чаты: {unsorted}</Badge></Link>}
        </div>
      )}
      <Input placeholder="Поиск по решениям, находкам, файлам…" value={q} onChange={(e) => setQ(e.target.value)} />

      {hits ? (
        <div className="space-y-3">
          {hits.length === 0 && <Empty>Ничего не нашлось.</Empty>}
          {hits.map((g) => (
            <Card key={g.project}>
              <Link to={`/p/${g.project}`} className="font-medium hover:text-accent">{g.title}</Link>
              <ul className="mt-2 space-y-1 text-sm">
                {g.hits.slice(0, 6).map((h) => (
                  <li key={`${h.type}-${h.id}`} className="truncate">
                    <span className="text-muted">{TYPE[h.type as ItemType]?.label ?? "Проект"}: </span>
                    {h.type === "project" ? h.text : <Link to={`/i/${h.id}`} className="hover:text-accent">{h.text}</Link>}
                  </li>
                ))}
              </ul>
            </Card>
          ))}
        </div>
      ) : (
        <>
          <div className="flex flex-wrap items-center gap-2 text-sm">
            {["all", ...areas].map((a) => (
              <button key={a} onClick={() => setArea(a)}
                className={`rounded-full px-3 py-1 ${area === a ? "bg-fg text-bg" : "text-muted hover:text-fg"}`}>
                {a === "all" ? "Все" : AREAS[a] ?? a}
              </button>
            ))}
            <label className="ml-auto flex items-center gap-1.5 text-muted">
              <input type="checkbox" checked={showClosed} onChange={(e) => setShowClosed(e.target.checked)} /> завершённые
            </label>
          </div>
          {shown.length === 0 && !error && <Empty>Проектов пока нет — их создаёт Claude через pj.</Empty>}
          <div className="grid gap-3 sm:grid-cols-2">
            {shown.map((p) => (
              <Link key={p.slug} to={`/p/${p.slug}`}>
                <Card className={`h-full space-y-2 transition hover:border-accent/50 ${isStale(p) ? "opacity-60" : ""}`}>
                  <div className="flex items-start justify-between gap-2">
                    <h2 className="font-medium leading-snug">{p.title}</h2>
                    <span className="shrink-0 text-xs text-muted">{ago(p.updated_at)}</span>
                  </div>
                  <Progress value={p.progress} />
                  {p.next_step && <p className="text-sm"><span className="text-muted">Дальше: </span>{p.next_step}</p>}
                  <div className="flex flex-wrap gap-1.5">
                    <Badge>{AREAS[p.area] ?? p.area}</Badge>
                    {p.status === "paused" && <Badge>на паузе</Badge>}
                    {isStale(p) && <Badge>заброшен</Badge>}
                    {p.open_user_todos > 0 && <Badge tone="amber">ждёт тебя: {p.open_user_todos}</Badge>}
                  </div>
                </Card>
              </Link>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
```

`web/src/pages/Project.tsx`:
```tsx
import { useCallback, useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type Card as CardT, type Item } from "../api";
import { AREAS, ago, day, resume } from "../format";
import { ItemList, Location } from "../items";
import { STATUS, TYPE, isOpen, tone, type ItemType } from "../types";
import { Badge, Card, CopyButton, Empty, Progress, Section, Tabs } from "../ui";

export default function Project() {
  const { slug = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab = params.get("tab") ?? "overview";
  const [p, setP] = useState<CardT | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.project(slug).then(setP).catch((e) => setError(String(e))), [slug]);
  useEffect(() => { load(); }, [load]);

  if (error) return <Card className="text-sm text-amber-fg">{error}</Card>;
  if (!p) return <Empty>Загрузка…</Empty>;

  const of = (t: ItemType) => p.items.filter((i) => i.type === t);
  const todos = of("todo");
  const userTodos = todos.filter((i) => i.owner === "user" && isOpen(i.status));
  const claudeTodos = todos.filter((i) => i.owner !== "user" && isOpen(i.status));
  const closedTodos = todos.filter((i) => !isOpen(i.status));
  const log: Item[] = [...of("decision"), ...of("finding"), ...of("note")].sort((a, b) => b.created_at.localeCompare(a.created_at));
  const tabs = [
    { id: "overview", label: "Обзор" },
    { id: "todos", label: "Задачи", count: userTodos.length + claudeTodos.length },
    { id: "artifacts", label: "Артефакты", count: of("artifact").length },
    { id: "log", label: "Решения", count: log.length },
    { id: "chats", label: "Чаты", count: p.sessions.length },
    { id: "history", label: "История" },
  ];

  return (
    <div className="space-y-5">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-2">
          <h1 className="text-2xl font-semibold">{p.title}</h1>
          <Badge>{AREAS[p.area] ?? p.area}</Badge>
          {p.status !== "active" && <Badge>{p.status}</Badge>}
        </div>
        <Progress value={p.progress} />
        {p.next_step && <p className="text-lg"><span className="text-muted">Дальше: </span>{p.next_step}</p>}
        {p.summary && <p className="text-sm text-muted">{p.summary}</p>}
      </div>

      {userTodos.length > 0 && (
        <Card className="space-y-1 border-transparent bg-amber-bg text-amber-fg">
          <h2 className="text-sm font-medium">Ждёт тебя</h2>
          <ItemList items={userTodos} onChange={load} />
        </Card>
      )}

      <Tabs tabs={tabs} value={tab} onChange={(id) => setParams({ tab: id }, { replace: true })} />

      {tab === "overview" && (
        <div className="grid gap-6 md:grid-cols-2">
          {of("milestone").length > 0 && <Section title="Этапы"><ItemList items={of("milestone")} onChange={load} /></Section>}
          {of("feature").length > 0 && <Section title="Фичи"><ItemList items={of("feature")} /></Section>}
          {of("plan").length > 0 && <Section title="Планы"><ItemList items={of("plan")} /></Section>}
          {claudeTodos.length > 0 && <Section title="Задачи Claude"><ItemList items={claudeTodos.slice(0, 8)} onChange={load} /></Section>}
          {log.length > 0 && <Section title="Последние решения и находки"><ItemList items={log.slice(0, 5)} /></Section>}
          {p.items.length === 0 && <Empty>Пока пусто.</Empty>}
        </div>
      )}

      {tab === "todos" && (
        <div className="space-y-6">
          <Section title="Тебе"><ItemList items={userTodos} onChange={load} empty="Ничего." /></Section>
          <Section title="Claude"><ItemList items={claudeTodos} onChange={load} empty="Ничего." /></Section>
          {closedTodos.length > 0 && (
            <details>
              <summary className="cursor-pointer text-sm text-muted">Готово и отменено ({closedTodos.length})</summary>
              <ItemList items={closedTodos} onChange={load} />
            </details>
          )}
        </div>
      )}

      {tab === "artifacts" && (
        <div className="grid gap-3 sm:grid-cols-2">
          {of("artifact").length === 0 && <Empty>Артефактов нет.</Empty>}
          {of("artifact").map((a) => (
            <Card key={a.id} className="space-y-2">
              <div className="flex items-start justify-between gap-2">
                <Link to={`/i/${a.id}`} className="font-medium hover:text-accent">{a.title}</Link>
                <Badge tone={tone(a.status)}>{STATUS[a.status]}</Badge>
              </div>
              {a.body && <p className="line-clamp-2 text-sm text-muted">{a.body}</p>}
              <Location item={a} />
            </Card>
          ))}
        </div>
      )}

      {tab === "log" && (
        <div className="space-y-3">
          {log.length === 0 && <Empty>Решений и находок пока нет.</Empty>}
          {log.map((i) => (
            <Card key={i.id} className={`space-y-1 border-l-4 ${i.type === "decision" ? "border-l-accent" : i.type === "finding" ? "border-l-ok" : ""}`}>
              <div className="text-xs text-muted">{TYPE[i.type].label} · {day(i.created_at)}</div>
              <Link to={`/i/${i.id}`} className="font-medium hover:text-accent">{i.title}</Link>
              {i.body && <p className="whitespace-pre-wrap text-sm text-muted">{i.body}</p>}
              <Location item={i} />
            </Card>
          ))}
        </div>
      )}

      {tab === "chats" && (
        <div className="space-y-2">
          {p.sessions.length === 0 && <Empty>Чатов пока нет.</Empty>}
          {p.sessions.map((s) => (
            <Card key={s.id} className="flex items-center justify-between gap-2">
              <Link to={`/s/${s.id}`} className="min-w-0 truncate hover:text-accent">
                {s.title || s.first_prompt || s.id.slice(0, 8)} <span className="text-xs text-muted">· {ago(s.ended_at ?? s.started_at)}</span>
              </Link>
              <CopyButton text={resume(s)} />
            </Card>
          ))}
        </div>
      )}

      {tab === "history" && (
        <div className="space-y-1.5 text-sm">
          {p.events.length === 0 && <Empty>Истории пока нет.</Empty>}
          {p.events.map((e) => (
            <div key={e.id} className="flex gap-3">
              <span className="w-16 shrink-0 text-xs text-muted">{day(e.ts)}</span>
              {e.item_id ? <Link to={`/i/${e.item_id}`} className="hover:text-accent">{e.text}</Link> : <span className="text-muted">{e.text}</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
```

`web/src/pages/Item.tsx`:
```tsx
import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type ItemDetail } from "../api";
import { ago, day, resume } from "../format";
import { ItemList, Location } from "../items";
import { REL, ROLE, STATUS, STATUSES, TYPE } from "../types";
import { Card, CopyButton, Empty, Progress, Section } from "../ui";

const select = "rounded-lg border border-line bg-card px-2 py-1 text-sm";

export default function ItemPage() {
  const { id = "" } = useParams();
  const [it, setIt] = useState<ItemDetail | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => api.item(Number(id)).then(setIt).catch((e) => setError(String(e))), [id]);
  useEffect(() => { load(); }, [load]);

  if (error) return <Card className="text-sm text-amber-fg">{error}</Card>;
  if (!it) return <Empty>Загрузка…</Empty>;
  const Icon = TYPE[it.type].icon;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="flex flex-wrap items-center gap-1.5 text-sm text-muted">
          <Icon size={16} />{TYPE[it.type].label} · <Link to={`/p/${it.project}`} className="hover:text-accent">{it.project}</Link>
          {it.parent && <> · в <Link to={`/i/${it.parent.id}`} className="hover:text-accent">{it.parent.title}</Link></>}
        </div>
        <h1 className="text-2xl font-semibold">{it.title}</h1>
        <div className="flex flex-wrap items-center gap-2">
          {STATUSES[it.type].length > 1 && (
            <select className={select} value={it.status} onChange={(e) => api.patchItem(it.id, { status: e.target.value }).then(load)}>
              {STATUSES[it.type].map((s) => <option key={s} value={s}>{STATUS[s]}</option>)}
            </select>
          )}
          {it.type === "todo" && (
            <select className={select} value={it.owner ?? "claude"} onChange={(e) => api.patchItem(it.id, { owner: e.target.value }).then(load)}>
              <option value="claude">делает Claude</option>
              <option value="user">делаешь ты</option>
            </select>
          )}
          <Location item={it} />
          <span className="text-xs text-muted">создано {day(it.created_at)}</span>
        </div>
        <Progress value={it.progress} />
      </div>

      {it.body && <Card><p className="whitespace-pre-wrap text-sm">{it.body}</p></Card>}

      <div className="grid gap-6 md:grid-cols-2">
        {it.children.length > 0 && <Section title="Внутри"><ItemList items={it.children} onChange={load} /></Section>}
        {it.relations.length > 0 && (
          <Section title="Связи">
            {it.relations.map((r) => (
              <div key={`${r.direction}-${r.kind}-${r.item.id}`} className="flex items-center gap-2 py-1 text-sm">
                <span className="shrink-0 text-muted">{REL[r.direction][r.kind] ?? r.kind}</span>
                <Link to={`/i/${r.item.id}`} className="truncate hover:text-accent">{r.item.title}</Link>
                {r.item.project !== it.project && <span className="text-xs text-muted">{r.item.project}</span>}
              </div>
            ))}
          </Section>
        )}
        {it.sessions.length > 0 && (
          <Section title="Чаты">
            {it.sessions.map((s) => (
              <div key={s.id} className="flex items-center justify-between gap-2 py-1 text-sm">
                <Link to={`/s/${s.id}`} className="min-w-0 truncate hover:text-accent">
                  {s.title || s.first_prompt || s.id.slice(0, 8)}
                  <span className="text-xs text-muted"> · {s.roles.map((r) => ROLE[r] ?? r).join(", ")} · {ago(s.ended_at ?? s.started_at)}</span>
                </Link>
                <CopyButton text={resume(s)} />
              </div>
            ))}
          </Section>
        )}
        {it.events.length > 0 && (
          <Section title="История">
            {it.events.map((e) => (
              <div key={e.id} className="flex gap-3 py-0.5 text-sm">
                <span className="w-16 shrink-0 text-xs text-muted">{day(e.ts)}</span><span>{e.text}</span>
              </div>
            ))}
          </Section>
        )}
      </div>
    </div>
  );
}
```

`web/src/pages/Waits.tsx`:
```tsx
import { useEffect, useState } from "react";
import { api, type Item } from "../api";
import { ItemList } from "../items";
import { Empty } from "../ui";

export default function Waits() {
  const [todos, setTodos] = useState<Item[] | null>(null);
  const load = () => api.userTodos().then(setTodos);
  useEffect(() => { load(); }, []);
  if (!todos) return <Empty>Загрузка…</Empty>;
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">Ждёт тебя</h1>
      <ItemList items={todos} onChange={load} withProject empty="Ничего не ждёт." />
    </div>
  );
}
```

`web/src/pages/Sessions.tsx`:
```tsx
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, type Project, type Session } from "../api";
import { ago, resume } from "../format";
import { Card, CopyButton, Empty } from "../ui";

export default function Sessions() {
  const [sessions, setSessions] = useState<Session[] | null>(null);
  const [projects, setProjects] = useState<Project[]>([]);
  const [remember, setRemember] = useState(true);
  const load = () => api.unsorted().then(setSessions);
  useEffect(() => { load(); api.projects().then(setProjects); }, []);

  async function attach(s: Session, slug: string) {
    await api.attach(s.id, slug);
    if (remember && s.cwd) await api.addPathMap(s.cwd, slug);
    load();
  }

  if (!sessions) return <Empty>Загрузка…</Empty>;
  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">Неразобранные чаты</h1>
        <label className="flex items-center gap-1.5 text-sm text-muted">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} /> запомнить папку за проектом
        </label>
      </div>
      {sessions.length === 0 && <Empty>Всё разобрано.</Empty>}
      {sessions.map((s) => (
        <Card key={s.id} className="space-y-2">
          <div className="flex items-start justify-between gap-2">
            <Link to={`/s/${s.id}`} className="font-medium hover:text-accent">{s.title || s.first_prompt.slice(0, 120) || s.id}</Link>
            <span className="shrink-0 text-xs text-muted">{ago(s.ended_at ?? s.started_at)}</span>
          </div>
          {s.title && s.first_prompt && <p className="line-clamp-2 text-sm text-muted">{s.first_prompt}</p>}
          <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
            <span className="truncate">{s.cwd}</span><span>· {s.user_turns} сообщ.</span>
            <CopyButton text={resume(s)} />
          </div>
          <select defaultValue="" onChange={(e) => e.target.value && attach(s, e.target.value)}
            className="w-full rounded-lg border border-line bg-card px-3 py-2 text-sm">
            <option value="" disabled>Привязать к проекту…</option>
            {projects.map((p) => <option key={p.slug} value={p.slug}>{p.title}</option>)}
          </select>
        </Card>
      ))}
    </div>
  );
}
```

`web/src/pages/Session.tsx`:
```tsx
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type SessionDetail } from "../api";
import { ago, resume } from "../format";
import { ROLE, STATUS, TYPE } from "../types";
import { Card, CopyButton, Empty, Section } from "../ui";

export default function SessionPage() {
  const { id = "" } = useParams();
  const [s, setS] = useState<SessionDetail | null>(null);
  const [error, setError] = useState("");
  useEffect(() => { api.session(id).then(setS).catch((e) => setError(String(e))); }, [id]);
  if (error) return <Card className="text-sm text-amber-fg">{error}</Card>;
  if (!s) return <Empty>Загрузка…</Empty>;

  return (
    <div className="space-y-6">
      <div className="space-y-2">
        <div className="text-sm text-muted">
          Чат · {ago(s.ended_at ?? s.started_at)}{s.project && <> · <Link to={`/p/${s.project}`} className="hover:text-accent">{s.project}</Link></>}
        </div>
        <h1 className="text-2xl font-semibold">{s.title || s.first_prompt.slice(0, 80) || s.id}</h1>
        {s.first_prompt && <p className="text-sm text-muted">{s.first_prompt}</p>}
        <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
          <span className="truncate">{s.cwd}</span><span>· {s.user_turns} сообщ.</span><CopyButton text={resume(s)} label="resume" />
        </div>
      </div>
      <Section title="Что создано и изменено">
        {s.items.length === 0 && <Empty>Этот чат ничего не записал в дашборд.</Empty>}
        {s.items.map((i) => {
          const Icon = TYPE[i.type].icon;
          return (
            <div key={i.id} className="flex items-center gap-2 py-1 text-sm">
              <Icon size={15} className="shrink-0 text-muted" />
              <Link to={`/i/${i.id}`} className="min-w-0 flex-1 truncate hover:text-accent">{i.title}</Link>
              <span className="shrink-0 text-xs text-muted">{STATUS[i.status]} · {i.roles.map((r) => ROLE[r] ?? r).join(", ")}</span>
            </div>
          );
        })}
      </Section>
      {s.files_changed.length > 0 && (
        <details className="rounded-xl border border-line bg-card p-4">
          <summary className="cursor-pointer text-sm text-muted">Изменённые файлы ({s.files_changed.length})</summary>
          <ul className="mt-2 space-y-1 text-xs">{s.files_changed.map((f) => <li key={f} className="truncate">{f}</li>)}</ul>
        </details>
      )}
    </div>
  );
}
```

- [ ] **Step 5: Build**

Run: `cd services/apps/projects/web && npm run build`
Expected: `tsc` passes, `dist/index.html` and `dist/assets/*.js|css` exist.

- [ ] **Step 6: Local check against a local API**

```bash
cd services/apps/projects
STATIC_DIR=web/dist PROJECTS_DB=/tmp/pj-local.db .venv/bin/uvicorn --factory projects_api.main:create_app --port 8790 &
sleep 2
J='content-type: application/json'
curl -s -XPOST localhost:8790/api/projects -H "$J" -d '{"slug":"demo","title":"Демо","area":"youtube","next_step":"свести звук","milestones":["сценарий","монтаж"]}'
curl -s -XPOST localhost:8790/api/projects/demo/items -H "$J" -d '{"type":"feature","title":"Озвучка","session_id":"chat-demo"}'
curl -s -XPOST localhost:8790/api/projects/demo/items -H "$J" -d '{"type":"todo","title":"Выбрать голос","parent_id":3,"owner":"user"}'
curl -s -XPOST localhost:8790/api/projects/demo/items -H "$J" -d '{"type":"artifact","title":"Рендер v6","location":"/tmp/v6.mp4","status":"final"}'
curl -s -XPOST localhost:8790/api/projects/demo/items -H "$J" -d '{"type":"decision","title":"ElevenLabs","body":"дешевле на 40%"}'
curl -s localhost:8790/ | grep -c 'id="root"'
```
Expected: JSON responses, then `1`. Open `http://localhost:8790/` in a browser at desktop width and at 375 px (devtools device mode) and walk: home card → project (every tab) → item "Озвучка" (child todo, chat) → chat page → "Ждёт тебя" (the user todo; ticking it removes it). No horizontal scroll at 375 px. Kill the server, `rm /tmp/pj-local.db*`.

- [ ] **Step 7: Commit**

```bash
cd ~/prj/homeserver/homelab
git add services/apps/projects/web/package.json services/apps/projects/web/package-lock.json services/apps/projects/web/vite.config.ts services/apps/projects/web/tsconfig.json services/apps/projects/web/index.html services/apps/projects/web/src
git commit -m "projects: web UI (home, project tabs, item, chat, waits, unsorted)

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: `pj` CLI — commands, chat linking, offline outbox

**Files:**
- Create: `services/apps/projects/client/pj.py`, `services/apps/projects/tests/test_pj.py`
- Modify: `services/apps/projects/tests/conftest.py` (add `live_url`, `pj_env` fixtures)

**Interfaces:**
- Consumes: the HTTP API (Tasks 1–3).
- Produces: `pj.main(argv: list[str]) -> int`; `pj.load_config() -> dict` (`url`, `token`; `PJ_HOME` env overrides `~/.config/pj`, `PJ_URL` overrides url); `pj.http(cfg, method, path, body=None, timeout=5)` raising `pj.Offline` / `pj.ApiError(code, msg)`; `pj.send(cfg, method, path, body)` (write via outbox; returns the JSON or `None` when queued); `pj.read(cfg, path)`; `pj.flush(cfg) -> int`; `pj.loc(s) -> str` (URL unchanged, path → absolute); `pj.encode_dir(path) -> str`; `pj.claude_projects() -> Path` (`PJ_CLAUDE_PROJECTS` env overrides `~/.claude/projects`); `pj.guess_session(cwd) -> str | None`; `pj.current_session() -> str | None` (`PJ_SESSION` env, else `guess_session(os.getcwd())`); `pj.build_parser()`; Tasks 7 and 9 register more subcommands inside it with its local `add(name, fn, project=True)` helper, before `return ap`.

- [ ] **Step 1: Add the live server fixtures** (append to `tests/conftest.py`)

```python
import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn


@pytest.fixture
def live_url(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(db_path=str(tmp_path / "live.db"), static_dir=str(tmp_path / "nostatic"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


@pytest.fixture
def pj_env(tmp_path, monkeypatch, live_url):
    sys.path.insert(0, str(Path(__file__).parents[1] / "client"))
    home = tmp_path / "pjhome"
    home.mkdir()
    monkeypatch.setenv("PJ_HOME", str(home))
    monkeypatch.setenv("PJ_URL", live_url)
    monkeypatch.setenv("PJ_CLAUDE_PROJECTS", str(tmp_path / "claude-projects"))
    monkeypatch.delenv("PJ_SESSION", raising=False)
    import pj
    return pj, home, live_url
```

- [ ] **Step 2: Write the failing tests**

`tests/test_pj.py`:
```python
import json
import sys
import urllib.request
from pathlib import Path


def get(url, path):
    with urllib.request.urlopen(url + path) as r:
        return json.loads(r.read())


def items(url, slug):
    return get(url, f"/api/projects/{slug}")["items"]


def by_title(url, slug, title):
    return next(i for i in items(url, slug) if i["title"] == title)


def test_new_add_show(pj_env, capsys, tmp_path):
    pj, home, url = pj_env
    d = tmp_path / "work" / "video02"
    d.mkdir(parents=True)
    assert pj.main(["new", "video02", "Видео 02", "--area", "youtube", "-m", "сценарий", "-m", "монтаж",
                    "--path", str(d)]) == 0
    assert pj.main(["add", "-p", "video02", "feature", "Озвучка", "-s", "in_progress"]) == 0
    f = by_title(url, "video02", "Озвучка")
    assert pj.main(["add", "-p", "video02", "todo", "Выбрать голос", "--parent", str(f["id"]), "-o", "user"]) == 0
    assert pj.main(["add", "-p", "video02", "todo", "Свести звук", "--parent", str(f["id"])]) == 0
    assert pj.main(["add", "-p", "video02", "artifact", "Рендер v6", "-l", str(d / "v6.mp4"), "-s", "final"]) == 0
    assert pj.main(["add", "-p", "video02", "decision", "ElevenLabs вместо Speechify", "-b", "дешевле на 40%"]) == 0
    assert pj.main(["done", str(by_title(url, "video02", "сценарий")["id"])]) == 0
    assert pj.main(["next", "-p", "video02", "свести звук"]) == 0
    capsys.readouterr()
    assert pj.main(["show", "-p", "video02"]) == 0
    out = capsys.readouterr().out
    for s in ["Видео 02", "50%", "Next: свести звук", "Waiting on the user", "Выбрать голос", "[x] #",
              "Озвучка [in_progress] 0%", "Свести звук", "Рендер v6 [final]", str(d / "v6.mp4"),
              "ElevenLabs вместо Speechify"]:
        assert s in out, s


def test_add_prints_id_and_relations(pj_env, capsys):
    pj, home, url = pj_env
    pj.main(["new", "a", "A"])
    capsys.readouterr()
    pj.main(["add", "-p", "a", "feature", "F"])
    fid = int(capsys.readouterr().out.split()[0].lstrip("#"))
    assert pj.main(["add", "-p", "a", "plan", "План F", "-l", "https://x.io/plan", "--rel", f"implements:{fid}"]) == 0
    rel = get(url, f"/api/items/{fid}")["relations"]
    assert rel[0]["direction"] == "in" and rel[0]["kind"] == "implements" and rel[0]["item"]["title"] == "План F"
    pid = rel[0]["item"]["id"]
    assert pj.main(["rel", str(pid), "relates", str(fid)]) == 0
    assert len(get(url, f"/api/items/{fid}")["relations"]) == 2


def test_bad_rel_spec_is_usage_error(pj_env):
    pj, home, url = pj_env
    import pytest
    with pytest.raises(SystemExit):
        pj.main(["add", "-p", "a", "note", "x", "--rel", "implements"])


def test_set_and_item(pj_env, capsys):
    pj, home, url = pj_env
    pj.main(["new", "a", "A"])
    pj.main(["add", "-p", "a", "todo", "t"])
    tid = by_title(url, "a", "t")["id"]
    assert pj.main(["set", str(tid), "-s", "doing", "-o", "user", "-b", "подробности"]) == 0
    t = by_title(url, "a", "t")
    assert t["status"] == "doing" and t["owner"] == "user" and t["body"] == "подробности"
    capsys.readouterr()
    assert pj.main(["item", str(tid)]) == 0
    out = capsys.readouterr().out
    assert "#%d todo [doing]" % tid in out and "подробности" in out


def test_api_error_exit_1(pj_env, capsys):
    pj, home, url = pj_env
    pj.main(["new", "a", "A"])
    assert pj.main(["add", "-p", "a", "todo", "x", "-s", "published"]) == 1
    assert "400" in capsys.readouterr().err


def test_project_resolved_from_cwd(pj_env, tmp_path, monkeypatch):
    pj, home, url = pj_env
    d = tmp_path / "work" / "site"
    (d / "sub").mkdir(parents=True)
    pj.main(["new", "site", "Сайт", "--path", str(d)])
    monkeypatch.chdir(d / "sub")
    assert pj.main(["add", "note", "задеплоил"]) == 0
    assert items(url, "site")[0]["title"] == "задеплоил"


def test_no_project_for_cwd_errors(pj_env, tmp_path, monkeypatch, capsys):
    pj, home, url = pj_env
    monkeypatch.chdir(tmp_path)
    assert pj.main(["add", "note", "x"]) == 2
    assert "pj new" in capsys.readouterr().err


def test_offline_write_goes_to_outbox(pj_env, monkeypatch, capsys):
    pj, home, url = pj_env
    monkeypatch.setenv("PJ_URL", "http://127.0.0.1:9")
    assert pj.main(["add", "-p", "a", "note", "офлайн", "--rel", "relates:1"]) == 0
    err = capsys.readouterr().err
    assert "queued" in err and "--rel skipped" in err
    lines = (home / "outbox.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["path"] == "/api/projects/a/items"


def test_outbox_replay_is_ordered_and_idempotent(pj_env, monkeypatch):
    pj, home, url = pj_env
    pj.main(["new", "a", "A"])
    monkeypatch.setenv("PJ_URL", "http://127.0.0.1:9")
    pj.main(["add", "-p", "a", "note", "первое"])
    pj.main(["add", "-p", "a", "note", "второе"])
    lines = (home / "outbox.jsonl").read_text().splitlines()
    (home / "outbox.jsonl").write_text("\n".join(lines + [lines[0]]) + "\n")  # a replay that already reached the server
    monkeypatch.setenv("PJ_URL", url)
    assert pj.main(["list"]) == 0
    assert [i["title"] for i in sorted(items(url, "a"), key=lambda i: i["id"])] == ["первое", "второе"]
    assert not (home / "outbox.jsonl").exists()


def test_loc():
    sys.path.insert(0, str(Path(__file__).parents[1] / "client"))
    import pj
    assert pj.loc("https://nodesize.kalik8s.com") == "https://nodesize.kalik8s.com"
    assert pj.loc("~/prj/x") == str(Path.home() / "prj" / "x")


def test_session_guessed_and_linked(pj_env, tmp_path, monkeypatch):
    pj, home, url = pj_env
    work = tmp_path / "w" / "x.y"
    (work / "deep").mkdir(parents=True)
    tdir = tmp_path / "claude-projects" / pj.encode_dir(str(work.resolve()))
    tdir.mkdir(parents=True)
    (tdir / "abc-123.jsonl").write_text("{}\n")
    assert pj.guess_session(str(work / "deep")) == "abc-123"
    pj.main(["new", "a", "A", "--path", str(work)])
    monkeypatch.chdir(work / "deep")
    pj.main(["add", "note", "n"])
    nid = items(url, "a")[0]["id"]
    assert [s["id"] for s in get(url, f"/api/items/{nid}")["sessions"]] == ["abc-123"]
    monkeypatch.setenv("PJ_SESSION", "override-1")
    pj.main(["done", str(nid)])
    assert {s["id"] for s in get(url, f"/api/items/{nid}")["sessions"]} == {"abc-123", "override-1"}
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/pytest tests/test_pj.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'pj'`

- [ ] **Step 4: Implement** `client/pj.py`

```python
#!/usr/bin/env python3
"""pj: client for the projects dashboard (https://projects.home.kalik8s.ru). Standard library only.

Every write carries the current Claude session id, so the dashboard knows which chat touched what.
Writes never fail a Claude session: when the server is unreachable they are queued in
~/.config/pj/outbox.jsonl and replayed, in order, before the next request.
"""
import argparse
import json
import os
import re
import sys
import time
import tomllib
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

DEFAULT_URL = "https://projects.home.kalik8s.ru"
AREAS = ["youtube", "sites", "infra", "jobs", "crypto", "research", "other"]
TYPES = ["feature", "milestone", "plan", "todo", "artifact", "decision", "finding", "note"]
RELATIONS = ["implements", "produced", "depends_on", "relates"]
STATUSES = ["active", "paused", "done", "dropped"]


class Offline(Exception):
    pass


class ApiError(Exception):
    def __init__(self, code: int, msg: str):
        super().__init__(f"{code}: {msg}")
        self.code = code


class Die(Exception):
    pass


def home() -> Path:
    return Path(os.environ.get("PJ_HOME", Path.home() / ".config" / "pj"))


def load_config() -> dict:
    cfg = {"url": DEFAULT_URL, "token": ""}
    f = home() / "config.toml"
    if f.exists():
        cfg.update(tomllib.loads(f.read_text()))
    if os.environ.get("PJ_URL"):
        cfg["url"] = os.environ["PJ_URL"]
    return cfg


def http(cfg: dict, method: str, path: str, body=None, timeout: float = 5):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(cfg["url"].rstrip("/") + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if cfg.get("token"):
        req.add_header("Authorization", f"Bearer {cfg['token']}")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            return json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        try:
            msg = json.loads(e.read()).get("error", e.reason)
        except Exception:
            msg = str(e.reason)
        raise ApiError(e.code, msg)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
        raise Offline(str(e))


def _outbox() -> Path:
    return home() / "outbox.jsonl"


def flush(cfg: dict) -> int:
    box = _outbox()
    if not box.exists():
        return 0
    lines = [l for l in box.read_text().splitlines() if l.strip()]
    done = 0
    for i, line in enumerate(lines):
        item = json.loads(line)
        try:
            http(cfg, item["method"], item["path"], item.get("body"))
        except Offline:
            box.write_text("\n".join(lines[i:]) + "\n")
            return done
        except ApiError as e:
            print(f"pj: dropped queued {item['method']} {item['path']}: {e}", file=sys.stderr)
        done += 1
    box.unlink()
    return done


def send(cfg: dict, method: str, path: str, body=None):
    try:
        flush(cfg)
        return http(cfg, method, path, body)
    except Offline as e:
        home().mkdir(parents=True, exist_ok=True)
        with _outbox().open("a") as f:
            f.write(json.dumps({"method": method, "path": path, "body": body}, ensure_ascii=False) + "\n")
        print(f"pj: dashboard unreachable ({e}); queued, will retry on the next call", file=sys.stderr)
        return None


def read(cfg: dict, path: str):
    flush(cfg)
    return http(cfg, "GET", path)


def loc(s: str) -> str:
    return s if re.match(r"https?://", s) else str(Path(s).expanduser().resolve())


def encode_dir(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "-", path)


def claude_projects() -> Path:
    return Path(os.environ.get("PJ_CLAUDE_PROJECTS", Path.home() / ".claude" / "projects"))


def guess_session(cwd: str) -> str | None:
    """Best effort: the newest transcript of this folder or a parent, touched in the last 15 minutes."""
    p = Path(cwd).resolve()
    for d in [p, *p.parents]:
        tdir = claude_projects() / encode_dir(str(d))
        if tdir.is_dir():
            files = sorted(tdir.glob("*.jsonl"), key=lambda f: f.stat().st_mtime, reverse=True)
            if files and time.time() - files[0].stat().st_mtime < 900:
                return files[0].stem
    return None


def current_session() -> str | None:
    return os.environ.get("PJ_SESSION") or guess_session(os.getcwd())


def project_slug(cfg: dict, args) -> str:
    if getattr(args, "project", None):
        return args.project
    cwd = os.getcwd()
    try:
        slug = read(cfg, "/api/resolve?cwd=" + urllib.parse.quote(cwd))["project"]
    except Offline:
        raise Die("dashboard unreachable and no -p given; pass -p <slug>")
    if not slug:
        raise Die(f"no project mapped to {cwd}; pass -p <slug>, or create one: pj new <slug> \"<title>\" --path {cwd}")
    return slug


def rel_spec(s: str) -> tuple[str, int]:
    kind, _, to = s.partition(":")
    if kind not in RELATIONS or not to.isdigit():
        raise argparse.ArgumentTypeError(f"expected <{'|'.join(RELATIONS)}>:<item id>, got {s!r}")
    return kind, int(to)


def fmt(i: dict) -> str:
    s = f"#{i['id']} {i['title']}"
    if i["status"] != "logged":
        s += f" [{i['status']}]"
    if i.get("progress") is not None:
        s += f" {i['progress']}%"
    if i.get("location"):
        s += f" — {i['location']}"
    return s


# --- commands -------------------------------------------------------------

def cmd_new(cfg, a):
    send(cfg, "POST", "/api/projects", {"slug": a.slug, "title": a.title, "area": a.area,
                                        "summary": a.summary or "", "milestones": a.milestone or []})
    for p in a.path or []:
        send(cfg, "POST", "/api/path-map", {"prefix": loc(p), "project": a.slug})
    print(f"created {a.slug}")


def cmd_add(cfg, a):
    slug = project_slug(cfg, a)
    body = {"type": a.type, "title": a.title, "body": a.body or "", "uid": str(uuid.uuid4()),
            "session_id": current_session()}
    if a.status:
        body["status"] = a.status
    if a.owner:
        body["owner"] = a.owner
    if a.loc:
        body["location"] = loc(a.loc)
    if a.parent is not None:
        body["parent_id"] = a.parent
    res = send(cfg, "POST", f"/api/projects/{slug}/items", body)
    if res is None:
        if a.rel:
            print("pj: --rel skipped (offline, the new item's id is unknown); add it later with pj rel", file=sys.stderr)
        return
    for kind, to in a.rel or []:
        send(cfg, "POST", f"/api/items/{res['id']}/relations", {"to_id": to, "kind": kind})
    print(f"#{res['id']} {res['type']} {res['title']}")


def cmd_set(cfg, a):
    body = {"session_id": current_session()}
    for key, val in (("title", a.title), ("body", a.body), ("status", a.status), ("owner", a.owner),
                     ("parent_id", a.parent)):
        if val is not None:
            body[key] = val
    if a.loc is not None:
        body["location"] = loc(a.loc)
    send(cfg, "PATCH", f"/api/items/{a.id}", body)


def cmd_done(cfg, a):
    send(cfg, "POST", f"/api/items/{a.id}/done", {"session_id": current_session()})


def cmd_rel(cfg, a):
    send(cfg, "POST", f"/api/items/{a.from_id}/relations", {"to_id": a.to_id, "kind": a.kind})


def cmd_next(cfg, a):
    send(cfg, "PATCH", f"/api/projects/{project_slug(cfg, a)}", {"next_step": a.text})


def cmd_status(cfg, a):
    send(cfg, "PATCH", f"/api/projects/{project_slug(cfg, a)}", {"status": a.value})


def cmd_map(cfg, a):
    send(cfg, "POST", "/api/path-map", {"prefix": loc(a.dir), "project": project_slug(cfg, a)})


def cmd_list(cfg, a):
    for p in read(cfg, "/api/projects"):
        prog = f"{p['progress']:>3}%" if p["progress"] is not None else "   -"
        print(f"{p['slug']:<24} {prog}  {p['status']:<7} {p['updated_at'][:10]}  {p['next_step'][:60]}")


def cmd_item(cfg, a):
    i = read(cfg, f"/api/items/{a.id}")
    out = [f"#{i['id']} {i['type']} [{i['status']}] {i['title']}  (project {i['project']})"]
    if i["owner"]:
        out.append(f"owner: {i['owner']}")
    if i["location"]:
        out.append(f"location: {i['location']}")
    if i["body"]:
        out.append(i["body"])
    if i["parent"]:
        out.append(f"parent: #{i['parent']['id']} {i['parent']['title']}")
    if i["children"]:
        out.append("children:")
        out += [f"  {fmt(c)}" for c in i["children"]]
    if i["relations"]:
        out.append("relations:")
        out += [f"  {r['direction']} {r['kind']} #{r['item']['id']} {r['item']['title']}" for r in i["relations"]]
    if i["sessions"]:
        out.append("chats:")
        out += [f"  {s['id']} {s['title'] or s['first_prompt'][:60]} ({', '.join(s['roles'])})" for s in i["sessions"]]
    print("\n".join(out))


def cmd_show(cfg, a):
    slug = project_slug(cfg, a)
    p = read(cfg, f"/api/projects/{slug}")
    items = p["items"]
    of = lambda t: [i for i in items if i["type"] == t]
    is_open = lambda i: i["status"] not in ("done", "dropped")
    prog = f", {p['progress']}%" if p["progress"] is not None else ""
    out = [f"# {p['title']} [{p['slug']}] — {p['status']}{prog}, updated {p['updated_at'][:16]}"]
    if p["summary"]:
        out.append(p["summary"])
    if p["next_step"]:
        out.append(f"Next: {p['next_step']}")
    todos = of("todo")
    sections = [
        ("Waiting on the user", [i for i in todos if i["owner"] == "user" and is_open(i)]),
        ("Features", of("feature")),
        ("Plans", of("plan")),
        ("Open todos (claude)", [i for i in todos if i["owner"] == "claude" and is_open(i)]),
        ("Artifacts", of("artifact")),
    ]
    if of("milestone"):
        out.append("Milestones:")
        out += [f"  [{'x' if m['status'] == 'done' else ' '}] #{m['id']} {m['title']}" for m in of("milestone")]
    for title, rows in sections:
        if rows:
            out.append(f"{title}:")
            out += [f"  {fmt(i)}" + (f" (in #{i['parent_id']})" if i["parent_id"] else "") for i in rows]
    log = sorted(of("decision") + of("finding"), key=lambda i: i["created_at"], reverse=True)[:10]
    if log:
        out.append("Decisions and findings:")
        out += [f"  {i['created_at'][:10]} {i['type']} #{i['id']}: {i['title']}" + (f" — {i['body'][:120]}" if i["body"] else "")
                for i in log]
    if p["events"]:
        out.append("Recent activity:")
        out += [f"  {e['ts'][:10]} {e['text']}" for e in p["events"][:10]]
    if p["sessions"]:
        s = p["sessions"][0]
        out.append(f"Chats: {len(p['sessions'])} (last: {s['title'] or s['id']}, claude --resume {s['id']})")
    print("\n".join(out))


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(prog="pj", description="projects dashboard client")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, project=True):
        sp = sub.add_parser(name)
        if project:
            sp.add_argument("-p", "--project")
        sp.set_defaults(fn=fn)
        return sp

    sp = add("new", cmd_new, project=False)
    sp.add_argument("slug"); sp.add_argument("title")
    sp.add_argument("--area", choices=AREAS, default="other"); sp.add_argument("--summary")
    sp.add_argument("-m", "--milestone", action="append"); sp.add_argument("--path", action="append")
    sp = add("add", cmd_add)
    sp.add_argument("type", choices=TYPES); sp.add_argument("title")
    sp.add_argument("-b", "--body"); sp.add_argument("-s", "--status"); sp.add_argument("-o", "--owner", choices=["claude", "user"])
    sp.add_argument("-l", "--loc"); sp.add_argument("--parent", type=int)
    sp.add_argument("--rel", type=rel_spec, action="append", help="kind:item_id, e.g. implements:12")
    sp = add("set", cmd_set, project=False)
    sp.add_argument("id", type=int); sp.add_argument("-t", "--title"); sp.add_argument("-b", "--body")
    sp.add_argument("-s", "--status"); sp.add_argument("-o", "--owner", choices=["claude", "user"])
    sp.add_argument("-l", "--loc"); sp.add_argument("--parent", type=int)
    add("done", cmd_done, project=False).add_argument("id", type=int)
    sp = add("rel", cmd_rel, project=False)
    sp.add_argument("from_id", type=int); sp.add_argument("kind", choices=RELATIONS); sp.add_argument("to_id", type=int)
    add("item", cmd_item, project=False).add_argument("id", type=int)
    add("next", cmd_next).add_argument("text")
    add("status", cmd_status).add_argument("value", choices=STATUSES)
    add("map", cmd_map).add_argument("dir", nargs="?", default=".")
    add("list", cmd_list, project=False)
    add("show", cmd_show)
    return ap


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config()
    try:
        args.fn(cfg, args)
    except Die as e:
        print(f"pj: {e}", file=sys.stderr)
        return 2
    except ApiError as e:
        print(f"pj: {e}", file=sys.stderr)
        return 1
    except Offline as e:
        print(f"pj: dashboard unreachable ({e})", file=sys.stderr)
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests -q`
Expected: all passed, 0 failed

- [ ] **Step 6: Commit**

```bash
cd ~/prj/homeserver/homelab
git add services/apps/projects/client/pj.py services/apps/projects/tests/test_pj.py services/apps/projects/tests/conftest.py
git commit -m "projects: pj CLI with chat linking and offline outbox

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Transcript parser, `session-end` hook, `backfill`

**Files:**
- Modify: `services/apps/projects/client/pj.py` (add `parse_transcript`, `session_payload`, `cmd_session_end`, `cmd_backfill`, register subcommands)
- Create: `services/apps/projects/tests/test_transcript.py`, `services/apps/projects/tests/fixtures/transcript.jsonl`

**Interfaces:**
- Consumes: `send`, `http`, `load_config` from Task 6.
- Produces: `pj.parse_transcript(path: Path) -> dict` with keys `title, first_prompt, started_at, ended_at, user_turns, files_changed`; `pj.session_payload(session_id, cwd, transcript_path) -> dict | None` (None when `user_turns < 3`); `pj session-end` (reads hook JSON `{session_id, transcript_path, cwd, ...}` from stdin, always exits 0); `pj backfill [--root DIR]` (posts every transcript ≥3 human turns, prints count).

Transcript facts (checked on real files, Claude Code 2.1.289): one JSON object per line; human prompts are `type=="user"` with `turnOrigin=="human"` and no `isCompactSummary`; their `message.content` is a string or a list with `text` blocks (images possible); tool results are `type=="user"` without `turnOrigin`; edits are `type=="assistant"` with `message.content[]` items `{"type":"tool_use","name":"Write"|"Edit"|"MultiEdit"|"NotebookEdit","input":{"file_path"|"notebook_path":...}}`; titles are `{"type":"custom-title","customTitle":...}` and `{"type":"ai-title","aiTitle":...}` (custom wins, last one wins); every message line has `"timestamp"` and `"cwd"`.

- [ ] **Step 1: Write the fixture** `tests/fixtures/transcript.jsonl` (one JSON object per line, exactly these 9 lines):

```
{"type":"ai-title","aiTitle":"Дашборд проектов","sessionId":"s-1"}
{"type":"user","turnOrigin":"human","timestamp":"2026-10-12T09:00:00.000Z","cwd":"/x/homeserver","message":{"role":"user","content":"<command-name>/clear</command-name>"}}
{"type":"user","turnOrigin":"human","timestamp":"2026-10-12T09:00:05.000Z","cwd":"/x/homeserver","message":{"role":"user","content":"сделай дашборд для проектов"}}
{"type":"assistant","timestamp":"2026-10-12T09:00:10.000Z","message":{"role":"assistant","content":[{"type":"tool_use","name":"Write","input":{"file_path":"/x/homeserver/spec.md"}}]}}
{"type":"user","timestamp":"2026-10-12T09:00:11.000Z","message":{"role":"user","content":[{"type":"tool_result","content":"ok"}]}}
{"type":"user","turnOrigin":"human","isCompactSummary":true,"timestamp":"2026-10-12T09:30:00.000Z","message":{"role":"user","content":"This session is being continued"}}
{"type":"user","turnOrigin":"human","timestamp":"2026-10-12T09:31:00.000Z","message":{"role":"user","content":[{"type":"image"},{"type":"text","text":"вот скрин"}]}}
{"type":"assistant","timestamp":"2026-10-12T09:32:00.000Z","message":{"role":"assistant","content":[{"type":"tool_use","name":"Edit","input":{"file_path":"/x/homeserver/spec.md"}},{"type":"tool_use","name":"Bash","input":{"command":"ls"}}]}}
{"type":"custom-title","customTitle":"Дашборд проектов (v2)","sessionId":"s-1"}
```

- [ ] **Step 2: Write the failing tests** `tests/test_transcript.py`:

```python
import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "client"))
import pj  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "transcript.jsonl"


def test_parse_transcript_counts_only_human_turns():
    t = pj.parse_transcript(FIX)
    assert t["user_turns"] == 3  # /clear wrapper counts as a turn, compact summary and tool results don't
    assert t["first_prompt"] == "сделай дашборд для проектов"
    assert t["title"] == "Дашборд проектов (v2)"
    assert t["started_at"] == "2026-10-12T09:00:00.000Z" and t["ended_at"] == "2026-10-12T09:32:00.000Z"
    assert t["files_changed"] == ["/x/homeserver/spec.md"]


def test_parse_large_transcript_fast(tmp_path):
    big = tmp_path / "big.jsonl"
    filler = json.dumps({"type": "assistant", "timestamp": "2026-10-12T10:00:00.000Z",
                         "message": {"role": "assistant", "content": [{"type": "text", "text": "x" * 2000}]}})
    big.write_text(FIX.read_text() + (filler + "\n") * 50_000)
    t0 = time.time()
    t = pj.parse_transcript(big)
    assert time.time() - t0 < 3
    assert t["ended_at"] == "2026-10-12T10:00:00.000Z"


def test_parse_tolerates_broken_lines(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text(FIX.read_text() + "{not json\n")
    assert pj.parse_transcript(f)["user_turns"] == 3


def test_short_session_skipped(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join(FIX.read_text().splitlines()[:3]) + "\n")
    assert pj.session_payload("s", "/x", str(f)) is None


def test_session_end_posts(pj_env, monkeypatch):
    pjm, home, url = pj_env
    hook = {"session_id": "s-1", "transcript_path": str(FIX), "cwd": "/x/homeserver", "hook_event_name": "SessionEnd"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook)))
    assert pjm.main(["session-end"]) == 0
    import urllib.request
    rows = json.loads(urllib.request.urlopen(url + "/api/sessions?unsorted=1").read())
    assert rows[0]["id"] == "s-1" and rows[0]["title"] == "Дашборд проектов (v2)" and rows[0]["user_turns"] == 3


def test_session_end_never_fails(pj_env, monkeypatch):
    pjm, home, url = pj_env
    monkeypatch.setattr(sys, "stdin", io.StringIO("garbage"))
    assert pjm.main(["session-end"]) == 0


def test_backfill(pj_env, tmp_path):
    pjm, home, url = pj_env
    root = tmp_path / "claude-projects" / "-x-homeserver"
    root.mkdir(parents=True)
    (root / "s-9.jsonl").write_text(FIX.read_text())
    assert pjm.main(["backfill", "--root", str(tmp_path / "claude-projects")]) == 0
    import urllib.request
    rows = json.loads(urllib.request.urlopen(url + "/api/sessions?unsorted=1").read())
    assert [r["id"] for r in rows] == ["s-9"] and rows[0]["cwd"] == "/x/homeserver"
```

- [ ] **Step 3: Run to verify failure**

Run: `.venv/bin/pytest tests/test_transcript.py -q`
Expected: FAIL — `AttributeError: module 'pj' has no attribute 'parse_transcript'`

- [ ] **Step 4: Implement** — add to `client/pj.py` above `build_parser`:

```python
EDIT_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
TS_RE = re.compile(r'"timestamp":"([^"]+)"')
CWD_RE = re.compile(r'"cwd":"([^"]+)"')


def _text_of(content) -> str:
    if isinstance(content, str):
        return content
    return " ".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")


def parse_transcript(path: Path) -> dict:
    """One pass, JSON-decoding only lines that can matter (big sessions run to 100+ MB)."""
    res = {"title": "", "first_prompt": "", "started_at": None, "ended_at": None,
           "user_turns": 0, "files_changed": [], "cwd": ""}
    ai_title = custom_title = ""
    files: dict[str, None] = {}
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = TS_RE.search(line)
            if m:
                res["started_at"] = res["started_at"] or m.group(1)
                res["ended_at"] = m.group(1)
            if not res["cwd"]:
                c = CWD_RE.search(line)
                if c:
                    res["cwd"] = c.group(1)
            if not ('"turnOrigin":"human"' in line or '"tool_use"' in line or '-title"' in line):
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            t = e.get("type")
            if t == "custom-title":
                custom_title = e.get("customTitle") or custom_title
            elif t == "ai-title":
                ai_title = e.get("aiTitle") or ai_title
            elif t == "user" and e.get("turnOrigin") == "human" and not e.get("isCompactSummary"):
                res["user_turns"] += 1
                text = _text_of(e.get("message", {}).get("content", "")).strip()
                if text and not res["first_prompt"] and not text.startswith("<"):
                    res["first_prompt"] = text[:300]
            elif t == "assistant":
                for b in e.get("message", {}).get("content", []) or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use" and b.get("name") in EDIT_TOOLS:
                        p = (b.get("input") or {}).get("file_path") or (b.get("input") or {}).get("notebook_path")
                        if p:
                            files[p] = None
    res["title"] = custom_title or ai_title
    res["files_changed"] = list(files)[:50]
    return res


def session_payload(session_id: str, cwd: str, transcript_path: str) -> dict | None:
    t = parse_transcript(Path(transcript_path))
    if t["user_turns"] < 3:
        return None
    return {"id": session_id, "title": t["title"], "cwd": cwd or t["cwd"], "first_prompt": t["first_prompt"],
            "started_at": t["started_at"], "ended_at": t["ended_at"], "user_turns": t["user_turns"],
            "files_changed": t["files_changed"], "transcript_path": transcript_path}


def cmd_session_end(cfg, a):
    # Runs as a Claude Code SessionEnd hook: must be quick and must never fail.
    try:
        hook = json.loads(sys.stdin.read())
        body = session_payload(hook["session_id"], hook.get("cwd", ""), hook["transcript_path"])
        if body:
            send(cfg, "POST", "/api/sessions", body)
    except Exception as e:
        print(f"pj session-end: {e}", file=sys.stderr)


def cmd_backfill(cfg, a):
    root = Path(a.root).expanduser() if a.root else claude_projects()
    sent = 0
    for f in sorted(root.glob("*/*.jsonl")):
        body = session_payload(f.stem, "", str(f))
        if body:
            send(cfg, "POST", "/api/sessions", body)
            sent += 1
    print(f"backfilled {sent} sessions")
```

In `build_parser`, before `return ap`:
```python
    add("session-end", cmd_session_end, project=False)
    add("backfill", cmd_backfill, project=False).add_argument("--root")
```

- [ ] **Step 5: Run tests**

Run: `.venv/bin/pytest tests -q`
Expected: all passed, 0 failed

- [ ] **Step 6: Commit**

```bash
cd ~/prj/homeserver/homelab
git add services/apps/projects/client/pj.py services/apps/projects/tests/test_transcript.py services/apps/projects/tests/fixtures/transcript.jsonl
git commit -m "projects: transcript parser, SessionEnd hook mode, backfill

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 8: Container, deploy to LXC 103, proxy host, backups, monitoring

**Files:**
- Create: `services/apps/projects/Dockerfile`, `docker-compose.yml`, `backup.py`, `deploy.sh`, `npm_proxy.py`, `README.md`
- Modify: `services/apps/uptime-kuma/kuma-setup.py` (one line in the "Сервисы" group), `services/apps/homepage/config/services.yaml` (one tile)

**Interfaces:**
- Consumes: Tasks 1–5 (image contents).
- Produces: container `projects` on `192.168.1.10:8790`; `https://projects.home.kalik8s.ru`; cron `/etc/cron.d/projects-backup` in LXC 103.

- [ ] **Step 1: Write the container files**

`Dockerfile`:
```dockerfile
FROM node:24-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
RUN npm run build

FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY projects_api/ projects_api/
COPY backup.py .
COPY --from=web /web/dist /app/static
ENV PROJECTS_DB=/data/projects.db STATIC_DIR=/app/static AUTH_MODE=none
EXPOSE 8790
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8790/api/health', timeout=3)"
CMD ["uvicorn", "--factory", "projects_api.main:create_app", "--host", "0.0.0.0", "--port", "8790"]
```

`docker-compose.yml`:
```yaml
# Дашборд проектов: https://projects.home.kalik8s.ru, только LAN и Tailscale. Без авторизации (AUTH_MODE=token включает её).
services:
  projects:
    build: .
    image: projects:local
    container_name: projects
    restart: unless-stopped
    ports:
      - "8790:8790"
    environment:
      TZ: Asia/Tbilisi
      AUTH_MODE: none
    volumes:
      - ./data:/data
    mem_limit: 256m
```

`backup.py`:
```python
"""Online SQLite backup into /data/backups, keeps the newest 14. Run: docker exec projects python /app/backup.py"""
import sqlite3
from datetime import datetime
from pathlib import Path

SRC = Path("/data/projects.db")
DST = Path("/data/backups")
DST.mkdir(exist_ok=True)
target = DST / f"projects-{datetime.now():%Y%m%d-%H%M}.db"
with sqlite3.connect(SRC) as src, sqlite3.connect(target) as dst:
    src.backup(dst)
for old in sorted(DST.glob("projects-*.db"))[:-14]:
    old.unlink()
print(target)
```

- [ ] **Step 2: Write `npm_proxy.py`**

```python
"""Create the NPM proxy host projects.home.kalik8s.ru -> 192.168.1.10:8790 (idempotent).

Credentials: services/apps/projects/.secrets/npm.env with NPM_EMAIL=... and NPM_PASSWORD=...
Without the file it prints what to add by hand and exits 0.
"""
import json
import sys
import urllib.request
from pathlib import Path

API = "http://192.168.1.4:81/api"
DOMAIN = "projects.home.kalik8s.ru"
SECRETS = Path(__file__).parent / ".secrets" / "npm.env"


def call(method, path, body=None, token=None):
    req = urllib.request.Request(API + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def main():
    if not SECRETS.exists():
        print(f"No {SECRETS}. Add a Proxy Host in https://npm.home.kalik8s.ru: domain {DOMAIN}, "
              "forward http://192.168.1.10:8790, SSL: the *.home.kalik8s.ru certificate, Force SSL on.")
        return 0
    env = dict(l.split("=", 1) for l in SECRETS.read_text().split() if "=" in l)
    token = call("POST", "/tokens", {"identity": env["NPM_EMAIL"], "secret": env["NPM_PASSWORD"]})["token"]
    hosts = call("GET", "/nginx/proxy-hosts", token=token)
    if any(DOMAIN in h["domain_names"] for h in hosts):
        print(f"{DOMAIN}: already there")
        return 0
    certs = call("GET", "/nginx/certificates", token=token)
    cert = next(c["id"] for c in certs if "*.home.kalik8s.ru" in c["domain_names"])
    call("POST", "/nginx/proxy-hosts", {
        "domain_names": [DOMAIN], "forward_scheme": "http", "forward_host": "192.168.1.10", "forward_port": 8790,
        "certificate_id": cert, "ssl_forced": True, "http2_support": True, "block_exploits": True,
        "allow_websocket_upgrade": False, "caching_enabled": False, "hsts_enabled": False, "hsts_subdomains": False,
        "access_list_id": 0, "advanced_config": "", "meta": {}, "locations": [],
    }, token=token)
    print(f"{DOMAIN}: created")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 3: Write `deploy.sh`**

```bash
#!/usr/bin/env bash
# Deploy the projects dashboard to LXC 103 (apps): sources -> /opt/projects, docker compose build, cron backup.
set -euo pipefail
cd "$(dirname "$0")"
CT=103
in_ct() { ssh homeserver "sudo pct exec $CT -- bash -lc $(printf %q "$1")"; }

COPYFILE_DISABLE=1 tar --no-xattrs -czf - \
  --exclude=data --exclude=.secrets --exclude=.venv --exclude=web/node_modules --exclude=web/dist \
  --exclude=__pycache__ --exclude=.pytest_cache --exclude=tests --exclude=client \
  . | ssh homeserver "sudo pct exec $CT -- bash -c 'mkdir -p /opt/projects/data && tar -xzf - -C /opt/projects'"

in_ct 'cd /opt/projects && docker compose up -d --build 2>&1 | tail -3'
in_ct 'echo "30 3 * * * root docker exec projects python /app/backup.py >/dev/null 2>&1" > /etc/cron.d/projects-backup && chmod 644 /etc/cron.d/projects-backup'
for i in $(seq 1 20); do
  if in_ct 'curl -sf localhost:8790/api/health' >/dev/null 2>&1; then echo "health: ok"; break; fi
  sleep 2
  [ "$i" = 20 ] && { echo "health: FAILED"; in_ct 'docker logs --tail 30 projects'; exit 1; }
done
python3 npm_proxy.py
```

`chmod +x deploy.sh`

- [ ] **Step 4: Write `README.md`**

````markdown
# projects

Дашборд долгосрочных проектов: https://projects.home.kalik8s.ru (LAN и Tailscale, без авторизации).
Спек: `docs/superpowers/specs/2026-10-12-projects-dashboard-design.md`.

- API + фронт в одном контейнере на LXC 103, порт 8790, база `/opt/projects/data/projects.db`, бэкапы в `data/backups` (03:30, 14 штук).
- Деплой: `./deploy.sh` (нужен `ssh homeserver`). Proxy host в NPM создаёт `npm_proxy.py`, если есть `.secrets/npm.env`.
- Тесты: `uv venv -p 3.12 .venv && uv pip install -p .venv -r requirements-dev.txt && .venv/bin/pytest -q`.
- Клиент: `client/pj.py` → `ln -s $PWD/client/pj.py ~/.local/bin/pj`; конфиг `~/.config/pj/config.toml` (`url`, `token`).
  Хук `SessionEnd` вызывает `pj session-end`, скилл `project-log` — копия `client/SKILL.md`.
- Включить авторизацию: `AUTH_MODE: token` и `AUTH_TOKEN` в compose, тот же `token` в `config.toml`.
````

- [ ] **Step 5: Deploy and verify**

Run: `cd ~/prj/homeserver/homelab/services/apps/projects && ./deploy.sh`
Expected: compose output, `health: ok`, then either `projects.home.kalik8s.ru: created` / `already there`, or the manual instruction (then ask the user to add the proxy host — one form — and wait).

Verify:
```bash
curl -s http://192.168.1.10:8790/api/health
curl -s https://projects.home.kalik8s.ru/api/health
curl -s https://projects.home.kalik8s.ru/ | grep -c 'id="root"'
ssh homeserver "sudo pct exec 103 -- docker exec projects python /app/backup.py"
```
Expected: `{"ok":true}` twice, `1`, a backup path printed.

- [ ] **Step 6: Monitoring and Homepage tile**

In `services/apps/uptime-kuma/kuma-setup.py`, in the `("Сервисы", [` group, after the `Speedtest Tracker` line add:
```python
        http("Проекты", "http://192.168.1.10:8790/api/health"),
```
Then apply it the way the script is meant to run (it connects to `127.0.0.1:3001`, so inside the `uptime-kuma` container):
```bash
cat ~/prj/homeserver/homelab/services/apps/uptime-kuma/kuma-setup.py | ssh homeserver "sudo pct exec 103 -- docker exec -i uptime-kuma python3 -"
```
If that fails because the container has no `socketio` module, check `services/apps/uptime-kuma/` for its run instructions and follow them; report if blocked.

In `services/apps/homepage/config/services.yaml`, after the `Pulse` tile add:
```yaml
    - Проекты:
        icon: mdi-view-dashboard-outline
        href: https://projects.home.kalik8s.ru
        description: Где я остановился, что ждёт меня
        server: local
        container: projects
```
Push it to the server: `scp services/apps/homepage/config/services.yaml homeserver:/tmp/services.yaml && ssh homeserver "sudo pct push 103 /tmp/services.yaml /opt/homepage/config/services.yaml"` (check first with `ssh homeserver "sudo pct exec 103 -- ls /opt/homepage/config"` that this is the live path).

- [ ] **Step 7: Commit** (both `kuma-setup.py` and `services.yaml` may hold the user's unrelated uncommitted edits — stage only this task's hunks)

```bash
cd ~/prj/homeserver/homelab
git add services/apps/projects/Dockerfile services/apps/projects/docker-compose.yml services/apps/projects/backup.py \
  services/apps/projects/deploy.sh services/apps/projects/npm_proxy.py services/apps/projects/README.md
for f in services/apps/uptime-kuma/kuma-setup.py services/apps/homepage/config/services.yaml; do
  if git diff --quiet HEAD -- "$f" 2>/dev/null; then :; fi
  # Build the index version = HEAD + only our insertion, leaving other working-tree edits unstaged.
  python3 - "$f" <<'EOF'
import subprocess, sys
f = sys.argv[1]
head = subprocess.run(["git", "show", f"HEAD:{f}"], capture_output=True, text=True, check=True).stdout
if f.endswith("kuma-setup.py"):
    anchor = '        http("Speedtest Tracker", "http://192.168.1.10:8081"),\n'
    add = '        http("Проекты", "http://192.168.1.10:8790/api/health"),\n'
else:
    anchor = "        container: pulse\n"
    add = ("    - Проекты:\n        icon: mdi-view-dashboard-outline\n        href: https://projects.home.kalik8s.ru\n"
           "        description: Где я остановился, что ждёт меня\n        server: local\n        container: projects\n")
assert anchor in head, f"anchor missing in HEAD:{f}"
new = head.replace(anchor, anchor + add, 1)
sha = subprocess.run(["git", "hash-object", "-w", "--stdin"], input=new, capture_output=True, text=True, check=True).stdout.strip()
mode = subprocess.run(["git", "ls-files", "-s", f], capture_output=True, text=True, check=True).stdout.split()[0]
subprocess.run(["git", "update-index", "--cacheinfo", f"{mode},{sha},{f}"], check=True)
EOF
done
git diff --cached --stat
git commit -m "projects: container, deploy to LXC 103, NPM proxy host, backups, monitoring

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Expected: `--stat` lists only the 6 new files and one-hunk changes to the two existing files.

---

### Task 9: Install on the Mac — `pj`, hook, skill, seed

**Files:**
- Create: `services/apps/projects/client/SKILL.md`; on the Mac: `~/.local/bin/pj` (symlink), `~/.config/pj/config.toml`, `~/.claude/skills/project-log/SKILL.md` (copy), `~/.config/pj/seed.json` (private, never committed)
- Modify: `services/apps/projects/client/pj.py` (add `seed`), `services/apps/projects/tests/test_pj.py` (seed test), `~/.claude/settings.json` (SessionEnd hook)

**Interfaces:**
- Consumes: everything above; live service from Task 8.
- Produces: `pj seed <file>`; file format:
  ```json
  {"projects": [{
    "slug": "nodesize", "title": "NodeSize", "area": "sites", "status": "active",
    "summary": "…", "next_step": "…", "paths": ["~/prj/homeserver/nodesize"],
    "items": [{"type": "milestone", "title": "…", "status": "done", "ts": "2026-10-11T12:00:00Z"},
              {"type": "feature", "title": "Калькулятор HPA"},
              {"type": "todo", "title": "…", "owner": "user", "parent": "Калькулятор HPA"},
              {"type": "artifact", "title": "Сайт", "location": "https://nodesize.kalik8s.com", "status": "published"},
              {"type": "decision", "title": "…", "body": "почему"}]
  }]}
  ```
  `parent` names the title of an earlier item of the same project. Existing slugs are skipped (`skip <slug>`), so re-running is safe; item uids are `seed-<slug>-<n>`.

- [ ] **Step 1: Failing test for seed** (append to `tests/test_pj.py`)

```python
def test_seed(pj_env, tmp_path, capsys):
    pj, home, url = pj_env
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"projects": [{
        "slug": "nodesize", "title": "NodeSize", "area": "sites", "summary": "калькулятор", "next_step": "AdSense",
        "paths": [str(tmp_path)],
        "items": [
            {"type": "milestone", "title": "сайт", "status": "done", "ts": "2026-10-11T12:00:00Z"},
            {"type": "milestone", "title": "AdSense"},
            {"type": "feature", "title": "HPA"},
            {"type": "todo", "title": "запросить ревью AdSense", "owner": "user", "parent": "HPA"},
            {"type": "artifact", "title": "Сайт", "location": "https://nodesize.kalik8s.com", "status": "published"},
        ],
    }]}, ensure_ascii=False))
    assert pj.main(["seed", str(seed)]) == 0
    assert pj.main(["seed", str(seed)]) == 0
    assert "skip nodesize" in capsys.readouterr().out
    card = get(url, "/api/projects/nodesize")
    assert card["progress"] == 50 and card["open_user_todos"] == 1
    assert by_title(url, "nodesize", "запросить ревью AdSense")["parent_id"] == by_title(url, "nodesize", "HPA")["id"]
    assert by_title(url, "nodesize", "Сайт")["location_kind"] == "url"
    assert by_title(url, "nodesize", "сайт")["created_at"] == "2026-10-11T12:00:00Z"
    assert get(url, "/api/resolve?cwd=" + str(tmp_path.resolve()))["project"] == "nodesize"
```

Run: `.venv/bin/pytest tests/test_pj.py::test_seed -q` → FAIL (`invalid choice: 'seed'`).

- [ ] **Step 2: Implement seed** — add to `client/pj.py` above `build_parser`:

```python
def cmd_seed(cfg, a):
    # Interactive one-off import: goes straight through http() so failures are loud.
    data = json.loads(Path(a.file).expanduser().read_text())
    existing = {p["slug"] for p in read(cfg, "/api/projects")}
    for p in data["projects"]:
        slug = p["slug"]
        if slug in existing:
            print(f"skip {slug}")
            continue
        http(cfg, "POST", "/api/projects", {"slug": slug, "title": p["title"], "area": p.get("area", "other"),
                                            "status": p.get("status", "active"), "summary": p.get("summary", ""),
                                            "next_step": p.get("next_step", "")})
        ids: dict[str, int] = {}
        for n, it in enumerate(p.get("items", [])):
            body = {"type": it["type"], "title": it["title"], "body": it.get("body", ""), "uid": f"seed-{slug}-{n}"}
            for key in ("status", "owner", "ts"):
                if it.get(key):
                    body[key] = it[key]
            if it.get("location"):
                body["location"] = loc(it["location"])
            if it.get("parent"):
                body["parent_id"] = ids[it["parent"]]
            ids[it["title"]] = http(cfg, "POST", f"/api/projects/{slug}/items", body)["id"]
        for d in p.get("paths", []):
            http(cfg, "POST", "/api/path-map", {"prefix": loc(d), "project": slug})
        print(f"seeded {slug}: {len(ids)} items")
```
In `build_parser`, before `return ap`: `add("seed", cmd_seed, project=False).add_argument("file")`

Run: `.venv/bin/pytest tests -q` → all passed, 0 failed.

- [ ] **Step 3: Write `client/SKILL.md`**

````markdown
---
name: project-log
description: Track long-running projects in the projects dashboard (https://projects.home.kalik8s.ru) with the pj CLI — typed items (feature, milestone, plan, todo, artifact, decision, finding, note) linked to each other and to the chats that touched them. Use when working on any multi-session project (a YouTube video, a site, a bot, a research run, the job search, homelab work), when the user asks what was done or where we stopped, or when a result, decision, finding or something needing the user's action comes up in such a project. Not for one-off questions.
---

# project-log

The dashboard is the user's memory of all projects across chats. Keep it current while you work, not only at the end.
Every `pj` write is linked to this chat automatically.

## Start of work on a project

1. `pj show` (inside the project folder) or `pj show -p <slug>`; `pj list` shows all slugs.
2. Use the output as context: next step, what waits on the user, open todos, last decisions.
3. No project for this folder and the work is clearly long-running → propose it to the user, then:
   `pj new <slug> "<Title>" --area youtube|sites|infra|jobs|crypto|research|other -m "<milestone>" … --path <project dir>`
   Milestones are the real stages of the deliverable (video: факты, сценарий, озвучка, монтаж, субтитры, обложка, публикация).

## What happened → which type

| What happened | Command |
|---|---|
| A new capability/component of the product is being built | `pj add feature "<name>" -s in_progress` |
| A stage of the deliverable is done | `pj done <milestone id>` |
| A plan or spec was written | `pj add plan "<name>" -l <file> --rel implements:<feature id>` |
| Work to do (by Claude) | `pj add todo "<task>" --parent <feature/plan id>` |
| Something only the user can do (approve, register, pay, click, give a secret) | `pj add todo "<exact action>" -o user` |
| A file, folder, site, video, report or claude.ai artifact was produced | `pj add artifact "<name>" -l <path or URL> -s draft|final|published` (+ `--rel` from the todo: `pj rel <todo> produced <artifact>`) |
| A choice was made | `pj add decision "<chose X over Y>" -b "<why, numbers>"` |
| Research turned up a fact | `pj add finding "<fact>" -b "<details>" -l <source URL or notes file>` |
| Anything else worth remembering | `pj add note "<text>"` |
| A todo/feature/plan finished | `pj done <id>`; other changes: `pj set <id> -s <status> / -b / -l / --parent` |
| Two items are connected | `pj rel <from> implements|produced|depends_on|relates <to>` |

Statuses: feature planned/in_progress/done/dropped · plan draft/approved/in_progress/done/dropped ·
todo open/doing/done/dropped · artifact draft/final/published · milestone open/done.
Ids are printed by `pj add` and shown by `pj show`; `pj item <id>` shows one item with its links and chats.

## Before the session ends or the topic changes

`pj next "<one concrete next step>"`. When a project is finished: `pj status done`.

## Rules

- Write titles in the user's language (Russian), short and concrete; details go in `-b`.
- Prefer one artifact per real result with its location over notes that mention files.
- Use `-p <slug>` when the current folder is not the project folder.
- `pj` queues writes when the dashboard is unreachable; a warning is fine, keep working.
- Don't log one-off questions, and never log secrets.
````

- [ ] **Step 4: Install on the Mac**

```bash
cd ~/prj/homeserver/homelab/services/apps/projects
chmod +x client/pj.py
mkdir -p ~/.local/bin ~/.config/pj ~/.claude/skills/project-log
ln -sf "$PWD/client/pj.py" ~/.local/bin/pj
printf 'url = "https://projects.home.kalik8s.ru"\n# token = ""   # set when AUTH_MODE=token is turned on\n' > ~/.config/pj/config.toml
cp client/SKILL.md ~/.claude/skills/project-log/SKILL.md
pj list
```
Expected: `pj list` prints nothing and exits 0 (empty dashboard). `pj` runs with the system `python3` (3.11+ needed for `tomllib`; Homebrew python3 is 3.14).

- [ ] **Step 5: Add the SessionEnd hook**

Read `~/.claude/settings.json` first. Merge (don't replace other hooks) this entry into `"hooks"`:
```json
"SessionEnd": [
  { "hooks": [ { "type": "command", "command": "$HOME/.local/bin/pj session-end", "timeout": 10 } ] }
]
```
Validate: `python3 -m json.tool ~/.claude/settings.json >/dev/null && echo ok`.
Test the hook command by hand on this session's transcript:
```bash
f=$(ls -t ~/.claude/projects/-Users-kalikys-prj-homeserver/*.jsonl | head -1)
echo "{\"session_id\":\"$(basename "$f" .jsonl)\",\"transcript_path\":\"$f\",\"cwd\":\"$HOME/prj/homeserver\"}" | pj session-end
curl -s 'https://projects.home.kalik8s.ru/api/sessions?unsorted=1' | python3 -c 'import json,sys; print(json.load(sys.stdin)[0]["title"])'
```
Expected: this chat's title.

- [ ] **Step 6: Draft the seed (Claude does this, not a script)**

Read every memory file with `type: project` in `~/.claude/projects/-Users-kalikys-prj-homeserver/memory/` (MEMORY.md lists them) and write `~/.config/pj/seed.json` in the format from this task's Interfaces. Per project:
- `slug` short kebab (`nodesize`, `toolsites`, `aviation-video02`, `crypto-trader`, `tg-bots`, …); `title` in Russian as the user calls it; `area` from the list; `status` `done`/`paused` when the memory says so.
- `summary` 1–2 sentences; `next_step` = the latest open item in the memory.
- `milestone` items only where the memory shows real stages (videos, launches), `status: done` where done, `ts` from the date in the memory (`T12:00:00Z`).
- `feature` items for the product's parts the memory names (e.g. NodeSize: node calculator, HPA calculator, EKS max pods).
- `todo` with `owner: user` for every item still waiting on the user (AdSense review, Publish app in GCP, hello@ mailbox, …); `owner: claude` for open work.
- `artifact` for every site, repo, folder, video, report and published post the memory names, with `location` and `status` (`published` for live sites/posts).
- `decision` / `finding` for the 2–5 most important choices and research results, with the reason/source in `body` and the date in `ts`.
- `paths` = the project folders under `~/prj/homeserver/`.
Show the user a compact table (slug · title · next step · counts per type) before posting.

- [ ] **Step 7: Seed and backfill**

```bash
pj seed ~/.config/pj/seed.json
pj backfill
pj list
curl -s 'https://projects.home.kalik8s.ru/api/sessions?unsorted=1&limit=500' | python3 -c 'import json,sys; print(len(json.load(sys.stdin)), "unsorted")'
```
Expected: `seeded <slug>: N items` per project, `backfilled N sessions`, the list, and the number of chats that matched no folder (they go to "Неразобранные чаты" for the user).

- [ ] **Step 8: Smoke test and cleanup**

```bash
pj new smoke-test "Smoke" -m a
pj add -p smoke-test feature "F" && pj add -p smoke-test artifact "A" -l https://example.com -s final
pj done "$(curl -s https://projects.home.kalik8s.ru/api/projects/smoke-test | python3 -c 'import json,sys; print([i["id"] for i in json.load(sys.stdin)["items"] if i["type"]=="milestone"][0])')"
pj show -p smoke-test
curl -s -XDELETE -o /dev/null -w '%{http_code}\n' https://projects.home.kalik8s.ru/api/projects/smoke-test
```
Expected: `show` prints `100%`, the feature and the artifact, and this chat under "Chats"; delete prints `204`.

- [ ] **Step 9: Commit and record**

```bash
cd ~/prj/homeserver/homelab
git add services/apps/projects/client/pj.py services/apps/projects/client/SKILL.md services/apps/projects/tests/test_pj.py
git commit -m "projects: seed command and project-log skill

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
Save a memory `projects-dashboard.md` (type project): URL, where code lives, `pj` + hook + skill installed, seed done on <date>, and the rule "log long-running work with the project-log skill". Add its line to MEMORY.md.
