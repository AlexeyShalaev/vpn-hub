"""Реестр источников динамических тарифов: id, подпись и синонимы имени провайдера.

Один источник правды для «какие провайдеры умеют живые тарифы»: id нормализуется из любого
написания (`UFO Hosting`, `ufo-hosting`, `ufo.hosting` → `ufo`). Фронтенд держит зеркальный список
в `frontend/src/lib/planSources.ts` — их совпадение проверяет тест реестра.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class PlanSource:
    id: str
    label: str
    aliases: tuple[str, ...] = ()


PLAN_SOURCES: tuple[PlanSource, ...] = (
    PlanSource("firstbyte", "FirstByte"),
    PlanSource("ufo", "UFO Hosting"),
    PlanSource("ishosting", "ISHOSTING", ("ishosting.com",)),
    PlanSource("ahost", "AHost", ("ahost.eu",)),
    PlanSource("serverspace", "Serverspace", ("serverspace.ru", "serverspace.io")),
    PlanSource("ultahost", "UltaHost", ("ulta", "ultahost.com")),
    PlanSource("62yun", "62YUN", ("yun62", "62yun.ru")),
    PlanSource("timeweb", "Timeweb Cloud", ("timeweb.cloud", "timeweb.com", "timeweb.ru")),
    PlanSource("beget", "Beget", ("beget.com", "beget.ru")),
)

_COMPACT_RE = re.compile(r"[\s._-]+")


def _compact(value: str) -> str:
    return _COMPACT_RE.sub("", value.strip().lower())


_ALIASES: dict[str, str] = {
    _compact(name): src.id for src in PLAN_SOURCES for name in (src.id, src.label, *src.aliases)
}


def _provider_key(provider_id: str) -> str:
    raw = (provider_id or "").strip().lower()
    return _ALIASES.get(_compact(raw), raw)
