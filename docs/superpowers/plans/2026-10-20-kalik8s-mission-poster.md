# kalik8s.com "Mission Poster" Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild kalik8s.com as a light, studio-grade "mission poster" scroll story in six chapters, remote-worldwide positioning, with Higgsfield art and retention tracking.

**Architecture:** Static site, no build step beyond `scripts/build-i18n.py`. `index.html` (EN) is rewritten into six chapters but keeps every id that `app.js`/`aero.js` render into. New `motion-core.js` (pure, tested) + `motion.js` (DOM) add reveals, progress bar, interludes and chapter-reached beacons. `styles.css` is replaced.

**Tech Stack:** HTML, CSS (scroll reveal via IntersectionObserver + CSS transitions), vanilla JS, Node `node:test`, Python i18n builder, nginx, Higgsfield CLI (Seedream 5.0 Flash stills, Seedance 2.0 Mini clip), ffmpeg.

**Spec:** `docs/superpowers/specs/2026-10-20-kalik8s-mission-poster-design.md`

## Global Constraints

- Edits start from `origin/main` (worktree `~/prj/homeserver/kalik8s-site-wt`, branch `redesign/mission-poster`).
- CSP: `style-src 'self' https://fonts.googleapis.com` — no inline `<style>` and no `style=""` attributes; JS may set `el.style.*`. `script-src 'self'` — no inline scripts, no CDN libraries. Media (`media-src`) falls back to `'self'`: self-host video.
- Palette: cream `#fdf6ec` → `#fbe3c8`, ink `#1b1410`, sun `#ff6a3d`. Light theme only.
- No "Košice", "relocat*", "Blue Card" anywhere in site text, meta, JSON-LD, `llms.txt`, `cv.md`, CV PDF. Location: Tbilisi, Georgia; open to remote work for a company in any country.
- Old ids stay: `impact cases experience aerospace skills projects homelab sandbox learning recruiters` plus every id used by `app.js`/`aero.js`.
- Existing `data-i18n` keys whose English text is unchanged keep their key; changed text gets the same key with new text in all three languages.
- Higgsfield: total spend ≤ 10 credits (free plan, 1 concurrent job). Always `higgsfield generate cost` first.
- `prefers-reduced-motion: reduce` → no motion, stills instead of clips. Content readable with JS off (reveal classes only added by JS).
- CI: `python3 scripts/build-i18n.py` leaves no diff; `node --check` on all site JS; `node --test tests/site/*.test.js`.

## Review Focus

1. JS disabled or blocked → all text visible (no element starts hidden in CSS without a `.js` root class).
2. Phone 360–390 px wide → no horizontal scroll, ticker and wide interludes fit, tap targets ≥ 44 px.
3. Reduced motion → no ticker scroll, no video autoplay, no counters; final numbers shown.
4. Slow network → first screen paints with the still; the clip loads only near the viewport and never blocks LCP.
5. RU/SK pages → longer strings do not break the poster headline or chips; CV link on SK stays `/Kalislav-Smirnov-CV-SK.pdf`.

---

### Task 1: Art assets

**Files:** Create `services/public/site/media/{launch,payload,flightlog,origin,ground,contact}.{webp,jpg}` (1600 w webp + 900 w jpg fallback), `media/launch.mp4`, `media/launch.webm`, `og.jpg` (1200×630).

- [ ] Stills: Seedream 5.0 Flash 21:9 2k, shared STYLE key (spec §Higgsfield assets). Raw files in `~/prj/homeserver/kalik8s-motion/assets/raw/`.
- [ ] Hero clip: Seedance 2.0 Mini, 5 s, 720p, `--start-image launch.png --end-image launch.png` (seamless loop), `generate_audio false`, prompt: slow drift of clouds and heat shimmer, satellite moves along the orbit, camera static.
- [ ] Encode: `ffmpeg` H.264 CRF 26 `-movflags +faststart -an`, VP9 webm CRF 36; each ≤ 1.5 MB. Stills: `cwebp -q 78`.
- [ ] `og.jpg`: launch still cropped 1200×630 with name and role set in HTML-rendered type (headless Chrome screenshot of a local page).
- [ ] Verify: `ls -la media` sizes; open each file.

