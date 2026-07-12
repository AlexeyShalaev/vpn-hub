"""Оркестратор установки контейнера-протокола (порт InstallController::setupContainer).

Повторяет порядок шагов и диагностику ошибок официального клиента: предчек sudo →
ожидание разблокировки пакетного менеджера → установка docker → prepare host →
remove(старого) → build → run → configure(внутри контейнера) → firewall → startup.
Ошибки детектируются по подстрокам в объединённом выводе (Amnezia игнорирует коды возврата).
Идемпотентность — по `docker ps` (см. already_installed_containers).
"""

from __future__ import annotations

import asyncio
import re

from vpnhub.common.net import is_valid_host, is_valid_port
from vpnhub.infra.provisioning import errors, templates
from vpnhub.infra.provisioning.constants import PROTOCOLS, ProtoSpec
from vpnhub.infra.provisioning.ssh import SshClient, SshError

# docker ps --format '{{.Names}} {{.Ports}}' → имя контейнера + опубликованный порт
_PS_RE = re.compile(r"(amnezia[-a-z0-9]*).*?:([0-9]+)->[0-9]+/(udp|tcp)")

# Переменные, которые подставляются в bundled-скрипты БЕЗ кавычек и подвержены влиянию
# пользователя (server.ip → $SERVER_IP_ADDRESS/$REMOTE_HOST, порты протоколов → $*_PORT).
_HOST_VAR_KEYS = ("$SERVER_IP_ADDRESS", "$REMOTE_HOST")


def _assert_safe_vars(script_vars: dict[str, str]) -> None:
    """Defense-in-depth перед подстановкой в shell.

    Граница (`ServerService`) уже валидирует `server.ip`, но провизионеры не должны на неё
    полагаться: host-переменные обязаны быть валидным IP/hostname, порты — числом 1..65535.
    Так закрывается shell-инъекция через `$SERVER_IP_ADDRESS`/`$*_PORT` в start.sh/run_container.sh.
    """
    for key in _HOST_VAR_KEYS:
        val = script_vars.get(key)
        if val and not is_valid_host(val):
            raise errors.make("internal", f"недопустимый {key}={val!r}")
    for key, val in script_vars.items():
        if key.endswith("_PORT") and val and not is_valid_port(val):
            raise errors.make("internal", f"недопустимый {key}={val!r}")


# все контейнеры, которыми управляет панель (amnezia-* + shadowbox); для сверки состояния
_KNOWN_CONTAINERS = frozenset(spec.container for spec in PROTOCOLS.values())

_DPKG_BUSY_ATTEMPTS = 30
_DPKG_BUSY_DELAY = 10.0  # сек


