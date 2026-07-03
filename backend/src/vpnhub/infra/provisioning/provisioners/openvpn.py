"""Провизионер OpenVPN — порт OpenVpnConfigurator + usersController::(revoke|get)OpenVpn.

Особенности vs awg/xray:
- PKI на сервере: install разворачивает easyrsa CA + серверный сертификат внутри контейнера
  (весь bootstrap — в server_scripts/openvpn/run_container.sh, как у Amnezia).
- Клиентский ключ + CSR генерятся ЛОКАЛЬНО в панели (RSA-2048); наружу уходит только .req,
  приватный ключ клиента сервер не видит. Контейнер лишь подписывает CSR (import-req + sign-req).
- clientId = CN сертификата (32 симв. [A-Za-z0-9]); он же имя файлов <cn>.req/<cn>.crt.
- Отзыв = easyrsa revoke + gen-crl (crl-verify перечитывает crl.pem на каждом коннекте —
  ни рестарта, ни SIGHUP не нужно, в отличие от Xray).
- Клиентский приватник и подписанный сертификат храним вместе как JSON в client_private_key
  (ClientMaterial) — панель шифрует это поле в DeviceConfig.client_secret_encrypted.
"""

from __future__ import annotations

import contextlib
import json
import re

from vpnhub.infra.provisioning import constants as c
from vpnhub.infra.provisioning import errors, keys, script_runner, templates
from vpnhub.infra.provisioning.provisioners import base
from vpnhub.infra.provisioning.provisioners.base import ClientMaterial, ConfigArtifact, ServerMaterial
from vpnhub.infra.provisioning.ssh import SshClient

# CN всегда генерим сами из [A-Za-z0-9] — но валидируем перед подстановкой в docker exec,
# чтобы исключить любую shell-инъекцию через clientId (в т.ч. пришедший из БД/сверки).
# fullmatch, а не ^…$: $ в Python допускает завершающий \n — fullmatch этого не пропустит.
_CN_RE = re.compile(r"[A-Za-z0-9]+")


def _sanitize_static_key(key: str) -> str:
    """Порт sanitizeStaticKey: убрать #-комментарии из ta.key, гарантировать финальный \\n."""
    lines = [ln for ln in key.split("\n") if not ln.strip().startswith("#")]
    result = "\n".join(lines)
    if not result.endswith("\n"):
        result += "\n"
    return result


