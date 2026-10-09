"""Worker-only application. The native Karix portal is its sole browser caller."""
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.routes import router
from app.config.settings import settings, strong_token
from app.core.dependencies import get_report_service
from app.core.local_storage import worker_storage_lock


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not strong_token(settings.machine_token):
        raise RuntimeError("A strong APPAREL_ATTRIBUTION_TOKEN must be configured before worker startup")
    if os.name != "nt":
        os.umask(0o077)
    with worker_storage_lock(settings.storage_dir):
        try:
            yield
        finally:
            await get_report_service().shutdown()


app = FastAPI(
    title=settings.app_name, lifespan=lifespan,
    docs_url=None, redoc_url=None, openapi_url=None,
)
app.include_router(router, prefix=settings.api_prefix)


@app.get("/healthz", include_in_schema=False)
async def readiness():
    return {"status": "ok"}
