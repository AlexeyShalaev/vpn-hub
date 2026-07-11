"""Серверная локализация ответов — тот же дух, что и на фронте (frontend/src/lib/i18n.ts).

Зачем: пользователь выбирает язык в интерфейсе, и бэкенд должен возвращать
человекочитаемый текст (ошибки, заметки релизов) на этом языке. Инфраструктуры
gettext/babel сознательно избегаем — панель self-hosted, зависимости держим под
контролем. Достаточно словаря ключ→{ru,en} + интерполяции `{var}`.

Как это связано с ошибками: доменные ошибки (`core.errors.DomainError`) несут
`key` + `params` вместо готовой строки. Центральный обработчик в
`api/entrypoint.py` определяет язык запроса (`resolve_lang`) и рендерит
`translate(key, lang, **params)`. `ru` — источник истины, `en` обязан покрывать
ровно те же ключи (проверяется тестом test_i18n_parity).

Как добавить сообщение: допишите ключ в `MESSAGES` с обоими языками и используйте
`raise BadRequest(key="...", params={...})` (или соответствующий подкласс).
"""

from __future__ import annotations

import re
from typing import Literal

Lang = Literal["ru", "en"]
LANGS: tuple[Lang, ...] = ("ru", "en")
DEFAULT_LANG: Lang = "ru"

