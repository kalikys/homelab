import threading
from datetime import datetime, timedelta, timezone

from projects_api import db as dbm

TODAY = datetime.now(timezone.utc).date()


def plus(days: int) -> str:
    return (TODAY + timedelta(days=days)).isoformat()


def new_app(client, **kw):
    body = {"company": "Deutsche Telekom ITS", "title": "DevOps Expert", "platform": "hirify", "status": "sent"} | kw
    r = client.post("/api/jobs/applications", json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_platforms_seeded_and_custom(client):
    slugs = [p["slug"] for p in client.get("/api/jobs/platforms").json()]
    assert {"hirify", "profesia", "linkedin", "recruiter"} <= set(slugs)
    r = client.post("/api/jobs/platforms", json={"slug": "djinni", "name": "Djinni", "url": "https://djinni.co"})
    assert r.status_code == 201
    assert client.patch("/api/jobs/platforms/djinni", json={"notes": "вход через Google"}).json()["notes"] == "вход через Google"
    assert client.post("/api/jobs/platforms", json={"slug": "djinni", "name": "x"}).status_code == 409


def test_create_sent_sets_dates_and_event(client):
    a = new_app(client)
    assert a["applied_at"] == TODAY.isoformat()
    assert a["next_action_at"] == plus(7)
    assert a["origin"] == "outbound"
    d = client.get(f"/api/jobs/applications/{a['id']}").json()
    assert d["events"][0]["kind"] == "created"
    assert d["platform_name"] == "Hirify"


def test_unknown_platform_is_created(client):
    a = new_app(client, platform="Djinni")
    assert a["platform"] == "djinni"
    assert any(p["slug"] == "djinni" and p["name"] == "Djinni" for p in client.get("/api/jobs/platforms").json())


def test_uid_is_idempotent(client):
    a = new_app(client, uid="jobwatch:1")
    r = client.post("/api/jobs/applications", json={"company": "X", "title": "Y", "uid": "jobwatch:1"})
    assert r.status_code == 200 and r.json()["id"] == a["id"]


def test_inbound_with_new_contact(client):
    r = client.post("/api/jobs/applications", json={
        "company": "Olmait", "title": "DevSecOps", "origin": "inbound", "platform": "linkedin",
        "contact": {"name": "Tamuna", "role": "Recruiter", "email": "t@olmait.ge", "telegram": "@tamuna"},
        "vacancy_text": "GCP, Terraform"})
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["status"] == "inbound" and a["next_action_at"] == plus(3)
    d = client.get(f"/api/jobs/applications/{a['id']}").json()
    assert d["contact"]["name"] == "Tamuna" and d["contact"]["telegram"] == "@tamuna"
    # The same e-mail reuses the contact.
    b = client.post("/api/jobs/applications", json={"company": "Olmait", "title": "SRE", "origin": "inbound",
                                                    "contact": {"name": "Tamuna K", "email": "T@olmait.ge"}}).json()
    assert b["contact_id"] == a["contact_id"]
    c = client.get(f"/api/jobs/contacts/{a['contact_id']}").json()
    assert {x["id"] for x in c["applications"]} == {a["id"], b["id"]}


def test_status_changes(client):
    a = new_app(client, status="draft")
    assert a["applied_at"] is None and a["next_action_at"] is None
    a = client.patch(f"/api/jobs/applications/{a['id']}", json={"status": "sent"}).json()
    assert a["applied_at"] == TODAY.isoformat() and a["next_action_at"] == plus(7)
    a = client.patch(f"/api/jobs/applications/{a['id']}", json={"status": "replied"}).json()
    assert a["next_action_at"] == plus(3) and a["replied_at"]
    a = client.patch(f"/api/jobs/applications/{a['id']}", json={"status": "rejected"}).json()
    assert a["next_action_at"] is None
    # An explicit date wins over the default.
    a = client.patch(f"/api/jobs/applications/{a['id']}", json={"status": "interview", "next_action_at": plus(10)}).json()
    assert a["next_action_at"] == plus(10) and a["interview_at"]
    ev = client.get(f"/api/jobs/applications/{a['id']}").json()["events"]
    assert any("отказ" in e["text"] for e in ev)
    assert client.patch(f"/api/jobs/applications/{a['id']}", json={"status": "nope"}).status_code == 400


def test_list_filters_and_search(client):
    new_app(client, company="Минебеа", title="Software Test Engineer", platform="profesia")
    new_app(client, company="Volvo Cars", title="Logistics Engineer", platform="profesia", status="draft")
    new_app(client, company="EMCD", title="Platform", platform="hirify")
    assert len(client.get("/api/jobs/applications?platform=profesia").json()) == 2
    assert [a["company"] for a in client.get("/api/jobs/applications?status=draft").json()] == ["Volvo Cars"]
    assert [a["company"] for a in client.get("/api/jobs/applications?q=минеб").json()] == ["Минебеа"]


def test_letters_versions_and_single_sent(client):
    a = new_app(client)
    l1 = client.post(f"/api/jobs/applications/{a['id']}/letters", json={"lang": "en", "body": "v1"}).json()
    l2 = client.post(f"/api/jobs/applications/{a['id']}/letters", json={"lang": "sk", "body": "ahoj"}).json()
    assert l1["status"] == "ready" and l1["source"] == "manual"
    client.patch(f"/api/jobs/letters/{l1['id']}", json={"body": "v2"})
    d = client.get(f"/api/jobs/letters/{l1['id']}").json()
    assert d["body"] == "v2" and [v["body"] for v in d["versions"]] == ["v1"]
    client.patch(f"/api/jobs/letters/{l1['id']}", json={"sent": True})
    client.patch(f"/api/jobs/letters/{l2['id']}", json={"sent": True})
    letters = client.get(f"/api/jobs/applications/{a['id']}").json()["letters"]
    assert {x["id"]: x["sent"] for x in letters} == {l1["id"]: False, l2["id"]: True}
    assert client.get("/api/jobs/applications").json()[0]["letters_count"] == 2
    assert client.delete(f"/api/jobs/letters/{l2['id']}").status_code == 204


def test_generate_claim_done(client):
    a = new_app(client, vacancy_text="Kubernetes on-prem")
    old = client.post(f"/api/jobs/applications/{a['id']}/letters", json={"lang": "en", "body": "older letter"}).json()
    l = client.post(f"/api/jobs/applications/{a['id']}/letters/generate", json={"lang": "en", "wish": "короче"}).json()
    assert l["status"] == "pending" and l["wish"] == "короче"
    job = client.post("/api/jobs/queue/claim").json()
    assert job["letter"]["id"] == l["id"]
    assert job["application"]["vacancy_text"] == "Kubernetes on-prem"
    assert [p["body"] for p in job["previous_letters"]] == ["older letter"]
    assert client.post("/api/jobs/queue/claim").status_code == 204
    r = client.post(f"/api/jobs/queue/{l['id']}/done", json={"body": "Hello"})
    assert r.json()["status"] == "ready" and r.json()["source"] == "generated"
    assert client.post(f"/api/jobs/queue/{l['id']}/done", json={"body": "again"}).status_code == 409
    assert old["id"] != l["id"]


def test_generate_on_create(client):
    a = new_app(client, generate={"lang": "ru", "wish": ""})
    d = client.get(f"/api/jobs/applications/{a['id']}").json()
    assert [x["status"] for x in d["letters"]] == ["pending"]


def test_claim_race(client, tmp_path):
    a = new_app(client)
    for _ in range(5):
        client.post(f"/api/jobs/applications/{a['id']}/letters/generate", json={"lang": "en"})
    got, lock = [], threading.Lock()

    def worker():
        while True:
            r = client.post("/api/jobs/queue/claim")
            if r.status_code == 204:
                return
            with lock:
                got.append(r.json()["letter"]["id"])

    ts = [threading.Thread(target=worker) for _ in range(4)]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert sorted(got) == sorted(set(got)) and len(got) == 5


def _age(client, letter_id: int, col: str, minutes: int):
    conn = dbm.connect(client.app.state.db_path)
    ts = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(f"UPDATE letter SET {col}=? WHERE id=?", (ts, letter_id))
    conn.commit()
    conn.close()


def test_stale_claim_reissued_and_timeout(client):
    a = new_app(client)
    l = client.post(f"/api/jobs/applications/{a['id']}/letters/generate", json={"lang": "en"}).json()
    client.post("/api/jobs/queue/claim")
    _age(client, l["id"], "claimed_at", 5)
    assert client.post("/api/jobs/queue/claim").json()["letter"]["id"] == l["id"]
    _age(client, l["id"], "requested_at", 11)
    d = client.get(f"/api/jobs/letters/{l['id']}").json()
    assert d["status"] == "failed" and d["error"]
    assert client.post("/api/jobs/queue/claim").status_code == 204
    r = client.post(f"/api/jobs/letters/{l['id']}/retry").json()
    assert r["status"] == "pending" and r["error"] is None
    assert client.post("/api/jobs/queue/claim").json()["letter"]["id"] == l["id"]
    client.post(f"/api/jobs/queue/{l['id']}/failed", json={"error": "claude timeout"})
    assert client.get(f"/api/jobs/letters/{l['id']}").json()["error"] == "claude timeout"


def test_files_upload_download_delete(client, tmp_path):
    a = new_app(client)
    r = client.put(f"/api/jobs/applications/{a['id']}/files?name=../../etc/Talent kit.pdf", content=b"%PDF-1.4 x")
    assert r.status_code == 201, r.text
    f = r.json()
    assert f["name"] == "Talent kit.pdf" and f["size"] == 10
    root = tmp_path / "files"
    stored = list(root.rglob("*.pdf"))
    assert len(stored) == 1 and stored[0].parent == root / str(a["id"])
    g = client.get(f"/api/jobs/files/{f['id']}")
    assert g.content == b"%PDF-1.4 x" and g.headers["content-disposition"].startswith("attachment")
    assert g.headers["x-content-type-options"] == "nosniff"
    img = client.put(f"/api/jobs/applications/{a['id']}/files?name=shot.png", content=b"\x89PNG").json()
    assert client.get(f"/api/jobs/files/{img['id']}").headers["content-disposition"].startswith("inline")
    assert client.put(f"/api/jobs/applications/{a['id']}/files?name=x.exe", content=b"MZ").status_code == 400
    assert client.put(f"/api/jobs/applications/{a['id']}/files?name=x.pdf", content=b"").status_code == 400
    assert len(client.get(f"/api/jobs/applications/{a['id']}").json()["attachments"]) == 2
    assert client.delete(f"/api/jobs/files/{img['id']}").status_code == 204
    client.delete(f"/api/jobs/applications/{a['id']}")
    assert not list(root.rglob("*.pdf"))
    assert client.get(f"/api/jobs/files/{f['id']}").status_code == 404


def test_file_too_big(client, monkeypatch):
    from projects_api import jobs
    monkeypatch.setattr(jobs, "MAX_FILE", 100)
    a = new_app(client)
    assert client.put(f"/api/jobs/applications/{a['id']}/files?name=a.pdf", content=b"x" * 101).status_code == 413


def test_summary_and_stats(client):
    a = new_app(client, platform="profesia")
    b = new_app(client, platform="profesia")
    new_app(client, platform="profesia", status="draft")
    client.patch(f"/api/jobs/applications/{a['id']}", json={"next_action_at": plus(-1)})
    conn = dbm.connect(client.app.state.db_path)
    conn.execute("UPDATE application SET updated_at='2026-01-01T00:00:00Z', applied_at='2026-01-01' WHERE id=?", (b["id"],))
    conn.commit()
    conn.close()
    s = client.get("/api/jobs/summary").json()
    assert [x["id"] for x in s["due"]] == [a["id"]]
    assert [x["id"] for x in s["silent"]] == [b["id"]]
    assert s["counts"]["sent"] == 2 and s["counts"]["draft"] == 1
    client.patch(f"/api/jobs/applications/{b['id']}", json={"status": "interview"})
    p = next(x for x in client.get("/api/jobs/platforms").json() if x["slug"] == "profesia")
    assert p["stats"]["sent"] == 2 and p["stats"]["replied"] == 1 and p["stats"]["interviews"] == 1
    assert p["stats"]["reply_rate"] == 50


def test_contacts_crud(client):
    c = client.post("/api/jobs/contacts", json={"name": "Zuzana Nagy", "company": "DT ITS"}).json()
    client.patch(f"/api/jobs/contacts/{c['id']}", json={"email": "z@dt.sk"})
    assert client.get("/api/jobs/contacts").json()[0]["email"] == "z@dt.sk"
    a = new_app(client, contact_id=c["id"])
    assert client.get(f"/api/jobs/applications/{a['id']}").json()["contact"]["name"] == "Zuzana Nagy"
    client.delete(f"/api/jobs/contacts/{c['id']}")
    assert client.get(f"/api/jobs/applications/{a['id']}").json()["contact"] is None


def test_chunked_upload_over_limit_is_cut(client, monkeypatch, tmp_path):
    from projects_api import jobs
    monkeypatch.setattr(jobs, "MAX_FILE", 100)
    a = new_app(client)
    sent = []

    def chunks():
        for _ in range(50):
            sent.append(1)
            yield b"x" * 10

    r = client.put(f"/api/jobs/applications/{a['id']}/files?name=a.pdf", content=chunks())
    assert r.status_code == 413
    assert not list((tmp_path / "files").rglob("*.pdf"))


def test_contact_without_email_reused_by_name_and_company(client):
    c = {"name": "Lívia Tomečková", "company": "DT ITS"}
    a = client.post("/api/jobs/applications", json={"company": "DT ITS", "title": "SRE", "contact": c}).json()
    b = client.post("/api/jobs/applications", json={"company": "DT ITS", "title": "DevOps", "contact": c}).json()
    other = client.post("/api/jobs/applications", json={"company": "VW", "title": "X", "contact": {"name": "Lívia Tomečková", "company": "VW"}}).json()
    assert a["contact_id"] == b["contact_id"] != other["contact_id"]
