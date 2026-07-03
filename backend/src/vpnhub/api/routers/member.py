"""Роутеры участника: «доступно мне», устройства, получение конфигов."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends

from vpnhub.api.deps import require_user, service
from vpnhub.services.auth import Identity
from vpnhub.services.configs import ConfigService
from vpnhub.services.devices import DeviceService
from vpnhub.services.groups import GroupService
from vpnhub.services.me import MeService

router = APIRouter(prefix="/api/v1", tags=["member"])


@router.get("/groups/by-token/{token}")
async def group_by_token(
    token: str, _: Identity = Depends(require_user), svc: GroupService = Depends(service(GroupService))
) -> dict:
    return await svc.peek_by_token(token)


@router.post("/groups/join/{token}")
async def join_group(
    token: str, ident: Identity = Depends(require_user), svc: GroupService = Depends(service(GroupService))
) -> dict:
    return await svc.join(ident.id, ident.name, token)


@router.get("/me/available")
async def available(
    ident: Identity = Depends(require_user), svc: MeService = Depends(service(MeService))
) -> list[dict]:
    return await svc.available(ident.id)


@router.get("/me/devices")
async def list_devices(
    ident: Identity = Depends(require_user), svc: DeviceService = Depends(service(DeviceService))
) -> list[dict]:
    return await svc.list(ident.id)


@router.post("/me/devices")
async def add_device(
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: DeviceService = Depends(service(DeviceService)),
) -> dict:
    return await svc.create(ident.id, body.get("name", ""), body.get("platform", "ios"))


@router.delete("/me/devices/{did}")
async def remove_device(
    did: str, ident: Identity = Depends(require_user), svc: DeviceService = Depends(service(DeviceService))
) -> dict:
    await svc.delete(ident.id, did)
    return {"ok": True}


@router.post("/configs")
async def gen_config(
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: ConfigService = Depends(service(ConfigService)),
) -> dict:
    return await svc.generate(
        ident.id, body.get("serverId", ""), body.get("vpn", ""), body.get("deviceId"), body.get("proto")
    )


@router.post("/configs/install")
async def install_config(
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: ConfigService = Depends(service(ConfigService)),
) -> dict:
    return await svc.install(
        ident.id, body.get("serverId", ""), body.get("vpn", ""), body.get("deviceId", ""), body.get("proto")
    )


@router.post("/configs/remove")
async def remove_config(
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: ConfigService = Depends(service(ConfigService)),
) -> dict:
    return await svc.remove(
        ident.id, body.get("serverId", ""), body.get("vpn", ""), body.get("deviceId", ""), body.get("proto")
    )
