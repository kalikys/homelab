import hmac
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import db, errors, items, jobs, projects, search, sessions


def create_app(db_path: str | None = None, static_dir: str | None = None,
               auth_mode: str | None = None, auth_token: str | None = None) -> FastAPI:
    app = FastAPI(title="projects", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.db_path = db_path or os.environ.get("PROJECTS_DB", "/data/projects.db")
    Path(app.state.db_path).parent.mkdir(parents=True, exist_ok=True)
    db.init(app.state.db_path)
    conn = db.connect(app.state.db_path)
    conn.executescript(jobs.SCHEMA)
    jobs.seed(conn)
    conn.commit()
    conn.close()
    # Attachments live next to the database unless JOBS_FILES says otherwise.
    app.state.files_dir = os.environ.get("JOBS_FILES") or str(Path(app.state.db_path).parent / "files")
    errors.install(app)

    # Auth is off on the LAN; AUTH_MODE=token is the switch for later.
    mode = auth_mode or os.environ.get("AUTH_MODE", "none")
    if mode == "token":
        expected = "Bearer " + (auth_token or os.environ["AUTH_TOKEN"])

        @app.middleware("http")
        async def require_token(request: Request, call_next):
            path = request.url.path
            if path.startswith("/api/") and path != "/api/health" and not hmac.compare_digest(request.headers.get("authorization", ""), expected):
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)

    app.include_router(projects.router)
    app.include_router(items.router)
    app.include_router(sessions.router)
    app.include_router(search.router)
    app.include_router(jobs.router)

    static = Path(static_dir or os.environ.get("STATIC_DIR", "/app/static"))
    index = static / "index.html"
    if (static / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=static / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/") or not index.is_file():
            raise HTTPException(404, "not found")
        file = static / path
        if path and file.is_file() and static in file.resolve().parents:
            return FileResponse(file)
        return FileResponse(index)

    return app
