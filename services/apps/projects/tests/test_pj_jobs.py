import json
import urllib.request


def get(url, path):
    with urllib.request.urlopen(url + path) as r:
        return json.loads(r.read())


def test_job_add_letter_status_show(pj_env, capsys, tmp_path):
    pj, home, url = pj_env
    text = tmp_path / "vacancy.txt"
    text.write_text("Kubernetes on bare metal")
    letter = tmp_path / "letter.md"
    letter.write_text("Hello DT, short letter.")
    assert pj.main(["job", "add", "DT ITS", "DevOps Expert", "--platform", "profesia", "--url", "https://x/1",
                    "--fit", "4", "--text-file", str(text), "--letter-file", str(letter), "--letter-lang", "en"]) == 0
    out = capsys.readouterr().out
    aid = int(out.split()[0].lstrip("#"))
    d = get(url, f"/api/jobs/applications/{aid}")
    assert d["status"] == "sent" and d["vacancy_text"] == "Kubernetes on bare metal" and d["fit"] == 4
    assert d["letters"][0]["body"] == "Hello DT, short letter." and d["letters"][0]["sent"] is True

    assert pj.main(["job", "add", "Olmait", "DevSecOps", "--inbound", "--contact", "Tamuna", "--contact-email",
                    "t@olmait.ge", "--contact-tg", "@tamuna", "--platform", "linkedin"]) == 0
    bid = int(capsys.readouterr().out.split()[0].lstrip("#"))
    b = get(url, f"/api/jobs/applications/{bid}")
    assert b["status"] == "inbound" and b["contact"]["telegram"] == "@tamuna"

    assert pj.main(["job", "status", str(aid), "interview", "--note", "созвон в пятницу"]) == 0
    assert get(url, f"/api/jobs/applications/{aid}")["status"] == "interview"

    assert pj.main(["job", "letter", str(bid), "--file", str(letter), "--lang", "ru"]) == 0
    assert len(get(url, f"/api/jobs/applications/{bid}")["letters"]) == 1

    capsys.readouterr()
    assert pj.main(["job", "list"]) == 0
    out = capsys.readouterr().out
    assert "DT ITS" in out and "Olmait" in out and "интервью" in out
    assert pj.main(["job", "show", str(aid)]) == 0
    out = capsys.readouterr().out
    assert "DevOps Expert" in out and "Hello DT" in out and "созвон в пятницу" in out


def test_job_add_offline_is_queued(pj_env, monkeypatch, capsys):
    pj, home, url = pj_env
    monkeypatch.setenv("PJ_URL", "http://127.0.0.1:9")
    assert pj.main(["job", "add", "Acme", "SRE"]) == 0
    assert "queued" in capsys.readouterr().err
    monkeypatch.setenv("PJ_URL", url)
    assert pj.main(["job", "list"]) == 0
    assert "Acme" in capsys.readouterr().out
