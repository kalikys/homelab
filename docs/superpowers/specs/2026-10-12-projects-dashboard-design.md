# Projects dashboard (`projects`) — design

Date: 2026-10-12 (revised the same day: typed items and links to chats)

## Problem

Work with Claude Code is spread over dozens of sessions (55 transcripts in `~/prj/homeserver` alone, ~29 project folders).
After a few days it is unclear what was done in which chat, what the result of a research run was, and where the
materials are. Long-running projects (YouTube videos, tool sites, crypto bot, job search) need one place that answers
"where did I stop, what is next, what is waiting on me, which chat did this".

## Goals

1. One screen with every long-running project: progress, last activity, next step.
2. One list of everything waiting on the user across all projects.
3. Typed entities (feature, milestone, plan, todo, artifact, decision, finding, note) so Claude knows how to record
   something and the site knows how to show it.
4. Links: items nest (todo inside a plan or feature), relate (`implements`, `produced`, `depends_on`, `relates`), and
   every item knows which chats created or changed it; every chat shows what it touched.
5. No session gets lost, even when the skill was not used (automatic capture).
6. Claude can read the state back at the start of a session (`pj show`).

Non-goals for the MVP: Telegram digest, project metrics (views, traffic), activity charts, multi-user access,
creating items from the web UI (Claude creates; the user ticks, changes status and attaches chats).

## Placement

- Service runs on LXC 103 `apps` (internal Docker host), `services/apps/projects/`, port `8790`.
- Reached at `https://projects.home.kalik8s.ru` through Nginx Proxy Manager (wildcard cert, AdGuard wildcard DNS),
  and at `http://192.168.1.10:8790` directly. Outside the home: Tailscale.
- Not published through the Cloudflare tunnel. No Terraform changes: LXC 103 is already managed.
- **No authentication.** Future hook: `AUTH_MODE` env (`none` now; `token` later checks `Authorization: Bearer`
  on every `/api/*` route except `/api/health`). `pj` reads an optional token from `~/.config/pj/config.toml` and sends
  it when present, so turning auth on needs no client change.
- The `homelab` repo is public: no project data in git (DB on the server, seed file in `~/.config/pj/`).

## Entities

| Type | Meaning | Statuses (first = default) | Shown as |
|---|---|---|---|
| `feature` | a capability or component of the project | planned, in_progress, done, dropped | card with progress from child todos and chat count |
| `milestone` | a stage of the deliverable | open, done | checklist in the project header; drives project % |
| `plan` | a plan/spec, usually a file | draft, approved, in_progress, done, dropped | document link + progress of its todos |
| `todo` | a task; `owner` = `claude` (default) or `user` | open, doing, done, dropped | board "Тебе / Claude"; open user todos = "Ждёт тебя" |
| `artifact` | a produced result: file, folder, site, video, report, claude.ai artifact | draft, final, published | gallery with open / copy-path |
| `decision` | a decision and why | logged | decisions feed |
| `finding` | a research finding and its source | logged | findings feed |
| `note` | anything else | logged | feed |

Every item: `title`, optional `body` (plain text/markdown), optional `location` (path or URL; kind `path` / `url` /
`repo` / `artifact` detected by the server), optional `parent_id` (same project), `owner` (todos only).

Relations between items (any projects): `implements` (plan → feature), `produced` (todo → artifact),
`depends_on`, `relates`.

Progress:
- project = `progress_override` if set, else done milestones / all milestones; no milestones → none;
- feature / plan = done child todos / child todos that are not dropped; no child todos → none.

"Finished" statuses: `done`, `final`, `published` (set `done_at`).

## Links to chats

- `pj` attaches the current Claude session id to every item it creates or changes (`session_item`, role `created` /
  `updated`). The session id is found from the newest transcript of the working folder (or its parents) modified in
  the last 15 minutes; `PJ_SESSION` overrides.
- The first link creates a stub `session` row bound to the item's project, so the current chat shows up at once; the
  `SessionEnd` hook later fills in title, prompt, times and files.
- A project's chat list = sessions bound to it plus sessions that touched any of its items.

## Data model (SQLite)

- `project`: `slug` PK, `title`, `area` (youtube / sites / infra / jobs / crypto / research / other), `status`
  (active / paused / done / dropped), `summary`, `next_step`, `progress_override`, `created_at`, `updated_at`.
