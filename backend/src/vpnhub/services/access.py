"""Расчёт эффективного доступа пользователя (пулы ∪ точечные серверы)."""

from __future__ import annotations

from vpnhub.infra.uow import UowTransaction


async def effective_access(tx: UowTransaction, user_id: str) -> tuple[dict[str, set[str]], dict[str, str]]:
    """Возвращает (server_id → доступные vpn-типы, server_id → имя группы-источника)."""
    access: dict[str, set[str]] = {}
    from_group: dict[str, str] = {}
    groups = await tx.groups.groups_for_user(user_id)
    for g in groups:
        # серверы из пулов группы → все установленные VPN
        for pid in await tx.groups.pool_ids(g.id):
            for sid in await tx.pools.server_ids(pid):
                srv = await tx.servers.get(sid)
                if not srv:
                    continue
                installed = {v.type for v in srv.vpns if v.installed}
                access.setdefault(sid, set()).update(installed)
                from_group.setdefault(sid, g.name)
        # точечный доступ
        for sid, vtypes in (await tx.groups.server_access(g.id)).items():
            srv = await tx.servers.get(sid)
            installed = {v.type for v in srv.vpns if v.installed} if srv else set()
            access.setdefault(sid, set()).update(set(vtypes) & installed)
            from_group.setdefault(sid, g.name)
    # убрать пустые
    return {k: v for k, v in access.items() if v}, from_group
