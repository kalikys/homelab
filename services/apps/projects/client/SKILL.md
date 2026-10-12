---
name: project-log
description: Track long-running projects in the projects dashboard (https://projects.home.kalik8s.ru) with the pj CLI — typed items (feature, milestone, plan, todo, artifact, decision, finding, note) linked to each other and to the chats that touched them. Use when working on any multi-session project (a YouTube video, a site, a bot, a research run, the job search, homelab work), when the user asks what was done or where we stopped, or when a result, decision, finding or something needing the user's action comes up in such a project. Not for one-off questions.
---

# project-log

The dashboard is the user's memory of all projects across chats. Keep it current while you work, not only at the end.
Every `pj` write is linked to this chat automatically.

## Start of work on a project

A SessionStart hook (`pj context`) already puts the project state, or the list of active projects, into context; read it before asking where we stopped. Chats are recorded automatically by the Stop/SessionEnd hooks.

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
