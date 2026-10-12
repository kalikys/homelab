import json
import sys
import urllib.request
from pathlib import Path


def get(url, path):
    with urllib.request.urlopen(url + path) as r:
        return json.loads(r.read())


def items(url, slug):
    return get(url, f"/api/projects/{slug}")["items"]


def by_title(url, slug, title):
    return next(i for i in items(url, slug) if i["title"] == title)


def test_new_add_show(pj_env, capsys, tmp_path):
    pj, home, url = pj_env
    d = tmp_path / "work" / "video02"
    d.mkdir(parents=True)
    assert pj.main(["new", "video02", "Видео 02", "--area", "youtube", "-m", "сценарий", "-m", "монтаж",
                    "--path", str(d)]) == 0
    assert pj.main(["add", "-p", "video02", "feature", "Озвучка", "-s", "in_progress"]) == 0
    f = by_title(url, "video02", "Озвучка")
    assert pj.main(["add", "-p", "video02", "todo", "Выбрать голос", "--parent", str(f["id"]), "-o", "user"]) == 0
    assert pj.main(["add", "-p", "video02", "todo", "Свести звук", "--parent", str(f["id"])]) == 0
    assert pj.main(["add", "-p", "video02", "artifact", "Рендер v6", "-l", str(d / "v6.mp4"), "-s", "final"]) == 0
    assert pj.main(["add", "-p", "video02", "decision", "ElevenLabs вместо Speechify", "-b", "дешевле на 40%"]) == 0
    assert pj.main(["done", str(by_title(url, "video02", "сценарий")["id"])]) == 0
    assert pj.main(["next", "-p", "video02", "свести звук"]) == 0
    capsys.readouterr()
    assert pj.main(["show", "-p", "video02"]) == 0
    out = capsys.readouterr().out
    for s in ["Видео 02", "50%", "Next: свести звук", "Waiting on the user", "Выбрать голос", "[x] #",
              "Озвучка [in_progress] 0%", "Свести звук", "Рендер v6 [final]", str(d / "v6.mp4"),
              "ElevenLabs вместо Speechify"]:
        assert s in out, s


def test_add_prints_id_and_relations(pj_env, capsys):
    pj, home, url = pj_env
    pj.main(["new", "a", "A"])
    capsys.readouterr()
    pj.main(["add", "-p", "a", "feature", "F"])
    fid = int(capsys.readouterr().out.split()[0].lstrip("#"))
    assert pj.main(["add", "-p", "a", "plan", "План F", "-l", "https://x.io/plan", "--rel", f"implements:{fid}"]) == 0
    rel = get(url, f"/api/items/{fid}")["relations"]
    assert rel[0]["direction"] == "in" and rel[0]["kind"] == "implements" and rel[0]["item"]["title"] == "План F"
    pid = rel[0]["item"]["id"]
    assert pj.main(["rel", str(pid), "relates", str(fid)]) == 0
    assert len(get(url, f"/api/items/{fid}")["relations"]) == 2


def test_bad_rel_spec_is_usage_error(pj_env):
    pj, home, url = pj_env
    import pytest
    with pytest.raises(SystemExit):
        pj.main(["add", "-p", "a", "note", "x", "--rel", "implements"])


def test_set_and_item(pj_env, capsys):
    pj, home, url = pj_env
    pj.main(["new", "a", "A"])
    pj.main(["add", "-p", "a", "todo", "t"])
    tid = by_title(url, "a", "t")["id"]
    assert pj.main(["set", str(tid), "-s", "doing", "-o", "user", "-b", "подробности"]) == 0
    t = by_title(url, "a", "t")
    assert t["status"] == "doing" and t["owner"] == "user" and t["body"] == "подробности"
    capsys.readouterr()
    assert pj.main(["item", str(tid)]) == 0
    out = capsys.readouterr().out
    assert "#%d todo [doing]" % tid in out and "подробности" in out


def test_api_error_exit_1(pj_env, capsys):
    pj, home, url = pj_env
    pj.main(["new", "a", "A"])
    assert pj.main(["add", "-p", "a", "todo", "x", "-s", "published"]) == 1
    assert "400" in capsys.readouterr().err


def test_project_resolved_from_cwd(pj_env, tmp_path, monkeypatch):
    pj, home, url = pj_env
    d = tmp_path / "work" / "site"
    (d / "sub").mkdir(parents=True)
    pj.main(["new", "site", "Сайт", "--path", str(d)])
    monkeypatch.chdir(d / "sub")
    assert pj.main(["add", "note", "задеплоил"]) == 0
    assert items(url, "site")[0]["title"] == "задеплоил"


