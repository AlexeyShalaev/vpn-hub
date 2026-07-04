"""Роутеры владельца: серверы, пулы, группы, доступы."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends

from vpnhub.api.deps import require_user, service
from vpnhub.infra.providers_store import ProviderStore
from vpnhub.services.auth import Identity
from vpnhub.services.groups import GroupService
from vpnhub.services.pools import PoolService
from vpnhub.services.server_access import ServerAccessService
from vpnhub.services.servers import ServerService

router = APIRouter(prefix="/api/v1", tags=["owner"])

# ---------- providers ----------


@router.get("/providers")
async def providers(store: ProviderStore = Depends(service(ProviderStore))) -> list[dict]:
    return store.list()


# ---------- servers ----------


@router.get("/servers")
async def list_servers(
    ident: Identity = Depends(require_user), svc: ServerService = Depends(service(ServerService))
) -> list[dict]:
    return await svc.list(ident.id)


@router.post("/servers")
async def create_server(
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: ServerService = Depends(service(ServerService)),
) -> dict:
    server = await svc.create(ident.id, body)
    # сразу пингуем и синхронизируем состояние (best-effort) — ответ уже отражает актуальное состояние
    await svc.check_and_sync(ident.id, server["id"])
    return await svc.get(ident.id, server["id"])


@router.get("/servers/{sid}")
async def get_server(
    sid: str, ident: Identity = Depends(require_user), svc: ServerService = Depends(service(ServerService))
) -> dict:
    return await svc.get(ident.id, sid)


@router.patch("/servers/{sid}")
async def update_server(
    sid: str,
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: ServerService = Depends(service(ServerService)),
) -> dict:
    return await svc.update(ident.id, sid, body)


@router.delete("/servers/{sid}")
async def delete_server(
    sid: str, ident: Identity = Depends(require_user), svc: ServerService = Depends(service(ServerService))
) -> dict:
    await svc.delete(ident.id, sid)
    return {"ok": True}


@router.post("/servers/{sid}/check")
async def check_server(
    sid: str, ident: Identity = Depends(require_user), svc: ServerService = Depends(service(ServerService))
) -> dict:
    return await svc.check(ident.id, sid)


@router.post("/servers/{sid}/sync")
async def sync_server(
    sid: str, ident: Identity = Depends(require_user), svc: ServerService = Depends(service(ServerService))
) -> dict:
    return await svc.sync(ident.id, sid)


@router.get("/servers/{sid}/access")
async def server_access_overview(
    sid: str,
    ident: Identity = Depends(require_user),
    svc: ServerAccessService = Depends(service(ServerAccessService)),
) -> dict:
    return await svc.overview(ident.id, sid)


@router.get("/servers/{sid}/vpns/{vtype}")
async def server_vpn_advanced(
    sid: str,
    vtype: str,
    ident: Identity = Depends(require_user),
    svc: ServerAccessService = Depends(service(ServerAccessService)),
) -> dict:
    return await svc.vpn_advanced(ident.id, sid, vtype)


@router.get("/servers/{sid}/vpns/{vtype}/external")
async def server_vpn_external(
    sid: str,
    vtype: str,
    ident: Identity = Depends(require_user),
    svc: ServerAccessService = Depends(service(ServerAccessService)),
) -> dict:
    return await svc.external_clients(ident.id, sid, vtype)


@router.patch("/servers/{sid}/clients/{cid}")
async def rename_server_client(
    sid: str,
    cid: str,
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: ServerAccessService = Depends(service(ServerAccessService)),
) -> dict:
    return await svc.rename_client(ident.id, sid, cid, body.get("name", ""))


@router.delete("/servers/{sid}/clients/{cid}")
async def revoke_server_client(
    sid: str,
    cid: str,
    ident: Identity = Depends(require_user),
    svc: ServerAccessService = Depends(service(ServerAccessService)),
) -> dict:
    return await svc.revoke_client(ident.id, sid, cid)


@router.post("/servers/{sid}/vpns/{vtype}/{op}")
async def vpn_op(
    sid: str,
    vtype: str,
    op: str,
    body: dict[str, Any] = Body(default={}),
    ident: Identity = Depends(require_user),
    svc: ServerService = Depends(service(ServerService)),
) -> dict:
    # install: body.protos — выбранные протоколы вендора (id); пусто/нет → все (обратная совместимость)
    protos = body.get("protos") if isinstance(body, dict) else None
    return await svc.vpn_op(ident.id, sid, vtype, op, protos)


@router.post("/servers/{sid}/protocols/{proto}/{op}")
async def protocol_op(
    sid: str,
    proto: str,
    op: str,
    ident: Identity = Depends(require_user),
    svc: ServerService = Depends(service(ServerService)),
) -> dict:
    # op ∈ {start, stop, remove}: свитчер контейнера одного протокола или снос с отзывом конфигов
    return await svc.protocol_op(ident.id, sid, proto, op)


# ---------- pools ----------


@router.get("/pools")
async def list_pools(
    ident: Identity = Depends(require_user), svc: PoolService = Depends(service(PoolService))
) -> list[dict]:
    return await svc.list(ident.id)


@router.post("/pools")
async def create_pool(
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: PoolService = Depends(service(PoolService)),
) -> dict:
    return await svc.create(ident.id, body.get("name", ""), body.get("serverIds", []))


@router.patch("/pools/{pid}")
async def update_pool(
    pid: str,
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: PoolService = Depends(service(PoolService)),
) -> dict:
    return await svc.update(ident.id, pid, body.get("name", ""), body.get("serverIds", []))


@router.delete("/pools/{pid}")
async def delete_pool(
    pid: str, ident: Identity = Depends(require_user), svc: PoolService = Depends(service(PoolService))
) -> dict:
    await svc.delete(ident.id, pid)
    return {"ok": True}


# ---------- groups ----------


@router.get("/groups")
async def list_groups(
    ident: Identity = Depends(require_user), svc: GroupService = Depends(service(GroupService))
) -> list[dict]:
    return await svc.list(ident.id)


@router.post("/groups")
async def create_group(
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: GroupService = Depends(service(GroupService)),
) -> dict:
    return await svc.create(ident.id, ident.name, body.get("name", ""))


@router.get("/groups/{gid}")
async def get_group(
    gid: str, ident: Identity = Depends(require_user), svc: GroupService = Depends(service(GroupService))
) -> dict:
    return await svc.get(ident.id, gid)


@router.patch("/groups/{gid}")
async def update_group(
    gid: str,
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: GroupService = Depends(service(GroupService)),
) -> dict:
    return await svc.update(ident.id, gid, body.get("name", ""))


@router.delete("/groups/{gid}")
async def delete_group(
    gid: str, ident: Identity = Depends(require_user), svc: GroupService = Depends(service(GroupService))
) -> dict:
    await svc.delete(ident.id, gid)
    return {"ok": True}


@router.post("/groups/{gid}/token")
async def regen_token(
    gid: str, ident: Identity = Depends(require_user), svc: GroupService = Depends(service(GroupService))
) -> dict:
    return await svc.regen_token(ident.id, gid)


@router.post("/groups/{gid}/members")
async def add_member(
    gid: str,
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: GroupService = Depends(service(GroupService)),
) -> dict:
    return await svc.add_member(ident.id, gid, body.get("name", ""), body.get("role", "member"), body.get("phone"))


@router.post("/groups/{gid}/members/{mid}/role")
async def toggle_member_role(
    gid: str,
    mid: str,
    ident: Identity = Depends(require_user),
    svc: GroupService = Depends(service(GroupService)),
) -> dict:
    return await svc.toggle_member_role(ident.id, gid, mid)


@router.delete("/groups/{gid}/members/{mid}")
async def remove_member(
    gid: str,
    mid: str,
    ident: Identity = Depends(require_user),
    svc: GroupService = Depends(service(GroupService)),
) -> dict:
    return await svc.remove_member(ident.id, gid, mid)


# ---------- access ----------


@router.put("/groups/{gid}/access/pools/{pool_id}")
async def toggle_pool(
    gid: str,
    pool_id: str,
    ident: Identity = Depends(require_user),
    svc: GroupService = Depends(service(GroupService)),
) -> dict:
    return await svc.toggle_pool(ident.id, gid, pool_id)


@router.put("/groups/{gid}/access/servers/{server_id}")
async def toggle_server(
    gid: str,
    server_id: str,
    ident: Identity = Depends(require_user),
    svc: GroupService = Depends(service(GroupService)),
) -> dict:
    return await svc.toggle_server(ident.id, gid, server_id)


@router.put("/groups/{gid}/access/servers/{server_id}/vpns/{vtype}")
async def toggle_server_vpn(
    gid: str,
    server_id: str,
    vtype: str,
    ident: Identity = Depends(require_user),
    svc: GroupService = Depends(service(GroupService)),
) -> dict:
    return await svc.toggle_server_vpn(ident.id, gid, server_id, vtype)
