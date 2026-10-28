def add(client, type_, title, slug="video02", **kw):
    r = client.post(f"/api/projects/{slug}/items", json={"type": type_, "title": title, **kw})
    assert r.status_code in (200, 201), r.json()
    return r.json()


def test_defaults_per_type(client, project):
    assert add(client, "feature", "Озвучка")["status"] == "planned"
    t = add(client, "todo", "Свести звук")
    assert t["status"] == "open" and t["owner"] == "claude"
    assert add(client, "decision", "ElevenLabs")["status"] == "logged"
    assert add(client, "feature", "Монтаж")["owner"] is None


def test_status_validated_per_type(client, project):
    r = client.post("/api/projects/video02/items", json={"type": "todo", "title": "x", "status": "published"})
    assert r.status_code == 400 and "open, doing, done, dropped" in r.json()["error"]
    assert add(client, "artifact", "Рендер", status="published")["done_at"]
    t = add(client, "todo", "y")
    assert client.patch(f"/api/items/{t['id']}", json={"status": "final"}).status_code == 400
    assert client.post("/api/projects/video02/items", json={"type": "bogus", "title": "x"}).status_code == 400


def test_owner_only_for_todo(client, project):
    r = client.post("/api/projects/video02/items", json={"type": "feature", "title": "x", "owner": "user"})
    assert r.status_code == 400
    f = add(client, "feature", "f")
    assert client.patch(f"/api/items/{f['id']}", json={"owner": "user"}).status_code == 400


def test_parent_must_be_same_project(client, project):
    client.post("/api/projects", json={"slug": "other", "title": "O"})
    f = add(client, "feature", "чужая", slug="other")
    r = client.post("/api/projects/video02/items", json={"type": "todo", "title": "x", "parent_id": f["id"]})
    assert r.status_code == 400
    mine = add(client, "feature", "своя")
    assert client.patch(f"/api/items/{mine['id']}", json={"parent_id": mine["id"]}).status_code == 400


def test_feature_progress_from_child_todos(client, project):
    f = add(client, "feature", "Озвучка")
    a = add(client, "todo", "a", parent_id=f["id"])
    add(client, "todo", "b", parent_id=f["id"])
    c = add(client, "todo", "c", parent_id=f["id"])
    client.post(f"/api/items/{a['id']}/done", json={})
    client.patch(f"/api/items/{c['id']}", json={"status": "dropped"})
    feat = next(i for i in client.get("/api/projects/video02").json()["items"] if i["id"] == f["id"])
    assert feat["progress"] == 50
    assert [ch["title"] for ch in client.get(f"/api/items/{f['id']}").json()["children"]] == ["a", "b", "c"]


def test_project_progress_from_milestones(client):
    client.post("/api/projects", json={"slug": "v", "title": "V", "milestones": ["a", "b", "c", "d"]})
    ms = client.get("/api/projects/v").json()["items"]
    client.post(f"/api/items/{ms[0]['id']}/done", json={})
    assert client.get("/api/projects/v").json()["progress"] == 25


def test_done_endpoint_per_type(client, project):
    a = add(client, "artifact", "Рендер")
    assert client.post(f"/api/items/{a['id']}/done", json={}).json()["status"] == "final"
    t = add(client, "todo", "t")
    r = client.post(f"/api/items/{t['id']}/done", json={}).json()
    assert r["status"] == "done" and r["done_at"]
    assert client.patch(f"/api/items/{t['id']}", json={"status": "open"}).json()["done_at"] is None


def test_uid_idempotent(client, project):
    a = client.post("/api/projects/video02/items", json={"type": "note", "title": "n", "uid": "u1"})
    b = client.post("/api/projects/video02/items", json={"type": "note", "title": "n", "uid": "u1"})
    assert a.status_code == 201 and b.status_code == 200 and a.json()["id"] == b.json()["id"]
    assert len(client.get("/api/projects/video02").json()["items"]) == 1


