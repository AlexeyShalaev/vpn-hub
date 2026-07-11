"""Доменные ошибки → HTTP-ответ.

Локализация: ошибка несёт `key` (+ опц. `params`) из словаря `core.i18n.MESSAGES`,
а не готовую строку. `.message` остаётся отрендеренной на языке по умолчанию (ru) —
для логов и обратной совместимости (старые вызовы с позиционным текстом и тесты,
проверяющие `.message`, продолжают работать). Локализованный текст под язык запроса
даёт `.localized(lang)`, который вызывает центральный обработчик в api/entrypoint.py.
"""

from __future__ import annotations

from vpnhub.core.i18n import DEFAULT_LANG, Lang, translate


class DomainError(Exception):
    def __init__(
        self,
        code: str,
        message: str | None = None,
        http_status: int = 400,
        *,
        key: str | None = None,
        params: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        self.key = key
        self.params: dict[str, object] = params or {}
        # message: явный текст важнее; иначе рендер ключа на языке по умолчанию; иначе код.
        if message is not None:
            self.message = message
        elif key is not None:
            self.message = translate(key, DEFAULT_LANG, **self.params)
        else:
            self.message = code
        self.http_status = http_status
        super().__init__(self.message)

    def localized(self, lang: Lang) -> str:
        """Текст ошибки на языке запроса (по ключу); без ключа — как есть."""
        if self.key is not None:
            return translate(self.key, lang, **self.params)
        return self.message


class NotFound(DomainError):
    def __init__(
        self, message: str | None = None, *, key: str | None = None, params: dict[str, object] | None = None
    ) -> None:
        if message is None and key is None:
            key = "error.not_found"
        super().__init__("NOT_FOUND", message, 404, key=key, params=params)


class Unauthorized(DomainError):
    def __init__(
        self, message: str | None = None, *, key: str | None = None, params: dict[str, object] | None = None
    ) -> None:
        if message is None and key is None:
            key = "error.unauthorized"
        super().__init__("UNAUTHORIZED", message, 401, key=key, params=params)


class Forbidden(DomainError):
    def __init__(
        self, message: str | None = None, *, key: str | None = None, params: dict[str, object] | None = None
    ) -> None:
        if message is None and key is None:
            key = "error.forbidden"
        super().__init__("FORBIDDEN", message, 403, key=key, params=params)


class BadRequest(DomainError):
    def __init__(
        self,
        message: str | None = None,
        code: str = "BAD_REQUEST",
        *,
        key: str | None = None,
        params: dict[str, object] | None = None,
    ) -> None:
        if message is None and key is None:
            key = "error.generic"
        super().__init__(code, message, 400, key=key, params=params)


class TooManyRequests(DomainError):
    def __init__(
        self,
        message: str | None = None,
        retry_after: int = 0,
        *,
        key: str | None = None,
        params: dict[str, object] | None = None,
    ) -> None:
        if message is None and key is None:
            key = "error.too_many_requests"
        super().__init__("TOO_MANY_REQUESTS", message, 429, key=key, params=params)
        self.retry_after = retry_after
