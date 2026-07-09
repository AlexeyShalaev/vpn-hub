"""In-memory кэш динамических тарифов провайдеров."""

from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from typing import Any

import structlog
from cashews import Cache

_PROVIDER_PLANS_CACHE_TTL_S = 30 * 60
_PROVIDER_PLANS_STALE_TTL_S = 6 * 60 * 60
_PROVIDER_PLANS_EMPTY_TTL_S = 5 * 60
_PlanFetcher = Callable[[], Awaitable[list[dict[str, Any]]]]
log = structlog.get_logger(__name__)

_PROVIDER_PLANS_CACHE = Cache()
_PROVIDER_PLANS_CACHE.setup("mem://")
_PROVIDER_PLANS_CACHE_VERSION = 0
_PROVIDER_PLANS_PROVIDER_VERSIONS: dict[str, int] = {}
_PLANS_REFRESH_LOCKS: dict[str, asyncio.Lock] = {}
_PLANS_LOCK = asyncio.Lock()


def clear_provider_plan_cache(provider_id: str | None = None) -> None:
    """Инвалидировать in-memory кэш тарифов (используется тестами и будущей ручной инвалидацией)."""
    global _PROVIDER_PLANS_CACHE_VERSION  # noqa: PLW0603 — синхронная инвалидация через namespace версии.
    if provider_id is None:
        _PROVIDER_PLANS_CACHE_VERSION += 1
        _PROVIDER_PLANS_PROVIDER_VERSIONS.clear()
        _PLANS_REFRESH_LOCKS.clear()
        return
    key = _provider_key(provider_id)
    _PROVIDER_PLANS_PROVIDER_VERSIONS[key] = _PROVIDER_PLANS_PROVIDER_VERSIONS.get(key, 0) + 1
    _PLANS_REFRESH_LOCKS.pop(key, None)


def _clone_plans(plans: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(p) for p in plans]


def _freeze_plans(plans: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], ...]:
    return tuple(_clone_plans(plans))


def _cache_key(provider_id: str, bucket: str) -> str:
    provider_version = _PROVIDER_PLANS_PROVIDER_VERSIONS.get(provider_id, 0)
    return f"provider-plans:v{_PROVIDER_PLANS_CACHE_VERSION}:{provider_id}:v{provider_version}:{bucket}"


async def _store_provider_plans(
    provider_id: str,
    plans: Iterable[Mapping[str, Any]],
    *,
    fresh_ttl: int,
    stale: bool,
) -> tuple[dict[str, Any], ...]:
    frozen = _freeze_plans(plans)
    if fresh_ttl > 0:
        await _PROVIDER_PLANS_CACHE.set(_cache_key(provider_id, "fresh"), frozen, expire=fresh_ttl)
    if stale:
        await _PROVIDER_PLANS_CACHE.set(
            _cache_key(provider_id, "stale"),
            frozen,
            expire=_PROVIDER_PLANS_STALE_TTL_S,
        )
    return frozen


async def _extend_stale_cache(provider_id: str, cached: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    frozen = await _store_provider_plans(
        provider_id,
        cached,
        fresh_ttl=_PROVIDER_PLANS_CACHE_TTL_S,
        stale=True,
    )
    return _clone_plans(frozen)


async def _refresh_lock(provider_id: str) -> asyncio.Lock:
    async with _PLANS_LOCK:
        return _PLANS_REFRESH_LOCKS.setdefault(provider_id, asyncio.Lock())


async def _cached_provider_plans(provider_id: str, fetcher: _PlanFetcher) -> list[dict[str, Any]]:
    """TTL-кэш в памяти процесса, чтобы UI не парсил сайт провайдера на каждый запрос."""
    key = provider_id.strip().lower()
    cached = await _PROVIDER_PLANS_CACHE.get(_cache_key(key, "fresh"))
    if cached is not None:
        return _clone_plans(cached)

    async with await _refresh_lock(key):
        cached = await _PROVIDER_PLANS_CACHE.get(_cache_key(key, "fresh"))
        if cached is not None:
            return _clone_plans(cached)
        stale = await _PROVIDER_PLANS_CACHE.get(_cache_key(key, "stale"))

        try:
            fresh = await fetcher()
        except Exception as exc:
            if stale is not None:
                log.warning("provider_plans_cache_stale", provider=key, error=str(exc))
                return await _extend_stale_cache(key, stale)
            raise

        if not fresh:
            if stale is not None:
                log.warning("provider_plans_cache_stale_empty", provider=key)
                return await _extend_stale_cache(key, stale)
            await _store_provider_plans(key, (), fresh_ttl=_PROVIDER_PLANS_EMPTY_TTL_S, stale=False)
            return []

        frozen = await _store_provider_plans(
            key,
            fresh,
            fresh_ttl=_PROVIDER_PLANS_CACHE_TTL_S,
            stale=True,
        )
        return _clone_plans(frozen)


def _provider_key(provider_id: str) -> str:
    raw = (provider_id or "").strip().lower()
    compact = re.sub(r"[\s_-]+", "", raw)
    if compact == "firstbyte":
        return "firstbyte"
    if compact in {"ufo", "ufohosting"}:
        return "ufo"
    if compact in {"ishosting", "ishostingcom"}:
        return "ishosting"
    if compact in {"ahost", "ahosteu"}:
        return "ahost"
    if compact in {"serverspace", "serverspaceru", "serverspaceio"}:
        return "serverspace"
    return raw
