"""Обзор доступа к серверу со стороны владельца.

Показывает, где сервер используется (пулы/группы) и кто им пользуется (пользователи + их
выданные конфиги), с возможностью переименовать/отозвать конкретный конфиг (пир).
"""

from __future__ import annotations

import json
import time

from sqlalchemy import select

from vpnhub.api.config import Settings
from vpnhub.core import audit_types
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.provisioners.base import read_clients_table
from vpnhub.infra.provisioning.ssh import SshClient, SshError
from vpnhub.infra.security import decrypt_secret
from vpnhub.infra.uow import Uow, UowTransaction
from vpnhub.services.limits import used_clients
from vpnhub.services.provisioning import PROVISIONED_VENDORS, ProvisioningService

# из material отдаём только публичное (приватные ключи/psk наружу не уходят).
# short_id/site публичны сами по себе — они видны в vless://-ссылке; нужны UI для формы Reality.
_PUBLIC_MATERIAL = ("server_public_key", "xray_public_key", "short_id", "site")


class ServerAccessService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    async def _owned(self, tx: UowTransaction, owner_id: str, sid: str) -> m.Server:
        s: m.Server | None = await tx.servers.get(sid)
        if not s or s.owner_user_id != owner_id:
            raise NotFound("Сервер не найден")
        return s

    async def overview(self, owner_id: str, sid: str) -> dict:
        async with self.uow.query() as tx:
            await self._owned(tx, owner_id, sid)

            # пулы, в которые входит сервер
            pool_ids = set(await tx.pools.pools_with_server(sid))
            pools = []
            for pid in pool_ids:
                p = await tx.pools.get(pid)
                if p:
                    pools.append({"id": p.id, "name": p.name})

            # группы владельца, у которых есть доступ к серверу (через пул или напрямую)
            groups_out: list[dict] = []
            access_users: dict[str, set[str]] = {}  # user_id -> имена групп-источников
            for g in await tx.groups.for_owner(owner_id):
                g_pools = set(await tx.groups.pool_ids(g.id))
                via_pools = [p["name"] for p in pools if p["id"] in g_pools]
                srv_access = await tx.groups.server_access(g.id)
                direct = sid in srv_access
                if not via_pools and not direct:
                    continue
                via = "пул " + ", ".join(via_pools) if via_pools else "напрямую"
                groups_out.append(
                    {
                        "id": g.id,
                        "name": g.name,
                        "via": via,
                        "vpns": srv_access.get(sid, []) if direct else [],
                    }
                )
                for mb in g.members:
                    if mb.user_id and mb.status == "active":
                        access_users.setdefault(mb.user_id, set()).add(g.name)

            # выданные конфиги на этом сервере: DeviceConfig ⋈ Device
            rows = (
                await tx.session.execute(
                    select(m.DeviceConfig, m.Device)
                    .join(m.Device, m.Device.id == m.DeviceConfig.device_id)
                    .where(m.DeviceConfig.server_id == sid)
                )
            ).all()
            configs_by_user: dict[str, list[dict]] = {}
            for cfg, dev in rows:
                configs_by_user.setdefault(dev.user_id, []).append(
                    {
                        "id": cfg.id,
                        "device": dev.name,
                        "platform": dev.platform,
                        "proto": cfg.proto or cfg.vpn_type,
                        "vpnType": cfg.vpn_type,
                        "clientName": cfg.client_name or "",
                        "status": cfg.status,
                    }
                )

            # объединяем: пользователи с доступом ∪ те, у кого уже есть конфиги
            users: list[dict] = []
            for uid in set(access_users) | set(configs_by_user):
                u = await tx.users.get(uid)
                if not u:
                    continue
                users.append(
                    {
                        "userId": u.id,
                        "name": u.name,
                        "phone": u.phone,
                        "hasAccess": uid in access_users,
                        "groups": sorted(access_users.get(uid, set())),
                        "configs": configs_by_user.get(uid, []),
                    }
                )
            users.sort(key=lambda x: (not x["hasAccess"], x["name"].lower()))

            return {"pools": pools, "groups": groups_out, "users": users}

    async def vpn_advanced(self, owner_id: str, sid: str, vtype: str) -> dict:
        """Advanced-режим по вендору VPN: контейнеры/протоколы (сырые параметры, публичные
        ключи) + пиры-клиенты. Приватные ключи и psk наружу не отдаём."""
        async with self.uow.query() as tx:
            s = await self._owned(tx, owner_id, sid)

            protocols = []
            for p in sorted((sp for sp in s.protocols if sp.vendor == vtype), key=lambda x: x.proto):
                params = None
                if p.params_json:
                    try:
                        params = json.loads(p.params_json)
                    except Exception:
                        params = None
                keys: dict[str, str] = {}
                if p.material_encrypted:
                    try:
                        mat = json.loads(decrypt_secret(self.settings.secret_key, p.material_encrypted))
                        keys = {k: mat[k] for k in _PUBLIC_MATERIAL if mat.get(k)}
                    except Exception:
                        keys = {}
                spec = pc.spec_by_id(p.proto)
                protocols.append(
                    {
                        "proto": p.proto,
                        "label": spec.label if spec else p.proto,
                        "container": p.container,
                        "port": p.port,
                        "state": p.state,
                        "installed": p.installed,
                        "running": p.running,
                        "error": p.error,
                        "externalClients": p.external_clients,
                        "params": params,
                        "keys": keys,
                        # лимит числа конфигов (soft-cap владельца; null = без лимита) + текущая занятость
                        "maxClients": p.max_clients,
                        "usedClients": await used_clients(tx.session, p),
                    }
                )

            rows = (
                await tx.session.execute(
                    select(m.DeviceConfig, m.Device)
                    .join(m.Device, m.Device.id == m.DeviceConfig.device_id)
                    .where(m.DeviceConfig.server_id == sid, m.DeviceConfig.vpn_type == vtype)
                )
            ).all()
            clients = []
            for cfg, dev in rows:
                u = await tx.users.get(dev.user_id)
                clients.append(
                    {
                        "id": cfg.id,
                        "clientName": cfg.client_name or "",
                        "user": u.name if u else "",
                        "device": dev.name,
                        "proto": cfg.proto or "",
                        "clientIp": cfg.client_ip or "",
                        "clientId": cfg.client_public_key or cfg.client_id or "",
                        "status": cfg.status,
                    }
                )

            return {"vendor": vtype, "protocols": protocols, "clients": clients}

    async def external_clients(self, owner_id: str, sid: str, vtype: str) -> dict:
        """Живое чтение внешних клиентов (заведённых мимо панели) по SSH: живой список минус наши id.

        Amnezia/OpenVPN читают clientsTable в контейнере; Outline — access-key через Management API
        (clientsTable у него нет), поэтому там список берём из провизионера."""
        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            s = await self._owned(tx, owner_id, sid)
            rows = (
                (
                    await tx.session.execute(
                        select(m.DeviceConfig).where(m.DeviceConfig.server_id == sid, m.DeviceConfig.vpn_type == vtype)
                    )
                )
                .scalars()
                .all()
            )
            our_ids = {(c.client_public_key or c.client_id) for c in rows if (c.client_public_key or c.client_id)}
            protos = [p.proto for p in s.protocols if p.vendor == vtype and p.installed and p.running]
            # провизионеры для протоколов без clientsTable (outline) — с материалом, из БД
            api_provs = {
                p.proto: prov.loaded_provisioner(p)
                for p in s.protocols
                if p.vendor == vtype
                and p.installed
                and p.running
                and p.material_encrypted
                and pc.spec_by_id(p.proto).kind == "outline"
            }
            server = s

        if server.status != "online":
            raise BadRequest("Сервер офлайн — внешних клиентов не прочитать")

        result: list[dict] = []
        try:
            async with SshClient(prov.creds(server)) as ssh:
                for pid in protos:
                    spec = pc.spec_by_id(pid)
                    try:
                        table = (
                            await api_provs[pid].list_clients(ssh)
                            if pid in api_provs
                            else await read_clients_table(ssh, spec)
                        )
                    except Exception:
                        table = []
                    ext = []
                    for row in table:
                        cid = row.get("clientId")
                        if cid and cid not in our_ids:
                            name = (row.get("userData") or {}).get("clientName") or ""
                            ext.append({"id": cid, "name": name})
                    if ext:
                        result.append({"proto": pid, "label": spec.label, "clients": ext})
        except SshError as e:
            raise BadRequest(f"Не удалось подключиться к серверу: {e}") from e

        return {"external": result}

    async def rename_client(self, owner_id: str, sid: str, config_id: str, name: str) -> dict:
        name = (name or "").strip()
        if not name:
            raise BadRequest("Введите имя конфига")
        async with self.uow.transaction() as tx:
            await self._owned(tx, owner_id, sid)
            cfg = await tx.session.get(m.DeviceConfig, config_id)
            if not cfg or cfg.server_id != sid:
                raise NotFound("Конфиг не найден")
            cfg.client_name = name
            await tx.session.flush()
        return {"ok": True}

    async def revoke_client(self, owner_id: str, sid: str, config_id: str) -> dict:
        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            await self._owned(tx, owner_id, sid)
            cfg = await tx.session.get(m.DeviceConfig, config_id)
            if not cfg or cfg.server_id != sid:
                raise NotFound("Конфиг не найден")
            vpn_type, proto, client_id, cfg_id = cfg.vpn_type, cfg.proto, cfg.client_id, cfg.id
            device_id, client_name = cfg.device_id, cfg.client_name

        # снять пир на сервере (best-effort через provisioning), затем удалить запись
        if vpn_type in PROVISIONED_VENDORS and client_id:
            await prov.revoke_on_servers([(sid, proto or "", client_id)])

        async with self.uow.transaction() as tx:
            obj = await tx.session.get(m.DeviceConfig, cfg_id)
            if obj is not None:
                await tx.session.delete(obj)
            owner = await tx.users.get(owner_id)
            tx.audit.add_event(
                at=time.time(),
                actor_kind="admin" if owner and await tx.admins.is_admin(owner_id) else "user",
                actor_id=owner_id,
                actor_name=owner.name if owner else "",
                type_=audit_types.ACCESS_REVOKE,
                target_kind="server",
                target_id=sid,
                owner_user_id=owner_id,
                meta_json=json.dumps(
                    {"vpn": vpn_type, "proto": proto, "deviceId": device_id, "clientName": client_name},
                    ensure_ascii=False,
                ),
            )
        return {"ok": True}

    async def set_paused(self, owner_id: str, sid: str, config_id: str, *, pause: bool) -> dict:
        """Ручная пауза/старт доступа по конфигу (владелец). Использует тот же suspend/resume-механизм,
        что и лимит трафика (Этап 3b), но помечает конфиг статусом "paused" — авто-реконсиляция лимита
        (status IN active/suspended) его НЕ трогает, поэтому ручная пауза не воюет с лимитом.
        """
        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            await self._owned(tx, owner_id, sid)
            cfg = await tx.session.get(m.DeviceConfig, config_id)
            if not cfg or cfg.server_id != sid:
                raise NotFound("Конфиг не найден")
            if cfg.vpn_type not in PROVISIONED_VENDORS or not cfg.client_id:
                raise BadRequest("Этот конфиг нельзя приостановить")
            ref = (sid, cfg.proto or "", prov.material_from_config(cfg))
            cfg_id, client_id = cfg.id, cfg.client_id

        # применяем на сервере ПЕРЕД сменой статуса: если сервер недоступен — статус не меняем
        done = await (prov.suspend_configs([ref]) if pause else prov.resume_configs([ref]))
        if client_id not in done:
            raise BadRequest("Сервер недоступен — не удалось изменить состояние конфига")

        new_status = "paused" if pause else "active"
        async with self.uow.transaction() as tx:
            obj = await tx.session.get(m.DeviceConfig, cfg_id)
            if obj is not None:
                obj.status = new_status
            owner = await tx.users.get(owner_id)
            tx.audit.add_event(
                at=time.time(),
                actor_kind="admin" if owner and await tx.admins.is_admin(owner_id) else "user",
                actor_id=owner_id,
                actor_name=owner.name if owner else "",
                type_=audit_types.ACCESS_REVOKE,
                target_kind="server",
                target_id=sid,
                owner_user_id=owner_id,
                meta_json=json.dumps(
                    {"action": "pause" if pause else "resume", "configId": cfg_id}, ensure_ascii=False
                ),
            )
        return {"ok": True, "status": new_status}
