"""HTTP-клиенты для загрузки публичных страниц провайдеров."""

from __future__ import annotations

import asyncio
import json
import ssl
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import certifi

_USER_AGENT = "vpnhub-provider-plans/0.1 (+https://github.com/AlexeyShalaev/vpn-hub)"
_BROWSER_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


# Свой пул потоков для блокирующих загрузок у провайдеров. Общий пул asyncio на 1 vCPU — это ~5 потоков,
# а «Подобрать тариф» разом тянет полсотни провайдеров (у некоторых — десятки страниц): в общем пуле они
# выстроились бы в очередь и заодно заняли бы потоки остальной панели. Загрузки ждут сеть, а не CPU.
_IO_POOL = ThreadPoolExecutor(max_workers=24, thread_name_prefix="provider-plans")


async def run_io[T](fn: Callable[..., T], *args: object) -> T:
    """Выполнить блокирующую загрузку/разбор в пуле провайдеров, не занимая общий пул asyncio."""
    return await asyncio.get_running_loop().run_in_executor(_IO_POOL, fn, *args)


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(
        self,
        req: urllib.request.Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


async def _fetch_url(url: str, timeout: float) -> str:
    def _get() -> str:
        req = urllib.request.Request(  # noqa: S310 — URL берётся из provider-констант/whitelist
            url,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            },
        )
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(  # noqa: S310 — URL whitelist выше/в константах
            req, timeout=timeout, context=ctx
        ) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            body: bytes = resp.read(2_500_000)
            return body.decode(charset, "replace")

    return await run_io(_get)


async def _fetch_browser_url(url: str, timeout: float) -> str:
    def _get() -> str:
        req = urllib.request.Request(  # noqa: S310 — URL берётся из provider-констант/whitelist
            url,
            headers={
                "User-Agent": _BROWSER_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
        )
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(  # noqa: S310 — URL whitelist выше/в константах
            req, timeout=timeout, context=ctx
        ) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            body: bytes = resp.read(2_500_000)
            return body.decode(charset, "replace")

    return await run_io(_get)


async def _post_form_url(url: str, form: Mapping[str, str], timeout: float) -> str:
    def _post() -> str:
        data = urllib.parse.urlencode(form).encode()
        req = urllib.request.Request(  # noqa: S310 — URL берётся из provider-констант/whitelist
            url,
            data=data,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/json,text/javascript,*/*;q=0.8",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(  # noqa: S310 — URL whitelist выше/в константах
            req, timeout=timeout, context=ctx
        ) as resp:
            charset = resp.headers.get_content_charset() or "utf-8"
            body: bytes = resp.read(2_500_000)
            return body.decode(charset, "replace")

    return await run_io(_post)


async def _fetch_json(url: str, timeout: float) -> Any:
    """GET публичного JSON API провайдера (без авторизации) → разобранный JSON."""

    def _get() -> Any:
        req = urllib.request.Request(  # noqa: S310 — URL берётся из provider-констант/whitelist
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
        )
        ctx = ssl.create_default_context(cafile=certifi.where())
        with urllib.request.urlopen(  # noqa: S310 — URL whitelist выше/в константах
            req, timeout=timeout, context=ctx
        ) as resp:
            body: bytes = resp.read(20_000_000)
            return json.loads(body.decode(resp.headers.get_content_charset() or "utf-8", "replace"))

    return await run_io(_get)
