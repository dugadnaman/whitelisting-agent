"""Worker-only application. The native Karix portal is its sole browser caller."""
from contextlib import asynccontextmanager
import fcntl
import os

from fastapi import FastAPI

from app.api.routes import router
from app.config.settings import settings, strong_token
from app.core.dependencies import get_report_service


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if not strong_token(settings.machine_token):
        raise RuntimeError("A strong APPAREL_ATTRIBUTION_TOKEN must be configured before worker startup")
    os.umask(0o077)
    settings.storage_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    settings.storage_dir.chmod(0o700)
    lock = (settings.storage_dir / "worker.lock").open("a")
    try:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("Only one worker process may use this /data volume and browser") from exc
        yield
    finally:
        await get_report_service().shutdown()
        lock.close()


app = FastAPI(
    title=settings.app_name, lifespan=lifespan,
    docs_url=None, redoc_url=None, openapi_url=None,
)
app.include_router(router, prefix=settings.api_prefix)


@app.get("/healthz", include_in_schema=False)
async def readiness():
    return {"status": "ok"}