def test_no_project_for_cwd_errors(pj_env, tmp_path, monkeypatch, capsys):
    pj, home, url = pj_env
    monkeypatch.chdir(tmp_path)
    assert pj.main(["add", "note", "x"]) == 2
    assert "pj new" in capsys.readouterr().err


def test_offline_write_goes_to_outbox(pj_env, monkeypatch, capsys):
    pj, home, url = pj_env
    monkeypatch.setenv("PJ_URL", "http://127.0.0.1:9")
    assert pj.main(["add", "-p", "a", "note", "офлайн", "--rel", "relates:1"]) == 0
    err = capsys.readouterr().err
    assert "queued" in err and "--rel skipped" in err
    lines = (home / "outbox.jsonl").read_text().splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["path"] == "/api/projects/a/items"


def test_outbox_replay_is_ordered_and_idempotent(pj_env, monkeypatch):
    pj, home, url = pj_env
    pj.main(["new", "a", "A"])
    monkeypatch.setenv("PJ_URL", "http://127.0.0.1:9")
    pj.main(["add", "-p", "a", "note", "первое"])
    pj.main(["add", "-p", "a", "note", "второе"])
    lines = (home / "outbox.jsonl").read_text().splitlines()
    (home / "outbox.jsonl").write_text("\n".join(lines + [lines[0]]) + "\n")  # a replay that already reached the server
    monkeypatch.setenv("PJ_URL", url)
    assert pj.main(["list"]) == 0
    assert [i["title"] for i in sorted(items(url, "a"), key=lambda i: i["id"])] == ["первое", "второе"]
    assert not (home / "outbox.jsonl").exists()


def test_loc():
    sys.path.insert(0, str(Path(__file__).parents[1] / "client"))
    import pj
    assert pj.loc("https://nodesize.kalik8s.com") == "https://nodesize.kalik8s.com"
    assert pj.loc("~/prj/x") == str(Path.home() / "prj" / "x")


def test_session_guessed_and_linked(pj_env, tmp_path, monkeypatch):
    pj, home, url = pj_env
    work = tmp_path / "w" / "x.y"
    (work / "deep").mkdir(parents=True)
    tdir = tmp_path / "claude-projects" / pj.encode_dir(str(work.resolve()))
    tdir.mkdir(parents=True)
    (tdir / "abc-123.jsonl").write_text("{}\n")
    assert pj.guess_session(str(work / "deep")) == "abc-123"
    pj.main(["new", "a", "A", "--path", str(work)])
    monkeypatch.chdir(work / "deep")
    pj.main(["add", "note", "n"])
    nid = items(url, "a")[0]["id"]
    assert [s["id"] for s in get(url, f"/api/items/{nid}")["sessions"]] == ["abc-123"]
    monkeypatch.setenv("PJ_SESSION", "override-1")
    pj.main(["done", str(nid)])
    assert {s["id"] for s in get(url, f"/api/items/{nid}")["sessions"]} == {"abc-123", "override-1"}


def test_seed(pj_env, tmp_path, capsys):
    pj, home, url = pj_env
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"projects": [{
        "slug": "nodesize", "title": "NodeSize", "area": "sites", "summary": "калькулятор", "next_step": "AdSense",
        "paths": [str(tmp_path)],
        "items": [
            {"type": "milestone", "title": "сайт", "status": "done", "ts": "2026-10-11T12:00:00Z"},
            {"type": "milestone", "title": "AdSense"},
            {"type": "feature", "title": "HPA"},
            {"type": "todo", "title": "запросить ревью AdSense", "owner": "user", "parent": "HPA"},
            {"type": "artifact", "title": "Сайт", "location": "https://nodesize.kalik8s.com", "status": "published"},
        ],
    }]}, ensure_ascii=False))
    assert pj.main(["seed", str(seed)]) == 0
    assert pj.main(["seed", str(seed)]) == 0
    assert "skip nodesize" in capsys.readouterr().out
    card = get(url, "/api/projects/nodesize")
    assert card["progress"] == 50 and card["open_user_todos"] == 1
    assert by_title(url, "nodesize", "запросить ревью AdSense")["parent_id"] == by_title(url, "nodesize", "HPA")["id"]
    assert by_title(url, "nodesize", "Сайт")["location_kind"] == "url"
    assert by_title(url, "nodesize", "сайт")["created_at"] == "2026-10-11T12:00:00Z"
    assert get(url, "/api/resolve?cwd=" + str(tmp_path.resolve()))["project"] == "nodesize"


def test_claude_code_session_id_wins_over_guess(pj_env, monkeypatch):
    pj, home, url = pj_env
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "cc-session-7")
    assert pj.current_session() == "cc-session-7"
    monkeypatch.setenv("PJ_SESSION", "explicit")
    assert pj.current_session() == "explicit"


