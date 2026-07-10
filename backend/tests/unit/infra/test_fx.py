"""Курсы валют ЦБ РФ с кэшем — для сведе́ния цен тарифов к одной валюте при подборе."""

from __future__ import annotations

import json

import pytest

from vpnhub.infra import fx

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
async def _clear_fx_cache() -> None:
    # in-memory кэш живёт в модуле между тестами — чистим, чтобы тесты не влияли друг на друга
    await fx._cache.clear()


_CBR_JSON = json.dumps(
    {
        "Date": "2026-07-10T11:30:00+03:00",
        "Valute": {
            "USD": {"CharCode": "USD", "Nominal": 1, "Value": 90.5},
            "EUR": {"CharCode": "EUR", "Nominal": 1, "Value": 98.0},
            "JPY": {"CharCode": "JPY", "Nominal": 100, "Value": 60.0},
        },
    }
)


def test__parse_cbr__normalizes_by_nominal_and_pins_rub() -> None:
    """RUB закреплён как 1; курс = Value / Nominal (JPY даётся за 100 → приводим к 1)."""
    # Act
    rates = fx._parse_cbr(_CBR_JSON)
    # Assert
    assert rates["RUB"] == 1.0
    assert rates["USD"] == 90.5
    assert rates["EUR"] == 98.0
    assert rates["JPY"] == pytest.approx(0.6)


def test__parse_cbr__skips_malformed_entries() -> None:
    """Битая запись Valute пропускается, а не роняет весь парсер."""
    # Arrange
    bad = json.dumps({"Valute": {"USD": {"Value": "n/a"}, "EUR": {"Nominal": 1, "Value": 98.0}}})
    # Act
    rates = fx._parse_cbr(bad)
    # Assert
    assert "USD" not in rates
    assert rates["EUR"] == 98.0
    assert rates["RUB"] == 1.0


async def test__get_rates__fetches_parses_and_caches(monkeypatch: pytest.MonkeyPatch) -> None:
    """Первый вызов ходит в сеть и парсит; второй берёт из кэша без повторного фетча."""
    # Arrange
    calls = 0

    async def fake_fetch(url: str, timeout: float) -> str:
        nonlocal calls
        calls += 1
        return _CBR_JSON

    monkeypatch.setattr(fx, "_fetch_url", fake_fetch)
    # Act
    first = await fx.get_rates()
    second = await fx.get_rates()
    # Assert
    assert first["source"] == "cbr"
    assert first["base"] == "RUB"
    assert first["rates"]["USD"] == 90.5
    assert second == first
    assert calls == 1


async def test__get_rates__network_error_without_cache_returns_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Нет сети и нет кэша → зашитый fallback, UI подбора не должен падать."""

    # Arrange
    async def boom(url: str, timeout: float) -> str:
        raise TimeoutError("no network")

    monkeypatch.setattr(fx, "_fetch_url", boom)
    # Act
    rates = await fx.get_rates()
    # Assert
    assert rates["source"] == "fallback"
    assert set(rates["rates"]) >= {"RUB", "USD", "EUR"}
    assert rates["rates"]["RUB"] == 1.0


async def test__get_rates__cold_start_outage_negative_caches_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Холодный старт при недоступном ЦБ: fallback кэшируется ненадолго, второй запрос не идёт в сеть."""
    # Arrange
    calls = 0

    async def boom(url: str, timeout: float) -> str:
        nonlocal calls
        calls += 1
        raise TimeoutError("down")

    monkeypatch.setattr(fx, "_fetch_url", boom)
    # Act
    first = await fx.get_rates()
    second = await fx.get_rates()
    # Assert
    assert first["source"] == "fallback"
    assert second["source"] == "fallback"
    assert calls == 1  # второй вызов взял fallback из короткого негативного кэша, а не из сети


async def test__get_rates__network_error_falls_back_to_stale(monkeypatch: pytest.MonkeyPatch) -> None:
    """Свежий ключ протух, сеть недоступна → отдаём последний удачный курс (stale)."""

    # Arrange: удачный фетч заполняет fresh + stale
    async def ok(url: str, timeout: float) -> str:
        return _CBR_JSON

    monkeypatch.setattr(fx, "_fetch_url", ok)
    await fx.get_rates()
    await fx._cache.delete(f"{fx._CACHE_KEY}:fresh")  # эмулируем истечение свежего курса

    async def boom(url: str, timeout: float) -> str:
        raise TimeoutError("down")

    monkeypatch.setattr(fx, "_fetch_url", boom)
    # Act
    rates = await fx.get_rates()
    # Assert
    assert rates["source"] == "cbr-stale"
    assert rates["rates"]["USD"] == 90.5
