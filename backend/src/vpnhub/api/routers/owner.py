"""Роутеры владельца: серверы, пулы, группы, доступы."""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Body, Depends, Query

from vpnhub.api.deps import require_user, service
from vpnhub.infra.providers_store import ProviderStore
from vpnhub.services.auth import Identity
from vpnhub.services.finance import FinanceService
from vpnhub.services.groups import GroupService
from vpnhub.services.hostmetrics import HostMetricsService
from vpnhub.services.multihop import ChainService
from vpnhub.services.pools import PoolService
from vpnhub.services.server_access import ServerAccessService
from vpnhub.services.servers import ServerService
from vpnhub.services.traffic import TrafficService

router = APIRouter(prefix="/api/v1", tags=["owner"])


def _pos_int(body: dict[str, Any], key: str) -> int | None:
    """Положительный int из тела запроса; строка/булево/прочее/≤0 → None (снять лимит).

    Санитайзер для лимитов из недоверенного JSON: не даём кривому значению долететь до
    сравнения `> 0` (иначе TypeError → 500) или до Integer-колонки (float).
    """
    raw = body.get(key) if isinstance(body, dict) else None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    n = int(raw)
    return n if n > 0 else None


# ---------- providers ----------


@router.get("/providers")
async def providers(store: ProviderStore = Depends(service(ProviderStore))) -> list[dict]:
    return store.list()


@router.get("/providers/{pid}/plans")
async def provider_plans(pid: str, _: Identity = Depends(require_user)) -> list[dict]:
    # справочные тарифные планы провайдера — для автозаполнения цены/квоты при создании сервера
    from vpnhub.infra.provider_plans import plans_for  # noqa: PLC0415 — лёгкий локальный импорт

    return plans_for(pid)


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


@router.post("/servers/{sid}/migrate")
async def migrate_server(
    sid: str,
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: ServerService = Depends(service(ServerService)),
) -> dict:
    # body: { ip (обяз.), sshPort?, sshUser?, auth?, secret? } — новые SSH-реквизиты VPS.
    # Переустанавливает все установленные протоколы на новом хосте (фон) и помечает
    # выданные конфиги revoked (требуют перевыдачи). См. tasks/07-server-migration.md.
    return await svc.migrate(ident.id, sid, body)


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


@router.get("/servers/{sid}/traffic")
async def server_traffic(
    sid: str,
    period: str = "24h",
    ident: Identity = Depends(require_user),
    svc: TrafficService = Depends(service(TrafficService)),
) -> dict:
    return await svc.overview(ident.id, sid, period)


@router.get("/monitoring")
async def monitoring(
    period: str = "24h",
    ident: Identity = Depends(require_user),
    svc: TrafficService = Depends(service(TrafficService)),
) -> dict:
    # супер-мониторинг: per-client трафик+онлайн по ВСЕМ серверам владельца (агрегаты + сводка)
    return await svc.global_overview(ident.id, period)


@router.get("/servers/{sid}/metrics")
async def server_metrics(
    sid: str,
    ident: Identity = Depends(require_user),
    svc: HostMetricsService = Depends(service(HostMetricsService)),
) -> dict:
    # ресурсы хоста этого сервера: последние значения + история сэмплов для мини-графиков
    return await svc.overview(ident.id, sid)


@router.post("/servers/{sid}/stats/enable")
async def server_stats_enable(
    sid: str,
    ident: Identity = Depends(require_user),
    svc: HostMetricsService = Depends(service(HostMetricsService)),
) -> dict:
    # включить точную онлайн-статистику (Xray Stats API / Hysteria2 trafficStats); рестарт xray/hysteria
    return {"enabled": await svc.enable_stats(ident.id, sid)}


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


@router.post("/servers/{sid}/clients/{cid}/pause")
async def pause_server_client(
    sid: str,
    cid: str,
    ident: Identity = Depends(require_user),
    svc: ServerAccessService = Depends(service(ServerAccessService)),
) -> dict:
    # ручная пауза доступа по конфигу (cid = config_id); статус → "paused"
    return await svc.set_paused(ident.id, sid, cid, pause=True)


