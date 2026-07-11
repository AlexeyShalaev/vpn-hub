"""Реестр стабильных кодов событий аудита и их русских подписей.

Коды-константы держим на бэке, чтобы фронт и запись не расходились. Подписи отдаём фронту
через сериализатор — фронт может использовать их как есть (i18n-библиотеки нет).
"""

from __future__ import annotations

# --- стабильные коды событий ---
AUTH_LOGIN = "auth.login"
GROUP_JOIN = "group.join"
CONFIG_DOWNLOAD = "config.download"
ACCESS_REVOKE = "access.revoke"

# code -> человекочитаемая русская подпись
LABELS: dict[str, str] = {
    AUTH_LOGIN: "Вход в систему",
    GROUP_JOIN: "Вступление в группу",
    CONFIG_DOWNLOAD: "Выдача конфига",
    ACCESS_REVOKE: "Отзыв доступа",
}


def label(code: str) -> str:
    """Русская подпись события; неизвестный код возвращается как есть (forward-совместимость)."""
    return LABELS.get(code, code)