def test_auto_events(client, project):
    t = add(client, "todo", "Свести звук")
    client.post(f"/api/items/{t['id']}/done", json={})
    client.patch(f"/api/items/{t['id']}", json={"body": "готово в Reaper"})
    client.patch(f"/api/items/{t['id']}", json={"position": 5})  # no event for reordering
    ev = client.get("/api/projects/video02").json()["events"]
    assert [e["kind"] for e in ev] == ["edited", "status", "created"]
    assert ev[2]["text"] == "Задача «Свести звук»" and ev[2]["item_type"] == "todo"
    assert ev[1]["text"].endswith("открыто → готово")
    assert len(client.get(f"/api/items/{t['id']}").json()["events"]) == 3


def test_relations(client, project):
    f = add(client, "feature", "Озвучка")
    p = add(client, "plan", "План озвучки", location="/x/plan.md")
    assert client.post(f"/api/items/{p['id']}/relations", json={"to_id": f["id"], "kind": "implements"}).status_code == 201
    client.post(f"/api/items/{p['id']}/relations", json={"to_id": f["id"], "kind": "implements"})  # duplicate ignored
    rel = client.get(f"/api/items/{f['id']}").json()["relations"]
    assert rel == [{"direction": "in", "kind": "implements",
                    "item": {"id": p["id"], "type": "plan", "title": "План озвучки", "status": "draft", "project": "video02"}}]
    assert client.post(f"/api/items/{p['id']}/relations", json={"to_id": p["id"], "kind": "relates"}).status_code == 400
    assert client.post(f"/api/items/{p['id']}/relations", json={"to_id": 999, "kind": "relates"}).status_code == 404
    assert client.delete(f"/api/items/{p['id']}/relations/implements/{f['id']}").status_code == 204
    assert client.get(f"/api/items/{f['id']}").json()["relations"] == []


def test_location_kind(client, project):
    assert add(client, "artifact", "repo", location="https://github.com/kalikys/homelab")["location_kind"] == "repo"
    assert add(client, "artifact", "art", location="https://claude.ai/artifact/abc")["location_kind"] == "artifact"
    assert add(client, "artifact", "site", location="https://nodesize.kalik8s.com")["location_kind"] == "url"
    assert add(client, "artifact", "file", location="/x/v6.mp4")["location_kind"] == "path"
    assert add(client, "note", "none")["location_kind"] is None


def test_user_todos(client, project):
    add(client, "todo", "нажать Publish app", owner="user")
    done = add(client, "todo", "старое", owner="user")
    client.post(f"/api/items/{done['id']}/done", json={})
    add(client, "todo", "моё", owner="claude")
    todos = client.get("/api/todos", params={"owner": "user"}).json()
    assert [t["title"] for t in todos] == ["нажать Publish app"] and todos[0]["project_title"] == "Видео 02"
    p = client.get("/api/projects").json()[0]
    assert p["open_user_todos"] == 1 and p["open_todos"] == 1


def test_item_404_and_delete(client, project):
    assert client.get("/api/items/999").status_code == 404
    n = add(client, "note", "черновик")
    assert client.delete(f"/api/items/{n['id']}").status_code == 204
    assert client.get(f"/api/items/{n['id']}").status_code == 404
    assert client.get("/api/projects/video02").json()["events"][0]["kind"] == "deleted"


def test_session_link_on_write(client, project):
    t = add(client, "todo", "t", session_id="chat-1")
    client.post(f"/api/items/{t['id']}/done", json={"session_id": "chat-1"})
    client.patch(f"/api/items/{t['id']}", json={"title": "t2", "session_id": "chat-2"})
    sessions = client.get(f"/api/items/{t['id']}").json()["sessions"]
    assert {s["id"]: sorted(s["roles"]) for s in sessions} == {"chat-1": ["created", "updated"], "chat-2": ["updated"]}
    assert next(i for i in client.get("/api/projects/video02").json()["items"])["session_count"] == 2
