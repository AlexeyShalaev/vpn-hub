"""Доменные ошибки → HTTP-ответ."""

from __future__ import annotations


class DomainError(Exception):
    def __init__(self, code: str, message: str, http_status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status


class NotFound(DomainError):
    def __init__(self, message: str = "Не найдено") -> None:
        super().__init__("NOT_FOUND", message, 404)


class Unauthorized(DomainError):
    def __init__(self, message: str = "Требуется вход") -> None:
        super().__init__("UNAUTHORIZED", message, 401)


class Forbidden(DomainError):
    def __init__(self, message: str = "Недостаточно прав") -> None:
        super().__init__("FORBIDDEN", message, 403)


class BadRequest(DomainError):
    def __init__(self, message: str, code: str = "BAD_REQUEST") -> None:
        super().__init__(code, message, 400)


class TooManyRequests(DomainError):
    def __init__(self, message: str = "Слишком много попыток, попробуйте позже", retry_after: int = 0) -> None:
        super().__init__("TOO_MANY_REQUESTS", message, 429)
        self.retry_after = retry_after
