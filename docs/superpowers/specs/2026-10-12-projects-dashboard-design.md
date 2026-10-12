# Projects dashboard (`projects`) — design

Date: 2026-10-12

## Problem

Work with Claude Code is spread over dozens of sessions (55 transcripts in `~/prj/homeserver` alone, ~29 project folders).
After a few days it is unclear what was done in which chat, what the result of a research run was, and where the
materials are. Long-running projects (YouTube videos, tool sites, crypto bot, job search) need one place that answers
"where did I stop, what is next, what is waiting on me".

## Goals

1. One screen with every long-running project: progress, last activity, next step.
2. One list of everything blocked on the user across all projects.
3. Per project: milestones, a timeline of what was done / decided / found per session, materials, sessions.
4. No session gets lost, even when the skill was not used (automatic capture).
5. Claude can read the state back at the start of a session (`pj show`).

Non-goals for the MVP: Telegram digest, project metrics (views, traffic), activity charts, multi-user access.

## Placement

- Service runs on LXC 103 `apps` (internal Docker host), `services/apps/projects/`, port `8790`.
- Reached at `https://projects.home.kalik8s.ru` through Nginx Proxy Manager (wildcard cert, AdGuard wildcard DNS),
  and at `http://192.168.1.10:8790` directly. Outside the home: Tailscale.
- Not published through the Cloudflare tunnel. No Terraform changes: LXC 103 is already managed.
- **No authentication.** Future hook: `AUTH_MODE` env (`none` now; `token` later checks `Authorization: Bearer`
  on every route). All clients (`pj`, the hook) already read an optional token from `~/.config/pj/config.toml` and send
  it when present, so turning auth on needs no client change.

## Components

| Unit | What it does | Depends on |
|---|---|---|
| `api` (FastAPI, Python 3.12) | REST API + serves the built frontend | SQLite file `/data/projects.db` |
| `web` (Vite + React + shadcn/ui) | three screens, built into `api/static` at image build time | `api` JSON |
| `pj` CLI (single-file Python, stdlib only) | writes/reads from any Claude session on the Mac | `api` |
| `SessionEnd` hook (`pj session-end`) | records every Claude Code session automatically | `pj` |
| skill `project-log` (`~/.claude/skills/project-log/`) | tells Claude when and how to call `pj` | `pj` |
| `seed.py` (one-off) | imports projects from memory files and project folders | `api` |
| backup cron on LXC 103 | nightly `sqlite3 .backup` to `/opt/apps/projects/backups`, keep 14 | — |

## Data model (SQLite)

- `project`: `slug` PK, `title`, `area` (youtube / sites / infra / jobs / crypto / research / other), `status`
  (active / paused / done / dropped), `summary`, `next_step`, `progress_override` (nullable int), `created_at`, `updated_at`.
- `milestone`: `id`, `project`, `title`, `done` (bool), `weight` (int, default 1), `position`, `done_at`.
- `event`: `id`, `project`, `session_id` (nullable), `ts`, `kind` (`progress` / `decision` / `finding` / `change` / `blocker` / `note`), `text`, `links` (JSON list).
- `wait`: `id`, `project`, `text`, `created_at`, `resolved_at` (nullable) — the "waiting on you" items.
- `material`: `id`, `project`, `kind` (`path` / `url` / `repo` / `artifact`), `label`, `location`, `created_at`. Unique on (`project`, `location`).
- `session`: `id` (Claude session id) PK, `project` (nullable = unsorted), `cwd`, `first_prompt` (first 300 chars), `started_at`, `ended_at`, `files_changed` (JSON list, max 50), `transcript_path`.
- `path_map`: `prefix` PK, `project` — maps a working directory to a project (longest prefix wins).
- FTS5 table over `event.text`, `material.label/location`, `project.title/summary` for search.

Progress = `progress_override` if set, else `sum(weight of done) / sum(weight)` × 100; no milestones → no percentage shown.
`updated_at` of a project is bumped by any write to its rows.

## API

```
GET    /api/projects                     list with progress, next_step, last activity, open waits count
POST   /api/projects                     create
GET    /api/projects/{slug}              full card: milestones, last 100 events, materials, sessions, waits
DELETE /api/projects/{slug}              delete with all rows (used by the smoke test)
PATCH  /api/projects/{slug}              status, summary, next_step, progress_override, title, area
POST   /api/projects/{slug}/milestones   add; PATCH/DELETE /api/milestones/{id}
POST   /api/projects/{slug}/events       add event
POST   /api/projects/{slug}/materials    add (upsert on location)
POST   /api/projects/{slug}/waits        add; PATCH /api/waits/{id} {resolved: true}
GET    /api/waits                        all open waits across projects
POST   /api/sessions                     upsert session (from the hook)
GET    /api/sessions?unsorted=1          sessions without a project
PATCH  /api/sessions/{id}                attach to a project
GET    /api/resolve?cwd=...              project for a directory via path_map
POST   /api/path-map                     add mapping
GET    /api/search?q=...                 FTS results grouped by project
GET    /api/health
```

