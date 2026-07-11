"""Небольшие HTML-парсеры, переиспользуемые несколькими провайдерами."""

from __future__ import annotations

import urllib.parse
from html.parser import HTMLParser

from .common import _norm


class _IshostingLinkParser(HTMLParser):
    """Достаёт ссылки вида /en/vps/<country> из SSR-страниц ISHOSTING."""

    def __init__(self, base_url: str) -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = base_url
        self.links: list[tuple[str, str]] = []
        self._href: str | None = None
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a" or self._href is not None:
            return
        attrs_d = {k: (v or "") for k, v in attrs}
        href = attrs_d.get("href")
        if not href:
            return
        self._href = urllib.parse.urljoin(self.base_url, href)
        self._text_parts = []

    def handle_data(self, data: str) -> None:
        if self._href is not None:
            self._text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._href is None:
            return
        self.links.append((self._href, _norm("".join(self._text_parts))))
        self._href = None
        self._text_parts = []
