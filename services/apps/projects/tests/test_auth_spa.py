from fastapi.testclient import TestClient

from projects_api.main import create_app


def test_token_mode(tmp_path):
    app = create_app(db_path=str(tmp_path / "t.db"), static_dir=str(tmp_path), auth_mode="token", auth_token="t")
    with TestClient(app) as c:
        assert c.get("/api/health").status_code == 200
        r = c.get("/api/projects")
        assert r.status_code == 401 and r.json() == {"error": "unauthorized"}
        assert c.get("/api/projects", headers={"Authorization": "Bearer t"}).status_code == 200


def test_spa_fallback(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<html>spa</html>")
    app = create_app(db_path=str(tmp_path / "t.db"), static_dir=str(tmp_path))
    with TestClient(app) as c:
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert "spa" in c.get("/p/video02").text
        assert c.get("/api/nope").status_code == 404


def test_token_compared_in_constant_time():
    import inspect
    from projects_api import main
    assert "compare_digest" in inspect.getsource(main)