Errors: JSON `{"error": "..."}` with 400 (validation), 404 (unknown slug/id), 409 (slug exists).

## Screens

Follows the "one obvious action per screen" rule.

1. **Home: "Where I stopped".** Project cards sorted by last activity: title, area tag, progress bar, next step,
   "3 days ago". Stale (>7 days, status active) cards are dimmed with a "stale" badge. A top strip shows
   "Waiting on you: N" and "Unsorted sessions: N" as links. Filter chips by area/status, search box.
2. **Project page.** Header with progress and next step. Milestones checklist (clickable). Timeline grouped by session,
   decisions and findings visually distinct. Materials list with copy buttons for paths. Sessions with a copy button
   for `claude --resume <id>` (and `cd <cwd>`). Open waits on top in an amber box.
3. **Waiting on you.** All open waits across projects, one "Done" button each.
4. **Unsorted sessions.** First prompt, folder, date, a project dropdown to attach (attaching also offers to save a path mapping).

Light and dark theme, works on a phone.

## `pj` CLI

Config `~/.config/pj/config.toml`: `url` (default `https://projects.home.kalik8s.ru`), optional `token`.
Project argument may be omitted: resolved from `$PWD` via `/api/resolve`.

```
pj show [slug]                       compact text summary for Claude (next step, waits, milestones, last 15 events, materials)
pj new <slug> "<title>" --area youtube [--milestones "a,b,c"] [--path <dir>]
pj event [slug] --kind decision "text" [--link url_or_path ...]
pj milestone [slug] "title" [--done] [--add]
pj next [slug] "next step"
pj wait [slug] "what is needed from the user"     /  pj unwait <id>
pj link [slug] <path|url> ["label"]
pj status [slug] active|paused|done|dropped
pj list
pj session-end                        hook mode: reads hook JSON from stdin
```

Network failure: `pj` prints a warning, appends the request to `~/.config/pj/outbox.jsonl` and exits 0;
every next call flushes the outbox first. A Claude session is never blocked by the dashboard being down.

## Automatic session capture

`SessionEnd` hook in `~/.claude/settings.json` runs `pj session-end`. From the hook input it takes `session_id`,
`cwd`, `transcript_path`; it reads the transcript JSONL to get the first user prompt, first/last timestamps, and file
paths from Write/Edit tool calls. Sessions shorter than 3 user turns are skipped. Project is set via `path_map` when the
cwd matches, else the session lands in "unsorted". Hook runs with a 10 s timeout and never fails the session.

## Skill `project-log`

Triggers: working on a long-running project (video, site, bot, research, job search, any multi-session work), or the
user asks what was done / where we stopped.

Rules it gives Claude:
- At the start of work on a project: `pj show` and use it as context; if the cwd has no project and the work is
  long-running, propose `pj new`.
- After each meaningful result: `pj event --kind progress|finding|decision` with links to the produced files/URLs;
  tick milestones; `pj link` every new material.
- When something needs the user (approval, registration, payment, a click): `pj wait`. When it gets done: `pj unwait`.
- Before the session ends or when the user switches topic: `pj next "<one concrete next step>"`.
- One-off questions are not logged.

## Seeding

During implementation Claude reads every memory file of type `project` in
`~/.claude/projects/-Users-kalikys-prj-homeserver/memory/` and writes `seed/projects.json` (title, area, summary,
next step, milestones, open waits, materials per project). `seed.py` (run once from the Mac) posts that file; plus path mappings for `~/prj/homeserver/<dir>` folders that match.
Also backfills `session` rows from existing transcripts in `~/.claude/projects/*/` (same parser as the hook).
The user reviews the result on the dashboard.

## Deployment

- `services/apps/projects/`: `Dockerfile` (multi-stage: node build of `web`, then python slim), `docker-compose.yml`
  (`restart: unless-stopped`, `./data:/data`, port `8790`, `TZ`, `AUTH_MODE=none`), `deploy.sh` (rsync to LXC 103,
  `docker compose up -d --build`).
- NPM proxy host `projects.home.kalik8s.ru` → `http://192.168.1.10:8790`, wildcard cert, Force SSL — created through
  the NPM REST API in `deploy.sh` if credentials are in `.secrets`, otherwise added by the user (one form).
- Gatus/Uptime Kuma check on `/api/health`.
- Homepage tile in `services/apps/homepage/config/services.yaml`.

## Testing

- API: pytest with a temp SQLite file — CRUD per resource, progress calculation, path resolve (longest prefix),
  FTS search, unsorted sessions, 404/409 errors.
- `pj`: pytest against a running test server; outbox behaviour when the server is down; transcript parser on a fixture
  JSONL (first prompt, file list, short-session skip).
- Web: build passes; manual check on desktop and phone width after deploy.
- Smoke after deploy: `pj new test …`, `pj event`, `pj show`, then delete the test project.
