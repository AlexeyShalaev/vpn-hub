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
    # ── ключи модулей (пополняются миграцией i18n) ───────────────────────────────
    # AUTO-KEYS-START — не удалять этот маркер: между ним и AUTO-KEYS-END живут
    # сообщения, извлечённые из сервисов/роутеров при переводе бэкенда.
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
