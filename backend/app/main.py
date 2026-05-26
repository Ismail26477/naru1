"""FastAPI application factory."""
from __future__ import annotations
from contextlib import asynccontextmanager
from fastapi import FastAPI, APIRouter
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import logging
from pathlib import Path

from app.core.config import settings
from app.core.logging_config import configure_logging
from app.api.v1 import auth as auth_router
from app.api.v1 import customers as customers_router
from app.api.v1 import admin as admin_router
from app.api.v1 import admin_customers as admin_customers_router
from app.api.v1 import admin_routes as admin_routes_router
from app.api.v1 import admin_deliveries as admin_deliveries_router
from app.api.v1 import admin_products as admin_products_router
from app.api.v1 import admin_billing as admin_billing_router
from app.api.v1 import admin_reports as admin_reports_router
from app.api.v1 import delivery as delivery_router
from app.api.v1 import webhooks as webhooks_router


configure_logging("INFO" if not settings.DEBUG else "DEBUG")
log = logging.getLogger("app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start APScheduler (guarded; disable via env if testing with pytest)
    if not app.state.__dict__.get("_disable_scheduler", False):
        try:
            from app.jobs.scheduler import start_scheduler, stop_scheduler
            start_scheduler()
        except Exception:
            log.exception("scheduler failed to start")
    yield
    try:
        from app.jobs.scheduler import stop_scheduler
        stop_scheduler()
    except Exception:
        pass


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version="0.1.0",
        description="Posuhtik — subscription milk & dairy delivery (Phase 1 backend)",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Static (local invoice PDFs in Phase 1)
    storage = Path(settings.LOCAL_STORAGE_PATH)
    storage.mkdir(parents=True, exist_ok=True)
    app.mount(settings.LOCAL_STORAGE_BASE_URL, StaticFiles(directory=str(storage)), name="static")

    # API v1 router — MUST be /api prefix for platform routing
    api = APIRouter(prefix="/api")

    @api.get("/")
    async def root():
        return {"app": settings.APP_NAME, "env": settings.APP_ENV, "status": "ok"}

    @api.get("/health")
    async def health():
        return {"status": "healthy"}

    api.include_router(auth_router.router)
    api.include_router(customers_router.router)
    api.include_router(admin_customers_router.router)
    api.include_router(admin_routes_router.router)
    api.include_router(admin_deliveries_router.router)
    api.include_router(admin_products_router.router)
    api.include_router(admin_billing_router.router)
    api.include_router(admin_reports_router.router)
    api.include_router(admin_router.router)
    api.include_router(delivery_router.router)
    api.include_router(webhooks_router.router)
    app.include_router(api)
    return app


app = create_app()
