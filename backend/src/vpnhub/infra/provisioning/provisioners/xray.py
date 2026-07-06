"""Провизионер Xray (VLESS+REALITY) — порт XrayConfigurator/usersController.

Особенности: reality-ключи и bootstrap-uuid генерятся в контейнере (`xray x25519/uuid`);
членство = правка inbounds[0].settings.clients в server.json + `docker restart`
(hot-reload у Xray нет — рестарт роняет активные сессии).
"""

from __future__ import annotations

import json
from typing import Any, cast

from vpnhub.infra.onlinestats import parse_xray_online
from vpnhub.infra.provisioning import constants as c
from vpnhub.infra.provisioning import keys, reality, script_runner, vpn_uri
from vpnhub.infra.provisioning.provisioners import base
from vpnhub.infra.provisioning.provisioners.base import ClientMaterial, ConfigArtifact, ServerMaterial
from vpnhub.infra.provisioning.ssh import SshClient, SshError

# порт локального API статистики Xray (dokodemo-door inbound, только 127.0.0.1)
XRAY_STATS_PORT = 10085
_STATS_API_INBOUND = {
    "listen": "127.0.0.1",
    "port": XRAY_STATS_PORT,
    "protocol": "dokodemo-door",
    "settings": {"address": "127.0.0.1"},
    "tag": "api",
}
_STATS_POLICY = {
    "levels": {"0": {"statsUserUplink": True, "statsUserDownlink": True, "statsUserOnline": True}},
    "system": {"statsInboundUplink": True, "statsInboundDownlink": True},
}


