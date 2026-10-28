# kalik8s.com redesign: "Mission Poster"

Date: 2026-10-20. Owner: Kalislav Smirnov (the site's subject). Status: draft for approval.

## Why

kalik8s.com is Kalislav's CV site. Today it reads like an engineer's résumé: long paragraphs about pipelines, flat lists, ten sections of equal weight, and Košice in every headline and meta tag. The main reader is an HR person or recruiter. They are usually not an engineer, and they decide in seconds whether a candidate is worth their time.

The goal is a site that looks like a design studio made it, makes the HR reader see an expert in the first seconds, and keeps them scrolling to the end of the experience. **Retention is the main metric** ("удержание по-максимуму").

The job search is now general: remote work for a company in any country. Relocation and Košice are no longer mentioned on the site (user, 2026-10-20: "переезд можно убрать, главное что работать откуда угодно готов").

## Goals

1. First screen: in about 5 seconds the reader knows who this is, what level, and that he is open to remote work.
2. The reader scrolls through all chapters. Every screen has one idea and one motion, and a flight progress bar shows how much is left.
3. Each case reads as "before → what I did → result" in plain words. Tech names stay as a secondary line.
4. The page ends in a contact action: message (Telegram/LinkedIn/email) or CV download.
5. SEO targets general searches: DevOps Engineer, Platform / Kubernetes Engineer, DevSecOps, remote.
6. Higgsfield AI (CLI installed and logged in on the Mac) makes the cinematic visuals, used as much as the budget allows.

## Non-goals

- No new hosting. The site stays static HTML/CSS/JS on the home server (LXC 104, `/opt/public/site`, nginx, Cloudflare Tunnel). We do not use Higgsfield website hosting.
- No framework or build step beyond what exists (`scripts/build-i18n.py`).
- No new facts about the career. Content comes from the current site, `cv.md` and `kosice-campaign/PROFILE.md`.

## Anti-goals (a failure even if it works)

- Dark HUD backgrounds. The user is tired of them.
- A cluttered "AI-made" look, motion for its own sake, random filler visuals (see the user's "clear UI path" rule: one obvious action per screen).
- Slow load or janky scroll on a phone. HR often opens links on a phone.
- Košice in the title, hero, meta description or schema.org as the target location.
- Fake testimonials, invented numbers, client names (the current site leaves them out on purpose).

## Visual direction (chosen by the user)

"Mission poster": the palette of 1970s space-agency posters, on a light base.

- Cream background (`#fdf6ec` → `#fbe3c8`), ink `#1b1410`, accent sun orange `#ff6a3d`. Light theme only. A dark theme is not required.
- A bold grotesque for headlines (uppercase, tight tracking). A monospace for telemetry labels and captions.
- Telemetry details borrowed from the "mission control" idea, only as small accents: chapter labels like `02 → PAYLOAD`, a ticker band with the impact numbers, a live-status dot.
- Light film grain over the page.
- The reference mockup is `.superpowers/brainstorm/*/content/blend.html`, option 2, in this folder.

## Structure (chosen by the user)

Ten current sections become six mission chapters. Nothing is deleted.

| # | Chapter | Content (from the current site) |
|---|---------|---------------------------------|
| 0 | Launch | Hero: name, role, one-line pitch, "open to remote work worldwide", main buttons (message, CV). Impact numbers (10h→20min, 5 platforms, 100+ VMs, 2w→3d) in the ticker and as big counters. |
| 1 | Payload | The 4 case studies, each as before → did → result, numbers counted up on screen. |
| 2 | Flight log | Experience as a timeline. Skills shown as tags on the jobs where they were used, plus a compact skill map at the end. |
| 3 | Origin | Aerospace (Bauman, thesis, the ballistic-arc animation from `aero.js`, made to fit the new style), education, Learning (CKA → CKAD → CKS, link to `/lab`). |
| 4 | Ground control | Homelab (live data, recent commits, status), Projects (GitHub repos loaded live), Sandbox (live shell). The message: "this is real". |
| 5 | Contact | For recruiters FAQ rewritten for remote work, CV download, contacts. |

`/lab` (and `/ru/lab`, `/sk/lab`) stays a separate page and gets the new style.

Languages: EN, RU and SK all stay. EN `index.html` is the source. `scripts/build-i18n.py` with `services/public/i18n/{ru,sk}.json` generates the other two, and CI fails if they are stale.

## Motion

- Scroll-driven chapters: headlines rise line by line, rules draw in, numbers count up when they enter the view, the orbit ring turns with the scroll.
- Cinematic interludes between chapters: a wide strip opens as you scroll into it and plays a Higgsfield clip, then closes.
- Flight progress bar (thin, top or side) tied to scroll position, with chapter marks.
- `prefers-reduced-motion`: all motion off, clips replaced by their still keyframe, content fully readable.
- Content must be readable with JS off: animation only adds to text that is already in the HTML.

## Higgsfield assets

One shared style key for every asset: a 1970s mission-poster illustration in the site palette (flat shapes, grain, sun orange on cream and deep navy), no text, no faces.

Pipeline: image first, then image-to-video (the user's earlier finding: text-to-video without keyframes gives slop).

1. A keyframe image for each scene. Candidates: Nano Banana 2 (2 credits) and GPT Image 2 (6.5 credits).
2. Image-to-video for each interlude, 5 s, made to loop. Candidates: Seedance 2.0 Mini (5 credits), Kling 3.0 (10 credits), Seedance 2.0 (22.5 credits), Seedance 2.5 (35 credits).
3. Encode for the web: short MP4 (H.264) + WebM, poster JPEG, small sizes for mobile.

Scenes (6): hero loop (sun and orbit over a launch site), Payload (a probe deploying from a fairing), Flight log (a trajectory over Earth at dawn), Origin (spacecraft drawings on a desk turning into a launch), Ground control (a ground station dish at dusk), Contact (a capsule returning under parachutes).

**Budget: the free 10 credits only. The user will not pay** (decided 2026-10-20). Spend plan:

| Item | Model | Credits |
|------|-------|---------|
| 6 keyframe stills, one per scene | Seedream 5.0 Flash (0.5 each) | 3 |
| 1 real 5 s clip for the hero, from the hero keyframe | Seedance 2.0 Mini | 5 |
| Reserve for 1–2 retries of stills | | 2 |

- First run 1 test still and check quality, watermark and usage terms on the free plan before spending the rest. If the free plan watermarks the output or forbids this use, stop and tell the user.
- The other five interludes are the stills animated in code (layered parallax, slow push-in, grain, light sweep), not clips.
- If a still is weak, the poster style is simple enough to draw in SVG/CSS instead. That costs no credits.
- Before each generation the CLI prints its cost (`higgsfield generate cost`). Never go over 10 credits in total.

## SEO and positioning

- Title and description on every page target: DevOps Engineer, Platform / Kubernetes Engineer, DevSecOps, remote, banking and air-gapped experience.
- Open Graph image: a new one in the poster style.
- schema.org `Person`: the job-seeking fields move to remote work worldwide. The location is Tbilisi.
- Košice and relocation are removed from every page, FAQ, `llms.txt`, `cv.md` and the CV PDF. The FAQ says: open to remote work for a company in any country; no visa is needed for remote work.
- `llms.txt`, `sitemap.xml`/`sitemap.txt`, `robots.txt`, `cv.md` get the same update.
- Short links (`/ke`, `/ke/ig` and the other UTM short codes in nginx) keep working.

## Constraints

- Every edit starts from `origin/main` (the user's rule after the 2026-10-11 incident). Never from the stale checkout on the host. Diff against live `/opt/public/site` before deploying.
- Deploy is by hand to LXC 104. Ssh writes from the agent are blocked, so the user gets a `!` command. Back up the live site first.
- CI must pass: i18n up to date, `node --check` on the JS, `node --test tests/site/*.test.js`.
- The analytics/tracking in `track-core.js` and the live widgets (homelab data, GitHub, sandbox, asciinema) keep working.
- Performance: the first screen does not wait for video. Clips load lazily when their chapter is near. Target: LCP under 2.5 s on mobile, no layout shift from media.
- Accessibility: headings in order, sufficient contrast on cream, keyboard reachable, the ticker pauses on hover/focus and under reduced motion.

## Decided by the user

- Direction: Mission poster, light, with telemetry accents and cinematic interludes.
- Positioning: remote worldwide, ready to work from anywhere. Košice and relocation removed.
- All three languages stay. All sections stay, regrouped into the six chapters above.
- Use Higgsfield, but only the free 10 credits. The user will not pay.

## Settled after the builder check (my calls, open to change)

- **Interlude component.** It takes either a still (animated in code) or a clip, so more clips can be added later without rework.
- **CV PDF.** The live `/Kalislav-Smirnov-CV.pdf` is regenerated with the existing `kosice-campaign/cv/build_cv.py` (from `cv_data.py`), with the same remote-first wording as the site. The current file is pulled from the server first and kept as a backup.
- **Retention measurement.** `track-core.js` gets chapter-reached events (one per chapter, once per visit) and a max scroll depth, sent through the existing events path. Tests extend `tests/site/track-core.test.js`.
- **Translations.** I write the RU and SK copy. The user, a native Russian speaker, reads RU before deploy. SK ships as it did before, written by me.
- **Aerospace arc.** The `aero.js` flight today goes TBS → KSC (Tbilisi → Košice). The route labels go; the arc becomes a generic suborbital flight over the Kármán line, as in the thesis.
- **Old anchors.** Old ids (`#impact`, `#cases`, `#experience`, `#aerospace`, `#skills`, `#projects`, `#homelab`, `#sandbox`, `#learning`, `#recruiters`) stay as ids on the matching blocks inside the new chapters, so existing links and `app.js` selectors keep working.

## Left to the builder (my calls, open to change)

- Fonts (free, self-hosted), exact spacing and type scale.
- The animation library: plain CSS + IntersectionObserver / scroll-driven animations, or a small library such as GSAP from a pinned CDN version. Pick the lighter one that does the job.
- Rewritten copy. It stays factual and short, in the same voice, and keeps all facts from the current site.
- How each interlude loops and how it degrades on slow networks.
