from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
    return app


app = create_app()
