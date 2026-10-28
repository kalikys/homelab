#!/usr/bin/env python3
"""Renders the CV (EN and SK) to HTML and PDF with headless Chrome.

Usage: python3 build_cv.py            -> out/Kalislav-Smirnov-CV.pdf, out/Kalislav-Smirnov-CV-SK.pdf, out/Kalislav-Smirnov-CV-Engineering.pdf
"""
import html
import pathlib
import subprocess
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from cv_data import CONTACTS, EN, ENG, SK, SKILLS_TAGS  # noqa: E402

HERE = pathlib.Path(__file__).parent
OUT = HERE / "out"
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

CSS = """
@page { size: A4; margin: 14mm 15mm 14mm; }
* { box-sizing: border-box; }
body { margin: 0; font: 9.6pt/1.42 Inter, "Helvetica Neue", Arial, sans-serif; color: #1f2937; }
h1 { margin: 0; font-size: 21pt; letter-spacing: -0.02em; color: #111827; }
.role { margin: 2px 0 0; font-size: 11.5pt; font-weight: 600; color: #0f766e; }
.meta { margin: 6px 0 0; color: #4b5563; font-size: 9pt; }
.meta a { color: #1d4ed8; text-decoration: none; }
.meta span + span::before { content: "·"; margin: 0 6px; color: #9ca3af; }
h2 { margin: 14px 0 6px; padding-bottom: 3px; border-bottom: 1px solid #d1d5db; font-size: 10.5pt;
     text-transform: uppercase; letter-spacing: 0.06em; color: #111827; }
p { margin: 0 0 5px; }
.job { margin: 0 0 9px; break-inside: avoid; }
.job__head { display: flex; justify-content: space-between; gap: 12px; }
.job__role { font-weight: 700; color: #111827; }
.job__company { color: #0f766e; font-weight: 600; }
.job__period { color: #6b7280; font-style: italic; white-space: nowrap; padding-right: 2px; }
ul { margin: 3px 0 3px; padding-left: 15px; }
li { margin: 1.5px 0; }
.stack { color: #4b5563; font-size: 8.8pt; }
.stack b { color: #374151; }
.degree { font-weight: 700; color: #111827; }
.note { color: #4b5563; }
.skills { display: grid; grid-template-columns: 150px 1fr; gap: 2px 10px; }
.skills dt { font-weight: 600; color: #374151; }
.skills dd { margin: 0; }
.keep { break-inside: avoid; }
"""


def esc(s):
    return html.escape(s, quote=True)


def render(d):
    contacts = "".join(f'<span><a href="{esc(u)}">{esc(t)}</a></span>' for t, u in CONTACTS)
    jobs = []
    for j in d["jobs"]:
        company = esc(j["company"]) + (f' · {esc(j["type"])}' if j["type"] else "")
        intro = f'<p>{esc(j["intro"])}</p>' if j["intro"] else ""
        points = "".join(f"<li>{esc(p)}</li>" for p in j["points"])
        jobs.append(
            f'<div class="job"><div class="job__head"><div><span class="job__role">{esc(j["role"])}</span>, '
            f'<span class="job__company">{company}</span></div><span class="job__period">{esc(j["period"])}</span></div>'
            f'{intro}<ul>{points}</ul><p class="stack"><b>{esc(d["stack_label"])}:</b> {esc(j["stack"])}</p></div>'
        )
    tags = sorted(SKILLS_TAGS.items(), key=lambda kv: kv[0] != "eng") if d.get("edu_first") else SKILLS_TAGS.items()
    skills = "".join(f'<dt>{esc(d["skills"][k])}</dt><dd>{esc(v)}</dd>' for k, v in tags)
    aero = "".join(f"<li>{esc(p)}</li>" for p in d["aero_points"])
    lab = "".join(f"<li>{esc(p)}</li>" for p in d["lab"])
    summary = "".join(f"<p>{esc(p)}</p>" for p in d["summary"])
    exp = f"<h2>{esc(d['h']['exp'])}</h2>{''.join(jobs)}"
    agents = ""
    if d.get("agents"):
        items = "".join(f'<li><b>{esc(t)}.</b> {esc(body)}</li>' for t, body in d["agents"])
        agents = f'<h2>{esc(d["h"]["agents"])}</h2><ul>{items}</ul>'
    edu = (f'<div class="keep"><h2>{esc(d["h"]["aero"])}</h2>'
           f'<p><span class="degree">{esc(d["degree"])}</span><br><span class="note">{esc(d["degree_note"])}</span></p>'
           f'<p>{esc(d["field"])}</p><ul>{aero}</ul><p class="stack"><b>{esc(d["aero_tools"])}</b></p></div>')
    if d.get("agents_first"):
        blocks = agents + exp + edu
    elif d.get("edu_first"):
        blocks = edu + exp + agents
    else:
        blocks = exp + agents + edu
    return f"""<!doctype html>
<html lang="{d['lang']}"><head><meta charset="utf-8"><title>{esc(d['title'])}</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap">
<style>{CSS}</style></head><body>
<h1>Kalislav Smirnov</h1>
<p class="role">{esc(d['role'])}</p>
<p class="meta"><span>{esc(d['location'])}</span>{contacts}</p>
<h2>{esc(d['h']['summary'])}</h2>{summary}
{blocks}
<div class="keep"><h2>{esc(d['h']['skills'])}</h2><dl class="skills">{skills}</dl></div>
<div class="keep"><h2>{esc(d['h']['lab'])}</h2><ul>{lab}</ul></div>
<div class="keep"><h2>{esc(d['h']['lang'])}</h2><p>{esc(d['languages'])}</p></div>
</body></html>"""


def main():
    OUT.mkdir(exist_ok=True)
    for d, name in [(EN, "Kalislav-Smirnov-CV"), (SK, "Kalislav-Smirnov-CV-SK"), (ENG, "Kalislav-Smirnov-CV-Engineering")]:
        src = OUT / f"{name}.html"
        src.write_text(render(d))
        pdf = OUT / f"{name}.pdf"
        subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                        f"--user-data-dir={OUT / '.chrome'}", "--virtual-time-budget=4000",
                        f"--print-to-pdf={pdf}", src.as_uri()],
                       check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("wrote", pdf)


if __name__ == "__main__":
    main()
