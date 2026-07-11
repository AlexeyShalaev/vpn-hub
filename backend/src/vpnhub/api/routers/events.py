"""Роутер аудит-лога: список событий с ролевой видимостью и фильтрами."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from vpnhub.api.deps import require_user, service
from vpnhub.services.audit import AuditService
from vpnhub.services.auth import Identity

router = APIRouter(prefix="/api/v1", tags=["events"])


@router.get("/events")
async def list_events(
    type: str | None = Query(default=None),
    since: float | None = Query(default=None),
    until: float | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    ident: Identity = Depends(require_user),
    svc: AuditService = Depends(service(AuditService)),
) -> list[dict]:
    # admin видит все события, owner — только свои ресурсы/действия (см. AuditService.list_for)
    return await svc.list_for(ident, type=type, since=since, until=until, limit=limit)
