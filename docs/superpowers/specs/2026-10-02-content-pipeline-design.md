# Content pipeline on the homelab: design

Date: 2026-10-02
Status: approved in chat 2026-10-02 (owner answered the open points; see the end)

## Goal

A pipeline on the home server that keeps Kalislav visible to people who hire DevOps / platform engineers, without daily work from him:

1. Produces short videos (Reels, Shorts, TikTok) on a schedule, queues them in Postiz at least 24 hours ahead, and sends him each video in Telegram before it goes out.
2. Collects view statistics, records what worked and what did not, and uses that to decide what to make next.
3. Once a week drafts an article for dev.to (written by Fable): either from his own material or as his commentary on newly published papers. Drafts only; he publishes.

Success is measured by inbound interest (profile visits, messages, calls booked through kalik8s.com), with views and retention as the leading signals the pipeline optimises day to day.

## Decisions already made by the owner

- Videos: queued automatically with a 24-hour buffer; anything he does not delete is published.
- Articles: saved to dev.to as drafts; he reads and publishes.
- Runs on the home server, not on the Mac.
- Three posts a day (one video a day on each of Instagram, YouTube and TikTok; a different video per platform is allowed).
- LinkedIn is out of scope: he posts there himself.
- Hermes (VM 220) is repurposed: it keeps the startup-farm skill and loses the homelab on-call and job-application roles; it gains content notifications.
- The pipeline is expected to experiment, including with deliberately simple "viral" formats, and to learn from poor results.

## Constraints

- No discrete GPU. The host is an i7-8700K with 32 GB RAM.
- Everything said about Kalislav must come from an allowlist of facts (`facts.md`, derived from kalik8s.com and his CV). No invented experience, numbers or employers. No mention of visa sponsorship. No "book a call" wording.
- Technical claims in videos and articles must be checked against a primary source before they are queued.
- One account per platform. No reposting the same file to the same platform.
- Secrets (ElevenLabs, Postiz, Anthropic, Telegram) live only on the VM in a mode-600 env file, never in git.

## Where it runs

A new VM `content` (VMID 250, 192.168.1.41; 240 is taken by `consulting`), managed by Terraform like `agent` and `farm`: 4 vCPU, 6 GB RAM, 80 GB disk, Ubuntu 24.04, `prevent_destroy`, firewall `policy_in: DROP` with SSH from the LAN, outbound limited by an egress allowlist (Anthropic, ElevenLabs, Postiz, Telegram, arXiv and the other article sources, package mirrors).

The existing video project (`kalik8s-ads`) moves into its own private Git repository and is cloned on the VM. Encoding switches from Blender to plain `ffmpeg`, which removes Blender from the server entirely.

## Video production without a GPU

Three sources of visuals, in order of cost:

1. **Plate library.** 3D scenes rendered once on the Mac and copied to the VM (2.1 GB today). A new video reuses plates with new text, voice and sound. The Mac is needed only when a new 3D scene is wanted; that stays a manual, occasional step.
2. **HTML scenes.** Interfaces, terminals, typography and 2D animation rendered in headless Chromium. No 3D involved; the server does these alone.
3. **Browser 3D (experiment).** Simple 3D scenes written for WebGL and rendered frame by frame in headless Chromium with software rendering. This gives new 3D-looking visuals without the Mac. Speed and quality on this CPU are unknown and are measured in the first week before the pipeline relies on it.

To widen the plate library up front, one batch of 10–15 generic background scenes (variations of the cluster, rack, pipeline and abstract motion) is rendered on the Mac during setup.

## Formats

Each video is an instance of a format. A format is a template plus the slots the generator fills:

| Group | Formats (initial) |
|---|---|
| Substance | One command or technique with a 10-second explanation; one case from the CV told in three beats; "what this alert actually means" |
| Recognisable | Variants of "3:47 AM" and "Friday deploy" with different hooks; "requirements in a DevOps vacancy" |
| Simple viral | "It is always DNS"; one-line captions over a satisfying pipeline animation |

New formats are added by the weekly run when it has a hypothesis worth testing; a format is retired after it has had a fair number of attempts and stays below the account median.

## Learning loop

State lives in SQLite on the VM (`content.db`) and in three text files the weekly run reads and rewrites:

- `experiments` table: one row per published video: format, hook text, hook type, topic, length, voice on/off, platform, publish time, and metrics at 24 h, 72 h and 7 days (views, average view duration or retention where the platform reports it, likes, comments, shares, saves).
- `lessons.md`: what the pipeline currently believes, each line with the evidence behind it (which videos, what numbers) and the date. Lines are removed when later data contradicts them.
- `backlog.md`: hypotheses to test next, each with what result would confirm or kill it.
- `facts.md`: the allowlist about Kalislav.

Rules that keep the learning honest:

