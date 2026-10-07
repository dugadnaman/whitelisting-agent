from __future__ import annotations

import hmac
import json
import logging

from fastapi import HTTPException, Request

from app.config.settings import settings, strong_token
from app.services.report_service import ReportService


report_service = ReportService(settings)
logger = logging.getLogger("apparel.audit")


def get_report_service() -> ReportService:
    return report_service


async def require_machine(request: Request) -> None:
    if not strong_token(settings.machine_token):
        raise HTTPException(status_code=503, detail="Configure a strong APPAREL_ATTRIBUTION_TOKEN before using this private worker")
    supplied = request.headers.get("X-Apparel-Attribution-Token", "")
    if not supplied or not hmac.compare_digest(supplied.encode(), settings.machine_token.encode()):
        raise HTTPException(status_code=401, detail="Invalid worker authentication")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        actor = request.headers.get("X-Apparel-Actor", "")
        if not actor or len(actor) > 512 or any(ord(char) < 32 for char in actor):
            raise HTTPException(status_code=400, detail="The verified gateway actor is required")
        logger.info("actor=%s action=%s path=%s", json.dumps(actor), request.method, request.url.path)
