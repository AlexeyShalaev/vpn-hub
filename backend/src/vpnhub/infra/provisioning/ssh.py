"""SSH-транспорт для provisioning (asyncssh) — порт SshSession/SshClient из amnezia-client.

Реплицирует ключевое поведение официального клиента:
- Скрипты Amnezia — это один логический bash-скрипт (строки склеены через `\\`), поэтому
  выполняем весь текст одной командой (эквивалентно построчному exec клиента, но надёжнее
  для многострочных конструкций). cwd/env между вызовами НЕ сохраняются.
- Коды возврата не используются для диагностики — ошибки детектируются по подстрокам в
  объединённом stdout+stderr (см. script_runner). exit_status отдаём дополнительно.
- sudo — только беспарольный (`sudo -n`), пароль нигде не передаётся (как в Amnezia).
- Файлы на хост — по SFTP; в контейнер — через /tmp staging + `docker cp` (+`cat >>` для append);
  чтение из контейнера — `docker exec ... xxd -p` + hex-декод.
"""

from __future__ import annotations

import secrets
import shlex
from dataclasses import dataclass
from typing import Any

import asyncssh


class SshError(Exception):
    """Ошибка SSH-транспорта (подключение/канал), не бизнес-ошибка provisioning."""


@dataclass(frozen=True)
class ServerCreds:
    host: str
    port: int
    username: str
    auth: str  # "key" | "password"
    secret: str  # приватный ключ (PEM/OpenSSH) или пароль


@dataclass(frozen=True)
class SshResult:
    stdout: str
    stderr: str
    exit_status: int

    @property
    def output(self) -> str:
        """Объединённый вывод — Amnezia матчит ошибки по нему целиком."""
        return (self.stdout or "") + (self.stderr or "")


def _rand_name() -> str:
    return secrets.token_hex(8)  # 16 hex-символов, как Utils::getRandomString(16)


class SshClient:
    """Асинхронный SSH-клиент к одному серверу. Использовать как async context manager."""

    def __init__(self, creds: ServerCreds, *, connect_timeout: float = 20.0) -> None:
        self.creds = creds
        self._connect_timeout = connect_timeout
        self._conn: asyncssh.SSHClientConnection | None = None

    async def __aenter__(self) -> SshClient:
        await self.connect()
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.close()

    async def connect(self) -> None:
        opts: dict[str, Any] = {
            "host": self.creds.host,
            "port": int(self.creds.port or 22),
            "username": self.creds.username or "root",
            "known_hosts": None,  # self-hosted: доверяем хосту при первом подключении (как libssh accept)
            "connect_timeout": self._connect_timeout,
            # keepalive на транспорте: если пир перестал отвечать после установления сессии
            # (firewall-blackhole, NAT idle-timeout, зависший `docker ps`), рвём соединение через
            # ~interval*count секунд. Иначе conn.run() без таймаута висел бы бесконечно — connect_timeout
            # покрывает только фазу подключения, но не уже открытый канал.
            "keepalive_interval": 10,
            "keepalive_count_max": 3,
        }
        if self.creds.auth == "password":
            opts["password"] = self.creds.secret
        else:
            try:
                key = asyncssh.import_private_key(self.creds.secret)
            except (asyncssh.KeyImportError, ValueError) as e:
                raise SshError(f"Некорректный SSH-ключ: {e}") from e
            opts["client_keys"] = [key]
        try:
            self._conn = await asyncssh.connect(**opts)
        except (OSError, asyncssh.Error) as e:
            raise SshError(f"Не удалось подключиться к {self.creds.host}: {e}") from e

    async def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            await self._conn.wait_closed()
            self._conn = None

    @property
    def _c(self) -> asyncssh.SSHClientConnection:
        if self._conn is None:
            raise SshError("SSH-соединение не установлено")
        return self._conn

    # ------------------------------------------------------------------ exec ---

    async def run(self, command: str) -> SshResult:
        """Выполнить команду/скрипт целиком; вернуть stdout/stderr/exit_status."""
        try:
            r = await self._c.run(command, check=False)
        except asyncssh.Error as e:
            raise SshError(f"Ошибка выполнения команды: {e}") from e
        return SshResult(
            stdout=r.stdout if isinstance(r.stdout, str) else (r.stdout or b"").decode(errors="replace"),
            stderr=r.stderr if isinstance(r.stderr, str) else (r.stderr or b"").decode(errors="replace"),
            exit_status=r.exit_status if isinstance(r.exit_status, int) else -1,
        )

    # Amnezia runScript == выполнение всего скрипта (строки склеены через `\`).
    run_script = run

    # ----------------------------------------------------------- file upload ---

    async def upload_to_host(self, data: str | bytes, remote_path: str) -> None:
        payload = data.encode() if isinstance(data, str) else data
        try:
            async with self._c.start_sftp_client() as sftp, sftp.open(remote_path, "wb") as f:
                await f.write(payload)
        except (OSError, asyncssh.Error) as e:
            raise SshError(f"SFTP upload не удался ({remote_path}): {e}") from e

    async def upload_to_container(
        self, container: str, data: str | bytes, path: str, *, append: bool = False
    ) -> SshResult:
        """Загрузить текст/файл в контейнер (порт uploadTextFileToContainer)."""
        tmp = f"/tmp/{_rand_name()}.tmp"  # noqa: S108 — путь на удалённом управляемом хосте, не локальный
        await self.upload_to_host(data, tmp)
        q_path = shlex.quote(path)
        await self.run(f'sudo docker exec -i {container} mkdir -p "$(dirname {q_path})"')
        if append:
            res = await self.run(f"sudo docker cp {tmp} {container}:{tmp}")
            res = await self.run(f'sudo docker exec -i {container} sh -c "cat {tmp} >> {q_path}"')
        else:
            res = await self.run(f"sudo docker cp {tmp} {container}:/{path.lstrip('/')}")
        await self.run(f"sudo shred -u {tmp}")
        return res

    async def read_container_file(self, container: str, path: str) -> bytes:
        """Прочитать файл из контейнера (docker exec + xxd -p + hex-декод)."""
        q_path = shlex.quote(path)
        res = await self.run(f"sudo docker exec -i {container} sh -c \"xxd -p '{path}'\"")
        hex_str = "".join(res.stdout.split())
        try:
            return bytes.fromhex(hex_str)
        except ValueError:
            # fallback: возможно xxd отсутствует — пробуем cat
            res = await self.run(f"sudo docker exec -i {container} cat {q_path}")
            return res.stdout.encode()

    async def read_container_text(self, container: str, path: str) -> str:
        return (await self.read_container_file(container, path)).decode(errors="replace").strip()

    async def run_container_script(self, container: str, script: str, *, use_sh: bool = False) -> SshResult:
        """Загрузить и выполнить скрипт ВНУТРИ контейнера как единый файл (порт runContainerScript)."""
        fname = f"/opt/amnezia/{_rand_name()}.sh"
        await self.upload_to_container(container, script, fname, append=False)
        shell = "sh" if use_sh else "bash"
        res = await self.run(f"sudo docker exec -i {container} {shell} {fname}")
        await self.run(f"sudo docker exec -i {container} rm {fname}")
        return res

    async def container_exec(self, container: str, command: str, *, detach: bool = False) -> SshResult:
        flag = "-d" if detach else "-i"
        return await self.run(f"sudo docker exec {flag} {container} {command}")
