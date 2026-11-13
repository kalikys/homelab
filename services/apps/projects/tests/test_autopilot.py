from datetime import datetime, timezone

TODAY = datetime.now(timezone.utc).date().isoformat()
PDF = b"%PDF-1.4\n%test\n"


def vac(vid, **kw):
    return {"vid": vid, "date": TODAY, "at": f"{TODAY} 10:00", "score": 4, "reason": "ok", "lang": "en",
            "title": "DevOps Engineer", "company": "Logos", "url": "https://job-boards.greenhouse.io/logos/jobs/1",
            "source": "hirify", "status": "sent", "channel": "ats:job-boards.greenhouse.io", "detail": "",
            "letter": "Hello, letter body.", "subject": "s", "answers": ""} | kw


def test_sync_creates_pool_application_with_letter_and_platform(client):
    r = client.post("/api/autopilot/sync", json={"vacancies": [vac("1276071")], "meta": {"paused": "0"}})
    assert r.status_code == 200, r.text
    assert r.json()["need_cv"] == ["1276071"]
    apps = client.get("/api/jobs/applications").json()
    assert len(apps) == 1
    a = apps[0]
    assert a["platform"] == "greenhouse" and a["status"] == "sent" and a["fit"] == 4 and a["vacancy_id"] == "1276071"
    d = client.get(f"/api/jobs/applications/{a['id']}").json()
    assert d["letters"][0]["sent"] is True and d["letters"][0]["body"] == "Hello, letter body."
    # idempotent: a second sync adds nothing
    client.post("/api/autopilot/sync", json={"vacancies": [vac("1276071")]})
    assert len(client.get("/api/jobs/applications").json()) == 1
    assert len(client.get(f"/api/jobs/applications/{a['id']}").json()["letters"]) == 1


def test_sync_reuses_mirrored_application_by_uid(client):
    m = client.post("/api/jobs/applications", json={"company": "PrimeHunters", "title": "DBA", "platform": "hirify",
                                                    "status": "sent", "uid": "jobwatch:abc", "vacancy_id": "852326"}).json()
    client.post("/api/autopilot/sync", json={"vacancies": [vac("852326", channel="hirify", app_uid="jobwatch:abc",
                                                               company="PrimeHunters")]})
    apps = client.get("/api/jobs/applications").json()
    assert [a["id"] for a in apps] == [m["id"]]
    assert apps[0]["platform"] == "hirify" and apps[0]["letter_sent"] == 1


def test_cv_upload_attaches_to_application_and_serves(client):
    client.post("/api/autopilot/sync", json={"vacancies": [vac("852326", channel="hirify")]})
    assert client.put("/api/autopilot/vacancies/852326/cv", content=b"not a pdf").status_code == 400
    assert client.put("/api/autopilot/vacancies/852326/cv", content=PDF).status_code == 201
    r = client.get("/api/autopilot/vacancies/852326/cv")
    assert r.status_code == 200 and r.content == PDF
    aid = client.get("/api/jobs/applications").json()[0]["id"]
    att = client.get(f"/api/jobs/applications/{aid}").json()["attachments"]
    assert [x["name"] for x in att] == ["Kalislav-Smirnov-CV-Logos.pdf"]  # named after the company
    # the formatted cover letter is stored and attached the same way
    assert client.put("/api/autopilot/vacancies/852326/letter", content=PDF).status_code == 201
    r = client.get("/api/autopilot/vacancies/852326/letter")
    assert r.status_code == 200 and "Cover-Letter-Logos" in r.headers["content-disposition"]
    assert client.get("/api/autopilot/vacancies/852326/resume").status_code == 400
    assert client.post("/api/autopilot/sync", json={"vacancies": []}).json()["need_cv"] == []
    assert client.get("/api/autopilot/vacancies/../x/cv").status_code in (400, 404)


def test_manual_queue_done_joins_pool(client):
    client.post("/api/autopilot/sync", json={"vacancies": [
        vac("1110735", status="manual", channel="link", company="Plata Card", url="https://plata.careers/x"),
        vac("him-0bff1510c1", status="skipped", reason="Обязателен продакшен AWS", channel=""),
    ]})
    assert client.get("/api/jobs/applications").json() == []
    s = client.get("/api/autopilot/stats?days=7").json()
    assert s["today"]["manual"] == 1 and s["manual_open"] == 1 and s["skip_reasons"] == [["нет продакшен-облака", 1]]
    r = client.post("/api/autopilot/vacancies/1110735/done")
    assert r.status_code == 200 and r.json()["manual_done_at"]
    apps = client.get("/api/jobs/applications").json()
    assert len(apps) == 1 and apps[0]["platform"] == "company-site"
    # sync again must not reset the manual mark
    client.post("/api/autopilot/sync", json={"vacancies": [vac("1110735", status="manual", channel="link")]})
    s = client.get("/api/autopilot/stats?days=7").json()
    assert s["manual_open"] == 0 and s["funnel"]["sent"] == 1


def test_events_and_stats(client):
    client.post("/api/autopilot/sync", json={"vacancies": [vac("1", channel="email"), vac("2", channel="hirify")],
                                            "events": [{"key": "m:1", "at": f"{TODAY} 12:00", "kind": "interview",
                                                        "company": "Logos", "summary": "зовут на созвон"},
                                                       {"key": "m:2", "at": f"{TODAY} 13:00", "kind": "rejection"}]})
    ev = client.get("/api/autopilot/events").json()
    assert [e["kind"] for e in ev] == ["interview", "rejection"]
    s = client.get("/api/autopilot/stats?days=7").json()
    assert s["today"]["sent"] == 2 and s["channels"] == {"email": 1, "hirify": 1}
    assert s["today"]["events"] == {"interview": 1, "rejection": 1}
    assert len(s["series"]) == 7 and s["series"][-1]["sent"] == 2
    assert "synced_at" in s["meta"]
    lst = client.get("/api/autopilot/vacancies?status=sent").json()
    assert {v["vid"] for v in lst} == {"1", "2"}


def test_bad_url_is_not_rendered(client):
    client.post("/api/autopilot/sync", json={"vacancies": [vac("9", status="manual", url="javascript:alert(1)")]})
    assert client.get("/api/autopilot/vacancies").json()[0]["url"] == ""
