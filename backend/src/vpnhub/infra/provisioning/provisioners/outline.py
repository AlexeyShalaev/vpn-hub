"""Провизионер Outline (Jigsaw shadowbox / Shadowsocks) — порт install_server.sh + Management API.

Отличие от awg/xray/openvpn: членством управляет НЕ правка файлов в контейнере, а REST-API
самого shadowbox (Management API). Поэтому:
- install разворачивает контейнер официальным `install_server.sh` (забандлен 1:1 в scripts/outline)
  и читает из его вывода `{"apiUrl","certSha256"}` — базовый URL с секретным префиксом + отпечаток
  self-signed серта. Это и есть серверный материал (ServerMaterial.outline_*).
- add/revoke/list — HTTP-вызовы к Management API. Ходим `curl`-ом ПО SSH на localhost сервера
  (как сам installer в wait_shadowbox), с `-k`: канал уже доверенный (SSH), а серт localhost не
  покрывает. Наружу порт API открывать не нужно.
- clientId = id access-key (строка-счётчик, что назначает shadowbox); секрет (method:password:port
  + готовый accessUrl) кладём JSON-ом в ClientMaterial.client_private_key — панель его шифрует.
- clientsTable у Outline нет: имена/ключи хранит сам shadowbox. list_clients возвращает строки в
  форме clientsTable, чтобы владельческие панели (external_clients) работали единообразно.
"""

from __future__ import annotations

import contextlib
import json
import re
import shlex
from urllib.parse import urlparse, urlunparse

from vpnhub.common.net import is_valid_host
from vpnhub.infra.provisioning import constants as c
from vpnhub.infra.provisioning import errors, templates, vpn_uri
from vpnhub.infra.provisioning.provisioners.base import ClientMaterial, ConfigArtifact, ServerMaterial
from vpnhub.infra.provisioning.ssh import SshClient

# id access-key из shadowbox — строка-счётчик; валидируем перед подстановкой в URL curl (anti-injection).
_KEY_ID_RE = re.compile(r"[A-Za-z0-9_-]+")
# apiUrl из install/adopt: https://<host>:<port>/<base64url-префикс>
_API_URL_RE = re.compile(r"https://[^\s/]+:\d+/[A-Za-z0-9_\-]+")
# строка вывода installer: {"apiUrl":"...","certSha256":"<hex>"}
_INSTALL_OUT_RE = re.compile(r'\{"apiUrl":"(?P<url>https://[^"]+)","certSha256":"(?P<sha>[0-9A-Fa-f]+)"\}')

# -f: HTTP>=400 → выход 22 (не 0), чтобы отличать успех от ошибки по коду; -k: серт localhost.
_CURL = "curl -sfk --max-time 20 --retry 2 --retry-delay 1"


