# Job applications dashboard — design

Date: 2026-10-13. Requested by the user: a separate dashboard for job applications with all their information, the cover
letters that were sent (editable, overwritable), the platforms applied through, manual entry, and cover-letter generation
from the web UI. Added the same day: when an HR person reaches out first, record their contacts, the status, and attach
the vacancy description.

## Placement

- Same container and stack as the projects dashboard (`services/apps/projects`, FastAPI + SQLite + React), separate
  tables and a separate section `/jobs` with its own navigation. A switch "Проекты | Отклики" at the top of the sidebar.
- Optional host `jobs.home.kalik8s.ru` (NPM proxy, same port 8790) opens `/jobs` directly; the SPA redirects `/` to
  `/jobs` when `location.host` starts with `jobs.`.
- No auth (LAN), same `AUTH_MODE` hook for later. Personal data lives only in the DB and on VM 220, never in the repo.

## Entities

**platform** — `id, slug, name, url, kind (board|ats|social|direct|recruiter|other), notes, created_at`.
Seeded: hirify, profesia, linkedin, smartrecruiters, himalayas, weworkremotely, remotive, company-site, recruiter,
email, telegram. No passwords stored; `notes` says so in the UI hint.

**contact** — a person: `id, name, company, role, email, phone, telegram, linkedin, notes, created_at, updated_at`.
One contact can be linked to many applications (the same recruiter brings several vacancies).

**application** —
- `id, company, title, url, platform (slug, nullable), origin (outbound|inbound), contact_id (nullable)`
- `location, work_format (remote|hybrid|onsite|relocation), salary (free text), fit (1–5, nullable)`
- `vacancy_text` (pasted or fetched description), `vacancy_id` (Hirify id, nullable), `notes`
- `status`, `applied_at` (date sent / date HR wrote), `next_action_at` (date), `next_action` (text)
- `created_at, updated_at`
- Statuses: `draft` (готовлю), `inbound` (HR написала), `sent` (отправил), `replied` (ответили), `interview`,
  `offer`, `rejected` (отказ), `declined` (сам отказался), `silent` (тишина). Any status may move to any other; every
  change is an event.
- `origin=inbound` starts at `inbound`; outbound starts at `draft` or `sent`.
- Default `next_action_at`: `sent` → +7 days, `replied`/`inbound` → +3 days; editable; cleared on final statuses
  (`offer, rejected, declined`).

**attachment** — files on an application (vacancy PDF, talent kit, screenshot): `id, application_id, name, mime, size,
path, created_at`. Stored under `/data/files/<application_id>/<id>-<safe name>`. Upload ≤ 15 MB, types: pdf, docx, txt,
md, png, jpg, webp, html. Served with `Content-Disposition: attachment` (never rendered inline, except images).

**letter** — `id, application_id, lang, body, status (pending|ready|failed), wish (the user's request text),
error, sent (bool), source (generated|manual|imported), created_at, updated_at`. Several per application. Editing
overwrites `body`; the previous body is kept in a `letter_version` row (`letter_id, body, created_at`). Marking one
letter `sent` unmarks the others of that application.

**job_event** — history: `application_id, kind (created|status|edited|letter|attachment|contact|note), text, at`.

## Screens (`/jobs/...`)

- **Воронка** (`/jobs`): columns by status (draft, inbound, sent, replied, interview, offer), finals folded. On top:
  "Пора напомнить" (next_action_at ≤ today) and "Без ответа 14+ дней" (sent, no change for 14 days). Cards: company,
  title, platform, fit, age.
- **Список** (`/jobs/list`): table with filters (status, platform, origin, text search over company/title/notes/contact).
- **Отклик** (`/jobs/a/:id`): header with status selector and next step; vacancy block (link, fields, description,
  attachments with upload); contact card (pick existing or create inline); letters (editor, copy, "Ушло", history of
  versions, "Сгенерировать" with language + wish); history.
- **Новый отклик** (`/jobs/new`): two modes — "Я откликнулся" and "HR написала сама". The inbound mode starts with the
  contact form (name, company, role, email, phone, Telegram, LinkedIn), then vacancy text and attachments. A checkbox
  "Сгенерировать письмо" queues one after saving.
- **Контакты** (`/jobs/contacts`): list, each with its applications.
- **Платформы** (`/jobs/platforms`): per platform: sent, replied, interviews, offers, reply rate, median days to first
  reply; add/edit platforms.

## Generation

- `POST /api/jobs/applications/{id}/letters/generate {lang, wish}` creates a `pending` letter.
- Worker on VM 220 (`~/jobletters/worker.py`, systemd user service, user `claude`): every 5 s
  `POST /api/jobs/queue/claim` (atomic: picks the oldest pending letter not claimed in the last 5 min, sets
  `claimed_at`, returns the application + vacancy text). If the application has a Hirify `vacancy_id` and no
  `vacancy_text`, the worker fetches it with the Hirify REST key already on the VM and stores it.
- Prompt: `candidate.md` and the style rules from jobwatch `prompt.md` (no dashes, no not-X-but-Y, banned words, one
  concrete vacancy detail, facts only, the rocket-science joke at most once per company), plus earlier letters to the same
  company so the joke and wording are not repeated. Vacancy text is framed as untrusted data.
- `claude -p --tools "" --strict-mcp-config`, timeout 180 s. Result → `POST /api/jobs/queue/{letter_id}/done {body}` or
  `/failed {error}`.
- Server marks a letter `failed` when pending > 5 minutes; UI shows "Повторить". UI polls the letter every 3 s while
  pending.

## Integrations

- Import: the 19 jobwatch applications (`state/applications.json`) and the letters in
  `kosice-campaign/LETTERS-2026-10-13.md` via a one-off `import_jobs.py` (idempotent by a `uid`).
- jobwatch bot switches its store to the API: `/log`, `/add`, "✅ Отправил сам" and the daily Hirify tracker sync
  (`followups.py`) write applications and status changes here; reminders read `next_action_at`. Its JSON stays as a
  fallback when the API is down.
- `pj job add|status|letter|contact|list` in the existing client, so Claude in a chat records applications and
  letters; the job-search skill is updated to use it.
- The maintainer (separate spec) covers this section too.

## Testing

- API: CRUD for each entity, status transitions + default next_action_at, letter overwrite keeps versions, single
  `sent` letter, platform stats, inbound flow with a new contact, attachment upload limits and type checks, path
  traversal in file names.
- Queue: two concurrent claims never get the same letter; stale claim re-issued after 5 min; pending > 5 min → failed;
  retry.
- Worker: unit test with a fake `claude` binary (ok, timeout, empty output).
- Web: `tsc` + build; screenshot check of the funnel, application card and new-inbound form at desktop and phone width.
- Live once: generate a letter for a real application end to end.
