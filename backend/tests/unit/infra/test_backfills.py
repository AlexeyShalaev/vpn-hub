"""Юнит-тесты бэкфиллов миграций (sync SQLite in-memory, без Alembic).

Бэкфилл вынесен в `vpnhub.infra.db.backfills`, чтобы тестировать логику напрямую:
последний сэмпл per (server, proto, client) → строка traffic_peer_state.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import sqlalchemy as sa

from vpnhub.infra.db.backfills import backfill_traffic_peer_state
from vpnhub.infra.db.orm import models as m

pytestmark = pytest.mark.unit


@pytest.fixture
def engine():
    eng = sa.create_engine("sqlite://")
    m.TrafficSample.__table__.create(eng)
    m.TrafficPeerState.__table__.create(eng)
    yield eng
    eng.dispose()


def _sample(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": uuid.uuid4().hex[:16],
        "server_id": "s1",
        "proto": "awg",
        "client_id": "A",
        "device_config_id": None,
        "at": 1000.0,
        "rx_bytes": 0,
        "tx_bytes": 0,
        "rx_delta": 0,
        "tx_delta": 0,
        "last_handshake": None,
        "online": None,
        "ext_name": None,
    }
    base.update(kw)
    return base


def test__backfill__takes_latest_sample_per_key(engine):
    """Из нескольких сэмплов клиента берётся последний по at; NULL client_id пропускается."""
    with engine.begin() as bind:
        bind.execute(
            m.TrafficSample.__table__.insert(),
            [
                _sample(at=1000.0, rx_bytes=10, tx_bytes=20),
                _sample(at=2000.0, rx_bytes=100, tx_bytes=200, last_handshake=1999.0, ext_name="Ext"),
                _sample(client_id="B", proto="xray", at=1500.0, rx_bytes=7, tx_bytes=8, online=True),
                _sample(client_id=None, at=3000.0, rx_bytes=999, tx_bytes=999),  # агрегат — пропуск
            ],
        )
        n = backfill_traffic_peer_state(bind)
        assert n == 2
        rows = bind.execute(sa.select(m.TrafficPeerState.__table__).order_by(sa.column("client_id"))).all()
    by_client = {r.client_id: r for r in rows}
    assert set(by_client) == {"A", "B"}
    a = by_client["A"]
    assert (a.rx_bytes, a.tx_bytes, a.last_at) == (100, 200, 2000.0)
    assert a.last_handshake == 1999.0 and a.ext_name == "Ext"
    assert a.rx_speed == 0.0 and a.tx_speed == 0.0  # скорость посчитается первым новым сэмплом
    b = by_client["B"]
    assert (b.proto, b.online) == ("xray", True)


def test__backfill__is_idempotent(engine):
    """Повторный прогон не дублирует и не перетирает существующие состояния."""
    with engine.begin() as bind:
        bind.execute(m.TrafficSample.__table__.insert(), [_sample(at=1000.0, rx_bytes=10, tx_bytes=20)])
        assert backfill_traffic_peer_state(bind) == 1
        assert backfill_traffic_peer_state(bind) == 0
        rows = bind.execute(sa.select(m.TrafficPeerState.__table__)).all()
    assert len(rows) == 1


def test__backfill__empty_samples_is_noop(engine):
    with engine.begin() as bind:
        assert backfill_traffic_peer_state(bind) == 0