# --- final review fixes ---------------------------------------------------

def test_5xx_queues_instead_of_dropping(pj_env, monkeypatch, capsys):
    import io
    import urllib.error
    pj, home, url = pj_env
    pj.main(["new", "a", "A"])
    real = urllib.request.urlopen
    state = {"failed": False}

    def flaky(req, timeout=None):
        if req.get_method() != "GET" and not state["failed"]:
            state["failed"] = True
            raise urllib.error.HTTPError(req.full_url, 502, "Bad Gateway", {}, io.BytesIO(b"<html>502</html>"))
        return real(req, timeout=timeout)

    monkeypatch.setattr(pj.urllib.request, "urlopen", flaky)
    assert pj.main(["add", "-p", "a", "note", "во время деплоя"]) == 0
    assert "queued" in capsys.readouterr().err
    monkeypatch.setattr(pj.urllib.request, "urlopen", real)
    pj.main(["list"])
    assert [i["title"] for i in items(url, "a")] == ["во время деплоя"]


def test_offline_without_project_flag_is_queued_and_resolved_later(pj_env, tmp_path, monkeypatch):
    pj, home, url = pj_env
    d = tmp_path / "work" / "site"
    d.mkdir(parents=True)
    pj.main(["new", "site", "Сайт", "--path", str(d)])
    monkeypatch.chdir(d)
    monkeypatch.setenv("PJ_URL", "http://127.0.0.1:9")
    assert pj.main(["add", "note", "без -p офлайн"]) == 0
    monkeypatch.setenv("PJ_URL", url)
    monkeypatch.chdir(tmp_path)
    pj.main(["list"])
    assert [i["title"] for i in items(url, "site")] == ["без -p офлайн"]


def test_corrupt_outbox_line_is_skipped(pj_env, capsys):
    pj, home, url = pj_env
    pj.main(["new", "a", "A"])
    good = json.dumps({"method": "POST", "path": "/api/projects/a/items", "body": {"type": "note", "title": "ok", "uid": "u-ok"}})
    (home / "outbox.jsonl").write_text(good + "\n" + '{"method": "POST", "pa' + "\n")
    assert pj.main(["list"]) == 0
    assert [i["title"] for i in items(url, "a")] == ["ok"]
    assert (home / "outbox.bad").read_text().startswith('{"method": "POST", "pa')
    assert "corrupt" in capsys.readouterr().err


def test_session_end_survives_bad_config(pj_env, monkeypatch):
    pj, home, url = pj_env
    (home / "config.toml").write_text("url = [broken")
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO("{}"))
    assert pj.main(["session-end"]) == 0


def test_seed_keeps_last_activity_date(pj_env, tmp_path):
    pj, home, url = pj_env
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps({"projects": [{"slug": "old", "title": "Old", "items": [
        {"type": "milestone", "title": "a", "status": "done", "ts": "2026-09-03T12:00:00Z"},
        {"type": "todo", "title": "без даты"}]}]}, ensure_ascii=False))
    pj.main(["seed", str(seed)])
    assert get(url, "/api/projects/old")["updated_at"] == "2026-09-03T12:00:00Z"


def _context(pj, monkeypatch, capsys, cwd):
    import io
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps({"session_id": "s", "cwd": str(cwd), "hook_event_name": "SessionStart"})))
    assert pj.main(["context"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    return out["hookSpecificOutput"]["additionalContext"]


def test_context_for_mapped_folder_shows_project(pj_env, tmp_path, monkeypatch, capsys):
    pj, home, url = pj_env
    d = tmp_path / "site"
    d.mkdir()
    pj.main(["new", "site", "Сайт", "--path", str(d)])
    pj.main(["next", "-p", "site", "задеплоить"])
    capsys.readouterr()
    ctx = _context(pj, monkeypatch, capsys, d)
    assert "Сайт" in ctx and "задеплоить" in ctx and "project-log" in ctx


def test_context_for_unmapped_folder_lists_projects(pj_env, tmp_path, monkeypatch, capsys):
    pj, home, url = pj_env
    pj.main(["new", "a", "Проект А"])
    capsys.readouterr()
    ctx = _context(pj, monkeypatch, capsys, tmp_path)
    assert "a" in ctx and "Проект А" in ctx and "-p <slug>" in ctx


def test_context_offline_still_reminds(pj_env, tmp_path, monkeypatch, capsys):
    pj, home, url = pj_env
    monkeypatch.setenv("PJ_URL", "http://127.0.0.1:9")
    ctx = _context(pj, monkeypatch, capsys, tmp_path)
    assert "project-log" in ctx
