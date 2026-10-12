import os
from pathlib import Path

from fastapi import FastAPI

from . import db, errors, items, projects, search, sessions


def create_app(db_path: str | None = None, static_dir: str | None = None,
               auth_mode: str | None = None, auth_token: str | None = None) -> FastAPI:
    app = FastAPI(title="projects", docs_url="/api/docs", openapi_url="/api/openapi.json")
    app.state.db_path = db_path or os.environ.get("PROJECTS_DB", "/data/projects.db")
    Path(app.state.db_path).parent.mkdir(parents=True, exist_ok=True)
    db.init(app.state.db_path)
    errors.install(app)
    app.include_router(projects.router)
    app.include_router(items.router)
    app.include_router(sessions.router)
    app.include_router(search.router)
    return app
