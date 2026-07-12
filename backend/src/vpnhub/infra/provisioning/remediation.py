"""Реестр подсказок-ремедиаций для ошибок provisioning.

Превращает машинный код ошибки (ProvisioningError.code, сохранённый в
ServerProtocol.error_code) в человекочитаемую подсказку: что случилось, почему и
как чинить. Часть кейсов чинится автоматически по SSH (kind="auto" + fix_id →
идемпотентный скрипт из scripts/), остальные — текстовая инструкция пользователю
(kind="manual") либо «неисправимо» (kind="none").

Модуль-лист: зависит только от errors (для распознавания префикса кода в легаси-строках),
поэтому его безопасно импортировать из common/serializers и из services.
"""

from __future__ import annotations

from dataclasses import dataclass

from vpnhub.infra.provisioning import errors


@dataclass(frozen=True)
class Remediation:
    """Одна запись реестра: как объяснить ошибку и (опционально) как её починить."""

    code: str  # совпадает с ServerProtocol.error_code / ProvisioningError.code
    kind: str  # "auto" | "manual" | "none"
    title: str  # короткая суть по-русски
    explanation: str  # почему так вышло
    detail_contains: str | None = None  # уточнение для перегруженных кодов (напр. "internal" + "fuser")
    fix_id: str | None = None  # для kind="auto": какой фикс запускать (см. FIXES / reinstall)
    fix_label: str | None = None  # подпись кнопки автофикса
    manual_steps: tuple[str, ...] = ()  # для kind="manual": шаги/команды для пользователя


@dataclass(frozen=True)
class FixScript:
    """Идемпотентный фикс-скрипт: имя файла в scripts/, маркер успеха, подсказка при провале."""

    script: str
    ok_marker: str
    fail_hint: str


# fix_id → скрипт. Специальный fix_id "reinstall" здесь НЕ значится: он означает
# «пред-скрипт не нужен, достаточно чистой переустановки контейнера» (см. ServerService.apply_fix).
FIXES: dict[str, FixScript] = {
    "install_psmisc": FixScript(
        script="fix_install_psmisc.sh",
        ok_marker="FIX_PSMISC_OK",
        fail_hint="Не удалось установить psmisc (fuser). Проверьте доступ в интернет и работу apt/dnf на сервере.",
    ),
    "start_docker": FixScript(
        script="fix_start_docker.sh",
        ok_marker="FIX_DOCKER_ACTIVE",
        fail_hint="Не удалось запустить службу Docker. Посмотрите `journalctl -u docker` на сервере.",
    ),
}