### Task 2: Retention tracking core

**Files:** Modify `services/public/site/track-core.js`, `tests/site/track-core.test.js`.

**Produces:** `TrackCore.CHAPTERS = ["launch","payload","flightlog","origin","ground","contact"]`; `TrackCore.reachEvent(chapter) -> "reach_<chapter>" | null`.

- [ ] Test `reachEvent names known chapters only`: `reachEvent("payload") === "reach_payload"`, `reachEvent("x") === null`, `reachEvent("launch") === null` (the first screen is every visit, not counted).
- [ ] Run `node --test tests/site/track-core.test.js` → FAIL, implement, → PASS. Commit.

### Task 3: Motion core

**Files:** Create `services/public/site/motion-core.js`, `tests/site/motion-core.test.js`.

**Produces (window.MotionCore / module.exports):**
- `progress(scrollY, docHeight, viewHeight) -> number` in [0,1]; 0 when `docHeight <= viewHeight`.
- `activeChapter(tops, y) -> index` — last index whose top ≤ y + 1, `-1` if none (`tops` sorted ascending).
- `openness(rectTop, rectHeight, viewHeight) -> number` in [0,1]: 0 when the interlude is fully below or above the view, 1 when its centre is within the middle 40 % of the view, linear in between.

- [ ] Tests with these exact cases: `progress(0,2000,1000)=0`, `progress(1000,2000,1000)=1`, `progress(500,2000,1000)=0.5`, `progress(50,800,1000)=0`, clamps for negative and overshoot; `activeChapter([0,900,1800],0)=0`, `(…,1799)=1`, `(…,5000)=2`, `([100],0)=-1`; `openness(1000,400,1000)=0`, `openness(300,400,1000)=1`, `openness(-400,400,1000)=0`, monotonic check between 1000 and 300.
- [ ] Fail → implement → pass. Commit.

### Task 4: Page, styles and motion (EN)

**Files:** Rewrite `services/public/site/index.html`, `services/public/site/styles.css`; create `services/public/site/motion.js`; modify `services/public/site/app.js` (only selectors that change, e.g. impact counters), `.github/workflows/ci.yml` (`node --check` motion-core.js, motion.js).

**Consumes:** Task 2 `reachEvent`, `CHAPTERS`; Task 3 functions; Task 1 media paths.

Layout (ids on `<section>`):
- `#launch` (chapter 0): label `MISSION KS · REMOTE · WORLDWIDE`, H1 name, role line, pitch, chips (open to offers / remote, any country / Tbilisi, GMT+4), CTAs (Telegram, LinkedIn, email, CV), poster art (launch still/clip as the right-hand illustration with sun ring), ticker band with the 4 impact numbers + pulse. Contains `#impact` metric grid right below the poster.
- Interlude `.interlude[data-scene=payload]` → `#payload` chapter holding `#cases` (4 cases as before → did → result: `case__problem` = before, points = did, `case__result` = result).
- Interlude flightlog → `#flightlog` holding `#experience` timeline and `#skills` map.
- Interlude origin → `#origin` holding `#aerospace` (flight figure kept) and `#learning`.
- Interlude ground → `#ground` holding `#homelab`, `#projects`, `#sandbox`.
- Interlude contact → `#contact` holding `#recruiters` FAQ + CTAs.
- Fixed `.flightbar` (progress + 6 chapter ticks, links to chapters, `aria-label="Mission progress"`).

Copy rules: keep facts, shorter lines; headline per chapter (e.g. Payload: "Systems banks trust with their releases."); Hero lead without Košice; FAQ q1 → "Where are you based?" a1 → "Tbilisi, Georgia (GMT+4). I work remotely for a company in any country."; q4 → "Do you need a visa?" a4 → "No. Remote work does not need one." Same edits in JSON-LD FAQ (build-i18n checks equality). JSON-LD `seeks.name` → "Full-time remote DevOps, platform or DevSecOps job", `areaServed` removed, `jobLocationType: "TELECOMMUTE"`; Person description without Košice. Title: "Kalislav Smirnov | DevOps Engineer · Kubernetes, DevSecOps · Remote". Nav: Payload/Flight log/Origin/Ground control/Contact with `data-i18n` keys `nav.payload` etc.