class OutlineProvisioner:
    def __init__(self, spec: c.ProtoSpec, material: ServerMaterial | None = None):
        self.spec = spec
        self._material = material

    @property
    def material(self) -> ServerMaterial:
        if self._material is None or not self._material.outline_api_url:
            raise ValueError("OutlineProvisioner: не задан серверный материал (apiUrl)")
        return self._material

    # ---- helpers: Management API ----

    def _local_api(self) -> str:
        """apiUrl с host→localhost (порт/префикс сохраняем): ходим на сам сервер по SSH."""
        u = urlparse(self.material.outline_api_url)
        return urlunparse(u._replace(netloc=f"127.0.0.1:{u.port}"))

    @staticmethod
    def _check_key_id(key_id: str) -> str:
        if not key_id or not _KEY_ID_RE.fullmatch(key_id):
            raise errors.make("internal", f"недопустимый Outline access-key id: {key_id!r}")
        return key_id

    async def _api(self, ssh: SshClient, method: str, path: str) -> tuple[int, str]:
        """curl к Management API без тела. path — уже безопасный суффикс (валидируется вызывающим)."""
        url = f"{self._local_api()}{path}"
        res = await ssh.run(f'{_CURL} -X {method} "{url}"')
        return res.exit_status, res.stdout

    # ---- install ----

    async def install(self, ssh: SshClient, server_ip: str, port: str) -> ServerMaterial:
        """Развернуть shadowbox официальным install_server.sh и прочитать apiUrl/certSha256."""
        keys_port = port or self.spec.default_port
        if not keys_port.isdigit():
            raise errors.make("internal", f"Outline: недопустимый keys-port {keys_port!r}")
        if not is_valid_host(server_ip):
            raise errors.make("internal", f"Outline: недопустимый server_ip {server_ip!r}")
        script = templates.load_protocol(self.spec.script_folder, "install_server.sh")
        remote = "/tmp/outline_install.sh"  # noqa: S108 — временный файл на удалённом хосте, ниже удаляем
        await ssh.upload_to_host(script, remote)
        try:
            res = await ssh.run(f"sudo bash {remote} --hostname {shlex.quote(server_ip)} --keys-port {keys_port}")
        finally:
            await ssh.run(f"sudo shred -u {remote} 2>/dev/null || sudo rm -f {remote}")

        m = _INSTALL_OUT_RE.search(res.output)
        if not m:
            raise errors.make("docker_failed", f"Outline: install_server.sh не вернул apiUrl (rc={res.exit_status})")
        material = ServerMaterial(outline_api_url=m.group("url"), outline_cert_sha256=m.group("sha").upper())
        self._material = material
        await self._open_firewall(ssh, keys_port)
        return material

    async def _open_firewall(self, ssh: SshClient, keys_port: str) -> None:
        """Best-effort: открыть keys-port (tcp+udp) на хостовом файрволе. Сбои игнорируем.

        Outline (--net host) слушает keys-port напрямую на хосте; installer файрвол НЕ трогает.
        Правила добавляем идемпотентно (-C || -I) и не роняем install на ошибке."""
        if not keys_port.isdigit():
            return
        for proto in ("tcp", "udp"):
            rule = f"INPUT -p {proto} --dport {keys_port} -j ACCEPT"
            await ssh.run(f"sudo iptables -C {rule} 2>/dev/null || sudo iptables -I {rule} 2>/dev/null || true")

    # ---- clients ----

    async def add_client(self, ssh: SshClient, server_ip: str, port: str, name: str) -> ClientMaterial:
        code, out = await self._api(ssh, "POST", "/access-keys")
        if code != 0:
            raise errors.make("internal", f"Outline: POST /access-keys не удался (rc={code})")
        try:
            key = json.loads(out)
        except json.JSONDecodeError as e:
            raise errors.make("internal", "Outline: неразобранный ответ POST /access-keys") from e
        key_id = self._check_key_id(str(key.get("id", "")))
        await self._rename(ssh, key_id, name)  # best-effort — имя видно в Outline Manager
        blob = json.dumps(
            {
                "method": key.get("method", ""),
                "password": key.get("password", ""),
                "port": str(key.get("port", "") or (port or self.spec.default_port)),
                "access_url": key.get("accessUrl", ""),
            }
        )
        return ClientMaterial(client_id=key_id, client_private_key=blob)

    async def _rename(self, ssh: SshClient, key_id: str, name: str) -> None:
        """PUT /access-keys/<id>/name с телом-JSON. Тело грузим файлом (без shell-инъекции)."""
        if not name:
            return
        body = f"/tmp/outline_name_{key_id}.json"  # noqa: S108 — временный файл на удалённом хосте, ниже удаляем
        try:
            # имя косметическое (видно в Outline Manager) — сбой не роняет выдачу ключа
            with contextlib.suppress(Exception):
                await ssh.upload_to_host(json.dumps({"name": name}), body)
                url = f"{self._local_api()}/access-keys/{key_id}/name"
                await ssh.run(f'{_CURL} -X PUT -H "Content-Type: application/json" -d @{body} "{url}"')
        finally:
            await ssh.run(f"rm -f {body} 2>/dev/null || true")

    async def revoke_client(self, ssh: SshClient, client_id: str) -> None:
        key_id = self._check_key_id(client_id)
        code, _ = await self._api(ssh, "DELETE", f"/access-keys/{key_id}")
        # 204 → curl rc 0; удаление отсутствующего ключа shadowbox отвечает 404 → curl -f rc 22.
        # revoke идемпотентен: отсутствующий ключ = уже снят, ошибку не поднимаем.
        if code not in (0, 22):
            raise errors.make("internal", f"Outline: DELETE access-key {key_id} не удался (rc={code})")

    async def _list_keys(self, ssh: SshClient) -> list[dict]:
        """Сырой GET /access-keys → список ключей. Бросает при недоступности API (не пустой список)."""
        code, out = await self._api(ssh, "GET", "/access-keys")
        if code != 0:
            raise errors.make("internal", f"Outline: GET /access-keys не удался (rc={code})")
        try:
            doc = json.loads(out)
        except json.JSONDecodeError as e:
            raise errors.make("internal", "Outline: неразобранный ответ GET /access-keys") from e
        keys = doc.get("accessKeys")
        if not isinstance(keys, list):
            raise errors.make("internal", "Outline: в ответе нет accessKeys")
        return keys

    async def list_clients(self, ssh: SshClient) -> list[dict]:
        """Строки в форме clientsTable (для единообразия с владельческими панелями)."""
        return [
            {"clientId": str(k.get("id", "")), "userData": {"clientName": k.get("name") or ""}}
            for k in await self._list_keys(ssh)
            if k.get("id") is not None
        ]

    async def list_client_ids(self, ssh: SshClient) -> set[str]:
        """Живые клиенты = id всех access-key. Пустой список ЗДЕСЬ легитимен (все ключи удалены),

        поэтому «читаемость» определяется успехом HTTP, а не непустотой (в отличие от awg/openvpn):
        при недоступности API _list_keys бросает → sync выставит readable=False → без ложного revoke.
        """
        return {str(k["id"]) for k in await self._list_keys(ssh) if k.get("id") is not None}

    async def adopt(self, ssh: SshClient) -> ServerMaterial:
        """Считать материал уже установленного (в т.ч. Outline Manager-ом) сервера из access.txt.

        Файл /opt/outline/access.txt содержит строки `apiUrl:<url>` и `certSha256:<hex>`."""
        res = await ssh.run(f"sudo cat {self.spec.outline_access_config}")
        api_url, sha = "", ""
        for raw in res.stdout.splitlines():
            line = raw.strip()
            if line.startswith("apiUrl:"):
                api_url = line[len("apiUrl:") :].strip()
            elif line.startswith("certSha256:"):
                sha = line[len("certSha256:") :].strip()
        if not _API_URL_RE.fullmatch(api_url or ""):
            raise errors.make("internal", "Outline: не удалось прочитать apiUrl из access.txt")
        return ServerMaterial(outline_api_url=api_url, outline_cert_sha256=sha.upper())

    async def status(self, ssh: SshClient) -> bool:
        res = await ssh.run(f"sudo docker inspect -f '{{{{.State.Running}}}}' {self.spec.container}")
        return "true" in res.stdout.lower()

    # ---- сборка артефакта (чистая, без SSH) ----

    def build_artifact(self, *, server_ip: str, port: str, server_name: str, client: ClientMaterial) -> ConfigArtifact:
        blob = json.loads(client.client_private_key) if client.client_private_key else {}
        method, password = blob.get("method", ""), blob.get("password", "")
        key_port = str(blob.get("port") or port or self.spec.default_port)
        alias = server_name or "Outline"
        if method and password:
            ss = vpn_uri.build_ss_url(
                method=method, password=password, host=server_ip, port=key_port, alias=alias, outline=True
            )
        else:  # запасной путь — готовый accessUrl от shadowbox (host в нём уже серверный)
            ss = blob.get("access_url", "")
        return ConfigArtifact(
            conf_text=ss,
            vpn_url=ss,
            filename=f"{alias.replace(' ', '_')}-outline.txt",
            hint="Скопируйте ключ ss:// и добавьте в приложении Outline → «+».",
        )
