#!/usr/bin/env python3
"""One-off import into the job applications dashboard. Idempotent: every record carries a uid.

  import_jobs.py jobwatch applications.json     # jobwatch log from VM 220 (state/applications.json)
  import_jobs.py letters LETTERS.md [--platform profesia] [--status draft]

Letters files: one `## <code> <Company>, <Title> (<contact or email>, ...)` section per vacancy with the
letter below it; vacancy links anywhere in the file are matched by code. Personal data stays out of the
repo: the files are read where they live.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import date, timedelta

URL = os.environ.get("PJ_URL", "http://192.168.1.10:8790").rstrip("/")

STATUS = {"sent": "sent", "reply": "replied", "replied": "replied", "interview": "interview", "offer": "offer",
          "rejected": "rejected", "silent": "silent", "declined": "declined"}


def call(method, path, body=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data, {"Content-Type": "application/json"}, method=method)
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status, json.load(r)


def platform_of(channel: str, source: str | None) -> str:
    c = (channel or "").lower()
    for key, slug in (("hirify", "hirify"), ("smartrecruiters", "smartrecruiters"), ("сайт dt", "smartrecruiters"),
                      ("linkedin", "linkedin"), ("profesia", "profesia"), ("himalayas", "himalayas"),
                      ("рекрутер", "recruiter"), ("email", "email"), ("почт", "email"), ("сайт", "company-site")):
        if key in c:
            return slug
    return source or channel or "other"


def next_reminder(r: dict) -> str | None:
    """jobwatch reminds 7 and 14 days after sending; keep the reminders it has not sent yet."""
    if r["status"] != "sent":
        return None
    for mark in (7, 14):
        if mark not in (r.get("reminded") or []):
            return (date.fromisoformat(r["date"]) + timedelta(days=mark)).isoformat()
    return None


def import_jobwatch(path: str) -> tuple[int, int]:
    new = old = 0
    for r in json.load(open(path, encoding="utf-8")):
        note = r.get("note") or ""
        channel = r.get("channel") or ""
        if channel and platform_of(channel, None) in ("recruiter", "company-site", "email") or channel.startswith("трекер"):
            note = f"{note}\nКанал: {channel}".strip()
        body = {"company": r["company"], "title": r["title"], "url": r.get("url") or "",
                "platform": platform_of(channel, r.get("source")), "status": STATUS.get(r["status"], "sent"),
                "applied_at": r["date"], "next_action_at": next_reminder(r), "notes": note, "uid": f"jobwatch:{r['id']}"}
        if body["next_action_at"]:
            body["next_action"] = "Написать follow-up"
        if r.get("vacancy_id") and str(r["vacancy_id"]).isdigit():
            body["vacancy_id"] = str(r["vacancy_id"])
        m = re.search(r"рекрутер (\S+)", channel)
        if m:
            body["contact"] = {"name": m.group(1), "company": r["company"], "role": "Recruiter"}
        status, _ = call("POST", "/api/jobs/applications", body)
        new, old = (new + 1, old) if status == 201 else (new, old + 1)
    return new, old


HEAD = re.compile(r"^## (?P<code>[A-Z]\d+)\s+(?P<rest>.+)$", re.M)


def detect_lang(text: str) -> str:
    if re.search(r"[а-яё]", text, re.I):
        return "ru"
    if re.search(r"\b(und|wir|Sie|für|mit|ich)\b", text):
        return "de"
    if re.search(r"[áäčďéíĺľňóôŕšťúýž]", text) and re.search(r"\b(som|je|sa|pre|vám)\b", text):
        return "sk"
    return "en"


def parse_letters(text: str) -> list[dict]:
    links = {m.group(1): m.group(0) for m in re.finditer(r"https://www\.profesia\.sk/praca/[\w.-]+/(O\d+)", text)}
    heads = list(HEAD.finditer(text))
    out, emails = [], {}
    for i, h in enumerate(heads):
        end = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        body = text[h.end():end]
        body = re.split(r"\n# ", body)[0]  # a new top-level part ("# Batch 2") ends the letter
        body = re.sub(r"\n-{3,}\s*$", "", body.strip()).strip()
        rest = re.sub(r"\s*=\s*hirify.*$", "", h.group("rest"))
        contact, head = None, rest
        parens = list(re.finditer(r"\(([^)]*)\)", rest))
        last = parens[-1] if parens else None
        first = last.group(1).split(",")[0].strip() if last else ""
        # Only the last bracket can be a contact, and only an e-mail or a person's name: "(Senior)" is part of a title.
        if "@" in first:
            contact = {"name": first, "email": first}
        elif first == "same email" and emails.get(rest.split(",")[0].strip()):
            e = emails[rest.split(",")[0].strip()]
            contact = {"name": e, "email": e}
        elif len(re.findall(r"\b[A-ZÁČĎÉÍĽŇÓŠŤÚÝŽ][\w.]+", first)) >= 2:
            contact = {"name": first}
        if last and (contact or first in ("same email", "German")):
            head = rest[:last.start()].rstrip(" ,") + rest[last.end():]
        company, _, title = head.partition(",")
        title = re.split(r",\s*(?=\d|remote|from|Košice|employment|closes)", title.strip())[0].strip(" ,")
        if contact and contact.get("email"):
            emails[company.strip()] = contact["email"]
        out.append({"code": h.group("code"), "company": company.strip(), "title": title.strip() or head,
                    "url": links.get(h.group("code"), ""), "contact": contact, "body": body, "lang": detect_lang(body)})
    return out


def import_letters(path: str, platform: str, status: str) -> tuple[int, int]:
    new = old = 0
    for l in parse_letters(open(path, encoding="utf-8").read()):
        if len(l["body"]) < 40:
            continue
        body = {"company": l["company"], "title": l["title"], "url": l["url"], "platform": platform,
                "status": status, "location": "Košice" if platform == "profesia" else "", "uid": f"letters:{l['code']}",
                "notes": f"Импорт из {os.path.basename(path)}"}
        if l["contact"]:
            body["contact"] = {**l["contact"], "company": l["company"]}
        code, app = call("POST", "/api/jobs/applications", body)
        if code == 201:
            call("POST", f"/api/jobs/applications/{app['id']}/letters",
                 {"lang": l["lang"], "body": l["body"], "source": "imported", "sent": status not in ("draft", "inbound")})
            new += 1
        else:
            old += 1
    return new, old


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="kind", required=True)
    sub.add_parser("jobwatch").add_argument("file")
    sp = sub.add_parser("letters")
    sp.add_argument("file"); sp.add_argument("--platform", default="profesia"); sp.add_argument("--status", default="draft")
    a = ap.parse_args(argv)
    try:
        new, old = import_jobwatch(a.file) if a.kind == "jobwatch" else import_letters(a.file, a.platform, a.status)
    except urllib.error.HTTPError as e:
        print(f"import failed: {e.code} {e.read().decode()[:300]}", file=sys.stderr)
        return 1
    print(f"imported {new}, already there {old}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
