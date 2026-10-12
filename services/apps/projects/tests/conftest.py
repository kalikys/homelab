import pytest
from fastapi.testclient import TestClient

from projects_api.main import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), static_dir=str(tmp_path / "nostatic"))
    with TestClient(app) as c:
        yield c


@pytest.fixture
def project(client):
    r = client.post("/api/projects", json={"slug": "video02", "title": "Видео 02", "area": "youtube"})
    assert r.status_code == 201
    return r.json()


import socket
import sys
import threading
import time
from pathlib import Path

import uvicorn


@pytest.fixture
def live_url(tmp_path):
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    app = create_app(db_path=str(tmp_path / "live.db"), static_dir=str(tmp_path / "nostatic"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    t.join(5)


@pytest.fixture
def pj_env(tmp_path, monkeypatch, live_url):
    sys.path.insert(0, str(Path(__file__).parents[1] / "client"))
    home = tmp_path / "pjhome"
    home.mkdir()
    monkeypatch.setenv("PJ_HOME", str(home))
    monkeypatch.setenv("PJ_URL", live_url)
    monkeypatch.setenv("PJ_CLAUDE_PROJECTS", str(tmp_path / "claude-projects"))
    monkeypatch.delenv("PJ_SESSION", raising=False)
    monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
    import pj
    return pj, home, live_url