async def already_installed_containers(ssh: SshClient) -> dict[str, str]:
    """{имя_контейнера: опубликованный_порт} для запущенных amnezia-* контейнеров."""
    res = await ssh.run("sudo docker ps --format '{{.Names}} {{.Ports}}'")
    out: dict[str, str] = {}
    for line in res.stdout.splitlines():
        m = _PS_RE.search(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


async def list_known_containers(ssh: SshClient) -> dict[str, bool]:
    """{имя_контейнера: running?} для ВСЕХ управляемых панелью контейнеров (amnezia-* + shadowbox),

    включая остановленные. Ключ по точному имени: shadowbox (Outline) не подходит под amnezia-* префикс.
    """
    res = await ssh.run("sudo docker ps -a --format '{{.Names}}|{{.State}}'")
    out: dict[str, bool] = {}
    for raw in res.stdout.splitlines():
        line = raw.strip()
        if "|" not in line:
            continue
        name, state = line.split("|", 1)
        if name in _KNOWN_CONTAINERS:
            out[name] = state.strip().lower() == "running"
    return out


async def _check_user_in_sudo(ssh: SshClient) -> None:
    out = (await ssh.run_script(templates.load_shared("check_user_in_sudo.sh"))).output
    is_root = (ssh.creds.username or "root") == "root"
    if not is_root and "sudo:" in out and "uname:" not in out and "not found" in out:
        raise errors.make("sudo_package_missing")
    if not is_root and "sudo" not in out and "wheel" not in out:
        raise errors.make("user_not_in_sudo")
    if "can't cd to" in out or "Permission denied" in out or "No such file or directory" in out:
        raise errors.make("permission_denied")
    if re.search(r"\bsudoers\b", out) or "is not allowed to" in out or "can't do that" in out:
        raise errors.make("user_not_in_sudoers")
    if "password is required" in out or "authentication is required" in out:
        raise errors.make("password_required")


async def _wait_dpkg_free(ssh: SshClient) -> None:
    script = templates.load_shared("check_server_is_busy.sh")
    for _ in range(_DPKG_BUSY_ATTEMPTS):
        out = (await ssh.run_script(script)).output
        if "Packet manager not found" in out:
            raise errors.make("package_manager_not_found")
        if "fuser not installed" in out or "cat not installed" in out:
            raise errors.make("internal", "нет fuser/cat для проверки блокировки")
        if not out.strip():  # пусто → не занято
            return
        await asyncio.sleep(_DPKG_BUSY_DELAY)
    raise errors.make("server_busy")


async def _install_docker(ssh: SshClient) -> None:
    out = (await ssh.run_script(templates.load_shared("install_docker.sh"))).output
    if "doesn't work on cgroups v2" in out:
        raise errors.make("docker_cgroups_v2")
    if "have reached" in out and "pull rate limit" in out:
        raise errors.make("docker_pull_rate_limit")
    if "Container runtime is not supported" in out:
        raise errors.make("docker_runtime_not_supported")
    # Пакет Docker не установился (напр. docker.io конфликтует с containerd.io) — проверяем ДО
    # docker_service_not_running: при отсутствии пакета служба тоже «не активна», но причина иная.
    if "Docker package not installed" in out:
        raise errors.make("docker_install_failed")
    if "Container runtime service not running" in out:
        raise errors.make("docker_service_not_running")


def _check_docker_run_output(out: str) -> None:
    if "address already in use" in out or "is already in use by container" in out:
        raise errors.make("port_in_use")
    if "invalid publish" in out:
        raise errors.make("docker_failed")
    if "have reached" in out and "pull rate limit" in out:
        raise errors.make("docker_pull_rate_limit")
    if "No such container" in out:
        raise errors.make("container_missing")


async def _prepare_host(ssh: SshClient, script_vars: dict[str, str]) -> None:
    script = templates.replace_vars(templates.load_shared("prepare_host.sh"), script_vars)
    await ssh.run_script(script)


async def _remove_container(ssh: SshClient, script_vars: dict[str, str]) -> None:
    # результат намеренно игнорируется (как в setupContainer:136)
    script = templates.replace_vars(templates.load_shared("remove_container.sh"), script_vars)
    await ssh.run_script(script)


async def _build_container(ssh: SshClient, spec: ProtoSpec, script_vars: dict[str, str]) -> None:
    folder = script_vars["$DOCKERFILE_FOLDER"]
    dockerfile = templates.replace_vars(templates.load_protocol(spec.script_folder, "Dockerfile"), script_vars)
    await ssh.run(f"sudo rm -f {folder}/Dockerfile")
    await ssh.upload_to_host(dockerfile, f"{folder}/Dockerfile")
    build_sh = templates.replace_vars(templates.load_shared("build_container.sh"), script_vars)
    out = (await ssh.run_script(build_sh)).output
    _check_docker_run_output(out)


async def _run_container(ssh: SshClient, spec: ProtoSpec, script_vars: dict[str, str]) -> None:
    script = templates.replace_vars(templates.load_protocol(spec.script_folder, "run_container.sh"), script_vars)
    out = (await ssh.run_script(script)).output
    _check_docker_run_output(out)


async def _configure_container(ssh: SshClient, spec: ProtoSpec, script_vars: dict[str, str]) -> None:
    script = templates.replace_vars(templates.load_protocol(spec.script_folder, "configure_container.sh"), script_vars)
    res = await ssh.run_container_script(spec.container, script)
    _check_docker_run_output(res.output)


async def _setup_firewall(ssh: SshClient, script_vars: dict[str, str]) -> None:
    # результат намеренно игнорируется (как в setupContainer:155)
    script = templates.replace_vars(templates.load_shared("setup_host_firewall.sh"), script_vars)
    await ssh.run_script(script)


async def _startup_container(ssh: SshClient, spec: ProtoSpec, script_vars: dict[str, str]) -> None:
    start_sh = templates.replace_vars(templates.load_protocol(spec.script_folder, "start.sh"), script_vars)
    await ssh.upload_to_container(spec.container, start_sh, "/opt/amnezia/start.sh", append=False)
    await ssh.container_exec(
        spec.container,
        'sh -c "chmod a+x /opt/amnezia/start.sh && /opt/amnezia/start.sh"',
        detach=True,
    )


async def setup_container(
    ssh: SshClient, spec: ProtoSpec, script_vars: dict[str, str], *, is_update: bool = False
) -> None:
    """Полная установка контейнера-протокола на сервер (11 шагов setupContainer)."""
    _assert_safe_vars(script_vars)
    try:
        await _check_user_in_sudo(ssh)
        await _wait_dpkg_free(ssh)
        await _install_docker(ssh)
        await _prepare_host(ssh, script_vars)
        await _remove_container(ssh, script_vars)
        await _build_container(ssh, spec, script_vars)
        await _run_container(ssh, spec, script_vars)
        await _configure_container(ssh, spec, script_vars)
        await _setup_firewall(ssh, script_vars)
        await _startup_container(ssh, spec, script_vars)
    except SshError as e:
        raise errors.make("ssh", str(e)) from e


async def remove_container(ssh: SshClient, script_vars: dict[str, str]) -> None:
    """Публичный remove (для vpn_op remove)."""
    try:
        await _remove_container(ssh, script_vars)
    except SshError as e:
        raise errors.make("ssh", str(e)) from e
