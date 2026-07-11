"""FastAPI-зависимости: текущая личность из cookie-сессии."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from fastapi import Request
from fastapi.responses import Response

from vpnhub.api.config import Settings, get_settings
from vpnhub.core.errors import Forbidden, TooManyRequests, Unauthorized
from vpnhub.core.i18n import Lang, resolve_lang
from vpnhub.infra.ratelimit import get_limiter
from vpnhub.services.auth import AuthService, Identity

COOKIE = "vpnhub_session"


def req_lang(request: Request) -> Lang:
    """Язык ответа для эндпоинтов, которые сами формируют локализованный текст
    (не через обработчик ошибок): берём из Accept-Language, как ставит фронт."""
    return resolve_lang(request.headers.get("accept-language"))


def _client_ip(request: Request, settings: Settings) -> str | None:
    """Реальный IP клиента.

    X-Forwarded-For доверяем ТОЛЬКО при `trusted_proxy` (приложение за обратным прокси,
    который сам дописывает IP клиента). Тогда берём ПОСЛЕДНИЙ элемент — его добавил доверенный
    прокси; левые значения клиент может подделать. Иначе — прямой сетевой пир (не спуфится),
    иначе rate-limit обходится сменой X-Forwarded-For.
    """
    if settings.trusted_proxy:
        fwd = request.headers.get("x-forwarded-for")
        if fwd:
            parts = [p.strip() for p in fwd.split(",") if p.strip()]
            if parts:
                return parts[-1]
    return request.client.host if request.client else None


def client_meta(request: Request, settings: Settings | None = None) -> tuple[str | None, str | None]:
    """(ip, user-agent). IP — с учётом trusted-proxy (см. _client_ip)."""
    settings = settings or get_settings()
    return _client_ip(request, settings), request.headers.get("user-agent")


def rate_limit(bucket: str, limit: int, window: float) -> Callable:
    """FastAPI-зависимость: не более `limit` запросов за `window` секунд с одного IP."""

    async def _dep(request: Request) -> None:
        ip, _ = client_meta(request)
        key = f"{bucket}:{ip or 'unknown'}"
        rl = get_limiter()
        if not rl.allow(key, limit, window):
            raise TooManyRequests(retry_after=rl.retry_after(key, window))

    return _dep


async def _get(request: Request, cls: type) -> Any:
    return await request.app.state.dishka_container.get(cls)


def service(cls: type) -> Any:
    """FastAPI-зависимость: достаёт сервис из Dishka-контейнера (APP-scope)."""

    async def _dep(request: Request) -> Any:
        return await request.app.state.dishka_container.get(cls)

    return _dep


async def current_identity(request: Request) -> Identity | None:
    token = request.cookies.get(COOKIE)
    svc: AuthService = await _get(request, AuthService)
    return await svc.resolve(token)


async def require_user(request: Request) -> Identity:
    ident = await current_identity(request)
    if not ident:
        raise Unauthorized()
    return ident


async def require_admin(request: Request) -> Identity:
    ident = await require_user(request)
    if ident.kind != "admin":
        raise Forbidden(key="deps.admin_required")
    return ident


def _forwarded_https(request: Request | None, settings: Settings) -> bool:
    """https ли исходное соединение по X-Forwarded-Proto (только при trusted_proxy)."""
    if request is None or not settings.trusted_proxy:
        return False
    proto = request.headers.get("x-forwarded-proto", "")
    return proto.split(",")[0].strip().lower() == "https"


def set_session_cookie(
    response: Response, token: str, settings: Settings | None = None, *, request: Request | None = None
) -> None:
    settings = settings or get_settings()
    # Secure, если панель на https напрямую ИЛИ за доверенным прокси, терминирующим TLS.
    secure = settings.base_url.startswith("https") or _forwarded_https(request, settings)
    response.set_cookie(
        COOKIE,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE, path="/")
