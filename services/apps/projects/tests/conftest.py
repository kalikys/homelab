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
