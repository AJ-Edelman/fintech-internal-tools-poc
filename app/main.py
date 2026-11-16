"""App factory. Each tool contributes a router; the foundation supplies everything else."""
from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

from app.foundation import admin_routes, connector_routes, connectors, web
from app.foundation.db import db_path_from_env, make_engine
from app.kyc.routes import router as kyc_router
from app.refunds.routes import router as refunds_router

TOOL_ROUTERS = [refunds_router, kyc_router]


def create_app(db_path: str | None = None) -> FastAPI:
    app = FastAPI(title="Internal tools", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db_path = db_path or db_path_from_env()
    app.state.engine = make_engine(app.state.db_path)
    web.install_error_handlers(app)
    app.include_router(web.router)
    app.include_router(admin_routes.router)
    app.include_router(connector_routes.router)
    for router in TOOL_ROUTERS:
        app.include_router(router)

    @app.middleware("http")
    async def _deliver_outbound(request: Request, call_next):
        # Delivery is separate from the request's transaction, which has committed by now.
        response = await call_next(request)
        await run_in_threadpool(connectors.deliver_pending, app.state.engine)
        return response

    return app