def _apply_stats_config(doc: dict) -> bool:
    """Мутировать server.json dict, включив StatsService (чистая, без IO; для юнит-тестов).

    Идемпотентна: возвращает True, если что-то реально изменилось, иначе False (уже включено).
    """
    changed = False

    if "stats" not in doc:
        doc["stats"] = {}
        changed = True

    desired_api = {"tag": "api", "services": ["StatsService"]}
    if doc.get("api") != desired_api:
        doc["api"] = desired_api
        changed = True

    if doc.get("policy") != _STATS_POLICY:
        doc["policy"] = json.loads(json.dumps(_STATS_POLICY))  # копия, чтобы не делить ссылку
        changed = True

    # email каждому клиенту во всех inbounds (серверный лейбл для statsUserOnline)
    for inbound in doc.get("inbounds", []):
        for client in inbound.get("settings", {}).get("clients", []):
            cid = client.get("id")
            if cid and not client.get("email"):
                client["email"] = cid
                changed = True

    # api-inbound (dokodemo-door на 127.0.0.1:10085), если ещё нет inbound с tag=="api"
    inbounds = doc.setdefault("inbounds", [])
    if not any(ib.get("tag") == "api" for ib in inbounds):
        inbounds.append(json.loads(json.dumps(_STATS_API_INBOUND)))
        changed = True

    # routing-правило api-inbound → api-outbound (в начало rules)
    rules = doc.setdefault("routing", {}).setdefault("rules", [])
    if not any(r.get("outboundTag") == "api" for r in rules):
        rules.insert(0, {"type": "field", "inboundTag": ["api"], "outboundTag": "api"})
        changed = True

    return changed


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

    async def enable_stats(self, ssh: SshClient) -> bool:
        """Идемпотентно включить StatsService в живом server.json (рестарт только при изменении).

        Возвращает True, если конфиг был изменён (и контейнер перезапущен), иначе False (no-op).
        Reality/клиенты сохраняются: добавляется только api-inbound/routing/policy + email каждому
        клиенту (email — серверный лейбл для statsUserOnline, клиентские vless-конфиги не ломает).
        """
        doc = await self._read_server_json(ssh)
        if not _apply_stats_config(doc):
            return False  # уже включено — контейнер не трогаем
        await self._write_and_restart(ssh, doc)
        return True

    async def query_online(self, ssh: SshClient) -> int | None:
        """Read-only: число онлайн-клиентов через statsquery. НИКОГДА не включает stats/не рестартит.

        stats не включён / бинарь недоступен / ошибка → None (неизвестно). См. parse_xray_online.
        """
        cmd = (
            f"sudo docker exec {self.spec.container} xray api statsquery "
            f"--server=127.0.0.1:{XRAY_STATS_PORT} -pattern '>>>online' 2>/dev/null"
        )
        try:
            res = await ssh.run(cmd)
        except SshError:
            return None
        if res.exit_status != 0:
            return None
        return parse_xray_online(res.output)

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

    # ---- suspend / resume (лимит трафика, Этап 3b) ----
    #
    # suspend убирает uuid только из ЖИВОГО server.json (clientsTable НЕ трогаем — имя/запись клиента
    # сохраняются); resume возвращает ТОТ ЖЕ uuid. uuid глобально уникален, поэтому новый выданный
    # конфиг никогда не займёт освободившийся «слот» — конфликта нет, конфиг пользователя не меняется.

    async def suspend_client(self, ssh: SshClient, material: ClientMaterial) -> None:
        cid = (material.client_id or "").strip()
        if not cid:
            return
        doc = await self._read_server_json(ssh)
        clients = doc["inbounds"][0]["settings"].get("clients", [])
        kept = [x for x in clients if x.get("id") != cid]
        if len(kept) == len(clients):
            return  # уже нет — контейнер не трогаем
        doc["inbounds"][0]["settings"]["clients"] = kept
        await self._write_and_restart(ssh, doc)

    async def resume_client(self, ssh: SshClient, material: ClientMaterial) -> None:
        cid = (material.client_id or "").strip()
        if not cid:
            return
        doc = await self._read_server_json(ssh)
        clients = doc["inbounds"][0]["settings"].setdefault("clients", [])
        if any(x.get("id") == cid for x in clients):
            return  # уже на месте — no-op
        clients.append({"id": cid} if self.spec.xray_network == "xhttp" else {"id": cid, "flow": c.XRAY_DEFAULT_FLOW})
        await self._write_and_restart(ssh, doc)

    async def set_reality(self, ssh: SshClient, *, short_id: str, sni: str) -> ServerMaterial:
        """Переписать realitySettings (shortIds/serverNames/dest) живого server.json + рестарт контейнера.

        Reality hot-reload у Xray нет — рестарт роняет активные сессии, поэтому reprovision короткий, но
        не бесшовный. Клиенты (uuid) сохраняются. Возвращает обновлённый ServerMaterial (short_id/site).
        """
        doc = await self._read_server_json(ssh)
        reality.rewrite_reality(doc, short_id=short_id, sni=sni)
        await self._write_and_restart(ssh, doc)
        boot = self._material.bootstrap_uuid if self._material else ""
        pub = self._material.xray_public_key if self._material else ""
        xhttp = self._material.xhttp_path if self._material else ""
        self._material = ServerMaterial(
            xray_public_key=pub, short_id=short_id, bootstrap_uuid=boot, site=sni, xhttp_path=xhttp
        )
        return self._material

    async def set_outbound_chain(
        self,
        ssh: SshClient,
        *,
        exit_host: str,
        exit_port: str,
        exit_public_key: str,
        exit_short_id: str,
        exit_sni: str,
        exit_uuid: str,
    ) -> None:
        """Мультихоп: заменить outbound entry-контейнера на vless-коннект к exit-серверу + рестарт.

        Трафик клиентов этого entry-сервера станет выходить в интернет через exit (entry = обычный
        vless-клиент exit). Reality hot-reload у Xray нет — рестарт роняет активные сессии.
        """
        doc = await self._read_server_json(ssh)
        doc["outbounds"] = [
            vpn_uri.build_chain_outbound(
                host=exit_host,
                port=exit_port,
                uuid=exit_uuid,
                public_key=exit_public_key,
                short_id=exit_short_id,
                sni=exit_sni,
                flow="" if self.spec.xray_network == "xhttp" else c.XRAY_DEFAULT_FLOW,
            )
        ]
        await self._write_and_restart(ssh, doc)

    async def clear_outbound_chain(self, ssh: SshClient) -> None:
        """Снять мультихоп: вернуть outbound entry-контейнера к прямому `freedom` + рестарт."""
        doc = await self._read_server_json(ssh)
        doc["outbounds"] = [dict(vpn_uri.FREEDOM_OUTBOUND)]
        await self._write_and_restart(ssh, doc)

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
        # xhttp выдаётся отдельной ссылкой (не в бандле), поэтому помечаем имя «XHTTP» —
        # чтобы в клиенте он явно отличался от обычного Xray/бандла того же сервера.
        base_alias = server_name or "AmneziaVPN"
        alias = f"{base_alias} XHTTP" if is_xhttp else base_alias
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
            alias=alias,
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
