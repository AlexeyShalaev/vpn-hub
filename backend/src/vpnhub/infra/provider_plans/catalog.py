"""Выбор провайдера и применение кэша к динамическим каталогам тарифов."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from .cache import _cached_provider_plans
from .keys import _provider_key

PlanFetcher = Callable[[], Awaitable[list[dict[str, Any]]]]


async def plans_for(provider_id: str, fetchers: Mapping[str, PlanFetcher]) -> list[dict[str, Any]]:
    """Планы провайдера по его id (пустой список, если каталога нет/сайт недоступен)."""
    provider = _provider_key(provider_id)
    fetcher = fetchers.get(provider)
    if fetcher is None:
        return []
    return await _cached_provider_plans(provider, fetcher)