- `item`: `id`, `project`, `type`, `title`, `body`, `status`, `owner`, `location`, `location_kind`, `parent_id`
  (→ item, set null on delete), `position`, `uid` (unique, client idempotency key), `created_at`, `updated_at`, `done_at`.
- `relation`: (`from_id`, `to_id`, `kind`) PK, both → item, cascade.
- `event`: `id`, `project`, `item_id`, `item_type`, `session_id`, `ts`, `kind` (`created` / `status` / `edited` /
  `deleted`), `text` — written by the server on every item change; nobody writes events by hand.
- `session`: `id` PK, `project` (nullable = unsorted), `title`, `cwd`, `first_prompt` (≤300 chars), `started_at`,
  `ended_at`, `user_turns`, `files_changed` (JSON, ≤50), `transcript_path`.
- `session_item`: (`session_id`, `item_id`, `role`) PK, `ts`.
- `path_map`: `prefix` PK, `project` — working directory → project (longest prefix on a path boundary wins).

`updated_at` of a project moves forward on any change to it or its items, never backwards (backfilled old sessions
don't make a project look fresh).

Search: substring match over project title/summary/next step and item title/body/location, case-insensitive
including Cyrillic (Python `lower()` registered as an SQL function; SQLite's own folding is ASCII-only).

## API

```
GET    /api/health
GET    /api/projects                         list: progress, next_step, updated_at, open_user_todos, open_todos
POST   /api/projects                         {slug,title,area?,status?,summary?,next_step?,milestones?: [title]}
GET    /api/projects/{slug}                  card: project + all items (with progress, session_count) + last 100 events + chats
PATCH  /api/projects/{slug}                  title, area, status, summary, next_step, progress_override
DELETE /api/projects/{slug}
POST   /api/projects/{slug}/items            {type,title,body?,status?,owner?,location?,parent_id?,uid?,session_id?,ts?}
GET    /api/items/{id}                       item + parent + children + relations (in/out) + chats with roles + events
PATCH  /api/items/{id}                       title, body, status, owner, location, parent_id, position (+ session_id)
POST   /api/items/{id}/done                  set the type's finished status (artifact → final, others → done)
DELETE /api/items/{id}
POST   /api/items/{id}/relations             {to_id, kind}
DELETE /api/items/{id}/relations/{kind}/{to_id}
GET    /api/todos?owner=user&project=        open todos (open, doing) with project_title
POST   /api/sessions                         upsert (hook/backfill)
GET    /api/sessions?unsorted=1&limit=100
GET    /api/sessions/{id}                    session + items it created/updated
PATCH  /api/sessions/{id}                    {project}
GET    /api/resolve?cwd=                     {"project": slug|null}
GET    /api/path-map    POST /api/path-map {prefix, project}
GET    /api/search?q=                        hits grouped by project
```

Errors: `{"error": "..."}` with 400 (validation, wrong status for the type, owner on a non-todo, parent from another
project), 404, 409 (slug exists), 401 when token auth is on.

## Screens

One obvious action per screen; Russian UI; light/dark; works at 375 px.

1. **Home "Где я остановился".** Project cards by last activity: title, area, progress, next step, "3 дня назад",
   badges "ждёт тебя: N", "заброшен" (active and >7 days quiet, dimmed). Top strip links to "Ждёт тебя" and
   "Неразобранные чаты". Area chips, "завершённые" toggle, search.
2. **Project.** Header: title, progress, next step, user todos in an amber box. Tabs:
   **Обзор** (milestones checklist, features, plans, open Claude todos, last decisions/findings) ·
   **Задачи** (Тебе / Claude / done folded) · **Артефакты** (location with open/copy) ·
   **Решения** (decisions, findings, notes with bodies) · **Чаты** (each with what it touched, copy `claude --resume`) ·
   **История** (events).
3. **Item.** Type, title, status select, owner, location, body, parent, children, relations, chats (with role), history.
4. **Ждёт тебя.** All open user todos across projects with a checkbox.
5. **Неразобранные чаты.** Sessions without a project: title/first prompt, folder, date, attach dropdown
   (optionally remembers the folder for that project).
6. **Chat.** Title, first prompt, folder, resume command, items created/updated, files changed (folded).

## `pj` CLI

Config `~/.config/pj/config.toml`: `url` (default `https://projects.home.kalik8s.ru`), optional `token`.
`-p <slug>` picks the project; without it the project is resolved from `$PWD` via `/api/resolve`.

```
pj show                                    overview for Claude: next step, user todos, milestones, features, plans,
                                           open todos, artifacts, recent decisions/findings, last chat
pj list
pj new <slug> "<title>" --area A [-m milestone]... [--path dir]...
pj add <type> "<title>" [-b body] [-s status] [-o user|claude] [-l path|url] [--parent ID] [--rel kind:ID]...
pj set <id> [-t title] [-b body] [-s status] [-o owner] [-l loc] [--parent ID]
pj done <id>
pj rel <from-id> <kind> <to-id>
pj item <id>                               item detail
pj next "<next step>"      pj status active|paused|done|dropped      pj map [dir]
pj session-end                             SessionEnd hook mode (stdin JSON)
pj backfill [--root DIR]                   all existing transcripts
pj seed <file>                             initial import
```

Network failure: warning on stderr, the write goes to `~/.config/pj/outbox.jsonl`, exit 0; the next call replays the
outbox in order (item creates carry a `uid`, so a replay never duplicates). `--rel` on an offline `add` is dropped with
a warning (the new item's id is unknown). A Claude session is never blocked by the dashboard being down.

## Automatic session capture

`SessionEnd` hook in `~/.claude/settings.json` runs `pj session-end`. From the hook input it takes `session_id`,
`cwd`, `transcript_path`; from the transcript: title (`customTitle`, else `aiTitle`), first human prompt, first/last
timestamps, human turn count (`turnOrigin == "human"`, not compact summaries), files from Write/Edit/MultiEdit/
NotebookEdit. Sessions with fewer than 3 human turns are skipped. Project: kept if already bound (stub or manual
attach), else via `path_map`, else unsorted. Timeout 10 s; never fails the session.

## Skill `project-log`

Triggers: working on a long-running project, or the user asks what was done / where we stopped.
It tells Claude: `pj show` at the start; pick the type with a "what happened → type" table; record results as
artifacts with locations, decisions with the reason, findings with the source, work as todos/features, anything the
user must do as `todo -o user`; `pj done` when finished; `pj next` before the session ends; don't log one-off questions
or secrets.

## Seeding

During implementation Claude reads every memory file of type `project` in
`~/.claude/projects/-Users-kalikys-prj-homeserver/memory/` and writes `~/.config/pj/seed.json` (projects with items,
dated where the memory gives dates, plus folder mappings). `pj seed` posts it (existing slugs skipped). `pj backfill`
then imports existing transcripts; unmatched ones land in "Неразобранные чаты". The user reviews the result.

## Deployment

- `services/apps/projects/`: `Dockerfile` (multi-stage: node build of `web`, then python slim), `docker-compose.yml`
  (`restart: unless-stopped`, `./data:/data`, port `8790`, `AUTH_MODE=none`), `deploy.sh` (tar over
  `ssh homeserver` + `pct exec 103` into `/opt/projects`, `docker compose up -d --build`).
- NPM proxy host `projects.home.kalik8s.ru` → `http://192.168.1.10:8790`, wildcard cert, Force SSL — created through
  the NPM REST API by `npm_proxy.py` if `.secrets/npm.env` exists, otherwise added by the user (one form).
- Nightly backup (cron in LXC 103 → `docker exec projects python /app/backup.py`) to `/opt/projects/data/backups`, keep 14.
- Uptime Kuma check on `/api/health`; Homepage tile.

## Testing

- API: pytest with a temp SQLite file — projects CRUD, per-type status validation, owner/parent rules, progress
  (project, feature, plan), relations, auto events, session links and stub sessions, session upsert rules, path
  resolve (boundary + longest prefix), Cyrillic search, open user todos, token auth, SPA fallback.
- `pj`: pytest against a live uvicorn server — every command, cwd resolution, outbox order and idempotent replay,
  session guessing, transcript parser on a fixture (and a 50k-line file in under 3 s), hook never failing, seed.
- Web: `tsc` + build pass; manual check at desktop and 375 px after deploy.
- Smoke after deploy: create a test project with items through `pj`, read it back, delete it.