# ── словарь сообщений: ключ → перевод на каждый язык ─────────────────────────────
# `ru` — источник истины. `en` обязан содержать те же ключи (см. тест паритета).
# Значения могут содержать плейсхолдеры `{name}` — их подставляет `translate(...)`.
MESSAGES: dict[str, dict[Lang, str]] = {
    # базовые дефолты доменных ошибок (core/errors.py)
    "error.generic": {"ru": "Ошибка", "en": "Error"},
    "error.not_found": {"ru": "Не найдено", "en": "Not found"},
    "error.unauthorized": {"ru": "Требуется вход", "en": "Sign in required"},
    "error.forbidden": {"ru": "Недостаточно прав", "en": "Insufficient permissions"},
    "error.too_many_requests": {
        "ru": "Слишком много попыток, попробуйте позже",
        "en": "Too many attempts, try again later",
    },
    "error.csrf": {"ru": "Запрос отклонён (CSRF)", "en": "Request rejected (CSRF)"},
    # статусы самообновления (возвращаются не как ошибка, а как data-ответ)
    "update.already_running": {"ru": "Обновление уже запущено", "en": "An update is already running"},
    "update.not_configured": {
        "ru": "Автообновление не настроено. Обновите образ вручную.",
        "en": "Auto-update is not configured. Update the image manually.",
    },
    "update.already_latest": {
        "ru": "Установлена последняя версия — обновлять нечего",
        "en": "You already have the latest version — nothing to update",
    },
    "update.check_disabled": {
        "ru": "Проверка обновлений отключена (VPNHUB_UPDATE_FEED_URL=off)",
        "en": "Update check is disabled (VPNHUB_UPDATE_FEED_URL=off)",
    },
    "update.feed_failed": {
        "ru": "Не удалось получить фид обновлений: {error}",
        "en": "Failed to fetch the update feed: {error}",
    },
    # ── ключи модулей (пополняются миграцией i18n) ───────────────────────────────
    # AUTO-KEYS-START — не удалять этот маркер: между ним и AUTO-KEYS-END живут
    # сообщения, извлечённые из сервисов/роутеров при переводе бэкенда.
    "admin.device_limit_min": {
        "ru": "Лимит устройств должен быть не меньше 1",
        "en": "Device limit must be at least 1",
    },
    "admin.name_phone_required": {"ru": "Имя и телефон обязательны", "en": "Name and phone are required"},
    "admin.retention_days_negative": {
        "ru": "Дни хранения не могут быть отрицательными",
        "en": "Retention days cannot be negative",
    },
    "admin.size_cap_negative": {
        "ru": "Лимит размера не может быть отрицательным",
        "en": "Size limit cannot be negative",
    },
    "admin.user_not_found": {"ru": "Пользователь не найден", "en": "User not found"},
    "auth.account_blocked": {
        "ru": "Аккаунт заблокирован. Обратитесь к администратору.",
        "en": "Account is blocked. Please contact the administrator.",
    },
    "auth.account_pending": {
        "ru": "Аккаунт ожидает подтверждения администратора.",
        "en": "Account is pending administrator approval.",
    },
    "auth.admin_already_created": {"ru": "Администратор уже создан", "en": "Administrator has already been created"},
    "auth.current_password_incorrect": {"ru": "Текущий пароль неверен", "en": "Current password is incorrect"},
    "auth.enter_phone_password": {"ru": "Введите телефон и пароль", "en": "Enter phone and password"},
    "auth.fill_name_phone_password": {
        "ru": "Заполните имя, телефон и пароль",
        "en": "Please fill in name, phone, and password",
    },
    "auth.invalid_credentials": {"ru": "Неверный телефон или пароль", "en": "Invalid phone or password"},
    "auth.invalid_phone": {"ru": "Введите корректный номер телефона", "en": "Enter a valid phone number"},
    "auth.passwords_mismatch": {"ru": "Пароли не совпадают", "en": "Passwords do not match"},
    "auth.phone_already_registered": {
        "ru": "Этот номер уже зарегистрирован",
        "en": "This phone number is already registered",
    },
    "auth.session_not_found": {"ru": "Сессия не найдена", "en": "Session not found"},
    "authApi.master_key_required": {"ru": "Задайте мастер-ключ восстановления", "en": "Set a recovery master key"},
    "authApi.master_key_too_short": {
        "ru": "Мастер-ключ — минимум 8 символов",
        "en": "Master key must be at least 8 characters",
    },
    "authApi.system_already_configured": {"ru": "Система уже настроена", "en": "The system is already set up"},
    "backup.corrupted_file": {"ru": "Повреждённый файл бэкапа", "en": "Corrupted backup file"},
    "backup.encryption_key_not_set": {
        "ru": "Не задан ключ шифрования бэкапов",
        "en": "Backup encryption key is not set",
    },
    "backup.enter_master_key": {"ru": "Введите мастер-ключ бэкапа", "en": "Enter the backup master key"},
    "backup.invalid_backup_name": {"ru": "Некорректное имя бэкапа", "en": "Invalid backup name"},
    "backup.invalid_frequency": {"ru": "Недопустимая частота бэкапа", "en": "Invalid backup frequency"},
    "backup.master_key_env_immutable": {
        "ru": "Мастер-ключ задан через переменную окружения и не меняется из интерфейса",
        "en": "The master key is set via an environment variable and cannot be changed from the interface",
    },
    "backup.master_key_too_short": {
        "ru": "Мастер-ключ — минимум 8 символов",
        "en": "Master key must be at least 8 characters",
    },
    "backup.master_key_too_simple": {"ru": "Слишком простой мастер-ключ", "en": "Master key is too simple"},
    "backup.not_a_backup_file": {"ru": "Файл не является бэкапом VPN Hub", "en": "This file is not a VPN Hub backup"},
    "backup.not_found": {"ru": "Бэкап не найден", "en": "Backup not found"},
    "backup.schema_version_mismatch": {
        "ru": "Бэкап сделан на другой версии схемы (в бэкапе {backup_rev}, сейчас {current_rev}). Восстановление возможно только на совпадающей версии приложения.",  # noqa: E501
        "en": "The backup was made on a different schema version (backup has {backup_rev}, current is {current_rev}). Restore is only possible on a matching application version.",  # noqa: E501
    },
    "backup.wrong_key_or_corrupted": {
        "ru": "Неверный ключ или повреждённый файл бэкапа",
        "en": "Wrong key or corrupted backup file",
    },
    "config.create_failed": {
        "ru": "Не удалось создать конфиг на сервере: {error}",
        "en": "Failed to create config on the server: {error}",
    },
    "config.device_not_found": {"ru": "Устройство не найдено", "en": "Device not found"},
    "config.limit_reached": {
        "ru": "Достигнут лимит конфигов на «{proto}» этого сервера ({used}/{max}). Владелец может увеличить лимит.",
        "en": 'Reached the config limit for "{proto}" on this server ({used}/{max}). The owner can increase the limit.',
    },
    "config.no_vpn_access": {"ru": "Нет доступа к этому VPN", "en": "No access to this VPN"},
    "config.proto_not_installed": {
        "ru": "Протокол ещё не установлен на этом сервере",
        "en": "The protocol is not installed on this server yet",
    },
    "config.select_device": {"ru": "Выберите устройство", "en": "Select a device"},
    "config.server_not_found": {"ru": "Сервер не найден", "en": "Server not found"},
    "config.traffic_limit_reached": {
        "ru": "Достигнут лимит трафика на «{server}» за период ({used} / {limit}). Доступ восстановится после сброса периода.",  # noqa: E501
        "en": 'Reached the traffic limit on "{server}" for this period ({used} / {limit}). Access will be restored after the period resets.',  # noqa: E501
    },
    "config.unknown_vpn_type": {"ru": "Неизвестный тип VPN", "en": "Unknown VPN type"},
    "deps.admin_required": {"ru": "Требуются права администратора", "en": "Administrator privileges required"},
    "device.limit_reached": {
        "ru": "Достигнут лимит устройств ({used}/{limit}). Обратитесь к владельцу, чтобы увеличить лимит.",
        "en": "Device limit reached ({used}/{limit}). Contact the owner to increase the limit.",
    },
    "device.name_required": {"ru": "Введите имя", "en": "Enter a name"},
    "device.not_found": {"ru": "Устройство не найдено", "en": "Device not found"},
    "finance.currency_invalid": {
        "ru": "Валюта — 3–8 латинских букв (напр. RUB, USD, EUR)",
        "en": "Currency must be 3–8 Latin letters (e.g. RUB, USD, EUR)",
    },
    "finance.period_invalid": {"ru": "Период — minute | day | month", "en": "Period must be minute | day | month"},
    "finance.price_not_finite": {"ru": "Цена должна быть конечным числом", "en": "Price must be a finite number"},
    "finance.price_too_large": {"ru": "Слишком большая цена", "en": "Price is too large"},
    "finance.report_period_invalid": {"ru": "Некорректный период отчёта", "en": "Invalid report period"},
    "finance.server_not_found": {"ru": "Сервер не найден", "en": "Server not found"},
    "group.invite_invalid": {
        "ru": "Приглашение недействительно или отозвано",
        "en": "Invite is invalid or has been revoked",
    },
    "group.member_name_required": {"ru": "Введите имя", "en": "Enter a name"},
    "group.member_not_found": {"ru": "Участник не найден", "en": "Member not found"},
    "group.name_required": {"ru": "Введите название", "en": "Enter a name"},
    "group.not_found": {"ru": "Группа не найдена", "en": "Group not found"},
    "hostmetrics.server_not_found": {"ru": "Сервер не найден", "en": "Server not found"},
    "multihop.both_servers_must_be_online": {
        "ru": "Оба сервера должны быть онлайн",
        "en": "Both servers must be online",
    },
    "multihop.chain_already_exists": {
        "ru": "У этого сервера уже есть цепочка — удалите её перед созданием новой",
        "en": "This server already has a chain — delete it before creating a new one",
    },
    "multihop.chain_not_found": {"ru": "Цепочка не найдена", "en": "Chain not found"},
    "multihop.entry_chain_apply_failed": {
        "ru": "Не удалось применить цепочку на входном сервере: {error}",
        "en": "Failed to apply the chain on the entry server: {error}",
    },
    "multihop.entry_exit_must_differ": {
        "ru": "Входной и выходной серверы должны различаться",
        "en": "Entry and exit servers must be different",
    },
    "multihop.exit_client_create_failed": {
        "ru": "Не удалось завести клиента на выходном сервере: {error}",
        "en": "Failed to create client on the exit server: {error}",
    },
    "multihop.server_not_found": {"ru": "Сервер не найден", "en": "Server not found"},
    "multihop.xray_no_material": {
        "ru": "У сервера «{server}» нет материала Xray — переустановите протокол",
        "en": 'Server "{server}" has no Xray material — reinstall the protocol',
    },
    "multihop.xray_not_running": {
        "ru": "На сервере «{server}» должен быть установлен и запущен Xray",
        "en": 'Xray must be installed and running on server "{server}"',
    },
    "pool.name_required": {"ru": "Введите название", "en": "Enter a name"},
    "pool.not_found": {"ru": "Пул не найден", "en": "Pool not found"},
    "provider.name_required": {"ru": "Введите название провайдера", "en": "Enter the provider name"},
    "provider.not_found": {"ru": "Провайдер не найден", "en": "Provider not found"},
    "security.password_too_short": {
        "ru": "Пароль — минимум {min_len} символов",
        "en": "Password must be at least {min_len} characters",
    },
    "security.password_too_weak": {
        "ru": "Пароль слишком простой: добавьте цифры, заглавные буквы или спецсимволы",
        "en": "Password is too weak: add digits, uppercase letters, or special characters",
    },
    "server.apply_params_failed": {
        "ru": "Не удалось применить параметры на сервере: {error}",
        "en": "Failed to apply parameters on the server: {error}",
    },
    "server.apply_reality_failed": {
        "ru": "Не удалось применить параметры Reality на сервере: {error}",
        "en": "Failed to apply Reality parameters on the server: {error}",
    },
    "server.fix_failed": {"ru": "Не удалось выполнить исправление: {error}", "en": "Failed to apply the fix: {error}"},
    "server.fix_not_automatic": {
        "ru": "Эту ошибку нельзя исправить автоматически",
        "en": "This error cannot be fixed automatically",
    },
    "server.invalid_host": {"ru": "Некорректный IP или хост сервера", "en": "Invalid server IP or hostname"},
    "server.location_required": {"ru": "Локация обязательна", "en": "Location is required"},
    "server.must_be_online": {"ru": "Сервер должен быть онлайн", "en": "Server must be online"},
    "server.new_ip_required": {"ru": "Укажите IP нового сервера", "en": "Specify the IP of the new server"},
    "server.no_current_obfuscation_params": {
        "ru": "Нет текущих параметров обфускации",
        "en": "No current obfuscation parameters",
    },
    "server.no_error_to_fix": {"ru": "Нет ошибки для исправления", "en": "There is no error to fix"},
    "server.no_protocols_selected": {
        "ru": "Не выбрано ни одного протокола для установки",
        "en": "No protocols selected for installation",
    },
    "server.not_found": {"ru": "Сервер не найден", "en": "Server not found"},
    "server.obfuscation_amneziawg_only": {
        "ru": "Параметры обфускации доступны только для AmneziaWG",
        "en": "Obfuscation parameters are only available for AmneziaWG",
    },
    "server.operation_failed": {
        "ru": "Не удалось выполнить операцию на сервере: {error}",
        "en": "Failed to perform the operation on the server: {error}",
    },
    "server.preset_or_values_required": {"ru": "Укажите preset или values", "en": "Specify preset or values"},
    "server.protocol_not_installed": {"ru": "Протокол не установлен", "en": "Protocol is not installed"},
    "server.protocol_not_installed_on_server": {
        "ru": "Протокол не установлен на сервере",
        "en": "Protocol is not installed on the server",
    },
    "server.protocol_not_installed_or_stopped": {
        "ru": "Протокол не установлен или остановлен",
        "en": "Protocol is not installed or is stopped",
    },
    "server.provider_metadata_invalid_json": {
        "ru": "Метаданные провайдера должны быть валидным JSON",
        "en": "Provider metadata must be valid JSON",
    },
    "server.provider_metadata_not_object": {
        "ru": "Метаданные провайдера должны быть JSON-объектом",
        "en": "Provider metadata must be a JSON object",
    },
    "server.provider_metadata_too_large": {
        "ru": "Метаданные провайдера слишком большие",
        "en": "Provider metadata is too large",
    },
    "server.reality_xray_only": {
        "ru": "Параметры Reality доступны только для Xray",
        "en": "Reality parameters are only available for Xray",
    },
    "server.required_fields_missing": {
        "ru": "Название, IP и локация обязательны",
        "en": "Name, IP and location are required",
    },
    "server.unknown_operation": {"ru": "Неизвестная операция", "en": "Unknown operation"},
    "server.unknown_protocol": {"ru": "Неизвестный протокол", "en": "Unknown protocol"},
    "server.unknown_vpn_type": {"ru": "Неизвестный тип VPN", "en": "Unknown VPN type"},
    "server.update_not_available": {
        "ru": "Обновление недоступно: компонент уже актуальной версии",
        "en": "Update not available: the component is already up to date",
    },
    "serverAccess.config_not_found": {"ru": "Конфиг не найден", "en": "Config not found"},
    "serverAccess.name_required": {"ru": "Введите имя конфига", "en": "Enter a config name"},
    "serverAccess.pause_not_supported": {
        "ru": "Этот конфиг нельзя приостановить",
        "en": "This config cannot be paused",
    },
    "serverAccess.server_not_found": {"ru": "Сервер не найден", "en": "Server not found"},
    "serverAccess.server_offline": {
        "ru": "Сервер офлайн — внешних клиентов не прочитать",
        "en": "Server is offline — cannot read external clients",
    },
    "serverAccess.server_unreachable": {
        "ru": "Сервер недоступен — не удалось изменить состояние конфига",
        "en": "Server is unreachable — failed to change config state",
    },
    "serverAccess.ssh_connect_failed": {
        "ru": "Не удалось подключиться к серверу: {error}",
        "en": "Failed to connect to the server: {error}",
    },
    "traffic.server_not_found": {"ru": "Сервер не найден", "en": "Server not found"},
    # AUTO-KEYS-END
}


