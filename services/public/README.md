# Public site (kalik8s.com)

Static CV site served by nginx in the `public` container (LXC 104) at `/opt/public/site`,
published through a Cloudflare Tunnel.

## Layout

- `site/` — the static site (HTML, `cv.md`, `llms.txt`, assets). **Source of truth is this repo.**
- `cvgen/` — the CV generator: `cv_data.py` (facts) + `build_cv.py` → PDF. See `cvgen/README.md`.
- `deploy.sh` — publishes `site/` + freshly built CV PDFs to the container.
- `nginx/`, `docker-compose.yml` — container config.

## Deploying

Everything the site serves is reproducible from this repo. **Never hand-edit files on the
server** — changes there are invisible to git and get overwritten on the next deploy.

1. Make changes on a branch off `origin/main` and open a PR (the site is developed PR-by-PR).
2. After merge, from a clean checkout of `main`:

   ```sh
   services/public/deploy.sh
   ```

   It rebuilds the CV PDFs from `cvgen/` and ships `site/` + the PDFs to LXC 104
   (additive sync; live-only paths `data/` and `cv/` are left untouched). Needs Chrome
   for the PDF build and ssh access to `homeserver` (pve, which has `sudo pct`).

Build artifacts (PDFs, `cvgen/out/`) are git-ignored on purpose: they are generated, not committed.
