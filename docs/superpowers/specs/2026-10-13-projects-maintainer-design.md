# Projects dashboard maintainer — design

Date: 2026-10-13. Autonomy level chosen by the user: **B** — the maintainer fixes and ships small things itself
(tests must pass, automatic rollback), anything big waits for the user's yes.

## What it is

A daily headless Claude Code run on VM 220 (user `claude`, next to jobwatch) that keeps the projects dashboard healthy
and improves it. It can push code only through a restricted git remote on LXC 103 whose hooks test, deploy and roll back.
It never gets a shell on LXC 103 or the Proxmox host.

## Daily run (systemd user timer, 09:00 Asia/Tbilisi)

`~/projects-maintainer/run.sh`:
1. `checks.py` (plain code) collects facts: `/api/health`, `/api/admin/status` (DB size, counts, newest backup age,
   last 50 server errors, last deploys), hygiene lists (active projects quiet >14 days, user todos open >7 days,
   unsorted chats), open backlog items. Writes `state/facts.json`.
2. Nothing to do (healthy, no backlog, nothing new since yesterday) → exit silently, no model call.
3. Otherwise `claude -p` with `MAINTAINER.md` as the prompt, in a git working copy of the homelab repo
   (`~/projects-maintainer/repo`, remote `lab`), `timeout 1800`, `--max-turns 60`, tools limited to Read/Edit/Write/
   Glob/Grep and Bash for `git`, `.venv/bin/pytest`, `npm run build`, `python3 client/pj.py` (PJ_URL = the LAN API).
4. The run ends with a short Russian report (what was found, what was fixed and deployed, what needs a yes) sent through
   the jobwatch Telegram bot (`~/jobwatch/tg_send.py`), and the same report is saved as a `note` in the dashboard
   project `projects-dashboard`.

## What counts as small (ship it) vs big (ask)

Small, the maintainer ships alone:
- bug fixes with a regression test that failed first;
- UI/UX polish inside existing screens; copy fixes;
- data hygiene through the API: binding unsorted chats by files/title when the match is unambiguous, closing todos the
  dashboard itself proves done, filling empty next steps from the latest events — every change logged as an event.

Big, the maintainer only proposes (a `plan` item with the change + a `todo -o user` "Одобрить: …" in `projects-dashboard`):
- new features, new screens, schema/API changes, deleting data, dependency changes, Dockerfile/compose/deploy changes,
  anything outside `services/apps/projects/{projects_api,web/src,tests,client}`, or a diff over 400 changed lines.
- When the user ticks that approval todo, the next run implements it (still inside the allowed paths; dependency,
  Dockerfile or deploy changes still need a Mac session and are reported as such).

Backlog sources: open `todo` items owned by `claude` in `projects-dashboard`, including ideas the user sends with the new
"Идея по дашборду" button in the web UI.

## Deploy channel: `lab` bare repo on LXC 103

- `/opt/projects/repo.git`, owned by a new user `deployer` (login shell `git-shell`, member of `docker`).
- `authorized_keys` of `deployer`: the Mac key with `command="PUSHER=owner git-shell -c \"$SSH_ORIGINAL_COMMAND\""`, the
  VM 220 maintainer key with `PUSHER=maintainer`. Hooks read `PUSHER`.
- `pre-receive`: only `refs/heads/main`, fast-forward only. For `PUSHER=maintainer` also: every changed path inside the
  allowed list, ≤400 changed lines unless the commit message carries `Approved-By: user (<item id>)` and that item is a
  done user todo (checked via the API), no changes to `requirements*.txt`, `web/package*.json`, `web/vite.config.ts`,
  `Dockerfile`, `docker-compose.yml`, `deploy.sh`.
- `post-receive`: export `services/apps/projects` of the new main to `/opt/projects/builds/<sha>`, `docker build` with a
  test stage (pytest + node test + tsc/vite build must pass), tag `projects:<sha>`; keep the running image as
  `projects:prev`; switch `projects:current` and `docker compose up -d`; poll `/api/health` 60 s; on failure re-tag
  `projects:prev` as current, bring it back up, and record `rolled_back`. Every deploy appends a line to
  `/opt/projects/data/deploys.jsonl` (sha, pusher, result, duration), which `/api/admin/status` returns.
- The Mac's `deploy.sh` becomes "push to `lab`" (same hooks, owner rules), so there is one deploy path. Before pushing,
  the Mac pulls `lab/main` so the maintainer's commits are not lost; GitHub (`origin`) is still pushed from the Mac only
  when the user asks.
- `client/pj.py` changes reach the Mac only after a `git pull lab main` there; the report says so when it happens.

## Server additions

- `/api/admin/status`: DB size, counts per type, newest backup file and age, last 50 errors, last 20 deploys.
- Error capture: unhandled exceptions are appended to `/data/errors.jsonl` (time, path, error class, message).
- Web: "Идея по дашборду" button (sidebar + mobile) → modal → `POST` a `todo` (owner claude) into `projects-dashboard`.

## Safety notes

- The dashboard has no auth on the LAN; its text reaches the maintainer's prompt framed as data (same rule as
  `pj context`). Code the maintainer pushes can only touch the app paths and only run inside the projects container and
  the image build. Known residual risk: someone on the LAN could plant instructions in dashboard text; the push
  restrictions and tests bound what that can do. Acceptable for a home LAN; revisit when auth is turned on.
- Budget: one run per day, 30 minutes, 60 turns; the run stops early when there is nothing to do.
- The maintainer never touches other homelab services, secrets, Terraform, or GitHub.

## Testing

- Hooks: shell tests that push allowed/forbidden changes as each pusher into a throwaway bare repo (path filter, size
  limit, approval trailer, fast-forward rule).
- Deploy: a deliberately broken commit (health fails) must roll back to the previous image; verified once live.
- `checks.py`: unit tests on canned API responses (silent when nothing to do).
- End to end once: a real small fix shipped by the maintainer, visible in deploys.jsonl and Telegram.
