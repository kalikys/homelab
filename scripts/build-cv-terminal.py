#!/usr/bin/env python3
"""Builds the terminal CV from services/public/site/cv.md, so it never drifts from the site.

Outputs (committed, served as static files):
  services/public/site/cv.txt        ANSI-coloured CV for `curl kalik8s.com/cv` (max 80 columns)
  services/public/site/cv-plain.txt  the same without colours (`curl kalik8s.com/cv?plain`)
  services/public/site/cv.json       JSON Resume (https://jsonresume.org/schema) for `curl kalik8s.com/cv.json`

Usage: build-cv-terminal.py [--check]   (--check exits 1 if the committed outputs are stale; CI runs it)
"""
import json
import pathlib
import re
import sys
import textwrap

ROOT = pathlib.Path(__file__).resolve().parent.parent
SITE = ROOT / "services/public/site"
WIDTH = 78  # leaves a margin inside an 80-column terminal

ORANGE, GREY, BOLD, RESET = "\033[38;5;208m", "\033[38;5;245m", "\033[1m", "\033[0m"

BANNER = [
    r"         /\           ",
    r"        /  \          ",
    r"       | KS |         ",
    r"       |    |    .    ",
    r"      /|    |\       *",
    r"     /_|____|_\       ",
    r"        /\/\    .     ",
]
MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def parse(md):
    """cv.md → title, intro paragraphs and an ordered list of (section, [(subsection, [lines])])."""
    title, intro, sections = "", [], []
    for raw in md.splitlines():
        line = raw.rstrip()
        if line.startswith("# "):
            title = line[2:].strip()
        elif line.startswith("## "):
            sections.append((line[3:].strip(), [(None, [])]))
        elif line.startswith("### "):
            sections[-1][1].append((line[4:].strip(), []))
        elif line.strip():
            (sections[-1][1][-1][1] if sections else intro).append(line)
    return title, intro, sections


def wrap(text, indent="", first=None):
    first = indent if first is None else first
    return textwrap.wrap(text, WIDTH, initial_indent=first, subsequent_indent=indent,
                         break_long_words=False, break_on_hyphens=False) or [first.rstrip()]


def plain_lines(md):
    title, intro, sections = parse(md)
    name, _, role = title.partition(",")
    hiring = dict(re.match(r"- ([^:]+): (.*)", l).groups() for s, subs in sections if s == "Hiring details"
                  for _, lines in subs for l in lines if re.match(r"- [^:]+: ", l))
    side = [name.strip().upper(), role.strip(), "Remote · any country · Tbilisi, GMT+4",
            "Open to offers now", "", "MISSION KS · T-0", ""]
    out = [f"{b}{s}".rstrip() for b, s in zip(BANNER, side)]
    out.append("")
    for p in intro:
        if p.startswith("Updated:"):
            continue
        out += wrap(p)
    out.append("")
    for section, subs in sections:
        out += [f"== {section.upper()} ".ljust(WIDTH, "="), ""]
        for sub, lines in subs:
            if sub:
                out += wrap(sub, "   ", ">> ")
            for l in lines:
                if l.startswith("- "):
                    out += wrap(l[2:], "     " if sub else "  ", "   · " if sub else "· ")
                else:
                    out += wrap(l, "   " if sub else "")
            if sub or lines:
                out.append("")
    out += ["-" * WIDTH,
            "Same CV:  https://kalik8s.com   ·   curl kalik8s.com/cv.json",
            "As a container:  docker run --rm ghcr.io/kalikys/cv",
            "Hiring? Book 20 minutes:  https://cal.com/kalikys/intro", ""]
    return out