motion.js: adds `js` class to `<html>` immediately (script in head is not allowed inline, so `motion.js` loads with `defer` and CSS hides `.reveal` only under `.js`); IntersectionObserver for `.reveal` (once); rAF scroll loop → `progress` to `--p` on `.flightbar`, `activeChapter` to `aria-current`, `openness` to `--open` per interlude; video `src` set when interlude within 1 view, `play()` when open > 0.2, `pause()` otherwise; chapter reach beacons via `navigator.sendBeacon(TrackCore.eventPath(TrackCore.reachEvent(id), source, lang))` once per chapter per page view (source read from `sessionStorage.src` like app.js); ticker paused on hover/focus; reduced motion → skip all of the above except beacons.

- [ ] Write HTML + CSS + motion.js.
- [ ] Verify: `node --check` all JS; `node --test tests/site/*.test.js` PASS; serve `python3 -m http.server -d services/public/site 8099` and screenshot 1440×900 and 390×844 (CDP device metrics) top, each chapter; no console errors; check with JS disabled.
- [ ] Commit.

### Task 5: Aerospace flight

**Files:** Modify `services/public/site/aero.js`.

- [ ] Replace TBS/KSC sites with `LAUNCH` / `LANDING` labels (no city names); keep RANGE physics (comments say "an intercontinental hop" instead of the route); recolor SVG gradients/strokes to the poster palette via CSS classes (stroke colours in `styles.css`, not inline).
- [ ] Verify in browser: arc animates, telemetry updates. Commit.

### Task 6: Translations

**Files:** Modify `services/public/i18n/ru.json`, `services/public/i18n/sk.json`; generated `site/ru/index.html`, `site/sk/index.html`.

- [ ] Add/replace every new or changed key; remove Košice/relocation strings.
- [ ] `python3 scripts/build-i18n.py` exits 0 (no missing keys); grep generated pages for `Košic|Кошиц|reloc|переезд|Blue Card` → nothing. Commit.

### Task 7: Lab page

**Files:** Modify `services/public/site/lab/index.html` (classes only where the new CSS needs them), CSS in `styles.css` (lab section).

- [ ] Lab page renders in the poster style; `lab.js` widgets work; build-i18n regenerates `/ru/lab/`, `/sk/lab/`. Commit.

### Task 8: SEO files and CV

**Files:** `services/public/site/{llms.txt,cv.md,sitemap.xml,sitemap.txt}`, `~/prj/homeserver/kosice-campaign/cv/cv_data.py` (summary/location lines) → new `Kalislav-Smirnov-CV.pdf` and `-SK.pdf` (deployed separately, not in repo, as today).

- [ ] Remove Košice/relocation; location "Tbilisi, Georgia; remote, any country"; lastmod 2026-10-20.
- [ ] Rebuild PDFs with `python3 build_cv.py`; read the PDF text back to check. Commit repo files.

### Task 9: nginx, events report, deploy

**Files:** `services/public/nginx/default.conf`, `scripts/site-events.sh`.

- [ ] Events location regex adds `reach_payload|reach_flightlog|reach_origin|reach_ground|reach_contact`; static regex adds `mp4|webm|webp`.
- [ ] `site-events.sh` prints contact clicks (as now, excluding `reach_*`) and a funnel: count per `reach_*` in chapter order.
- [ ] `nginx -t` in a throwaway `nginx:alpine` container is optional (Docker may be off); at least review the diff.
- [ ] Push branch, open PR to main; after CI green, give the user one `!` command: backup `/opt/public` on LXC 104, rsync `site/` + `nginx/default.conf`, reload nginx, then curl checks.
