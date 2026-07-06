"""Провизионер AmneziaWG (Awg2) и AmneziaWG Legacy (Awg) — порт WireguardConfigurator.

Один класс на оба варианта: различия (интерфейс awg0/wg0, бинарники awg/wg, наличие S3/S4)
инкапсулированы в ProtoSpec/AwgParams.
"""

from __future__ import annotations

import re

from vpnhub.infra.provisioning import constants as c
from vpnhub.infra.provisioning import errors, ipalloc, keys, script_runner, templates, vpn_uri
from vpnhub.infra.provisioning.awg_params import AwgParams, rewrite_interface_params
from vpnhub.infra.provisioning.awg_params import generate as gen_params
from vpnhub.infra.provisioning.provisioners import base
from vpnhub.infra.provisioning.provisioners.base import ClientMaterial, ConfigArtifact, ServerMaterial
from vpnhub.infra.provisioning.ssh import SshClient


class AwgProvisioner:
    def __init__(self, spec: c.ProtoSpec, params: AwgParams | None = None, material: ServerMaterial | None = None):
        self.spec = spec
        self._params = params
        self._material = material

    # ---- доступ к состоянию ----

    @property
    def params(self) -> AwgParams:
        if self._params is None:
            raise ValueError("AwgProvisioner: не заданы obfuscation-параметры")
        return self._params

    @property
    def material(self) -> ServerMaterial:
        if self._material is None:
            raise ValueError("AwgProvisioner: не задан серверный материал (pubkey/psk)")
        return self._material

    @staticmethod
    def new_params(is_awg2: bool) -> AwgParams:
        return gen_params(is_awg2=is_awg2)

    # ---- переменные скриптов ----

    def install_vars(self, server_ip: str, port: str) -> dict[str, str]:
        variables = {
            "$REMOTE_HOST": server_ip,
            "$CONTAINER_NAME": self.spec.container,
            "$DOCKERFILE_FOLDER": f"/opt/amnezia/{self.spec.container}",
            "$SERVER_IP_ADDRESS": server_ip,
            "$PRIMARY_SERVER_DNS": c.SERVER_PRIMARY_DNS,
            "$SECONDARY_SERVER_DNS": c.SERVER_SECONDARY_DNS,
            "$AWG_SERVER_PORT": port or self.spec.default_port,
        }
        variables.update(self.params.script_vars())
        return variables

    # ---- install ----

    async def install(self, ssh: SshClient, server_ip: str, port: str) -> ServerMaterial:
        variables = self.install_vars(server_ip, port)
        await script_runner.setup_container(ssh, self.spec, variables)
        server_pub = await ssh.read_container_text(self.spec.container, self.spec.server_pubkey_path)
        psk = await ssh.read_container_text(self.spec.container, self.spec.server_psk_path)
        self._material = ServerMaterial(server_public_key=server_pub, psk=psk)
        return self._material

    # ---- clients ----

    async def add_client(self, ssh: SshClient, server_ip: str, port: str, name: str) -> ClientMaterial:
        priv, pub = keys.gen_wg_keypair()
        server_conf = await ssh.read_container_text(self.spec.container, self.spec.server_config_path)
        client_ip = ipalloc.next_client_ip(server_conf, self.params.subnet_address)

        peer = f"[Peer]\nPublicKey = {pub}\nPresharedKey = {self.material.psk}\nAllowedIPs = {client_ip}/32\n\n"
        await ssh.upload_to_container(self.spec.container, peer, self.spec.server_config_path, append=True)
        await self._syncconf(ssh)
        await base.append_client_row(ssh, self.spec, pub, name)
        return ClientMaterial(client_id=pub, client_private_key=priv, client_public_key=pub, client_ip=client_ip)

    async def revoke_client(self, ssh: SshClient, client_id: str) -> None:
        conf = await ssh.read_container_text(self.spec.container, self.spec.server_config_path)
        # разбиваем по "[", выкидываем секцию с pubkey клиента, собираем обратно (порт usersController)
        parts = conf.split("[")
        kept = ["[" + p for p in parts if p.strip() and client_id not in p]
        new_conf = "".join(kept)
        await ssh.upload_to_container(self.spec.container, new_conf, self.spec.server_config_path, append=False)
        await self._syncconf(ssh)
        await base.remove_client_row(ssh, self.spec, client_id)

    # ---- suspend / resume (лимит трафика, Этап 3b) ----
    #
    # ПИР НЕ ТРОГАЕМ: удаление [Peer] освободило бы IP-слот (ipalloc берёт последний AllowedIPs+1 —
    # порядок важен) и на resume мог бы возникнуть конфликт по IP. Вместо этого режем трафик клиента
    # на хосте через iptables DROP его /32 в обе стороны (FORWARD). Материал и конфиг остаются целыми,
    # resume снимает правило — клиент продолжает работать тем же конфигом.

    @staticmethod
    def _fw_rules(client_ip: str) -> list[str]:
        return [f"FORWARD -s {client_ip}/32 -j DROP", f"FORWARD -d {client_ip}/32 -j DROP"]

    async def suspend_client(self, ssh: SshClient, material: ClientMaterial) -> None:
        ip = (material.client_ip or "").strip()
        if not ip:
            return
        for rule in self._fw_rules(ip):
            # идемпотентно: добавить, только если такого правила ещё нет
            await ssh.run(f"sudo iptables -C {rule} 2>/dev/null || sudo iptables -I {rule}")

    async def resume_client(self, ssh: SshClient, material: ClientMaterial) -> None:
        ip = (material.client_ip or "").strip()
        if not ip:
            return
        for rule in self._fw_rules(ip):
            # снять правило, пока оно есть (на случай дублей — в цикле); отсутствие правила не ошибка
            await ssh.run(f"while sudo iptables -C {rule} 2>/dev/null; do sudo iptables -D {rule}; done; true")

    async def set_params(self, ssh: SshClient, new_params: AwgParams) -> None:
        """Переписать obfuscation-строки в живом [Interface] awg0.conf и применить (syncconf).

        Пиры ([Peer]) сохраняются — простой ~секунды. После вызова self._params — новые.
        """
        conf = await ssh.read_container_text(self.spec.container, self.spec.server_config_path)
        new_conf = rewrite_interface_params(conf, new_params, self.spec.is_awg2)
        await ssh.upload_to_container(self.spec.container, new_conf, self.spec.server_config_path, append=False)
        await self._syncconf(ssh)
        self._params = new_params

    async def _syncconf(self, ssh: SshClient) -> None:
        b, iface, path = self.spec.bin, self.spec.interface, self.spec.server_config_path
        await ssh.run(
            f"sudo docker exec -i {self.spec.container} bash -c '{b} syncconf {iface} <({b}-quick strip {path})'"
        )

    async def list_clients(self, ssh: SshClient) -> list[dict]:
        return await base.read_clients_table(ssh, self.spec)

    async def list_peer_ids(self, ssh: SshClient) -> set[str]:
        """Живые пиры на сервере = все PublicKey в [Peer] серверного конфига.

        Как и openvpn.list_client_ids: пустой/сбойный ответ НЕ трактуем как «нет пиров».
        Живой awg0.conf всегда содержит секцию [Interface]; её отсутствие = сбой чтения
        (ssh.run(check=False) + bytes.fromhex("") не бросают) → raise, чтобы sync выставил
        readable=False и не сделал ложный revoke / не погасил долг вслепую (plan_drain).
        """
        conf = await ssh.read_container_text(self.spec.container, self.spec.server_config_path)
        if "[Interface]" not in conf:
            raise errors.make("internal", f"{self.spec.id}: не удалось прочитать server config (awg0.conf)")
        return {m.group(1) for m in re.finditer(r"PublicKey\s*=\s*(\S+)", conf)}

    async def adopt(self, ssh: SshClient) -> tuple[ServerMaterial, AwgParams]:
        """Считать материал и параметры уже установленного (в т.ч. внешним клиентом) контейнера."""
        pub = await ssh.read_container_text(self.spec.container, self.spec.server_pubkey_path)
        psk = await ssh.read_container_text(self.spec.container, self.spec.server_psk_path)
        conf = await ssh.read_container_text(self.spec.container, self.spec.server_config_path)
        params = AwgParams.from_server_conf(conf, self.spec.is_awg2)
        return ServerMaterial(server_public_key=pub, psk=psk), params

    async def status(self, ssh: SshClient) -> bool:
        res = await ssh.run(f"sudo docker inspect -f '{{{{.State.Running}}}}' {self.spec.container}")
        return "true" in res.stdout.lower()

    # ---- сборка артефактов (чистая, без SSH) ----

    def _render_conf(self, server_ip: str, port: str, client: ClientMaterial) -> str:
        """Клиентский WireGuard .conf (подстановка template.conf) — общий для artifact и bundle-контейнера."""
        conf_vars = {
            "$WIREGUARD_CLIENT_IP": client.client_ip,
            "$WIREGUARD_CLIENT_PRIVATE_KEY": client.client_private_key,
            "$WIREGUARD_SERVER_PUBLIC_KEY": self.material.server_public_key,
            "$WIREGUARD_PSK": self.material.psk,
            "$PRIMARY_DNS": c.CLIENT_PRIMARY_DNS,
            "$SECONDARY_DNS": c.CLIENT_SECONDARY_DNS,
            "$SERVER_IP_ADDRESS": server_ip,
            "$AWG_SERVER_PORT": port or self.spec.default_port,
        }
        conf_vars.update(self.params.script_vars())
        return templates.replace_vars(templates.load_protocol(self.spec.script_folder, "template.conf"), conf_vars)

    def build_container(self, *, server_ip: str, port: str, server_name: str, client: ClientMaterial) -> dict:
        """Элемент containers[] для мульти-протокольного vpn:// (без SSH). server_name не нужен (общий на бандл)."""
        conf_text = self._render_conf(server_ip, port, client)
        return vpn_uri.build_awg_container(
            container=self.spec.container,
            is_awg2=self.spec.is_awg2,
            server_ip=server_ip,
            port=port or self.spec.default_port,
            params=self.params,
            conf_text=conf_text,
            client_ip=client.client_ip,
            client_priv_key=client.client_private_key,
            client_pub_key=client.client_public_key,
            server_pub_key=self.material.server_public_key,
            psk=self.material.psk,
        )

    def build_artifact(self, *, server_ip: str, port: str, server_name: str, client: ClientMaterial) -> ConfigArtifact:
        conf_text = self._render_conf(server_ip, port, client)
        native = vpn_uri.build_awg_native_config(
            container=self.spec.container,
            is_awg2=self.spec.is_awg2,
            server_ip=server_ip,
            server_name=server_name,
            port=port or self.spec.default_port,
            params=self.params,
            conf_text=conf_text,
            client_ip=client.client_ip,
            client_priv_key=client.client_private_key,
            client_pub_key=client.client_public_key,
            server_pub_key=self.material.server_public_key,
            psk=self.material.psk,
        )
        return ConfigArtifact(
            conf_text=conf_text,
            vpn_url=vpn_uri.encode_vpn_url(native),
            filename=f"{server_name or 'server'}-{self.spec.id}.conf",
            hint="Импортируйте .conf в AmneziaWG/WireGuard или откройте vpn:// в AmneziaVPN → «+» → из буфера.",
        )
