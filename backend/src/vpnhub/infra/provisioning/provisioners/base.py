"""Общие типы провизионеров + работа с clientsTable внутри контейнера."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol, runtime_checkable

from vpnhub.infra.provisioning import constants as c
from vpnhub.infra.provisioning.ssh import SshClient


@dataclass
class ServerMaterial:
    """Серверный материал, читаемый после install и хранимый в ServerProtocol."""

    # wireguard/awg
    server_public_key: str = ""
    psk: str = ""
    # xray
    xray_public_key: str = ""
    short_id: str = ""
    bootstrap_uuid: str = ""
    site: str = ""
    xhttp_path: str = ""  # путь XHTTP (только для xray_xhttp); пусто для tcp-Reality
    # hysteria2: salamander-пароль обфускации + pinSHA256 self-signed серта
    hysteria_obfs_password: str = ""
    hysteria_cert_sha256: str = ""
    # openvpn (shared per-server: CA cert + tls-auth key + выбранный транспорт)
    ca_cert: str = ""
    ta_key: str = ""
    transport: str = ""  # udp | tcp
    # outline (shadowbox Management API): базовый URL с секретным префиксом + отпечаток TLS-серта
    outline_api_url: str = ""  # https://<host>:<api_port>/<secret_prefix>
    outline_cert_sha256: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "server_public_key": self.server_public_key,
            "psk": self.psk,
            "xray_public_key": self.xray_public_key,
            "short_id": self.short_id,
            "bootstrap_uuid": self.bootstrap_uuid,
            "site": self.site,
            "xhttp_path": self.xhttp_path,
            "hysteria_obfs_password": self.hysteria_obfs_password,
            "hysteria_cert_sha256": self.hysteria_cert_sha256,
            "ca_cert": self.ca_cert,
            "ta_key": self.ta_key,
            "transport": self.transport,
            "outline_api_url": self.outline_api_url,
            "outline_cert_sha256": self.outline_cert_sha256,
        }

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> ServerMaterial:
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})


@dataclass
class ClientMaterial:
    """Клиентский материал, хранимый в DeviceConfig."""

    client_id: str = ""  # pubkey (wg/awg) или uuid (xray)
    client_private_key: str = ""
    client_public_key: str = ""
    client_ip: str = ""

    def as_dict(self) -> dict[str, str]:
        return {
            "client_id": self.client_id,
            "client_private_key": self.client_private_key,
            "client_public_key": self.client_public_key,
            "client_ip": self.client_ip,
        }

    @classmethod
    def from_dict(cls, d: dict[str, str]) -> ClientMaterial:
        return cls(**{k: v for k, v in (d or {}).items() if k in cls.__dataclass_fields__})


@dataclass
class ConfigArtifact:
    """Готовые артефакты конфига для клиента."""

    conf_text: str = ""  # WireGuard/AmneziaWG .conf
    vpn_url: str = ""  # vpn:// (native Amnezia)
    vless_url: str = ""  # vless:// (Xray)
    filename: str = ""
    hint: str = ""
    protos: list[str] = field(default_factory=list)


@runtime_checkable
class Provisioner(Protocol):
    spec: c.ProtoSpec

    def install_vars(self, server_ip: str, port: str) -> dict[str, str]: ...
    async def install(self, ssh: SshClient, port: str) -> ServerMaterial: ...
    async def add_client(self, ssh: SshClient, server_ip: str, port: str, name: str) -> ClientMaterial: ...
    async def revoke_client(self, ssh: SshClient, client_id: str) -> None: ...
    async def list_clients(self, ssh: SshClient) -> list[dict]: ...
    async def status(self, ssh: SshClient) -> bool: ...


# ------------------------------------------------------------- clientsTable ---


def _now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S")


async def read_clients_table(ssh: SshClient, spec: c.ProtoSpec) -> list[dict]:
    """Прочитать clientsTable (JSON-массив) из контейнера. [] если пусто/нет файла."""
    path = c.clients_table_path(spec)
    try:
        raw = await ssh.read_container_text(spec.container, path)
    except Exception:
        return []
    raw = raw.strip()
    if not raw:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


async def write_clients_table(ssh: SshClient, spec: c.ProtoSpec, rows: list[dict]) -> None:
    path = c.clients_table_path(spec)
    await ssh.upload_to_container(spec.container, json.dumps(rows), path, append=False)


async def append_client_row(ssh: SshClient, spec: c.ProtoSpec, client_id: str, client_name: str) -> None:
    rows = await read_clients_table(ssh, spec)
    rows = [r for r in rows if r.get("clientId") != client_id]
    rows.append({"clientId": client_id, "userData": {"clientName": client_name, "creationDate": _now_iso()}})
    await write_clients_table(ssh, spec, rows)


async def remove_client_row(ssh: SshClient, spec: c.ProtoSpec, client_id: str) -> None:
    rows = await read_clients_table(ssh, spec)
    rows = [r for r in rows if r.get("clientId") != client_id]
    await write_clients_table(ssh, spec, rows)