@router.post("/servers/{sid}/clients/{cid}/resume")
async def resume_server_client(
    sid: str,
    cid: str,
    ident: Identity = Depends(require_user),
    svc: ServerAccessService = Depends(service(ServerAccessService)),
) -> dict:
    return await svc.set_paused(ident.id, sid, cid, pause=False)


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


@router.patch("/servers/{sid}/protocols/{proto}/params")
async def set_protocol_params(
    sid: str,
    proto: str,
    body: dict[str, Any] = Body(default={}),
    ident: Identity = Depends(require_user),
    svc: ServerService = Depends(service(ServerService)),
) -> dict:
    # body: { "preset"?: "default"|"aggressive"|"mobile", "values"?: {jc,jmin,...} } — смена obfuscation AWG
    preset = body.get("preset") if isinstance(body, dict) else None
    values = body.get("values") if isinstance(body, dict) else None
    return await svc.set_protocol_params(ident.id, sid, proto, preset, values)


@router.patch("/servers/{sid}/protocols/{proto}/reality")
async def set_reality(
    sid: str,
    proto: str,
    body: dict[str, Any] = Body(default={}),
    ident: Identity = Depends(require_user),
    svc: ServerService = Depends(service(ServerService)),
) -> dict:
    # body: { "rotate_short_id"?: bool, "short_id"?: str, "sni"?: str } — управление Xray-Reality с reprovision
    rotate = bool(body.get("rotate_short_id")) if isinstance(body, dict) else False
    short_id = body.get("short_id") if isinstance(body, dict) else None
    sni = body.get("sni") if isinstance(body, dict) else None
    return await svc.set_reality(ident.id, sid, proto, rotate_short_id=rotate, short_id=short_id, sni=sni)


@router.patch("/servers/{sid}/protocols/{proto}/limit")
async def set_protocol_limit(
    sid: str,
    proto: str,
    body: dict[str, Any] = Body(default={}),
    ident: Identity = Depends(require_user),
    svc: ServerService = Depends(service(ServerService)),
) -> dict:
    # body: { "maxClients": int | null } — мягкий лимит числа конфигов на протоколе (null/0 → снять)
    return await svc.set_protocol_limit(ident.id, sid, proto, _pos_int(body, "maxClients"))


@router.patch("/servers/{sid}/quota")
async def set_bandwidth_quota(
    sid: str,
    body: dict[str, Any] = Body(default={}),
    ident: Identity = Depends(require_user),
    svc: ServerService = Depends(service(ServerService)),
) -> dict:
    # body: { "quotaBytes": int|null (квота трафика тарифа), "billingDay": 1..31|null (день сброса) }
    day = _pos_int(body, "billingDay")
    return await svc.set_bandwidth_quota(ident.id, sid, _pos_int(body, "quotaBytes"), day)


@router.get("/servers/{sid}/usage")
async def server_usage(
    sid: str,
    ident: Identity = Depends(require_user),
    svc: ServerService = Depends(service(ServerService)),
) -> dict:
    return await svc.usage(ident.id, sid)


# ---------- финансовый учёт (стоимость серверов) ----------

_MONTH_SECONDS = 30 * 86400


@router.get("/servers/{sid}/price")
async def get_server_price(
    sid: str,
    ident: Identity = Depends(require_user),
    svc: FinanceService = Depends(service(FinanceService)),
) -> dict:
    return {"price": await svc.get_price(ident.id, sid)}


@router.put("/servers/{sid}/price")
async def set_server_price(
    sid: str,
    body: dict[str, Any] = Body(default={}),
    ident: Identity = Depends(require_user),
    svc: FinanceService = Depends(service(FinanceService)),
) -> dict:
    # body: { amount: number|null, currency: str, period: minute|day|month, anchorDay: int|null }
    raw = body.get("amount")
    amount = float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
    day = body.get("anchorDay")
    anchor = int(day) if isinstance(day, (int, float)) and not isinstance(day, bool) else None
    price = await svc.set_price(
        ident.id, sid, amount, str(body.get("currency") or "RUB"), str(body.get("period") or "month"), anchor
    )
    return {"price": price}


