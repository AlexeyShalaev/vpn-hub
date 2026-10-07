"""Gzip только для публичных справочников API.

Каталог провайдеров и их тарифы — сотни килобайт JSON (сотни провайдеров, тысячи тарифов), и на
мобильном это заметно. Остальной API не сжимаем намеренно: в его ответах бывают ключи и конфиги рядом с
пользовательским вводом, а сжатие таких ответов даёт BREACH-подобный оракул по длине. Справочники
секретов не содержат, им сжатие безопасно.
"""

from __future__ import annotations

from starlette.middleware.gzip import GZipMiddleware
from starlette.types import ASGIApp, Receive, Scope, Send

_COMPRESSED_PREFIXES = ("/api/providers",)


class CatalogGZipMiddleware:
    def __init__(self, app: ASGIApp, minimum_size: int = 1024, compresslevel: int = 6) -> None:
        self.app = app
        self.gzip = GZipMiddleware(app, minimum_size=minimum_size, compresslevel=compresslevel)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and str(scope.get("path", "")).startswith(_COMPRESSED_PREFIXES):
            await self.gzip(scope, receive, send)
        else:
            await self.app(scope, receive, send)