class OpenVpnProvisioner:
    def __init__(self, spec: c.ProtoSpec, material: ServerMaterial | None = None, transport: str = ""):
        self.spec = spec
        self._material = material
        self._transport = transport  # желаемый транспорт на install (иначе — из spec)

    @property
    def material(self) -> ServerMaterial:
        if self._material is None:
            raise ValueError("OpenVpnProvisioner: не задан серверный материал (ca/ta)")
        return self._material

    @staticmethod
    def _check_cn(cn: str) -> str:
        if not cn or not _CN_RE.fullmatch(cn):
            raise errors.make("internal", f"недопустимый clientId OpenVPN: {cn!r}")
        return cn

    # ---- переменные скриптов ----

    def install_vars(self, server_ip: str, port: str, transport: str) -> dict[str, str]:
        return {
            "$REMOTE_HOST": server_ip,
            "$CONTAINER_NAME": self.spec.container,
            "$DOCKERFILE_FOLDER": f"/opt/amnezia/{self.spec.container}",
            "$SERVER_IP_ADDRESS": server_ip,
            "$PRIMARY_SERVER_DNS": c.SERVER_PRIMARY_DNS,
            "$SECONDARY_SERVER_DNS": c.SERVER_SECONDARY_DNS,
            "$OPENVPN_PORT": port or self.spec.default_port,
            "$OPENVPN_TRANSPORT_PROTO": transport or self.spec.transport,
            "$OPENVPN_SUBNET_IP": c.OPENVPN_SUBNET_IP,
            "$OPENVPN_SUBNET_MASK": c.OPENVPN_SUBNET_MASK,
            "$OPENVPN_SUBNET_CIDR": c.OPENVPN_SUBNET_CIDR,
            "$OPENVPN_NCP_DISABLE": "",  # defaultNcpDisable=false
            "$OPENVPN_CIPHER": c.OPENVPN_DEFAULT_CIPHER,
            "$OPENVPN_HASH": c.OPENVPN_DEFAULT_HASH,
            "$OPENVPN_TLS_AUTH": c.OPENVPN_TLS_AUTH_LINE,  # defaultTlsAuth=true
            "$OPENVPN_ADDITIONAL_SERVER_CONFIG": "",
        }

    # ---- install ----

    async def install(self, ssh: SshClient, server_ip: str, port: str, transport: str = "") -> ServerMaterial:
        transport = transport or self._transport or self.spec.transport
        variables = self.install_vars(server_ip, port, transport)
        await script_runner.setup_container(ssh, self.spec, variables)
        ca_cert = await ssh.read_container_text(self.spec.container, self.spec.openvpn_ca_path)
        ta_key = await ssh.read_container_text(self.spec.container, self.spec.openvpn_ta_path)
        self._material = ServerMaterial(ca_cert=ca_cert, ta_key=ta_key, transport=transport)
        return self._material

    # ---- clients ----

    async def add_client(self, ssh: SshClient, server_ip: str, port: str, name: str) -> ClientMaterial:
        cn = self._check_cn(keys.gen_client_cn())
        priv_pem, csr_pem = keys.gen_openvpn_client_request(cn)

        # 1) загрузить .req в контейнер, 2) import-req + sign-req внутри контейнера
        await ssh.upload_to_container(
            self.spec.container, csr_pem, f"{self.spec.openvpn_clients_dir}/{cn}.req", append=False
        )
        await self._sign_cert(ssh, cn)

        # 3) забрать подписанный сертификат
        cert = await ssh.read_container_text(self.spec.container, f"{self.spec.openvpn_issued_dir}/{cn}.crt")
        if "BEGIN CERTIFICATE" not in cert:
            raise errors.make("openvpn_sign_failed", f"CN={cn}")

        await base.append_client_row(ssh, self.spec, cn, name)
        # приватник + сертификат кладём вместе (панель зашифрует это одно поле)
        secret_blob = json.dumps({"priv": priv_pem, "cert": cert})
        return ClientMaterial(client_id=cn, client_private_key=secret_blob, client_public_key="", client_ip="")

    async def _sign_cert(self, ssh: SshClient, cn: str) -> None:
        """Порт OpenVpnConfigurator::signCert: import-req + sign-req client внутри контейнера."""
        self._check_cn(cn)
        cont = self.spec.container
        await ssh.run(
            f"sudo docker exec -i {cont} bash -c "
            f'"cd /opt/amnezia/openvpn && easyrsa import-req {self.spec.openvpn_clients_dir}/{cn}.req {cn}"'
        )
        await ssh.run(
            f"sudo docker exec -i {cont} bash -c "
            f'"export EASYRSA_BATCH=1; cd /opt/amnezia/openvpn && easyrsa sign-req client {cn}"'
        )

    async def revoke_client(self, ssh: SshClient, client_id: str) -> None:
        """Порт usersController::revokeOpenVpn: revoke + gen-crl + обновить crl.pem (без рестарта)."""
        cn = self._check_cn(client_id)
        await ssh.run(
            f"sudo docker exec -i {self.spec.container} bash -c "
            f"'cd /opt/amnezia/openvpn ;easyrsa revoke {cn} ;easyrsa gen-crl ;chmod 666 pki/crl.pem ;cp pki/crl.pem .'"
        )
        await base.remove_client_row(ssh, self.spec, cn)

    async def list_clients(self, ssh: SshClient) -> list[dict]:
        return await base.read_clients_table(ssh, self.spec)

    async def list_client_ids(self, ssh: SshClient) -> set[str]:
        """Живые клиенты OpenVPN = выпущенные сертификаты (pki/issued/*.crt) минус AmneziaReq.crt.

        Порт usersController::getOpenVpnClients — источник правды именно pki/issued, а не index.txt.

        ВАЖНО для сверки (contract: no false revoke): пустой/ошибочный ответ НЕ трактуем как
        «нет клиентов». Здоровый контейнер ВСЕГДА содержит серверный AmneziaReq.crt (run_container.sh
        копирует его, не удаляя), поэтому пустой список или ненулевой код возврата = сбой чтения →
        поднимаем ошибку. sync ловит её (readable=False) и не помечает конфиги revoked.
        """
        res = await ssh.run(f"sudo docker exec -i {self.spec.container} bash -c 'ls {self.spec.openvpn_issued_dir}'")
        names = {tok.strip()[:-4] for tok in res.stdout.split() if tok.strip().endswith(".crt")}
        if res.exit_status != 0 or "AmneziaReq" not in names:
            raise errors.make("internal", f"OpenVPN: не удалось прочитать pki/issued (rc={res.exit_status})")
        names.discard("AmneziaReq")
        return {n for n in names if n}

    async def adopt(self, ssh: SshClient) -> ServerMaterial:
        """Считать материал уже установленного (в т.ч. внешним клиентом) OpenVPN-контейнера."""
        ca_cert = await ssh.read_container_text(self.spec.container, self.spec.openvpn_ca_path)
        ta_key = await ssh.read_container_text(self.spec.container, self.spec.openvpn_ta_path)
        transport = self.spec.transport
        with contextlib.suppress(Exception):
            conf = await ssh.read_container_text(self.spec.container, self.spec.server_config_path)
            for line in conf.splitlines():
                parts = line.strip().split()
                if len(parts) >= 2 and parts[0] == "proto":
                    transport = parts[1]
                    break
        return ServerMaterial(ca_cert=ca_cert, ta_key=ta_key, transport=transport)

    async def status(self, ssh: SshClient) -> bool:
        res = await ssh.run(f"sudo docker inspect -f '{{{{.State.Running}}}}' {self.spec.container}")
        return "true" in res.stdout.lower()

    # ---- сборка артефактов (чистая, без SSH) ----

    def build_artifact(self, *, server_ip: str, port: str, server_name: str, client: ClientMaterial) -> ConfigArtifact:
        blob = json.loads(client.client_private_key) if client.client_private_key else {}
        priv, cert = blob.get("priv", ""), blob.get("cert", "")
        transport = self.material.transport or self.spec.transport
        conf_vars = {
            "$REMOTE_HOST": server_ip,
            "$OPENVPN_PORT": port or self.spec.default_port,
            "$OPENVPN_TRANSPORT_PROTO": transport,
            "$OPENVPN_NCP_DISABLE": "",
            "$OPENVPN_CIPHER": c.OPENVPN_DEFAULT_CIPHER,
            "$OPENVPN_HASH": c.OPENVPN_DEFAULT_HASH,
            "$OPENVPN_ADDITIONAL_CLIENT_CONFIG": "",
            "$PRIMARY_DNS": c.CLIENT_PRIMARY_DNS,
            "$SECONDARY_DNS": c.CLIENT_SECONDARY_DNS,
            "$OPENVPN_CA_CERT": self.material.ca_cert,
            "$OPENVPN_CLIENT_CERT": cert,
            "$OPENVPN_PRIV_KEY": priv,
            "$OPENVPN_TA_KEY": _sanitize_static_key(self.material.ta_key),
        }
        conf_text = templates.replace_vars(templates.load_protocol(self.spec.script_folder, "template.ovpn"), conf_vars)
        return ConfigArtifact(
            conf_text=conf_text,
            filename=f"{(server_name or 'server').replace(' ', '_')}-openvpn-{transport}.ovpn",
            hint="Импортируйте .ovpn в OpenVPN Connect (или другой OpenVPN-клиент).",
        )