@router.get("/servers/{sid}/cost")
async def server_cost(
    sid: str,
    start: float | None = Query(default=None),
    end: float | None = Query(default=None),
    ident: Identity = Depends(require_user),
    svc: FinanceService = Depends(service(FinanceService)),
) -> dict:
    now = time.time()
    return await svc.server_cost(ident.id, sid, start if start is not None else now - _MONTH_SECONDS, end or now)


@router.get("/finance/cost")
async def finance_cost(
    start: float | None = Query(default=None),
    end: float | None = Query(default=None),
    ident: Identity = Depends(require_user),
    svc: FinanceService = Depends(service(FinanceService)),
) -> dict:
    now = time.time()
    return await svc.cost_report(ident.id, start if start is not None else now - _MONTH_SECONDS, end or now)


# ---------- multihop / chains (entry -> exit) ----------


@router.get("/servers/{sid}/chains")
async def list_chains(
    sid: str,
    ident: Identity = Depends(require_user),
    svc: ChainService = Depends(service(ChainService)),
) -> list[dict]:
    # цепочки, где этот сервер — вход (entry); показывается в секции «Цепочка» страницы сервера
    return await svc.list_for_entry(ident.id, sid)


@router.post("/servers/{sid}/chains")
async def create_chain(
    sid: str,
    body: dict[str, Any] = Body(...),
    ident: Identity = Depends(require_user),
    svc: ChainService = Depends(service(ChainService)),
) -> dict:
    # body: { "exitServerId": str } — направить выход этого (entry) сервера через exit-сервер
    return await svc.create(ident.id, sid, body.get("exitServerId", ""))


@router.delete("/servers/{sid}/chains/{chain_id}")
async def delete_chain(
    sid: str,
    chain_id: str,
    ident: Identity = Depends(require_user),
    svc: ChainService = Depends(service(ChainService)),
) -> dict:
    return await svc.delete(ident.id, sid, chain_id)


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


@router.patch("/groups/{gid}/limit")
async def set_group_limit(
    gid: str,
    body: dict[str, Any] = Body(default={}),
    ident: Identity = Depends(require_user),
    svc: GroupService = Depends(service(GroupService)),
) -> dict:
    # body: { "maxDevices": int | null } — override лимита устройств для участников (null/0 → снять)
    return await svc.set_group_limit(ident.id, gid, _pos_int(body, "maxDevices"))


@router.patch("/groups/{gid}/members/{mid}/limit")
async def set_member_limit(
    gid: str,
    mid: str,
    body: dict[str, Any] = Body(default={}),
    ident: Identity = Depends(require_user),
    svc: GroupService = Depends(service(GroupService)),
) -> dict:
    # body: { "maxDevices": int | null } — персональный override лимита устройств участника
    return await svc.set_member_limit(ident.id, gid, mid, _pos_int(body, "maxDevices"))


@router.patch("/groups/{gid}/byte-limit")
async def set_group_bytes(
    gid: str,
    body: dict[str, Any] = Body(default={}),
    ident: Identity = Depends(require_user),
    svc: GroupService = Depends(service(GroupService)),
) -> dict:
    # body: { "maxBytes": int | null } — override лимита трафика участников группы (null/0 → снять)
    return await svc.set_group_bytes(ident.id, gid, _pos_int(body, "maxBytes"))


@router.patch("/groups/{gid}/members/{mid}/byte-limit")
async def set_member_bytes(
    gid: str,
    mid: str,
    body: dict[str, Any] = Body(default={}),
    ident: Identity = Depends(require_user),
    svc: GroupService = Depends(service(GroupService)),
) -> dict:
    # body: { "maxBytes": int | null } — персональный override лимита трафика участника
    return await svc.set_member_bytes(ident.id, gid, mid, _pos_int(body, "maxBytes"))


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
