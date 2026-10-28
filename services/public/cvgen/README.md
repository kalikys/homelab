# CV generator for the public site

Source of truth for the downloadable CVs on https://kalik8s.com.

- `cv_data.py` — all CV content (facts), in English (`EN`), Slovak (`SK`) and an
  engineering-first variant (`ENG`). Edit facts here.
- `build_cv.py` — renders each variant to HTML + A4 PDF with headless Chrome into `out/`.

```sh
python3 build_cv.py   # -> out/Kalislav-Smirnov-CV{,-SK,-Engineering}.pdf
```

The PDFs are build artifacts (git-ignored). Publishing is done by `../deploy.sh`,
which rebuilds them and ships the site + PDFs to the `public` container — the live
site is always reproducible from this repo, nothing is hand-edited on the server.

Note: per-vacancy tailored CVs for job applications live separately in
`services/jobwatch/cv/` (same base content, chosen/reordered per vacancy).
