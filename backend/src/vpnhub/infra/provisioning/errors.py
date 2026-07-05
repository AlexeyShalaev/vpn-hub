"""Ошибки provisioning с человекочитаемыми сообщениями (порт ErrorCode из amnezia-client)."""

from __future__ import annotations


class ProvisioningError(Exception):
    """Бизнес-ошибка установки/настройки протокола на сервере."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


# code -> сообщение (RU), аналог набора ErrorCode Amnezia
MESSAGES: dict[str, str] = {
    "sudo_package_missing": "На сервере не установлен пакет sudo",
    "user_not_in_sudo": "Пользователь не входит в группу sudo/wheel",
    "user_not_in_sudoers": "Пользователю запрещён sudo (sudoers)",
    "password_required": "Требуется беспарольный sudo (sudo -n)",
    "permission_denied": "Недостаточно прав на сервере",
    "server_busy": "Менеджер пакетов сервера занят (dpkg/yum lock)",
    "package_manager_not_found": "Не найден менеджер пакетов на сервере",
    "docker_cgroups_v2": "Docker несовместим с cgroups v2 на этом сервере",
    "docker_pull_rate_limit": "Docker Hub: превышен лимит загрузок образа",
    "docker_runtime_not_supported": "Среда контейнеров не поддерживается (например, podman)",
    "docker_service_not_running": "Служба Docker не запущена",
    "docker_failed": "Ошибка Docker при сборке/запуске контейнера",
    "kernel_too_old": "Слишком старое ядро Linux для AmneziaWG",
    "port_in_use": "Порт уже занят на сервере",
    "container_missing": "Контейнер не найден на сервере",
    "openvpn_sign_failed": "Не удалось подписать клиентский сертификат OpenVPN на сервере",
    "ssh": "Ошибка SSH-подключения к серверу",
    "invalid_params": "Некорректные параметры обфускации",
    "internal": "Внутренняя ошибка provisioning",
}


def make(code: str, detail: str = "") -> ProvisioningError:
    msg = MESSAGES.get(code, code)
    if detail:
        msg = f"{msg}: {detail}"
    return ProvisioningError(code, msg)
