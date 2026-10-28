import importlib
import json
import sys
import urllib.request
from pathlib import Path

import pytest

LETTERS = """# How to send

| 1 | Acme DevOps | https://www.profesia.sk/praca/acme/O1000001 | A | Jane |

# Letters

## O1000001 Acme, DevOps Engineer, remote, from 2 800 € (Ing. Jane Doe)

Your team runs Kubernetes on bare metal, which is what I did for a bank for two years.

Kalislav

---

## O1000002 Beta GmbH, Data Engineer (hr@beta.sk, German)

Ich habe vier Jahre lang Plattformen betrieben und lerne schnell, und wir können gerne sprechen.

# Batch 2

## O1000003 Gamma, SRE = hirify 999 (same email)

short
"""

JOBWATCH = [
    {"id": "a1", "date": "2026-10-05", "company": "Olmait", "title": "DevSecOps", "channel": "рекрутер Tamuna", "url": None,
     "vacancy_id": None, "source": None, "status": "interview", "note": "HR пройдено", "reminded": []},
    {"id": "a2", "date": "2026-10-03", "company": "EMCD", "title": "Platform", "channel": "трекер hirify", "url": None,
     "vacancy_id": 1088, "source": "hirify", "status": "sent", "note": None, "reminded": [7]},
    {"id": "a3", "date": "2026-09-28", "company": "Toughbyte", "title": "SRE", "channel": "hirify", "url": None,
     "vacancy_id": None, "source": "hirify", "status": "rejected", "note": None, "reminded": []},
]


@pytest.fixture
def imp(live_url, monkeypatch):
    monkeypatch.setenv("PJ_URL", live_url)
    sys.path.insert(0, str(Path(__file__).parents[1] / "client"))
    import import_jobs
    importlib.reload(import_jobs)
    return import_jobs, live_url


def get(url, path):
    return json.load(urllib.request.urlopen(url + path))


def test_parse_letters(imp):
    ls = imp[0].parse_letters(LETTERS)
    assert [l["code"] for l in ls] == ["O1000001", "O1000002", "O1000003"]
    a, b, _ = ls
    assert a["company"] == "Acme" and a["title"] == "DevOps Engineer" and a["url"].endswith("/O1000001")
    assert a["contact"] == {"name": "Ing. Jane Doe"} and a["body"].endswith("Kalislav") and a["lang"] == "en"
    assert b["contact"]["email"] == "hr@beta.sk" and b["lang"] == "de" and "Batch" not in b["body"]


def test_import_both_idempotent(imp, tmp_path):
    import_jobs, url = imp
    jw = tmp_path / "applications.json"
    jw.write_text(json.dumps(JOBWATCH, ensure_ascii=False))
    lf = tmp_path / "LETTERS.md"
    lf.write_text(LETTERS)
    assert import_jobs.main(["jobwatch", str(jw)]) == 0
    assert import_jobs.main(["letters", str(lf)]) == 0
    assert import_jobs.main(["jobwatch", str(jw)]) == 0
    assert import_jobs.main(["letters", str(lf)]) == 0
    apps = get(url, "/api/jobs/applications")
    assert len(apps) == 5  # the 'short' letter is skipped
    by = {a["company"]: a for a in apps}
    assert by["Olmait"]["status"] == "interview" and by["Olmait"]["contact_name"] == "Tamuna"
    assert by["Olmait"]["applied_at"] == "2026-10-05"
    assert by["EMCD"]["platform"] == "hirify" and by["EMCD"]["vacancy_id"] == "1088"
    assert by["EMCD"]["next_action_at"] == "2026-10-17"  # 7-day reminder already sent, the 14-day one is left
    assert by["Toughbyte"]["next_action_at"] is None
    assert by["Acme"]["status"] == "draft" and by["Acme"]["letters_count"] == 1 and by["Acme"]["platform"] == "profesia"
    d = get(url, f"/api/jobs/applications/{by['Acme']['id']}")
    assert d["letters"][0]["source"] == "imported" and d["letters"][0]["sent"] is False
