import json
import sqlite3
import urllib.request


def post(url, path, body):
    req = urllib.request.Request(url + path, json.dumps(body).encode(), {"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req) as r:
        return json.load(r)


def test_write_is_committed_when_the_response_arrives(live_url, tmp_path):
    """The UI chains requests (create a contact, then link it): the first write must be visible at once."""
    db = sqlite3.connect(tmp_path / "live.db")
    for i in range(30):
        c = post(live_url, "/api/jobs/contacts", {"name": f"n{i}"})
        assert db.execute("SELECT 1 FROM contact WHERE id=?", (c["id"],)).fetchone(), f"not committed on try {i}"
        a = post(live_url, "/api/jobs/applications", {"company": "A", "title": "B", "contact_id": c["id"]})
        assert a["contact_id"] == c["id"]
