"""Провизионер Hysteria2 (apernet/hysteria server).

Особенности vs xray/awg:
- Установка — контейнерная (setup_container), как у amnezia-* протоколов: контейнер
  amnezia-hysteria2 с QUIC-сервером, self-signed сертом, salamander-обфускацией и masquerade.
- Членство — НЕ clientsTable как источник правды, а файл токенов
  /opt/amnezia/hysteria2/users (строки "<client_id> <password>"). auth.type=command грепает
  его на каждое подключение, поэтому add/revoke = правка файла БЕЗ рестарта демона
  (как revoke у openvpn через crl — активные сессии не роняются).
- clientId — случайный [A-Za-z0-9]{32} (лежит в DeviceConfig.client_id, по нему revoke);
  секрет-пароль (в ClientMaterial.client_private_key, шифруется панелью) уходит в
  hysteria2://-ссылку. Разведены, чтобы секрет не лежал в открытом client_id.
"""

from __future__ import annotations

import re

from vpnhub.infra.provisioning import constants as c
from vpnhub.infra.provisioning import errors, keys, script_runner, vpn_uri
from vpnhub.infra.provisioning.provisioners import base
from vpnhub.infra.provisioning.provisioners.base import ClientMaterial, ConfigArtifact, ServerMaterial
from vpnhub.infra.provisioning.ssh import SshClient

# client_id/пароль генерим сами из [A-Za-z0-9]; валидируем перед подстановкой в файл/фильтрацию.
_ID_RE = re.compile(r"[A-Za-z0-9]+")


class HysteriaProvisioner:
    def __init__(self, spec: c.ProtoSpec, material: ServerMaterial | None = None):
        self.spec = spec
        self._material = material

    @property
    def material(self) -> ServerMaterial:
        if self._material is None:
            raise ValueError("HysteriaProvisioner: не задан серверный материал (obfs/cert)")
        return self._material

    @staticmethod
    def _check_id(cid: str) -> str:
        if not cid or not _ID_RE.fullmatch(cid):
            raise errors.make("internal", f"недопустимый clientId Hysteria2: {cid!r}")
        return cid

    # ---- переменные скриптов ----

    def install_vars(self, server_ip: str, port: str) -> dict[str, str]:
        return {
            "$CONTAINER_NAME": self.spec.container,
            "$DOCKERFILE_FOLDER": f"/opt/amnezia/{self.spec.container}",
            "$SERVER_IP_ADDRESS": server_ip,
            "$HYSTERIA_PORT": port or self.spec.default_port,
            "$HYSTERIA_SNI": self.spec.hysteria_sni,
        }

    # ---- install ----

    async def install(self, ssh: SshClient, server_ip: str, port: str) -> ServerMaterial:
        variables = self.install_vars(server_ip, port)
        await script_runner.setup_container(ssh, self.spec, variables)
        obfs = (await ssh.read_container_text(self.spec.container, self.spec.hysteria_obfs_file)).strip()
        cert_sha = (await ssh.read_container_text(self.spec.container, self.spec.hysteria_cert_sha_file)).strip()
        self._material = ServerMaterial(
            hysteria_obfs_password=obfs, hysteria_cert_sha256=cert_sha, site=self.spec.hysteria_sni
        )
        return self._material

    # ---- clients ----

    async def add_client(self, ssh: SshClient, server_ip: str, port: str, name: str) -> ClientMaterial:
        cid = self._check_id(keys.gen_client_cn())
        password = keys.gen_client_cn()
        await ssh.upload_to_container(
            self.spec.container, f"{cid} {password}\n", self.spec.hysteria_users_path, append=True
        )
        await base.append_client_row(ssh, self.spec, cid, name)
        return ClientMaterial(client_id=cid, client_private_key=password)

    async def revoke_client(self, ssh: SshClient, client_id: str) -> None:
        cid = self._check_id(client_id)
        raw = await ssh.read_container_text(self.spec.container, self.spec.hysteria_users_path)
        kept = [ln for ln in raw.splitlines() if ln.split() and ln.split()[0] != cid]
        new_text = ("\n".join(kept) + "\n") if kept else ""
        await ssh.upload_to_container(self.spec.container, new_text, self.spec.hysteria_users_path, append=False)
        await base.remove_client_row(ssh, self.spec, cid)

    async def list_clients(self, ssh: SshClient) -> list[dict]:
        return await base.read_clients_table(ssh, self.spec)

    async def list_client_ids(self, ssh: SshClient) -> set[str]:
        """Живые клиенты = первый столбец файла токенов.

        Как awg/openvpn (contract: no false revoke): пустой/сбойный ответ НЕ трактуем как «нет
        клиентов». Сначала читаем config.yaml как sentinel — здоровый контейнер всегда содержит
        `listen:`; его отсутствие = сбой чтения → raise, чтобы sync выставил readable=False и не
        сделал ложный revoke. Пустой users при живом config — легитимный «ноль клиентов».
        """
        cfg = await ssh.read_container_text(self.spec.container, self.spec.hysteria_config_path)
        if "listen:" not in cfg:
            raise errors.make("internal", "hysteria2: не удалось прочитать config.yaml")
        raw = await ssh.read_container_text(self.spec.container, self.spec.hysteria_users_path)
        return {parts[0] for ln in raw.splitlines() if (parts := ln.split())}

    async def adopt(self, ssh: SshClient) -> ServerMaterial:
        """Считать материал уже установленного контейнера (obfs/cert/sni)."""
        obfs = (await ssh.read_container_text(self.spec.container, self.spec.hysteria_obfs_file)).strip()
        cert_sha = (await ssh.read_container_text(self.spec.container, self.spec.hysteria_cert_sha_file)).strip()
        return ServerMaterial(hysteria_obfs_password=obfs, hysteria_cert_sha256=cert_sha, site=self.spec.hysteria_sni)

    async def status(self, ssh: SshClient) -> bool:
        res = await ssh.run(f"sudo docker inspect -f '{{{{.State.Running}}}}' {self.spec.container}")
        return "true" in res.stdout.lower()

    # ---- сборка артефакта (чистая, без SSH) ----

    def build_artifact(self, *, server_ip: str, port: str, server_name: str, client: ClientMaterial) -> ConfigArtifact:
        url = vpn_uri.build_hysteria2_url(
            password=client.client_private_key,
            host=server_ip,
            port=port or self.spec.default_port,
            sni=self.material.site or self.spec.hysteria_sni,
            obfs_password=self.material.hysteria_obfs_password,
            pin_sha256=self.material.hysteria_cert_sha256,
            alias=server_name or "Hysteria2",
        )
        return ConfigArtifact(
            conf_text=url,
            vpn_url=url,
            filename=f"{(server_name or 'server').replace(' ', '_')}-hysteria2.txt",
            hint="Скопируйте ссылку hysteria2:// и добавьте в Hiddify / Karing / sing-box.",
        )