def _interpolate(text: str, params: dict[str, object]) -> str:
    """Подставляет `{name}` из params; неизвестные плейсхолдеры оставляет как есть."""
    if not params:
        return text
    return re.sub(r"\{(\w+)\}", lambda m: str(params[m.group(1)]) if m.group(1) in params else m.group(0), text)


def translate(key: str, lang: Lang = DEFAULT_LANG, /, **params: object) -> str:
    """Возвращает локализованный текст ключа. Фолбэк: язык по умолчанию → сам ключ."""
    entry = MESSAGES.get(key)
    if entry is None:
        # ключа нет в словаре — это баг, но ответ не должен падать: возвращаем ключ.
        return key
    text = entry.get(lang) or entry.get(DEFAULT_LANG) or key
    return _interpolate(text, params)


def resolve_lang(accept_language: str | None, pref: str | None = None) -> Lang:
    """Определяет язык ответа: явное предпочтение → заголовок Accept-Language → дефолт.

    Фронт кладёт выбранный язык в `Accept-Language` (просто "ru" или "en"); тут
    хватает разбора первого тега. `pref` — задел под будущее per-user хранение.
    """
    if pref in LANGS:
        return pref  # type: ignore[return-value]  # сужено проверкой членства выше
    if accept_language:
        head = accept_language.split(",", 1)[0].strip().lower()
        for lang in LANGS:
            if head.startswith(lang):
                return lang
    return DEFAULT_LANG
