"""Устройства участника."""

from __future__ import annotations

import builtins
from collections import defaultdict

from sqlalchemy import select

from vpnhub.api.config import Settings
from vpnhub.common.serializers import device_to_dict
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.uow import Uow, UowTransaction
from vpnhub.services.provisioning import PROVISIONED_VENDORS, ProvisioningService
from vpnhub.services.sync_logic import dump_pending, parse_pending


class DeviceService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    async def list(self, user_id: str) -> list[dict]:
        async with self.uow.query() as tx:
            return [device_to_dict(d) for d in await tx.devices.for_user(user_id)]

    async def create(self, user_id: str, name: str, platform: str) -> dict:
        if not name:
            raise BadRequest("Введите имя")
        async with self.uow.transaction() as tx:
            d = m.Device(user_id=user_id, name=name, platform=platform or "ios")
            tx.devices.add(d)
            await tx.session.flush()
            await tx.session.refresh(d)
            return device_to_dict(d)

    async def delete(self, user_id: str, did: str) -> None:
        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            d = await tx.devices.get(did)
            if not d or d.user_id != user_id:
                raise NotFound("Устройство не найдено")
            refs = [
                (c.server_id, c.proto or "", c.client_id or "")
                for c in d.configs
                if c.vpn_type in PROVISIONED_VENDORS and c.client_id
            ]
        # durable: фиксируем долг на снятие И удаляем устройство в одной транзакции (атомарно).
        # Долг живёт на ServerProtocol → переживёт cascade-удаление DeviceConfig и снятие подстрахует sync.
        async with self.uow.transaction() as tx:
            d = await tx.devices.get(did)
            if not d or d.user_id != user_id:
                return
            await self._enqueue_revoke(tx, refs)
            await tx.session.delete(d)  # cascade удалит DeviceConfig
        await prov.revoke_on_servers(refs)  # быстрый путь (best-effort); недоснятое погасит sync

    @staticmethod
    async def _enqueue_revoke(tx: UowTransaction, refs: builtins.list[tuple[str, str, str]]) -> None:
        """Добавить client_id в ledger pending_revoke_json соответствующих ServerProtocol (дедуп)."""
        by_proto: dict[tuple[str, str], set[str]] = defaultdict(set)
        for server_id, proto_label, client_id in refs:
            spec = pc.spec_by_label(proto_label)
            if spec and client_id:
                by_proto[(server_id, spec.id)].add(client_id)
        for (server_id, proto_id), cids in by_proto.items():
            sp = (
                await tx.session.execute(
                    select(m.ServerProtocol).where(
                        m.ServerProtocol.server_id == server_id,
                        m.ServerProtocol.proto == proto_id,
                    )
                )
            ).scalar_one_or_none()
            if sp is not None:
                sp.pending_revoke_json = dump_pending(parse_pending(sp.pending_revoke_json) | cids)
