"""Интеграционные тесты MetricsService: overview/scrape_tick/purge_old на in-memory SQLite."""

from __future__ import annotations

import time

import pytest

from tests.conftest import TEST_SECRET_KEY
from tests.factories.orm import make_server, make_user, seed
from vpnhub.api.config import Settings
from vpnhub.infra.db.orm import models as m
from vpnhub.services.metrics import MetricsService

pytestmark = pytest.mark.integration


@pytest.fixture
def settings() -> Settings:
    return Settings(
        _env_file=None,
        secret_key=TEST_SECRET_KEY,
        master_key=None,
        admin_phone=None,
        metrics_retention_days=30,
    )


@pytest.fixture
def metrics_service(uow, settings) -> MetricsService:
    return MetricsService(uow, settings)


async def test__overview__groups_samples_into_ordered_series(metrics_service, session_maker) -> None:
    """overview собирает точки одной серии (name+labels) в порядке возрастания at."""
    # Arrange
    now = time.time()
    async with seed(session_maker) as s:
        s.add(m.MetricSample(name="vpnhub_servers", labels="status=online", at=now - 20, value=1.0))
        s.add(m.MetricSample(name="vpnhub_servers", labels="status=online", at=now - 10, value=2.0))
        s.add(m.MetricSample(name="vpnhub_servers", labels="status=offline", at=now - 10, value=1.0))
    # Act
    out = await metrics_service.overview("24h")
    # Assert
    online = next(x for x in out["series"] if x["labels"] == "status=online")
    assert [p["value"] for p in online["points"]] == [1.0, 2.0]  # отсортировано по at
    assert out["servers"]["online"] == 2.0  # сводка «сейчас» = последняя точка
    assert out["servers"]["offline"] == 1.0
    assert out["period"] == "24h"


async def test__overview__filters_by_period_window(metrics_service, session_maker) -> None:
    """Точки старше окна периода не попадают в overview."""
    # Arrange
    now = time.time()
    async with seed(session_maker) as s:
        s.add(m.MetricSample(name="vpnhub_servers", labels="status=online", at=now - 30, value=5.0))
        s.add(m.MetricSample(name="vpnhub_servers", labels="status=online", at=now - 7200, value=9.0))  # >1h
    # Act
    out = await metrics_service.overview("1h")
    # Assert
    online = next(x for x in out["series"] if x["labels"] == "status=online")
    assert [p["value"] for p in online["points"]] == [5.0]  # старая точка отфильтрована


async def test__scrape_tick__writes_rows_visible_to_overview(metrics_service, session_maker) -> None:
    """scrape_tick пишет строки (в т.ч. серверы по статусу из БД), которые видит overview."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110001", name="Owner")
        await make_server(s, owner_id=owner.id, name="a", status="online")
        await make_server(s, owner_id=owner.id, name="b", status="offline")
    # Act
    written = await metrics_service.scrape_tick()
    out = await metrics_service.overview("1h")
    # Assert
    assert written > 0
    assert out["servers"]["online"] == 1.0
    assert out["servers"]["offline"] == 1.0


async def test__purge_old__deletes_samples_outside_retention(metrics_service, session_maker, settings) -> None:
    """purge_old удаляет сэмплы старше окна ретеншна, свежие оставляет."""
    # Arrange
    now = time.time()
    old_at = now - (settings.metrics_retention_days + 1) * 86400
    async with seed(session_maker) as s:
        s.add(m.MetricSample(name="vpnhub_servers", labels="status=online", at=old_at, value=1.0))
        s.add(m.MetricSample(name="vpnhub_servers", labels="status=online", at=now, value=2.0))
    # Act
    deleted = await metrics_service.purge_old()
    out = await metrics_service.overview("7d")
    # Assert
    assert deleted == 1
    online = next(x for x in out["series"] if x["labels"] == "status=online")
    assert [p["value"] for p in online["points"]] == [2.0]
