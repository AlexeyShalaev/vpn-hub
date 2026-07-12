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
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.provisioners.base import ServerMaterial
from vpnhub.infra.uow import Uow, UowTransaction
from vpnhub.services.provisioning import ProvisioningService

log = structlog.get_logger(__name__)

# Мультихоп поддержан для СЕМЕЙСТВА Xray (VLESS+Reality): xray (tcp) и xray_xhttp (XHTTP). entry
# предъявляет обычный vless-клиент exit; транспорт outbound на entry подстраивается под exit-протокол.
_DEFAULT_CHAIN_PROTO = "xray"


def _is_chain_proto(proto: str) -> bool:
    """Пригоден ли протокол для мультихопа — семейство Xray (VLESS+Reality: xray / xray_xhttp)."""
    try:
        return pc.spec_by_id(proto).kind == "xray"
    except KeyError:
        return False


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
    def _chain_sp(server: m.Server, proto: str) -> m.ServerProtocol:
        """Установленный и запущенный Xray-семейства протокол `proto` сервера (иначе BadRequest)."""
        if not _is_chain_proto(proto):
            raise BadRequest(key="multihop.proto_not_chainable", params={"proto": proto})
        sp = next((p for p in server.protocols if p.proto == proto), None)
        if not sp or not sp.installed or not sp.running:
            raise BadRequest(key="multihop.xray_not_running", params={"server": server.name})
        if not sp.material_encrypted:
            raise BadRequest(key="multihop.xray_no_material", params={"server": server.name})
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

    async def create(
        self,
        owner_id: str,
        entry_sid: str,
        exit_sid: str,
        *,
        entry_proto: str = _DEFAULT_CHAIN_PROTO,
        exit_proto: str = _DEFAULT_CHAIN_PROTO,
    ) -> dict:
        """Связать entry(entry_proto) → exit(exit_proto): завести клиента на exit и направить на него
        outbound entry-контейнера. Транспорт outbound строится под exit-протокол (tcp | xhttp+path).

        Валидация (owned/online/installed на нужном протоколе), затем два SSH-шага: add_client на exit
        и set_chain на entry. При сбое второго шага снимаем заведённого на exit клиента (best-effort).
        """
        if entry_sid == exit_sid:
            raise BadRequest(key="multihop.entry_exit_must_differ")

        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            entry = await self._owned(tx, owner_id, entry_sid)
            exit_srv = await self._owned(tx, owner_id, exit_sid)
            if entry.status != "online" or exit_srv.status != "online":
                raise BadRequest(key="multihop.both_servers_must_be_online")
            entry_sp = self._chain_sp(entry, entry_proto)
            exit_sp = self._chain_sp(exit_srv, exit_proto)
            existing = (
                await tx.session.execute(
                    select(m.ChainLink).where(
                        m.ChainLink.entry_server_id == entry_sid, m.ChainLink.proto == entry_proto
                    )
                )
            ).scalar_one_or_none()
            if existing is not None:
                raise BadRequest(key="multihop.chain_already_exists")
            exit_material = ServerMaterial.from_dict(prov._dec(exit_sp.material_encrypted))
            exit_ip, exit_port = exit_srv.ip, exit_sp.port
            # транспорт outbound на entry обязан совпасть с inbound exit-контейнера
            exit_network = "xhttp" if pc.spec_by_id(exit_proto).xray_network == "xhttp" else "tcp"
            exit_path = exit_material.xhttp_path or ""

        # шаг 1: клиент на exit (entry предъявит его uuid как обычный vless-клиент)
        try:
            client = await prov.add_client(exit_srv, exit_sp, f"chain:{entry.name}")
        except Exception as e:
            raise BadRequest(key="multihop.exit_client_create_failed", params={"error": str(e)}) from e

        # шаг 2: outbound entry → exit (под транспорт exit); при сбое откатываем клиента exit
        try:
            await prov.set_chain(
                entry,
                entry_sp,
                exit_host=exit_ip,
                exit_port=exit_port,
                exit_material=exit_material,
                exit_uuid=client.client_id,
                exit_network=exit_network,
                exit_path=exit_path,
            )
        except Exception as e:
            try:
                await prov.revoke_client(exit_srv, exit_sp, client.client_id)
            except Exception as rollback_err:
                log.warning("chain rollback failed", entry=entry_sid, exit=exit_sid, error=str(rollback_err))
            raise BadRequest(key="multihop.entry_chain_apply_failed", params={"error": str(e)}) from e

        async with self.uow.transaction() as tx:
            link = m.ChainLink(
                owner_user_id=owner_id,
                entry_server_id=entry_sid,
                exit_server_id=exit_sid,
                proto=entry_proto,
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
            # exit-протокол цепочки не хранится, поэтому клиента снимаем на том Xray-контейнере exit,
            # где он реально есть (иначе лишний рестарт другого контейнера уронил бы его сессии).
            exit_sps = (
                [p for p in exit_srv.protocols if _is_chain_proto(p.proto) and p.installed and p.material_encrypted]
                if exit_srv is not None
                else []
            )
            exit_client_id = link.exit_client_id

        if entry_sp is not None and entry_sp.installed and entry_sp.material_encrypted:
            try:
                await prov.clear_chain(entry, entry_sp)
            except Exception as e:
                log.warning("chain clear failed", entry=entry_sid, error=str(e))
        if exit_srv is not None and exit_client_id:
            for exit_sp in exit_sps:
                try:
                    if exit_client_id in await prov.client_ids(exit_srv, exit_sp):
                        await prov.revoke_client(exit_srv, exit_sp, exit_client_id)
                        break
                except Exception as e:
                    log.warning("chain exit revoke failed", exit=link.exit_server_id, proto=exit_sp.proto, error=str(e))

        async with self.uow.transaction() as tx:
            obj = await tx.session.get(m.ChainLink, chain_id)
            if obj is not None:
                await tx.session.delete(obj)
        return {"ok": True}