# Порядок важен: для одного code сначала ищется запись с detail_contains (специфичная),
# затем общая (detail_contains=None). См. resolve().
REMEDIATIONS: tuple[Remediation, ...] = (
    # ---- авто-исправимые по SSH (только безопасные идемпотентные) ----
    Remediation(
        code="internal",
        detail_contains="fuser",
        kind="auto",
        fix_id="install_psmisc",
        fix_label="Исправить и продолжить",
        title="Не хватает утилиты fuser для проверки блокировки пакетов",
        explanation=(
            "На сервере не установлен пакет psmisc (даёт fuser). Панель не может проверить, "
            "занят ли менеджер пакетов, и прерывает установку. Поставим psmisc и продолжим установку."
        ),
    ),
    Remediation(
        code="docker_service_not_running",
        kind="auto",
        fix_id="start_docker",
        fix_label="Запустить Docker",
        title="Служба Docker не запущена",
        explanation="Docker установлен, но демон не активен. Запустим его и продолжим установку.",
    ),
    Remediation(
        code="container_missing",
        kind="auto",
        fix_id="reinstall",
        fix_label="Переустановить",
        title="Контейнер не найден на сервере",
        explanation="Контейнер не создался или сразу упал. Поможет чистая переустановка протокола.",
    ),
    # ---- инструкция пользователю (kind="manual") ----
    Remediation(
        code="server_busy",
        kind="manual",
        title="Менеджер пакетов сервера занят",
        explanation=(
            "Другой процесс (apt/dnf или автообновления) держит блокировку пакетного менеджера. "
            "Панель уже ждала около 5 минут."
        ),
        manual_steps=(
            "Дождитесь окончания текущих обновлений и повторите установку.",
            "Если висит надолго: sudo systemctl stop unattended-upgrades",
        ),
    ),
    Remediation(
        code="port_in_use",
        kind="manual",
        title="Порт уже занят на сервере",
        explanation="Порт протокола занят другим процессом или контейнером.",
        manual_steps=(
            "Посмотрите, кто держит порт: sudo ss -ltnup | grep <порт>",
            "Проверьте контейнеры: sudo docker ps --filter publish=<порт>",
            "Освободите порт или переустановите протокол на другом порту.",
        ),
    ),
    Remediation(
        code="sudo_package_missing",
        kind="manual",
        title="На сервере не установлен sudo",
        explanation="Установка требует sudo, но пакет отсутствует.",
        manual_steps=(
            "Зайдите на сервер под root.",
            "Установите sudo: apt-get install -y sudo (или dnf/yum/zypper/pacman).",
        ),
    ),
    Remediation(
        code="user_not_in_sudo",
        kind="manual",
        title="Пользователь не входит в группу sudo/wheel",
        explanation="У пользователя нет прав sudo, поэтому установка невозможна.",
        manual_steps=(
            "Под root: usermod -aG sudo <user> (Debian/Ubuntu) или usermod -aG wheel <user> (RHEL/Arch).",
            "Перезайдите по SSH, чтобы права применились.",
        ),
    ),
    Remediation(
        code="user_not_in_sudoers",
        kind="manual",
        title="Пользователю запрещён sudo (sudoers)",
        explanation="Панель использует только беспарольный sudo (sudo -n), а у пользователя его нет.",
        manual_steps=(
            "Под root добавьте правило NOPASSWD:",
            "echo '<user> ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/vpnhub && chmod 440 /etc/sudoers.d/vpnhub",
        ),
    ),
    Remediation(
        code="password_required",
        kind="manual",
        title="Нужен беспарольный sudo",
        explanation="Панель никогда не передаёт пароль sudo — требуется NOPASSWD-правило либо вход под root.",
        manual_steps=(
            "Под root настройте NOPASSWD sudo:",
            "echo '<user> ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/vpnhub && chmod 440 /etc/sudoers.d/vpnhub",
            "Либо укажите в карточке сервера пользователя root.",
        ),
    ),
    Remediation(
        code="permission_denied",
        kind="manual",
        title="Недостаточно прав на сервере",
        explanation="Обычно это отсутствующий или недоступный домашний каталог пользователя.",
        manual_steps=(
            "Проверьте домашний каталог пользователя.",
            "mkdir -p /home/<user> && chown <user>: /home/<user>",
        ),
    ),
    Remediation(
        code="docker_cgroups_v2",
        kind="manual",
        title="Docker несовместим с cgroups v2",
        explanation="Старая версия Docker на хосте с чистым cgroup v2.",
        manual_steps=(
            "Обновите Docker до версии с поддержкой cgroup v2 (docker-ce/docker.io).",
            "Либо переведите хост на cgroup v1: добавьте systemd.unified_cgroup_hierarchy=0 в GRUB_CMDLINE_LINUX,"
            " затем update-grub && reboot.",
        ),
    ),
    Remediation(
        code="docker_pull_rate_limit",
        kind="manual",
        title="Docker Hub: превышен лимит загрузок образа",
        explanation="Анонимный лимит Docker Hub исчерпан — образ не скачивается.",
        manual_steps=(
            "Авторизуйтесь на сервере: sudo docker login (аккаунт поднимает лимит).",
            "Либо подождите ~6 часов до сброса лимита и повторите.",
        ),
    ),
    Remediation(
        code="docker_runtime_not_supported",
        kind="manual",
        title="Среда контейнеров не поддерживается",
        explanation="На сервере обнаружен podman вместо Docker.",
        manual_steps=(
            "Установите настоящий Docker: dnf install -y docker-ce (или docker.io на Debian).",
            "При необходимости удалите podman-docker.",
        ),
    ),
    Remediation(
        code="docker_install_failed",
        kind="manual",
        title="Не удалось установить Docker",
        explanation=(
            "Пакет Docker не установился. Частая причина на Ubuntu/Debian — конфликт пакета docker.io "
            "с уже стоящим containerd.io (из официального репозитория Docker): вместе они не уживаются. "
            "Панель предпочитает docker-ce, но здесь установка не завершилась (нет доступа к "
            "download.docker.com, apt занят или репозиторий сломан)."
        ),
        manual_steps=(
            "Посмотрите, что установлено: dpkg -l | grep -E 'docker|containerd'",
            "Если стоит containerd.io — ставьте docker-ce, не docker.io: sudo apt-get install -y docker-ce",
            "Проверьте доступ в интернет и apt: sudo apt-get update",
            "После установки Docker переустановите протокол в панели.",
        ),
    ),
    Remediation(
        code="ssh",
        kind="manual",
        title="Не удалось подключиться к серверу по SSH",
        explanation="Транспортная ошибка: панель не смогла открыть SSH-канал к серверу.",
        manual_steps=(
            "Проверьте доступность host:port: nc -vz <host> <port>",
            "Проверьте логин, порт, ключ/пароль в карточке сервера.",
            "Проверьте firewall/security-group на SSH-порт.",
        ),
    ),
    # ---- неисправимо / только диагностика (kind="none") ----
    Remediation(
        code="package_manager_not_found",
        kind="none",
        title="Неподдерживаемый дистрибутив",
        explanation=(
            "Панель поддерживает apt/dnf/yum/zypper/pacman, но на сервере ни один не найден. "
            "Используйте поддерживаемый Linux (Debian/Ubuntu, Fedora/RHEL, openSUSE, Arch)."
        ),
    ),
    Remediation(
        code="internal",
        kind="none",
        title="Внутренняя ошибка provisioning",
        explanation=(
            "Обычно это признак бага панели или нездорового контейнера — авто-исправление недоступно. "
            "Проверьте `docker logs` соответствующего контейнера на сервере."
        ),
    ),
)


def _parse_code_prefix(text: str | None) -> str | None:
    """Достать код из легаси-строки вида 'code: message' (для строк без error_code)."""
    if not text:
        return None
    head = text.split(":", 1)[0].strip()
    return head if head in errors.MESSAGES else None


def resolve(code: str | None, error_text: str | None) -> Remediation | None:
    """Подобрать подсказку по коду ошибки (или по префиксу легаси-строки).

    Для перегруженных кодов (напр. "internal") сначала выбирается запись с detail_contains,
    подходящая под текст ошибки, затем — общая запись без detail_contains.
    """
    eff = code or _parse_code_prefix(error_text)
    if not eff:
        return None
    text = error_text or ""
    candidates = [r for r in REMEDIATIONS if r.code == eff]
    for r in candidates:
        if r.detail_contains and r.detail_contains in text:
            return r
    for r in candidates:
        if not r.detail_contains:
            return r
    return None


def to_dict(rem: Remediation) -> dict:
    """Сериализация подсказки в DTO для фронта (camelCase)."""
    return {
        "kind": rem.kind,
        "title": rem.title,
        "explanation": rem.explanation,
        "canAutoFix": rem.kind == "auto",
        "fixLabel": rem.fix_label,
        "manualSteps": list(rem.manual_steps),
    }
