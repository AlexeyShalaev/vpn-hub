"""Пулы серверов."""

from __future__ import annotations

import builtins

from vpnhub.api.config import Settings
from vpnhub.common.serializers import pool_to_dict
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.uow import Uow


class PoolService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow

    async def list(self, owner_id: str) -> list[dict]:
        async with self.uow.query() as tx:
            out = []
            for p in await tx.pools.for_owner(owner_id):
                out.append(pool_to_dict(p, await tx.pools.server_ids(p.id)))
            return out

    async def create(self, owner_id: str, name: str, server_ids: builtins.list[str]) -> dict:
        if not name:
            raise BadRequest("Введите название")
        async with self.uow.transaction() as tx:
            p = m.Pool(owner_user_id=owner_id, name=name)
            tx.pools.add(p)
            await tx.session.flush()
            await tx.pools.set_servers(p.id, server_ids or [])
            return pool_to_dict(p, server_ids or [])

    async def update(self, owner_id: str, pid: str, name: str, server_ids: builtins.list[str]) -> dict:
        async with self.uow.transaction() as tx:
            p = await tx.pools.get(pid)
            if not p or p.owner_user_id != owner_id:
                raise NotFound("Пул не найден")
            if name:
                p.name = name
            await tx.pools.set_servers(pid, server_ids or [])
            return pool_to_dict(p, server_ids or [])

    async def delete(self, owner_id: str, pid: str) -> None:
        async with self.uow.transaction() as tx:
            p = await tx.pools.get(pid)
            if not p or p.owner_user_id != owner_id:
                raise NotFound("Пул не найден")
            await tx.session.delete(p)
