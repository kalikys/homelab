# Job applications dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** a `/jobs` section of the projects service: applications, contacts, platforms, letters with versions,
attachments, and letter generation by a worker on VM 220.

**Architecture:** new module `projects_api/jobs.py` (router + schema in `JOBS_SCHEMA`, created by `db.init`), React pages
under `web/src/jobs/`, worker `services/apps/projects/worker/letters.py` deployed to VM 220, `pj job` commands.

**Tech Stack:** as the projects service (FastAPI 0.118, SQLite, React 19, Tailwind 4, motion). No new dependencies:
file upload is a raw request body (`PUT .../files?name=`), not multipart.

**Spec:** `docs/superpowers/specs/2026-10-13-job-applications-design.md`

## Global Constraints

- No new Python or npm dependencies.
- All UI text in Russian; one obvious action per screen (user rule "clear UI path").
- Personal data (applications, candidate.md, letters) never enters the repo; import data is read from the VM/kosice
  files at run time.
- Generator runs `claude -p --tools "" --strict-mcp-config`; vacancy text framed as untrusted data.
- Upload ≤ 15 MB; allowed extensions pdf docx txt md png jpg jpeg webp html; stored name sanitised.

## Review Focus

- Two workers claiming at once must never get the same letter (single UPDATE … RETURNING inside the write lock).
- File names with `../`, slashes, NUL or unicode must stay inside `/data/files/<id>/`.
- Overwriting a letter must keep the old body in `letter_version`.
- Moving an application to a final status clears `next_action_at`; reopening sets the default again.
- Deleting an application removes its files from disk too.

---

### Task 1: Jobs API

**Files:** Create `projects_api/jobs.py`, `tests/test_jobs.py`; Modify `projects_api/db.py` (init runs JOBS_SCHEMA),
`projects_api/main.py` (include router, `files_dir`).

**Produces (HTTP):**
- `GET/POST /api/jobs/platforms`, `PATCH /api/jobs/platforms/{slug}`; stats in GET.
- `GET/POST /api/jobs/contacts`, `GET/PATCH/DELETE /api/jobs/contacts/{id}`.
- `GET /api/jobs/applications?status=&platform=&origin=&q=`, `POST` (accepts nested `contact` object or `contact_id`,
  `uid` for idempotency, `generate: {lang, wish}`), `GET/PATCH/DELETE /api/jobs/applications/{id}` (GET includes
  contact, letters, attachments, events).
- `GET /api/jobs/summary` → `{due: [...], silent: [...], counts: {status: n}}`.
- Letters: `POST /api/jobs/applications/{id}/letters` (manual), `POST .../letters/generate`, `PATCH /api/jobs/letters/{id}`
  (body/lang/sent), `DELETE`, `GET /api/jobs/letters/{id}` (with versions).
- Queue: `POST /api/jobs/queue/claim` → 204 or `{letter, application, previous_letters}`;
  `POST /api/jobs/queue/{id}/done {body}`, `/failed {error}`; `POST /api/jobs/letters/{id}/retry`.
- Files: `PUT /api/jobs/applications/{id}/files?name=` raw body, `GET /api/jobs/files/{id}`, `DELETE`.
- Vacancy fetch result: `PATCH application {vacancy_text}` (worker).

Tests (pytest): CRUD, status defaults for next_action_at, inbound with new contact, letter versions + single sent,
queue claim race (threads), stale claim reissue, pending timeout → failed, retry, upload limits/types/traversal,
delete removes files, platform stats, summary due/silent.

### Task 2: `pj job` + import

**Files:** Modify `client/pj.py`, `client/SKILL.md`; Create `client/import_jobs.py`; Test `tests/test_pj_jobs.py`.

- `pj job add COMPANY TITLE [--url --platform --status --inbound --contact-name --contact-email ... --text-file --note --fit --uid]`
- `pj job status ID STATUS [--note]`, `pj job letter ID --file F [--lang --sent]`, `pj job list [--status]`,
  `pj job show ID`.
- `import_jobs.py APPLICATIONS_JSON [LETTERS_MD]`: maps jobwatch records (status sent→sent, reply→replied, …,
  channel → platform guess), uid `jobwatch:<id>`; letters parsed from `## ` sections, attached by company match.

### Task 3: Web `/jobs`

**Files:** Create `web/src/jobs/{api.ts,model.ts,Shell.tsx,Funnel.tsx,List.tsx,Application.tsx,NewApplication.tsx,
Contacts.tsx,Platforms.tsx,Letters.tsx}`; Modify `web/src/App.tsx` (section switch, routes, `jobs.` host redirect).

UX: funnel with "Пора напомнить" strip; card page with status pills, next-step chip, vacancy block, contact card,
letters panel (editor with autosave-on-blur + explicit "Сохранить", copy, "Ушло", versions, generate with language +
wish, pending shimmer with polling); new form with two big mode tiles. Check with tsc/build and CDP screenshots at 1280
and 390 px.

### Task 4: Letter worker on VM 220

**Files:** Create `worker/letters.py`, `worker/jobletters.service`, `tests/test_worker.py`.

Loop: claim → (fetch Hirify vacancy if needed) → build prompt (candidate.md, style rules, previous letters, vacancy as
data) → `claude -p` with timeout 180 → done/failed. Tests with a fake `claude` script: ok, timeout, empty output.

### Task 5: Deploy, import, jobwatch hook-up, review

Deploy with `deploy.sh`; run import; install worker on VM 220; switch jobwatch `applications.add/update` to also write
to the API (best effort, JSON stays); live generation once; final review; memory + dashboard note.
