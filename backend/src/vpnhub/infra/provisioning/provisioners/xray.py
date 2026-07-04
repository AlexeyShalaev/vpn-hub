"""Провизионер Xray (VLESS+REALITY) — порт XrayConfigurator/usersController.

Особенности: reality-ключи и bootstrap-uuid генерятся в контейнере (`xray x25519/uuid`);
членство = правка inbounds[0].settings.clients в server.json + `docker restart`
(hot-reload у Xray нет — рестарт роняет активные сессии).
"""

from __future__ import annotations

import json
from typing import Any, cast

from vpnhub.infra.provisioning import constants as c
from vpnhub.infra.provisioning import keys, script_runner, vpn_uri
from vpnhub.infra.provisioning.provisioners import base
from vpnhub.infra.provisioning.provisioners.base import ClientMaterial, ConfigArtifact, ServerMaterial
from vpnhub.infra.provisioning.ssh import SshClient


class XrayProvisioner:
    def __init__(self, spec: c.ProtoSpec, material: ServerMaterial | None = None):
        self.spec = spec
        self._material = material

    @property
    def material(self) -> ServerMaterial:
        if self._material is None:
            raise ValueError("XrayProvisioner: не задан серверный материал (pubkey/shortId)")
        return self._material

    def install_vars(self, server_ip: str, port: str, site: str) -> dict[str, str]:
        return {
            "$CONTAINER_NAME": self.spec.container,
            "$DOCKERFILE_FOLDER": f"/opt/amnezia/{self.spec.container}",
            "$SERVER_IP_ADDRESS": server_ip,
            "$XRAY_SERVER_PORT": port or self.spec.default_port,
            "$XRAY_SITE_NAME": site or c.XRAY_DEFAULT_SITE,
        }

    async def install(self, ssh: SshClient, server_ip: str, port: str, site: str = "") -> ServerMaterial:
        site = site or c.XRAY_DEFAULT_SITE
        variables = self.install_vars(server_ip, port, site)
        await script_runner.setup_container(ssh, self.spec, variables)
        pub = await ssh.read_container_text(self.spec.container, self.spec.xray_public_key_path)
        short_id = await ssh.read_container_text(self.spec.container, self.spec.xray_short_id_path)
        boot_uuid = await ssh.read_container_text(self.spec.container, self.spec.xray_uuid_path)
        xhttp_path = await self._read_xhttp_path(ssh)
        self._material = ServerMaterial(
            xray_public_key=pub, short_id=short_id, bootstrap_uuid=boot_uuid, site=site, xhttp_path=xhttp_path
        )
        return self._material

    async def _read_xhttp_path(self, ssh: SshClient) -> str:
        """Путь XHTTP из контейнера (генерится configure_container.sh). Пусто для tcp-Reality."""
        if self.spec.xray_network != "xhttp" or not self.spec.xray_xhttp_path_file:
            return ""
        return (await ssh.read_container_text(self.spec.container, self.spec.xray_xhttp_path_file)).strip()

    async def _read_server_json(self, ssh: SshClient) -> dict:
        raw = await ssh.read_container_text(self.spec.container, "/opt/amnezia/xray/server.json")
        return cast("dict[Any, Any]", json.loads(raw))

    async def _write_and_restart(self, ssh: SshClient, doc: dict) -> None:
        await ssh.upload_to_container(
            self.spec.container, json.dumps(doc, indent=2), "/opt/amnezia/xray/server.json", append=False
        )
        await ssh.run(f"sudo docker restart {self.spec.container}")

    async def add_client(self, ssh: SshClient, server_ip: str, port: str, name: str) -> ClientMaterial:
        uuid = keys.gen_uuid()
        doc = await self._read_server_json(ssh)
        clients = doc["inbounds"][0]["settings"].setdefault("clients", [])
        # flow (xtls-rprx-vision) — только для tcp; на XHTTP Vision не применяется
        entry = {"id": uuid} if self.spec.xray_network == "xhttp" else {"id": uuid, "flow": c.XRAY_DEFAULT_FLOW}
        clients.append(entry)
        await self._write_and_restart(ssh, doc)
        await base.append_client_row(ssh, self.spec, uuid, name)
        return ClientMaterial(client_id=uuid)

    async def revoke_client(self, ssh: SshClient, client_id: str) -> None:
        doc = await self._read_server_json(ssh)
        clients = doc["inbounds"][0]["settings"].get("clients", [])
        doc["inbounds"][0]["settings"]["clients"] = [x for x in clients if x.get("id") != client_id]
        await self._write_and_restart(ssh, doc)
        await base.remove_client_row(ssh, self.spec, client_id)

    async def list_clients(self, ssh: SshClient) -> list[dict]:
        rows = await base.read_clients_table(ssh, self.spec)
        boot = self._material.bootstrap_uuid if self._material else ""
        return [r for r in rows if r.get("clientId") != boot]

    async def list_client_ids(self, ssh: SshClient) -> set[str]:
        """Живые клиенты Xray = uuid из inbounds[0].settings.clients (без bootstrap-uuid)."""
        doc = await self._read_server_json(ssh)
        ids = {cl.get("id") for cl in doc["inbounds"][0]["settings"].get("clients", [])}
        ids.discard(self._material.bootstrap_uuid if self._material else "")
        ids.discard("")
        ids.discard(None)
        return {i for i in ids if i}

    async def adopt(self, ssh: SshClient) -> ServerMaterial:
        """Считать материал уже установленного (в т.ч. внешним клиентом) Xray-контейнера."""
        pub = await ssh.read_container_text(self.spec.container, self.spec.xray_public_key_path)
        short = await ssh.read_container_text(self.spec.container, self.spec.xray_short_id_path)
        boot = await ssh.read_container_text(self.spec.container, self.spec.xray_uuid_path)
        site = c.XRAY_DEFAULT_SITE
        try:
            doc = await self._read_server_json(ssh)
            names = doc["inbounds"][0]["streamSettings"]["realitySettings"].get("serverNames", [])
            if names:
                site = names[0]
        except (KeyError, IndexError, ValueError):
            pass
        xhttp_path = await self._read_xhttp_path(ssh)
        return ServerMaterial(
            xray_public_key=pub, short_id=short, bootstrap_uuid=boot, site=site, xhttp_path=xhttp_path
        )

    async def status(self, ssh: SshClient) -> bool:
        res = await ssh.run(f"sudo docker inspect -f '{{{{.State.Running}}}}' {self.spec.container}")
        return "true" in res.stdout.lower()

    def build_container(self, *, server_ip: str, port: str, server_name: str, client: ClientMaterial) -> dict:
        """Элемент containers[] для мульти-протокольного vpn:// (tcp-Reality; xhttp сюда не попадает)."""
        return vpn_uri.build_xray_container(
            container=self.spec.container,
            host=server_ip,
            port=port or self.spec.default_port,
            uuid=client.client_id,
            public_key=self.material.xray_public_key,
            short_id=self.material.short_id,
            sni=self.material.site or c.XRAY_DEFAULT_SITE,
        )

    def build_artifact(self, *, server_ip: str, port: str, server_name: str, client: ClientMaterial) -> ConfigArtifact:
        is_xhttp = self.spec.xray_network == "xhttp"
        vless = vpn_uri.build_vless_url(
            uuid=client.client_id,
            host=server_ip,
            port=port or self.spec.default_port,
            public_key=self.material.xray_public_key,
            short_id=self.material.short_id,
            sni=self.material.site or c.XRAY_DEFAULT_SITE,
            flow="" if is_xhttp else c.XRAY_DEFAULT_FLOW,
            network=self.spec.xray_network,
            path=self.material.xhttp_path if is_xhttp else "",
            mode=self.spec.xray_xhttp_mode if is_xhttp else "",
            alias=server_name or "AmneziaVPN",
        )
        hint = (
            "Скопируйте ссылку vless:// и добавьте в клиент с поддержкой XHTTP (Hiddify / v2RayTun)."
            if is_xhttp
            else "Скопируйте ссылку vless:// и добавьте в AmneziaVPN → «+» → Xray (или v2RayTun)."
        )
        return ConfigArtifact(
            vless_url=vless,
            filename=f"{server_name or 'server'}-{self.spec.id}.txt",
            hint=hint,
        )
