# CV generator for the public site

Source of truth for the CVs on https://kalik8s.com.

- `cv_data.py` — all CV content (facts): English (`EN`), Slovak (`SK`), engineering-first (`ENG`) and the
  role variants in `ROLE_CVS` (DevOps, DevSecOps, Platform-SRE, Master), which reuse the `EN` facts and
  change only the headline, the summary and the order of bullets. Edit facts once, every CV follows.
- `build_cv.py` — renders them with headless Chrome:
  - `out/Kalislav-Smirnov-CV{,-SK,-Engineering}.pdf` → site root
  - `out/cv/Kalislav-Smirnov-<Role>.{pdf,txt,docx}` → `/cv/`
- `Dockerfile` — the build environment used by the autodeploy (Chromium, Inter, python-docx).

Local preview on the Mac:

```sh
uv run --no-project --with python-docx python3 build_cv.py
```

The outputs are git-ignored build artifacts; the autodeploy rebuilds them from the merged commit.

Note: per-vacancy tailored CVs for job applications live separately in `services/jobwatch/cv/`.
