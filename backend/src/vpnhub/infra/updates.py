"""Проверка обновлений: тянет фид релизов и сравнивает версии.

По умолчанию фид — **официальные GitHub Releases** продукта (release-please их и
наполняет), поэтому кнопка «Проверить обновления» работает из коробки без настройки.
`VPNHUB_UPDATE_FEED_URL` можно переопределить (форк/зеркало/свой фид) или отключить
(`off`) — тогда апдейт-чек работает в офлайне по last-known из кэша.

Понимаются два формата ответа:
  • GitHub API: массив релизов (или один релиз) с полями `tag_name`/`published_at`/`body`;
  • наш простой JSON: {"latest": "1.2.3", "releases": [{"v", "date", "notes": [...]}, …]}.

Без внешних зависимостей: stdlib urllib в отдельном потоке (сеть не блокирует event-loop).
"""

from __future__ import annotations

import asyncio
import json
import urllib.request
from datetime import datetime
from typing import Any

# Официальный источник обновлений по умолчанию — релизы репозитория продукта.
OFFICIAL_FEED_URL = "https://api.github.com/repos/AlexeyShalaev/vpn-hub/releases"

# Значения, отключающие проверку (офлайн/air-gapped): пусто или явное «выкл».
_DISABLED_VALUES = {"", "off", "none", "disabled", "-", "0", "false"}


def feed_disabled(url: str) -> bool:
    """Пустой URL или явный флаг выключения → проверка обновлений отключена."""
    return (url or "").strip().lower() in _DISABLED_VALUES


def parse_version(v: str) -> tuple[int, ...]:
    out: list[int] = []
    for part in (v or "").strip().lstrip("vV").split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out) or (0,)


def is_newer(latest: str, current: str) -> bool:
    return parse_version(latest) > parse_version(current)


async def fetch_feed(url: str, timeout: float = 6.0) -> dict | list:
    """Скачать и распарсить JSON фида. Возвращает dict (наш формат / один релиз GitHub)
    или list (массив релизов GitHub). Нормализация — в `normalize_feed`."""

    def _get() -> dict | list:
        if not url.lower().startswith(("http://", "https://")):
            raise ValueError("feed URL must be http(s)")
        req = urllib.request.Request(  # noqa: S310 — схема проверена выше
            url,
            headers={
                "User-Agent": "vpnhub-update-check",
                "Accept": "application/vnd.github+json",  # игнорируется не-GitHub фидами
            },
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
            data = json.loads(resp.read().decode("utf-8"))
        if not isinstance(data, dict | list):
            raise ValueError("feed must be a JSON object or array")  # noqa: TRY004 — контракт фида
        return data

    return await asyncio.to_thread(_get)


def _fmt_date(iso: Any) -> str:
    """GitHub `published_at` (ISO-8601, UTC) → «дд.мм.гггг». Мусор → пустая строка."""
    if not isinstance(iso, str) or not iso:
        return ""
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%d.%m.%Y")
    except ValueError:
        return ""


def _body_to_notes(body: Any, limit: int = 12) -> list[str]:
    """Тело GitHub-релиза (markdown от release-please) → список пунктов для UI.

    Берём строки-буллеты (`* …` / `- …`), чистим markdown-разметку и хвостовую
    ссылку на коммит `([hash](url))`. Заголовки/пустые строки пропускаем.
    """
    notes: list[str] = []
    for raw in str(body or "").splitlines():
        line = raw.strip()
        if not line.startswith(("* ", "- ")):
            continue
        text = line[2:].strip()
        # убрать хвостовую ссылку на коммит, добавляемую release-please
        text = text.split(" ([", 1)[0].strip()
        # снять markdown-выделение: **scope:** и `code`
        text = text.replace("**", "").replace("`", "").strip()
        if text:
            notes.append(text)
        if len(notes) >= limit:
            break
    return notes


def _gh_release(r: dict) -> dict:
    tag = str(r.get("tag_name") or r.get("name") or "")
    return {
        "v": tag.lstrip("vV"),
        "date": _fmt_date(r.get("published_at") or r.get("created_at")),
        "notes": _body_to_notes(r.get("body")),
    }


def normalize_feed(data: dict | list) -> dict:
    """Свести любой поддерживаемый ответ к {"latest": str, "releases": [{v, date, notes}]}.

    latest — самый свежий (по версии) релиз. Для GitHub отбрасываем draft/prerelease.
    """
    # наш простой формат: объект с latest/releases
    if isinstance(data, dict) and "tag_name" not in data and ("latest" in data or "releases" in data):
        releases = data.get("releases") if isinstance(data.get("releases"), list) else []
        return {"latest": str(data.get("latest") or ""), "releases": releases}

    # GitHub: массив релизов или один релиз (пропускаем draft/prerelease и записи без тега)
    def _usable(r: Any) -> bool:
        if not isinstance(r, dict) or r.get("draft") or r.get("prerelease"):
            return False
        return bool(r.get("tag_name") or r.get("name"))

    raw = data if isinstance(data, list) else [data]
    gh = [_gh_release(r) for r in raw if _usable(r)]
    gh.sort(key=lambda r: parse_version(r["v"]), reverse=True)
    return {"latest": gh[0]["v"] if gh else "", "releases": gh}
