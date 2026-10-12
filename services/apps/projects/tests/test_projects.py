def test_health(client):
    assert client.get("/api/health").json() == {"ok": True}


def test_create_and_get(client, project):
    assert project["slug"] == "video02" and project["progress"] is None
    assert project["open_user_todos"] == 0
    card = client.get("/api/projects/video02").json()
    assert card["title"] == "Видео 02"
    assert card["items"] == [] and card["events"] == [] and card["sessions"] == []


def test_create_with_milestones(client):
    r = client.post("/api/projects", json={"slug": "s1", "title": "S", "milestones": ["a", "b"]})
    assert r.json()["progress"] == 0
    items = client.get("/api/projects/s1").json()["items"]
    assert [(i["type"], i["title"], i["status"]) for i in items] == [("milestone", "a", "open"), ("milestone", "b", "open")]


def test_duplicate_slug_409(client, project):
    r = client.post("/api/projects", json={"slug": "video02", "title": "x"})
    assert r.status_code == 409 and "error" in r.json()


def test_bad_slug_400(client):
    r = client.post("/api/projects", json={"slug": "Bad Slug", "title": "x"})
    assert r.status_code == 400 and "error" in r.json()


def test_unknown_404(client):
    r = client.get("/api/projects/nope")
    assert r.status_code == 404 and r.json() == {"error": "project not found: nope"}


def test_patch_and_clear_override(client, project):
    r = client.patch("/api/projects/video02", json={"next_step": "монтаж", "progress_override": 70})
    assert r.json()["next_step"] == "монтаж" and r.json()["progress"] == 70
    r = client.patch("/api/projects/video02", json={"progress_override": None})
    assert r.json()["progress"] is None
    assert client.patch("/api/projects/video02", json={"title": None}).status_code == 400


def test_list_sorted_by_activity(client):
    client.post("/api/projects", json={"slug": "a", "title": "A"})
    client.post("/api/projects", json={"slug": "b", "title": "B"})
    client.patch("/api/projects/a", json={"summary": "touched"})
    assert client.get("/api/projects").json()[0]["slug"] == "a"


def test_delete(client, project):
    assert client.delete("/api/projects/video02").status_code == 204
    assert client.get("/api/projects/video02").status_code == 404
