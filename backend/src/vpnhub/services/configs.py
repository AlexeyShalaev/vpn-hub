"""Получение конфига участником.

Все вендоры (Amnezia / OpenVPN / Outline) — реальный provisioning: при первом запросе на
устройство добавляется пир/клиент на сервере (SSH), материал сохраняется в DeviceConfig, далее
конфиг пересобирается из него.
"""

from __future__ import annotations

from typing import Any

from vpnhub.api.config import Settings
from vpnhub.common.catalog import PROTOS, clients_for
from vpnhub.core.errors import BadRequest, Forbidden, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.errors import ProvisioningError
from vpnhub.infra.provisioning.provisioners import ClientMaterial
from vpnhub.infra.provisioning.ssh import SshClient, SshError
from vpnhub.infra.security import decrypt_secret, encrypt_secret
from vpnhub.infra.uow import Uow, UowTransaction
from vpnhub.services.access import effective_access
from vpnhub.services.provisioning import PROVISIONED_VENDORS, ProvisioningService


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
        self, user_id: str, server_id: str, vpn_type: str, device_id: str | None, proto: str | None
    ) -> dict:
        async with self.uow.query() as tx:
            access, _ = await effective_access(tx, user_id)
            if vpn_type not in access.get(server_id, set()):
                raise Forbidden("Нет доступа к этому VPN")
            s = await tx.servers.get(server_id)
            if not s:
                raise NotFound("Сервер не найден")
            platform = "ios"
            if device_id:
                d = await tx.devices.get(device_id)
                if d and d.user_id == user_id:
                    platform = d.platform

        if vpn_type not in PROVISIONED_VENDORS:
            raise BadRequest("Неизвестный тип VPN")
        return await self._generate_provisioned(vpn_type, user_id, server_id, device_id, proto, platform)

    async def _generate_provisioned(
        self, vpn_type: str, user_id: str, server_id: str, device_id: str | None, proto: str | None, platform: str
    ) -> dict:
        if not device_id:
            raise BadRequest("Выберите устройство")
        # протокол должен принадлежать вендору vpn_type; иначе — дефолтный протокол вендора
        spec = pc.spec_by_label(proto or "")
        if spec is None or spec.vendor != vpn_type:
            spec = pc.spec_by_label(PROTOS[vpn_type][0])
        if spec is None:
            raise BadRequest("Неизвестный протокол")

        prov = ProvisioningService(self.uow, self.settings)

        # фаза 1: читаем состояние, готовим провизионер и креды (плоские значения)
        async with self.uow.query() as tx:
            s = await self._owned_server(tx, server_id)
            device = await tx.devices.get(device_id)
            if not device or device.user_id != user_id:
                raise NotFound("Устройство не найдено")
            sp = next((p for p in s.protocols if p.proto == spec.id), None)
            if not sp or not sp.installed:
                raise BadRequest("Протокол ещё не установлен на этом сервере")
            server_ip, server_name, port = s.ip, s.name, sp.port
            creds = prov.creds(s)
            prov_obj = prov.loaded_provisioner(sp)
            user = await tx.users.get(user_id)
            client_name = self._client_name(user, device)
            existing = self._find_config(device, server_id, spec)
            client = self._client_from_config(existing) if existing else None

        # фаза 2: если материала нет — добавляем клиента на сервере и сохраняем
        if client is None:
            try:
                async with SshClient(creds) as ssh:
                    client = await prov_obj.add_client(ssh, server_ip, port, client_name)
            except (SshError, ProvisioningError) as e:
                raise BadRequest(f"Не удалось создать конфиг на сервере: {e}") from e
            await self._persist_client(device_id, server_id, spec, client, client_name)

        artifact = prov_obj.build_artifact(server_ip=server_ip, port=port, server_name=server_name, client=client)
        clients = clients_for(vpn_type, platform)
        if spec.kind == "xray":
            clients = [c for c in clients if not c.get("wgOnly")]
        text = artifact.conf_text or artifact.vless_url
        uri = artifact.vpn_url or artifact.vless_url
        formats = _provisioned_formats(vpn_type, artifact, server_name, spec.id)
        return {
            "type": vpn_type,
            "proto": spec.label,
            "filename": artifact.filename,
            "text": text,
            "uri": uri,
            "hint": artifact.hint,
            "clients": clients,
            "protos": PROTOS.get(vpn_type, []),
            "serverId": server_id,
            "formats": formats,
        }

    # -------------------------------------------------------------- install ---

    async def install(self, user_id: str, server_id: str, vpn_type: str, device_id: str, proto: str | None) -> dict:
        if not device_id:
            raise BadRequest("Выберите устройство")
        if vpn_type in PROVISIONED_VENDORS:
            # реальный provisioning: создаст клиента на сервере и сохранит DeviceConfig
            await self._generate_provisioned(vpn_type, user_id, server_id, device_id, proto, platform="ios")
            return {"ok": True}
        # outline — только пометка на устройстве
        async with self.uow.transaction() as tx:
            d = await tx.devices.get(device_id)
            if not d or d.user_id != user_id:
                raise NotFound("Устройство не найдено")
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
            raise BadRequest("Выберите устройство")
        prov = ProvisioningService(self.uow, self.settings)
        async with self.uow.query() as tx:
            d = await tx.devices.get(device_id)
            if not d or d.user_id != user_id:
                raise NotFound("Устройство не найдено")
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
            raise NotFound("Сервер не найден")
        return s

    @staticmethod
    def _find_config(device: m.Device, server_id: str, spec: pc.ProtoSpec) -> m.DeviceConfig | None:
        for c in device.configs:
            if (
                c.server_id == server_id
                and c.vpn_type == spec.vendor
                and c.proto == spec.label
                and c.client_id
                and c.status == "active"  # отозванный (revoked) переиздаём заново
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