- Compare formats by median, not by their best video: one outlier is expected in every format and proves nothing.
- A conclusion needs at least five videos per arm. Before that, the entry in `lessons.md` is marked as a guess.
- Each week roughly two thirds of the videos come from the best-performing formats and one third are experiments. The experimental share never drops to zero.
- Change one thing at a time when testing a hook or a format, otherwise the result cannot be attributed.

## Schedule

| When (Asia/Tbilisi) | Job | What it does |
|---|---|---|
| Daily 08:00 | `collect` | Pulls post and channel analytics from the Postiz API into `content.db`. Deterministic script, no model. |
| Daily 09:00 | `produce` | Ensures the queue is full for the next 48–72 hours: writes scripts for missing slots, checks facts, generates voice and sound, renders, encodes, uploads to Postiz, schedules. Sends each new video file to Telegram with its publish time. |
| Sunday 10:00 | `reflect` | Reads the week's numbers, rewrites `lessons.md` and `backlog.md`, decides next week's mix, proposes or retires formats. Sends a short report to Telegram. |
| Monday 10:00 | `article` | Drafts the weekly dev.to article (below). |

Jobs are systemd timers. `collect` is a plain script. `produce`, `reflect` and `article` run Claude Code headless with a fixed prompt file, a tool allowlist, and a per-run spending cap.

## Articles (Fable)

Two kinds, alternating by default:

- **From his own material:** the homelab repository and the cases on kalik8s.com.
- **Commentary on new research:** each week the job lists new papers and engineering write-ups from a fixed source list (arXiv cs.SE and cs.DC, USENIX, ACM Queue, CNCF and SRE publications), picks one or two that a platform engineer would care about, reads them in full, and writes an opinion piece in his voice.

Pipeline for one article: select sources → outline with the claim the article makes → draft (Fable) → fact check by a second agent that verifies every statement about a paper against the paper and every statement about Kalislav against `facts.md` → humanising pass (remove the patterns that mark machine-written text, keep the meaning) → save to dev.to as a draft through Postiz → Telegram message with the link and a three-line summary.

Rules: every paper is named and linked; the piece says plainly that it is commentary on that work; no experience is attributed to him that is not in `facts.md`; if the fact check cannot confirm a statement, it is cut. Publishing stays manual, because he is the one who will be asked about the article in an interview.

## Hermes (VM 220)

- Removed: skills `homelab` and `job-apply`, the daily homelab summary cron, and the job-search memory. Files under `/home/hermes/work/jobs` are archived to a tarball on the VM rather than deleted.
- Kept: skill `farm` and its token.
- Added: skill `content` (read-only): answers "what goes out tomorrow", "how did yesterday's videos do", "what did the pipeline learn" from a status endpoint on the content VM.
- Video files and the daily and weekly messages are sent by the pipeline itself through the Telegram Bot API (a plain `sendVideo` / `sendMessage`) with the Hermes bot token, not through the Hermes model: delivery must not depend on a model call.

The homelab loses its daily health summary with this change. Gatus and Uptime Kuma keep running; only the Telegram digest goes away.

## Safety

- The 24-hour buffer is the owner's review window. The Telegram message for each video carries the Postiz link where it can be deleted.
- A kill switch: a file on the VM (and a Hermes command that tells him how to set it) that makes `produce` stop queuing.
- Budget caps per run and per month for the Anthropic API and for ElevenLabs credits; when a cap is hit the job stops and reports instead of degrading silently.
- Claude Code on the VM runs as an unprivileged user with a tool allowlist limited to the project directory, the pipeline scripts and the Postiz tools. It has no SSH keys and no route to the rest of the LAN except the status endpoint that Hermes reads.
- Synthetic voice is labelled where the platform offers a label through Postiz (TikTok). YouTube's label is not settable through Postiz; the owner accepted posting with voice regardless.

## Owner decisions on the open points (2026-10-02)

1. **Model billing:** the Claude subscription, through a `claude setup-token` token in the VM env file (the way the farm does it). No API key.
2. **Postiz plan:** decided when the trial ends. If it is not renewed, `produce` has nowhere to queue and reports that instead of failing silently.
3. **Homelab daily summary:** goes away with the Hermes reset; intended.
4. **YouTube:** videos are posted with voice.
5. **Articles:** his opinion and overview of news and papers, in the first person: where a topic is heading, or why it is a dead end. Sources are linked.
6. **Telegram delivery** uses the Hermes bot identity, so everything arrives in the chat he already uses.

## Out of scope

- LinkedIn posting.
- Paid advertising.
- Changes to kalik8s.com (analytics pixels are a separate task).
- Moving 3D rendering to the server.

## Verification

- A dry run of `produce` with scheduling disabled yields a playable video and a Telegram message, and writes nothing to Postiz.
- A deliberately false fact in a test script is rejected by the fact check.
- With the kill switch set, `produce` queues nothing and says so.
- `collect` reproduces the numbers shown in the Postiz UI for a known post.
- After the Hermes change, a homelab question gets "not available any more", a farm question still works, and a content question is answered from live data.
- No secret appears in git, in logs, or in Telegram messages.
