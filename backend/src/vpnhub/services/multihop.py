"""Мультихоп / цепочки серверов (entry → exit) поверх Xray outbound chaining.

Клиент подключается к entry-серверу (например, с российским IP), а его xray-контейнер на entry
выпускает трафик в интернет не напрямую (`freedom`), а через vless-коннект на exit-сервер в другой
стране. То есть entry становится обычным vless-клиентом exit — цепочка целиком на уровне конфигов
двух xray, без правки ядра/маршрутизации. См. tasks/05-multihop.md.

Оркестрация здесь: валидация (оба сервера owned/online, xray installed на обоих), заведение
клиента на exit (штатный add_client), переключение outbound на entry (set_chain) и запись связки
ChainLink. Реальная правка server.json — в XrayProvisioner.set_outbound_chain.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select

from vpnhub.api.config import Settings
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning.provisioners.base import ServerMaterial
from vpnhub.infra.uow import Uow, UowTransaction
from vpnhub.services.provisioning import ProvisioningService

log = structlog.get_logger(__name__)

# Мультихоп поддержан только для tcp-Reality Xray: entry предъявляет обычный vless-клиент exit.
CHAIN_PROTO = "xray"


def chain_to_dict(link: m.ChainLink, *, exit_name: str = "") -> dict:
    return {
        "id": link.id,
        "entryServerId": link.entry_server_id,
        "exitServerId": link.exit_server_id,
        "exitServerName": exit_name,
        "proto": link.proto,
        "state": link.state,
        "error": link.error,
    }


class ChainService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    async def _owned(self, tx: UowTransaction, owner_id: str, sid: str) -> m.Server:
        s: m.Server | None = await tx.servers.get(sid)
        if not s or s.owner_user_id != owner_id:
            raise NotFound(key="multihop.server_not_found")
        return s

    @staticmethod
    def _xray_sp(server: m.Server) -> m.ServerProtocol:
        """Установленный и запущенный tcp-Reality Xray-протокол сервера (иначе BadRequest)."""
        sp = next((p for p in server.protocols if p.proto == CHAIN_PROTO), None)
        if not sp or not sp.installed or not sp.running:
            raise BadRequest(
                key="multihop.xray_not_running", params={"server": server.name}
            )
        if not sp.material_encrypted:
            raise BadRequest(
                key="multihop.xray_no_material", params={"server": server.name}
            )
        return sp

    async def list_for_entry(self, owner_id: str, sid: str) -> list[dict]:
        """Цепочки, где данный сервер — вход (entry). Показывается в секции «Цепочка» его страницы."""
        async with self.uow.query() as tx:
            await self._owned(tx, owner_id, sid)
            rows = (
                (
                    await tx.session.execute(
                        select(m.ChainLink).where(
                            m.ChainLink.owner_user_id == owner_id, m.ChainLink.entry_server_id == sid
                        )
                    )
                )
                .scalars()
                .all()
            )
            out = []
            for link in rows:
                exit_srv = await tx.servers.get(link.exit_server_id)
                out.append(chain_to_dict(link, exit_name=exit_srv.name if exit_srv else ""))
            return out

    async def create(self, owner_id: str, entry_sid: str, exit_sid: str) -> dict:
        """Связать entry → exit: завести клиента на exit и направить outbound entry на него.

        Валидация как у set_reality (owned/online/installed), затем два SSH-шага: add_client на exit
        и set_chain на entry. При сбое второго шага снимаем заведённого на exit клиента (best-effort),
        чтобы не копить висячие uuid.
        """
        if entry_sid == exit_sid:
            raise BadRequest(key="multihop.entry_exit_must_differ")

        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            entry = await self._owned(tx, owner_id, entry_sid)
            exit_srv = await self._owned(tx, owner_id, exit_sid)
            if entry.status != "online" or exit_srv.status != "online":
                raise BadRequest(key="multihop.both_servers_must_be_online")
            entry_sp = self._xray_sp(entry)
            exit_sp = self._xray_sp(exit_srv)
            existing = (
                await tx.session.execute(
                    select(m.ChainLink).where(
                        m.ChainLink.entry_server_id == entry_sid, m.ChainLink.proto == CHAIN_PROTO
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise BadRequest(key="multihop.chain_already_exists")
            exit_material = ServerMaterial.from_dict(prov._dec(exit_sp.material_encrypted))
            exit_ip, exit_port = exit_srv.ip, exit_sp.port

        # шаг 1: клиент на exit (entry предъявит его uuid как обычный vless-клиент)
        try:
            client = await prov.add_client(exit_srv, exit_sp, f"chain:{entry.name}")
        except Exception as e:
            raise BadRequest(
                key="multihop.exit_client_create_failed", params={"error": str(e)}
            ) from e

        # шаг 2: outbound entry → exit; при сбое откатываем клиента exit
        try:
            await prov.set_chain(
                entry,
                entry_sp,
                exit_host=exit_ip,
                exit_port=exit_port,
                exit_material=exit_material,
                exit_uuid=client.client_id,
            )
        except Exception as e:
            try:
                await prov.revoke_client(exit_srv, exit_sp, client.client_id)
            except Exception as rollback_err:
                log.warning("chain rollback failed", entry=entry_sid, exit=exit_sid, error=str(rollback_err))
            raise BadRequest(
                key="multihop.entry_chain_apply_failed", params={"error": str(e)}
            ) from e

        async with self.uow.transaction() as tx:
            link = m.ChainLink(
                owner_user_id=owner_id,
                entry_server_id=entry_sid,
                exit_server_id=exit_sid,
                proto=CHAIN_PROTO,
                exit_client_id=client.client_id,
                state="linked",
            )
            tx.session.add(link)
            await tx.session.flush()
            return chain_to_dict(link, exit_name=exit_srv.name)

    async def delete(self, owner_id: str, entry_sid: str, chain_id: str) -> dict:
        """Снять цепочку: вернуть outbound entry к freedom и снять клиента exit (оба best-effort)."""
        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            entry = await self._owned(tx, owner_id, entry_sid)
            link = await tx.session.get(m.ChainLink, chain_id)
            if link is None or link.owner_user_id != owner_id or link.entry_server_id != entry_sid:
                raise NotFound(key="multihop.chain_not_found")
            exit_srv = await tx.servers.get(link.exit_server_id)
            entry_sp = next((p for p in entry.protocols if p.proto == link.proto), None)
            exit_sp = next((p for p in exit_srv.protocols if p.proto == link.proto), None) if exit_srv else None
            exit_client_id = link.exit_client_id

        if entry_sp is not None and entry_sp.installed and entry_sp.material_encrypted:
            try:
                await prov.clear_chain(entry, entry_sp)
            except Exception as e:
                log.warning("chain clear failed", entry=entry_sid, error=str(e))
        if exit_srv is not None and exit_sp is not None and exit_client_id and exit_sp.material_encrypted:
            try:
                await prov.revoke_client(exit_srv, exit_sp, exit_client_id)
            except Exception as e:
                log.warning("chain exit revoke failed", exit=link.exit_server_id, error=str(e))

        async with self.uow.transaction() as tx:
            obj = await tx.session.get(m.ChainLink, chain_id)
            if obj is not None:
                await tx.session.delete(obj)
        return {"ok": True}
