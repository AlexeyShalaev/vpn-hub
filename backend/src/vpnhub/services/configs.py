"""Получение конфига участником.

Все вендоры (Amnezia / OpenVPN / Outline) — реальный provisioning: при первом запросе на
устройство добавляется пир/клиент на сервере (SSH), материал сохраняется в DeviceConfig, далее
конфиг пересобирается из него.
"""

from __future__ import annotations

import json
import time
from typing import Any

from vpnhub.api.config import Settings
from vpnhub.common.catalog import PROTOS, clients_for
from vpnhub.core import audit_types
from vpnhub.core.errors import BadRequest, Forbidden, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning import vpn_uri
from vpnhub.infra.provisioning.errors import ProvisioningError
from vpnhub.infra.provisioning.provisioners import ClientMaterial
from vpnhub.infra.provisioning.ssh import SshClient, SshError
from vpnhub.infra.security import decrypt_secret, encrypt_secret
from vpnhub.infra.uow import Uow, UowTransaction
from vpnhub.services.access import effective_access
from vpnhub.services.limits import (
    effective_byte_limit,
    fmt_bytes,
    over_limit,
    period_start,
    period_usage,
    used_clients,
)
from vpnhub.services.provisioning import PROVISIONED_VENDORS, ProvisioningService

# протоколы Amnezia, которые объединяются в один vpn:// (multi-container).
# xray_xhttp исключён: в клиенте нет контейнера amnezia-xray-xhttp — его отдаём отдельным vless://.
_BUNDLABLE_AMNEZIA = ("awg", "awg_legacy", "xray")


def _amnezia_formats(artifact: Any, server_name: str, proto_id: str) -> list[dict]:
    """Форматы экспорта как в клиенте Amnezia: файл .vpn (приложение) и/или нативный .conf / vless."""
    base = (server_name or "amnezia").replace(" ", "_")
    fmts: list[dict] = []
    if artifact.vpn_url:
        fmts.append(
            {
                "id": "amnezia",
                "label": "AmneziaVPN",
                "sub": "для приложения AmneziaVPN",
                "text": artifact.vpn_url,
                "filename": f"{base}-{proto_id}.vpn",
                "qr": artifact.vpn_url,
            }
        )
    if artifact.conf_text:
        fmts.append(
            {
                "id": "native",
                "label": "WireGuard",
                "sub": "нативный .conf — WG-приложение или роутер",
                "text": artifact.conf_text,
                "filename": f"{base}-{proto_id}.conf",
                "qr": artifact.conf_text,
            }
        )
    if artifact.vless_url:
        fmts.append(
            {
                "id": "xray",
                "label": "Xray",
                "sub": "AmneziaVPN / v2RayTun",
                "text": artifact.vless_url,
                "filename": f"{base}-xray.txt",
                "qr": artifact.vless_url,
            }
        )
    return fmts


def _openvpn_formats(artifact: Any, server_name: str) -> list[dict]:
    """Единственный формат OpenVPN — файл .ovpn с инлайн-сертификатами.

    В qr кладём тот же .ovpn (как amnezia native .conf): он заведомо больше ёмкости QR,
    поэтому фронт покажет подсказку «слишком большой для QR — используйте файл», а не спиннер."""
    base = (server_name or "openvpn").replace(" ", "_")
    return [
        {
            "id": "openvpn",
            "label": "OpenVPN",
            "sub": "файл .ovpn — OpenVPN Connect / роутер",
            "text": artifact.conf_text,
            "filename": artifact.filename or f"{base}-openvpn.ovpn",
            "qr": artifact.conf_text,
        }
    ]


def _outline_formats(artifact: Any, server_name: str) -> list[dict]:
    """Единственный формат Outline — ключ ss:// (accessUrl). QR помещается легко (короткий)."""
    base = (server_name or "outline").replace(" ", "_")
    ss = artifact.vpn_url or artifact.conf_text
    return [
        {
            "id": "outline",
            "label": "Outline",
            "sub": "ключ ss:// — приложение Outline",
            "text": ss,
            "filename": artifact.filename or f"{base}-outline.txt",
            "qr": ss,
        }
    ]


def _hysteria2_formats(artifact: Any, server_name: str) -> list[dict]:
    """Единственный формат Hysteria2 — ссылка hysteria2:// (в conf_text и vpn_url). QR помещается."""
    base = (server_name or "hysteria2").replace(" ", "_")
    url = artifact.vpn_url or artifact.conf_text
    return [
        {
            "id": "hysteria2",
            "label": "Hysteria2",
            "sub": "ссылка hysteria2:// — Hiddify / Karing / sing-box",
            "text": url,
            "filename": artifact.filename or f"{base}-hysteria2.txt",
            "qr": url,
        }
    ]


