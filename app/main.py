"""App factory. Each tool contributes a router; the foundation supplies everything else."""
from fastapi import FastAPI

from app.foundation import web
from app.foundation.db import db_path_from_env, make_engine
from app.refunds.routes import router as refunds_router

TOOL_ROUTERS = [refunds_router]


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="Internal tools", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db_path = db_path or db_path_from_env()
    app.state.engine = make_engine(app.state.db_path)
    web.install_error_handlers(app)
    app.include_router(web.router)
    for router in TOOL_ROUTERS:
        app.include_router(router)
    return app
