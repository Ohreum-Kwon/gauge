from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from app.config import get_settings
from app.routers import audit_log, auth, labeling, projects, quality, review, users


def create_app() -> FastAPI:
    app = FastAPI(
        title="Gauge",
        description="Data labeling with statistical process control on labeler quality.",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=get_settings().cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    api = APIRouter(prefix="/api")
    for module in (auth, users, projects, labeling, quality, review, audit_log):
        api.include_router(module.router)

    @api.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(api)
    if dist := get_settings().frontend_dist:
        _serve_frontend(app, dist.resolve())
    return app


def _serve_frontend(app: FastAPI, dist: Path) -> None:
    """Serve the built single-page app: real files as they are, any other path as
    index.html so the client-side router can handle it."""
    index = dist / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str) -> FileResponse:
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
        file = (dist / path).resolve()
        if path and file.is_relative_to(dist) and file.is_file():
            return FileResponse(file)
        return FileResponse(index)


app = create_app()