def _provisioned_formats(vpn_type: str, artifact: Any, server_name: str, proto_id: str) -> list[dict]:
    if vpn_type == pc.VENDOR_OUTLINE:
        return _outline_formats(artifact, server_name)
    if vpn_type == pc.VENDOR_OPENVPN:
        return _openvpn_formats(artifact, server_name)
    if vpn_type == pc.VENDOR_HYSTERIA2:
        return _hysteria2_formats(artifact, server_name)
    return _amnezia_formats(artifact, server_name, proto_id)


class ConfigService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    # ------------------------------------------------------------- generate ---

    async def generate(
        self,
        user_id: str,
        server_id: str,
        vpn_type: str,
        device_id: str | None,
        proto: str | None,
        peek: bool = False,
        bundle: bool = True,
    ) -> dict:
        """peek=True: вернуть только список протоколов/клиентов для выбора в модалке БЕЗ провижининга
        (не создаёт клиента на сервере и не собирает бандл). Реальная выдача — с peek=False.

        bundle=True (по умолчанию): для amnezia склеиваемые протоколы (awg/awg_legacy/xray) выдаются
        одним vpn://. bundle=False: выдаётся ТОЛЬКО запрошенный протокол (по одному), даже если он
        склеиваемый — так пользователь может получить конфиг конкретного протокола."""
        async with self.uow.query() as tx:
            access, _ = await effective_access(tx, user_id)
            if vpn_type not in access.get(server_id, set()):
                raise Forbidden(key="config.no_vpn_access")
            s = await tx.servers.get(server_id)
            if not s:
                raise NotFound(key="config.server_not_found")
            platform = "ios"
            if device_id:
                d = await tx.devices.get(device_id)
                if d and d.user_id == user_id:
                    platform = d.platform

        if vpn_type not in PROVISIONED_VENDORS:
            raise BadRequest(key="config.unknown_vpn_type")
        return await self._generate_provisioned(vpn_type, user_id, server_id, device_id, proto, platform, peek, bundle)

    async def _generate_provisioned(
        self,
        vpn_type: str,
        user_id: str,
        server_id: str,
        device_id: str | None,
        proto: str | None,
        platform: str,
        peek: bool = False,
        bundle: bool = True,
    ) -> dict:
        if not device_id:
            raise BadRequest(key="config.select_device")
        # запрошенный протокол должен принадлежать вендору; иначе решаем по установленным ниже
        requested = pc.spec_by_label(proto or "")
        if requested is not None and requested.vendor != vpn_type:
            requested = None

        prov = ProvisioningService(self.uow, self.settings)

        # фаза 1: читаем состояние, готовим провизионер и креды (плоские значения)
        async with self.uow.query() as tx:
            s = await self._owned_server(tx, server_id)
            device = await tx.devices.get(device_id)
            if not device or device.user_id != user_id:
                raise NotFound(key="config.device_not_found")
            # только установленные протоколы вендора (в каталожном порядке) — их отдаём и из них выбираем
            installed_ids = {p.proto for p in s.protocols if p.vendor == vpn_type and p.installed}
            installed_labels = [
                lbl for lbl in PROTOS.get(vpn_type, []) if (x := pc.spec_by_label(lbl)) and x.id in installed_ids
            ]
            # выбранный протокол должен быть установлен; иначе — первый установленный протокол вендора
            spec = (
                requested
                if (requested and requested.id in installed_ids)
                else (pc.spec_by_label(installed_labels[0]) if installed_labels else None)
            )
            if spec is None:
                raise BadRequest(key="config.proto_not_installed")
            # «Все протоколы» (bundle) без явно запрошенного протокола: подставляем первый склеиваемый,
            # чтобы объединённый vpn:// точно собрался. Явный выбор (в т.ч. xray_xhttp) НЕ трогаем —
            # тогда bundle=False по факту (несклеиваемый) и отдаётся конфиг именно этого протокола.
            if bundle and vpn_type == pc.VENDOR_AMNEZIA and requested is None and spec.id not in _BUNDLABLE_AMNEZIA:
                bundlable = [
                    lbl for lbl in installed_labels if (x := pc.spec_by_label(lbl)) and x.id in _BUNDLABLE_AMNEZIA
                ]
                if bundlable and (nb := pc.spec_by_label(bundlable[0])):
                    spec = nb
            sp = next(p for p in s.protocols if p.proto == spec.id)
            server_ip, server_name, port = s.ip, s.name, sp.port
            server_owner_id = s.owner_user_id
            creds = prov.creds(s)
            prov_obj = prov.loaded_provisioner(sp)
            user = await tx.users.get(user_id)
            client_name = self._client_name(user, device)
            existing = self._find_config(device, server_id, spec)
            client = self._client_from_config(existing) if existing else None
            # лимит конфигов на протоколе (soft-cap владельца): проверяем только на НОВУЮ выдачу
            if existing is None and sp.max_clients is not None:
                used = await used_clients(tx.session, sp)
                if over_limit(used, sp.max_clients):
                    raise BadRequest(
                        key="config.limit_reached",
                        params={"proto": spec.label, "used": used, "max": sp.max_clients},
                    )
            # лимит трафика per (user, server) за биллинг-период: блок выдачи НОВОГО конфига при превышении
            # (уже выданные конфиги отсекаются отдельно — Этап 3b; здесь только мягкий блок новых)
            if existing is None:
                byte_limit = await effective_byte_limit(tx.session, user_id)
                if byte_limit is not None:
                    ps = period_start(time.time(), s.billing_day)
                    urx, utx = await period_usage(tx.session, server_id, user_id, ps)
                    if urx + utx >= byte_limit:
                        raise BadRequest(
                            key="config.traffic_limit_reached",
                            params={
                                "server": server_name,
                                "used": fmt_bytes(urx + utx),
                                "limit": fmt_bytes(byte_limit),
                            },
                        )

        # установленные amnezia-протоколы, что склеиваются в ОДИН vpn:// (awg/awg_legacy/xray).
        # UI выдаёт их одной кнопкой «все сразу»; xray_xhttp и прочие вендоры сюда не входят.
        bundle_labels = (
            [lbl for lbl in installed_labels if (x := pc.spec_by_label(lbl)) and x.id in _BUNDLABLE_AMNEZIA]
            if vpn_type == pc.VENDOR_AMNEZIA
            else []
        )

        # peek: только метаданные для выбора в модалке (протоколы + приложения) — БЕЗ провижининга
        # (не создаём клиента и не собираем бандл, иначе выбор устройства/протокола сам бы выдал конфиг).
        if peek:
            clients = clients_for(vpn_type, platform)
            if spec.kind == "xray":
                clients = [c for c in clients if not c.get("wgOnly")]
            return {
                "type": vpn_type,
                "proto": spec.label,
                "filename": "",
                "text": "",
                "uri": "",
                "hint": "",
                "clients": clients,
                "protos": installed_labels,
                "bundle": bundle_labels,
                "serverId": server_id,
                "formats": [],
            }

        # фаза 2: если материала нет — добавляем клиента на сервере и сохраняем
        if client is None:
            try:
                async with SshClient(creds) as ssh:
                    client = await prov_obj.add_client(ssh, server_ip, port, client_name)
            except (SshError, ProvisioningError) as e:
                raise BadRequest(key="config.create_failed", params={"error": str(e)}) from e
            await self._persist_client(device_id, server_id, spec, client, client_name)

        artifact = prov_obj.build_artifact(server_ip=server_ip, port=port, server_name=server_name, client=client)
        clients = clients_for(vpn_type, platform)
        if spec.kind == "xray":
            clients = [c for c in clients if not c.get("wgOnly")]
        text = artifact.conf_text or artifact.vless_url
        uri = artifact.vpn_url or artifact.vless_url
        formats = _provisioned_formats(vpn_type, artifact, server_name, spec.id)
        # Amnezia: формат «AmneziaVPN» (.vpn) = ОДИН vpn:// со всеми склеиваемыми протоколами сервера
        # (awg2/awg_legacy/xray). Подмешиваем его, только когда запрошен бандл (bundle=True) и выбран
        # склеиваемый протокол. При bundle=False (выдача по одному) или xray_xhttp — свой конфиг протокола.
        if bundle and vpn_type == pc.VENDOR_AMNEZIA and spec.id in _BUNDLABLE_AMNEZIA:
            bundle_uri = await self._build_amnezia_bundle(user_id, server_id, device_id)
            formats = self._with_bundle_format(formats, bundle_uri, server_name)
            if bundle_uri:
                uri = bundle_uri
        await self._audit_download(user_id, server_id, server_owner_id, vpn_type, spec, device_id)
        return {
            "type": vpn_type,
            "proto": spec.label,
            "filename": artifact.filename,
            "text": text,
            "uri": uri,
            "hint": artifact.hint,
            "clients": clients,
            "protos": installed_labels,
            "bundle": bundle_labels,
            "serverId": server_id,
            "formats": formats,
        }

    @staticmethod
    def _with_bundle_format(formats: list[dict], bundle: str | None, server_name: str) -> list[dict]:
        """Заменить одиночный формат amnezia на объединённый .vpn (бандл всех протоколов сервера)."""
        out = [f for f in formats if f.get("id") != "amnezia"]
        if bundle:
            base = (server_name or "amnezia").replace(" ", "_")
            out.insert(
                0,
                {
                    "id": "amnezia",
                    "label": "AmneziaVPN",
                    "sub": "все протоколы в одном сервере",
                    "text": bundle,
                    "filename": f"{base}.vpn",
                    "qr": bundle,
                },
            )
        return out

    async def _build_amnezia_bundle(self, user_id: str, server_id: str, device_id: str | None) -> str | None:
        """Собрать ОДИН vpn:// со всеми установленными бандлящимися amnezia-протоколами сервера.

        Клиент импортирует его как один сервер с переключателем протоколов. Для протоколов без
        активного конфига на устройстве создаём клиента (одна SSH-сессия), затем строим containers[].
        SSH нужен только на первую выдачу — потом конфиги переиспользуются из DeviceConfig.
        """
        if not device_id:
            return None
        prov = ProvisioningService(self.uow, self.settings)
        # фаза 1: план (spec, port, provisioner, существующий клиент) по установленным протоколам
        async with self.uow.query() as tx:
            s = await self._owned_server(tx, server_id)
            device = await tx.devices.get(device_id)
            if not device or device.user_id != user_id:
                return None
            user = await tx.users.get(user_id)
            client_name = self._client_name(user, device)
            server_ip, server_name = s.ip, s.name
            creds = prov.creds(s)
            plan: list[tuple[pc.ProtoSpec, str, Any, ClientMaterial | None]] = []
            for sp in s.protocols:
                if sp.vendor != pc.VENDOR_AMNEZIA or not sp.installed or sp.proto not in _BUNDLABLE_AMNEZIA:
                    continue
                spec = pc.spec_by_id(sp.proto)
                existing = self._find_config(device, server_id, spec)
                client = self._client_from_config(existing) if existing else None
                plan.append((spec, sp.port, prov.loaded_provisioner(sp), client))
        if not plan:
            return None
        plan.sort(key=lambda t: _BUNDLABLE_AMNEZIA.index(t[0].id))

        # фаза 2: для протоколов без клиента — add_client в ОДНОЙ SSH-сессии, затем persist
        missing = [(spec, port, provisioner) for spec, port, provisioner, client in plan if client is None]
        created: dict[str, ClientMaterial] = {}
        if missing:
            try:
                async with SshClient(creds) as ssh:
                    for spec, port, provisioner in missing:
                        created[spec.id] = await provisioner.add_client(ssh, server_ip, port, client_name)
            except (SshError, ProvisioningError) as e:
                raise BadRequest(key="config.create_failed", params={"error": str(e)}) from e
            for spec, _port, _prov in missing:
                await self._persist_client(device_id, server_id, spec, created[spec.id], client_name)

        # фаза 3: собрать containers[] (без SSH)
        containers: list[dict] = []
        default_container = ""
        for spec, port, provisioner, client in plan:
            cm = client or created.get(spec.id)
            if cm is None:
                continue
            containers.append(
                provisioner.build_container(server_ip=server_ip, port=port, server_name=server_name, client=cm)
            )
            if spec.id == "xray":  # xray-reality — предпочтительный defaultContainer клиента
                default_container = spec.container
        if not containers:
            return None
        return vpn_uri.build_bundle_vpn_url(
            containers=containers,
            host=server_ip,
            description=server_name,
            default_container=default_container or containers[0]["container"],
        )

    # -------------------------------------------------------------- install ---

    async def install(
        self, user_id: str, server_id: str, vpn_type: str, device_id: str, proto: str | None, bundle: bool = True
    ) -> dict:
        if not device_id:
            raise BadRequest(key="config.select_device")
        if vpn_type in PROVISIONED_VENDORS:
            # реальный provisioning: создаст клиента на сервере и сохранит DeviceConfig
            await self._generate_provisioned(
                vpn_type, user_id, server_id, device_id, proto, platform="ios", bundle=bundle
            )
            return {"ok": True}
        # outline — только пометка на устройстве
        async with self.uow.transaction() as tx:
            d = await tx.devices.get(device_id)
            if not d or d.user_id != user_id:
                raise NotFound(key="config.device_not_found")
            for c in list(d.configs):
                if c.server_id == server_id and c.vpn_type == vpn_type and c.proto == proto:
                    await tx.session.delete(c)
            tx.session.add(m.DeviceConfig(device_id=device_id, server_id=server_id, vpn_type=vpn_type, proto=proto))
            await tx.session.flush()
            return {"ok": True}

    # --------------------------------------------------------------- remove ---

    async def remove(self, user_id: str, server_id: str, vpn_type: str, device_id: str, proto: str | None) -> dict:
        """Снять конфиг с устройства + отозвать клиента на сервере (симметрично generate)."""
        if not device_id:
            raise BadRequest(key="config.select_device")
        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            d = await tx.devices.get(device_id)
            if not d or d.user_id != user_id:
                raise NotFound(key="config.device_not_found")
            target = next(
                (c for c in d.configs if c.server_id == server_id and c.vpn_type == vpn_type and c.proto == proto),
                None,
            )
            if target is None:
                return {"ok": True}
            cfg_id, client_id = target.id, target.client_id or ""

        if vpn_type in PROVISIONED_VENDORS and client_id:
            await prov.revoke_on_servers([(server_id, proto or "", client_id)])

        async with self.uow.transaction() as tx:
            obj = await tx.session.get(m.DeviceConfig, cfg_id)
            if obj is not None:
                await tx.session.delete(obj)
        return {"ok": True}

    # --------------------------------------------------------------- helpers ---

    @staticmethod
    def _client_name(user: m.User | None, device: m.Device) -> str:
        uname = (user.name if user and user.name else "").strip()
        dname = (device.name or "").strip() or "устройство"
        return f"{uname} · {dname}" if uname else dname

    async def _owned_server(self, tx: UowTransaction, server_id: str) -> m.Server:
        s: m.Server | None = await tx.servers.get(server_id)
        if not s:
            raise NotFound(key="config.server_not_found")
        return s

    @staticmethod
    def _find_config(device: m.Device, server_id: str, spec: pc.ProtoSpec) -> m.DeviceConfig | None:
        for c in device.configs:
            if (
                c.server_id == server_id
                and c.vpn_type == spec.vendor
                and c.proto == spec.label
                and c.client_id
                # отозванный (revoked) переиздаём заново; приостановленный по лимиту (suspended) или
                # вручную (paused) ПЕРЕИСПОЛЬЗУЕМ — иначе перевыдача создала бы дубль, а старого
                # серверного клиента (пир+DROP awg / data-limit outline / disable openvpn) осиротила бы.
                and c.status in ("active", "suspended", "paused")
            ):
                return c
        return None

    def _client_from_config(self, c: m.DeviceConfig) -> ClientMaterial:
        priv = ""
        if c.client_secret_encrypted:
            priv = decrypt_secret(self.settings.secret_key, c.client_secret_encrypted)
        return ClientMaterial(
            client_id=c.client_id or "",
            client_private_key=priv,
            client_public_key=c.client_public_key or "",
            client_ip=c.client_ip or "",
        )

    async def _audit_download(
        self,
        user_id: str,
        server_id: str,
        server_owner_id: str,
        vpn_type: str,
        spec: pc.ProtoSpec,
        device_id: str | None,
    ) -> None:
        """Событие выдачи конфига (актор = участник, владелец затронутого ресурса = владелец сервера)."""
        async with self.uow.transaction() as tx:
            user = await tx.users.get(user_id)
            tx.audit.add_event(
                at=time.time(),
                actor_kind="user",
                actor_id=user_id,
                actor_name=user.name if user else "",
                type_=audit_types.CONFIG_DOWNLOAD,
                target_kind="server",
                target_id=server_id,
                owner_user_id=server_owner_id,
                meta_json=json.dumps({"vpn": vpn_type, "proto": spec.label, "deviceId": device_id}, ensure_ascii=False),
            )

    async def _persist_client(
        self, device_id: str, server_id: str, spec: pc.ProtoSpec, client: ClientMaterial, client_name: str
    ) -> None:
        async with self.uow.transaction() as tx:
            d = await tx.devices.get(device_id)
            if not d:
                return
            for c in list(d.configs):
                if c.server_id == server_id and c.vpn_type == spec.vendor and c.proto == spec.label:
                    await tx.session.delete(c)
            tx.session.add(
                m.DeviceConfig(
                    device_id=device_id,
                    server_id=server_id,
                    vpn_type=spec.vendor,
                    proto=spec.label,
                    client_id=client.client_id,
                    client_ip=client.client_ip,
                    client_public_key=client.client_public_key,
                    client_secret_encrypted=encrypt_secret(self.settings.secret_key, client.client_private_key)
                    if client.client_private_key
                    else None,
                    client_name=client_name,
                )
            )
            await tx.session.flush()