def colour(line, i):
    if i < len(BANNER):
        art, text = line[:22], line[22:]
        return ORANGE + art + RESET + (BOLD + text + RESET if text else "")
    if line.startswith("== "):
        return BOLD + ORANGE + line + RESET
    if line.lstrip().startswith(">> "):
        return BOLD + line + RESET
    unit = r"(?:\s?(?:hours|minutes|weeks|days|min|VMs|h)\b)?"
    num = rf"(?<![\w/.-])\d[\d.,]*(?:\+|%)?{unit}(?:\s?→\s?\d[\d.,]*{unit})?"
    url = r"https?://\S+|\b(?:kalik8s\.com/\S*|ghcr\.io/\S+)"
    # One pass, so a number inside a URL (or inside an escape code) is never coloured twice.
    line = re.sub(rf"(?P<url>{url})|(?P<num>{num})",
                  lambda m: (GREY if m.group("url") else ORANGE) + m.group(0) + RESET, line)
    return line


def month(s):
    mon, year = s.split()
    return f"{year}-{MONTHS[mon[:3]]:02d}"


def resume_json(md):
    title, intro, sections = parse(md)
    sec = {s: subs for s, subs in sections}
    name, _, label = title.partition(",")
    summary = next(p for p in intro if not p.startswith("Updated:"))
    work = []
    for sub, lines in sec["Experience"][1:]:
        m = re.match(r"(.+?), (.+?) \((\w+ \d{4}) - (\w+ \d{4})", sub)
        role, company, start, end = m.groups()
        bullets = [l[2:] for l in lines if l.startswith("- ")]
        intro_l = [l for l in lines if not l.startswith("- ")]
        work.append({"name": company, "position": role, "startDate": month(start), "endDate": month(end),
                     **({"summary": intro_l[0]} if intro_l else {}), "highlights": bullets})
    skills = []
    for l in sec["Skills"][0][1]:
        k, _, v = l[2:].partition(": ")
        skills.append({"name": k, "keywords": [x.strip() for x in v.split(",")]})
    edu = sec["Education"][0][1]
    return {
        "$schema": "https://raw.githubusercontent.com/jsonresume/resume-schema/v1.0.0/schema.json",
        "basics": {
            "name": name.strip(), "label": label.strip(), "email": "kalikys@outlook.com",
            "url": "https://kalik8s.com/", "summary": summary,
            "location": {"city": "Tbilisi", "countryCode": "GE"},
            "profiles": [
                {"network": "GitHub", "username": "kalikys", "url": "https://github.com/kalikys"},
                {"network": "LinkedIn", "username": "devops-kalislav-smirnov",
                 "url": "https://www.linkedin.com/in/devops-kalislav-smirnov/"},
                {"network": "Telegram", "username": "kalikys", "url": "https://t.me/kalikys"},
            ],
        },
        "work": work,
        "education": [{"institution": "Bauman Moscow State Technical University", "area": "Aerospace Engineering",
                       "studyType": "Integrated Master's degree (Specialist, Engineer)",
                       "startDate": "2020", "endDate": "2026", "courses": [edu[0][2:], edu[2][2:]]}],
        "skills": skills,
        "languages": [{"language": "English", "fluency": "B2"}, {"language": "Russian", "fluency": "Native"}],
        "projects": [{"name": "homelab", "url": "https://github.com/kalikys/homelab",
                      "description": " ".join(sec["Home lab"][0][1])}],
        "meta": {"canonical": "https://kalik8s.com/cv.json", "version": "v1.0.0",
                 "lastModified": re.search(r"Updated: (\S+)", "\n".join(intro)).group(1)},
    }


def build():
    md = (SITE / "cv.md").read_text()
    lines = plain_lines(md)
    return {
        "cv-plain.txt": "\n".join(lines),
        "cv.txt": "\n".join(colour(l, i) for i, l in enumerate(lines)),
        "cv.json": json.dumps(resume_json(md), ensure_ascii=False, indent=2) + "\n",
    }


def main(argv):
    stale = []
    for name, text in build().items():
        path = SITE / name
        if "--check" in argv:
            if not path.exists() or path.read_text() != text:
                stale.append(name)
        else:
            path.write_text(text)
            print(f"wrote {path.relative_to(ROOT)}")
    if stale:
        sys.exit(f"build-cv-terminal: stale {stale}; run python3 scripts/build-cv-terminal.py")


if __name__ == "__main__":
    main(sys.argv[1:])
