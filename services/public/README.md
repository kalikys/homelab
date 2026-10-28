# Public site (kalik8s.com)

Static CV site served by nginx in the `public` container (LXC 104) from `/opt/public/site`,
published through a Cloudflare Tunnel.

## Layout

- `site/` — the static site (HTML, `cv.md`, `llms.txt`, `ads.txt`, assets). **Source of truth is this repo.**
- `cvgen/` — the CV generator: `cv_data.py` (facts) + `build_cv.py` → downloadable PDFs and the role CVs
  in `/cv/` (PDF, TXT, DOCX). See `cvgen/README.md`.
- `autodeploy/` — GitOps pull deploy that runs on LXC 104. See `autodeploy/README.md`.
- `deploy.sh` — deploy `origin/main` now, without waiting for the timer.
- `nginx/`, `docker-compose.yml` — container config (not covered by the autodeploy).

## Changing the site

1. Branch off `origin/main`, change the sources, open a PR. CI checks that the generated files are fresh:
   after editing `site/cv.md` run `python3 scripts/build-cv-terminal.py`; after blog/i18n changes run
   `scripts/build-blog.py` / `scripts/build-i18n.py`.
2. Merge. Within 5 minutes LXC 104 builds the CVs and syncs the site (`./deploy.sh` to do it at once).

Never edit files on the server: the next deploy replaces the web root with the commit (`--delete`),
except `data/`, which the stats service writes live. Build artifacts (PDFs, DOCX, `cvgen/out/`) are
git-ignored: they are generated, not committed.
