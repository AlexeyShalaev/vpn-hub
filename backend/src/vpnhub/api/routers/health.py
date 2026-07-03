"""Операционные эндпоинты без версии: healthz / readyz / metrics + публичный конфиг."""

from __future__ import annotations

import hmac

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import text

from vpnhub.api.config import Settings, get_settings
from vpnhub.api.deps import service
from vpnhub.infra.uow import Uow

router = APIRouter(tags=["ops"])


def metrics_authorized(configured: str, header: str | None, query_token: str | None) -> bool:
    """Пускать ли к /metrics (чистая логика, отдельно тестируется).

    Пустой `configured` → эндпоинт открыт (совместимость; закрывайте на обратном прокси).
    Иначе требуется совпадение токена: `Authorization: Bearer <token>` или `?token=<token>`.
    Сравнение — постоянного времени (hmac.compare_digest).
    """
    if not configured:
        return True
    provided = ""
    if header and header.lower().startswith("bearer "):
        provided = header[7:].strip()
    elif query_token:
        provided = query_token
    return bool(provided) and hmac.compare_digest(provided, configured)


@router.get("/healthz")
async def healthz() -> dict:
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(response: Response, uow: Uow = Depends(service(Uow))) -> dict:
    try:
        async with uow.query() as tx:
            await tx.session.execute(text("SELECT 1"))
    except Exception:
        # 503 → k8s readinessProbe выведет под из эндпоинтов Service, пока БД недоступна
        response.status_code = 503
        return {"status": "not-ready"}
    return {"status": "ready"}


@router.get("/metrics")
async def metrics(request: Request, settings: Settings = Depends(get_settings)) -> Response:
    if not metrics_authorized(
        settings.metrics_token, request.headers.get("authorization"), request.query_params.get("token")
    ):
        return PlainTextResponse("forbidden", status_code=403)
    return PlainTextResponse(generate_latest().decode(), media_type=CONTENT_TYPE_LATEST)


@router.get("/api/config")
async def public_config(settings: Settings = Depends(get_settings)) -> dict:
    return {"name": "VPN Hub", "version": settings.version, "baseUrl": settings.base_url}
