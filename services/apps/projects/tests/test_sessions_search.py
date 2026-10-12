def mk(client, slug, title="T"):
    assert client.post("/api/projects", json={"slug": slug, "title": title}).status_code == 201


def test_resolve_boundary_and_longest_prefix(client):
    mk(client, "home")
    mk(client, "nodesize")
    client.post("/api/path-map", json={"prefix": "/x/homeserver", "project": "home"})
    client.post("/api/path-map", json={"prefix": "/x/homeserver/nodesize/", "project": "nodesize"})
    r = lambda cwd: client.get("/api/resolve", params={"cwd": cwd}).json()["project"]
    assert r("/x/homeserver/nodesize/site") == "nodesize"
    assert r("/x/homeserver/nodesize") == "nodesize"
    assert r("/x/homeserver/nodesize-old") == "home"
    assert r("/x/homeserverx") is None


def test_path_map_unknown_project_404(client):
    assert client.post("/api/path-map", json={"prefix": "/a", "project": "nope"}).status_code == 404


def test_session_resolves_project_from_cwd(client):
    mk(client, "nodesize")
    client.post("/api/path-map", json={"prefix": "/x/nodesize", "project": "nodesize"})
    s = client.post("/api/sessions", json={"id": "s1", "cwd": "/x/nodesize/web", "first_prompt": "привет",
                                           "ended_at": "2026-10-12T10:00:00Z", "user_turns": 5}).json()
    assert s["project"] == "nodesize"
    assert client.get("/api/projects/nodesize").json()["sessions"][0]["id"] == "s1"


def test_session_upsert_keeps_first_prompt_and_project(client):
    mk(client, "a")
    client.post("/api/sessions", json={"id": "s1", "cwd": "/nowhere", "first_prompt": "первый", "user_turns": 3})
    client.patch("/api/sessions/s1", json={"project": "a"})
    s = client.post("/api/sessions", json={"id": "s1", "cwd": "/nowhere", "first_prompt": "другой",
                                           "user_turns": 9, "ended_at": "2026-10-12T11:00:00Z"}).json()
    assert s["first_prompt"] == "первый" and s["project"] == "a" and s["user_turns"] == 9


def test_item_links_current_chat_and_hook_keeps_project(client):
    mk(client, "v")
    it = client.post("/api/projects/v/items", json={"type": "todo", "title": "t", "session_id": "chat-1"}).json()
    card = client.get("/api/projects/v").json()
    assert [s["id"] for s in card["sessions"]] == ["chat-1"]
    s = client.post("/api/sessions", json={"id": "chat-1", "cwd": "/unmapped", "title": "Дашборд",
                                           "started_at": "2000-01-01T00:00:00Z", "ended_at": "2099-01-01T00:00:00Z",
                                           "user_turns": 4}).json()
    assert s["project"] == "v" and s["title"] == "Дашборд" and s["started_at"] == "2000-01-01T00:00:00Z"
    detail = client.get("/api/sessions/chat-1").json()
    assert detail["items"] == [{"id": it["id"], "type": "todo", "title": "t", "status": "open", "project": "v",
                                "roles": ["created"]}]


def test_unsorted_sessions(client):
    client.post("/api/sessions", json={"id": "s1", "cwd": "/nowhere", "ended_at": "2026-10-01T00:00:00Z"})
    client.post("/api/sessions", json={"id": "s2", "cwd": "/nowhere", "ended_at": "2026-10-02T00:00:00Z"})
    assert [s["id"] for s in client.get("/api/sessions", params={"unsorted": 1}).json()] == ["s2", "s1"]


def test_old_session_does_not_bump_updated_at(client):
    mk(client, "a")
    before = client.get("/api/projects/a").json()["updated_at"]
    client.post("/api/sessions", json={"id": "old", "project": "a", "ended_at": "2026-08-01T00:00:00Z"})
    assert client.get("/api/projects/a").json()["updated_at"] == before


def test_session_errors(client):
    assert client.post("/api/sessions", json={"id": "s", "project": "nope"}).status_code == 404
    assert client.get("/api/sessions/nope").status_code == 404


def test_search_cyrillic_case_insensitive(client):
    mk(client, "v", "Видео")
    client.post("/api/projects/v/items", json={"type": "finding", "title": "Монтаж готов", "body": "в DaVinci"})
    client.post("/api/projects/v/items", json={"type": "artifact", "title": "Рендер", "location": "/x/50%_done.mp4"})
    res = client.get("/api/search", params={"q": "монтаж"}).json()
    assert res[0]["project"] == "v" and res[0]["hits"][0]["type"] == "finding"
    assert res[0]["hits"][0]["text"].startswith("Монтаж готов")
    assert client.get("/api/search", params={"q": "davinci"}).json()[0]["hits"][0]["type"] == "finding"
    assert [h["type"] for h in client.get("/api/search", params={"q": "50%_"}).json()[0]["hits"]] == ["artifact"]
    assert client.get("/api/search", params={"q": "  "}).json() == []


def test_session_project_from_changed_files_when_cwd_unmapped(client):
    mk(client, "nodesize")
    mk(client, "toolsites")
    client.post("/api/path-map", json={"prefix": "/x/nodesize", "project": "nodesize"})
    client.post("/api/path-map", json={"prefix": "/x/toolsites", "project": "toolsites"})
    s = client.post("/api/sessions", json={"id": "root-chat", "cwd": "/x", "files_changed": [
        "/x/nodesize/build.py", "/x/nodesize/site/a.html", "/x/toolsites/README.md", "/elsewhere/notes.md"]}).json()
    assert s["project"] == "nodesize"
    none = client.post("/api/sessions", json={"id": "no-files", "cwd": "/x", "files_changed": ["/elsewhere/a"]}).json()
    assert none["project"] is None
