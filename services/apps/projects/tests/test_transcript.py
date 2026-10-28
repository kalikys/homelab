import io
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "client"))
import pj  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "transcript.jsonl"


def test_parse_transcript_counts_only_human_turns():
    t = pj.parse_transcript(FIX)
    assert t["user_turns"] == 3  # /clear wrapper counts as a turn, compact summary and tool results don't
    assert t["first_prompt"] == "сделай дашборд для проектов"
    assert t["title"] == "Дашборд проектов (v2)"
    assert t["started_at"] == "2026-10-12T09:00:00.000Z" and t["ended_at"] == "2026-10-12T09:32:00.000Z"
    assert t["files_changed"] == ["/x/homeserver/spec.md"]


def test_parse_large_transcript_fast(tmp_path):
    big = tmp_path / "big.jsonl"
    filler = json.dumps({"type": "assistant", "timestamp": "2026-10-12T10:00:00.000Z",
                         "message": {"role": "assistant", "content": [{"type": "text", "text": "x" * 2000}]}})
    big.write_text(FIX.read_text() + (filler + "\n") * 50_000)
    t0 = time.time()
    t = pj.parse_transcript(big)
    assert time.time() - t0 < 3
    assert t["ended_at"] == "2026-10-12T10:00:00.000Z"


def test_parse_tolerates_broken_lines(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text(FIX.read_text() + "{not json\n")
    assert pj.parse_transcript(f)["user_turns"] == 3


def test_short_session_skipped(tmp_path):
    f = tmp_path / "t.jsonl"
    f.write_text("\n".join(FIX.read_text().splitlines()[:3]) + "\n")
    assert pj.session_payload("s", "/x", str(f)) is None


def test_session_end_posts(pj_env, monkeypatch):
    pjm, home, url = pj_env
    hook = {"session_id": "s-1", "transcript_path": str(FIX), "cwd": "/x/homeserver", "hook_event_name": "SessionEnd"}
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(hook)))
    assert pjm.main(["session-end"]) == 0
    import urllib.request
    rows = json.loads(urllib.request.urlopen(url + "/api/sessions?unsorted=1").read())
    assert rows[0]["id"] == "s-1" and rows[0]["title"] == "Дашборд проектов (v2)" and rows[0]["user_turns"] == 3


def test_session_end_never_fails(pj_env, monkeypatch):
    pjm, home, url = pj_env
    monkeypatch.setattr(sys, "stdin", io.StringIO("garbage"))
    assert pjm.main(["session-end"]) == 0


def test_backfill(pj_env, tmp_path):
    pjm, home, url = pj_env
    root = tmp_path / "claude-projects" / "-x-homeserver"
    root.mkdir(parents=True)
    (root / "s-9.jsonl").write_text(FIX.read_text())
    assert pjm.main(["backfill", "--root", str(tmp_path / "claude-projects")]) == 0
    import urllib.request
    rows = json.loads(urllib.request.urlopen(url + "/api/sessions?unsorted=1").read())
    assert [r["id"] for r in rows] == ["s-9"] and rows[0]["cwd"] == "/x/homeserver"
