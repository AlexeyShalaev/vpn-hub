"""Юнит-тесты чистой rollup-математики (без БД): бакетирование и агрегация."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from vpnhub.services.traffic_rollup import (
    _HOUR,
    aggregate_rollups,
    aggregate_samples,
    bucket_start,
)

pytestmark = pytest.mark.unit


def _sample(**kw):
    base = {
        "server_id": "s1",
        "proto": "awg",
        "client_id": "A",
        "device_config_id": None,
        "ext_name": None,
        "at": 0.0,
        "rx_delta": 0,
        "tx_delta": 0,
        "online": None,
        "last_handshake": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test__bucket_start__aligns_to_grid() -> None:
    assert bucket_start(3600.0, 3600) == 3600  # ровно на границе → сам бакет
    assert bucket_start(3600.9, 3600) == 3600
    assert bucket_start(7199.0, 3600) == 3600  # внутри второго часа
    assert bucket_start(7200.0, 3600) == 7200  # граница третьего часа → правый бакет
    assert bucket_start(86400.0, 86400) == 86400


def test__aggregate_samples__sums_deltas_and_counts_online() -> None:
    window = 300
    rows = [
        # первый час: два сэмпла клиента A (один онлайн по свежести handshake)
        _sample(at=100.0, rx_delta=10, tx_delta=20, last_handshake=50.0),  # 100-50=50<300 → онлайн
        _sample(at=200.0, rx_delta=5, tx_delta=6, last_handshake=None),  # без handshake → офлайн
        # второй час: клиент A
        _sample(at=3700.0, rx_delta=1, tx_delta=2, last_handshake=3690.0),
        # клиент B (stats-протокол: online-флаг)
        _sample(client_id="B", proto="xray", at=150.0, rx_delta=7, tx_delta=8, online=True),
    ]
    out = aggregate_samples(rows, _HOUR, window)
    a0 = out[("s1", "awg", "A", 0)]
    assert (a0.rx, a0.tx) == (15, 26)
    assert a0.samples_total == 2 and a0.samples_online == 1
    assert a0.last_handshake == 50.0  # max за бакет
    a1 = out[("s1", "awg", "A", 3600)]
    assert (a1.rx, a1.tx, a1.samples_total, a1.samples_online) == (1, 2, 1, 1)
    b = out[("s1", "xray", "B", 0)]
    assert (b.rx, b.tx, b.samples_online) == (7, 8, 1)


def test__aggregate_samples__carries_nonempty_meta() -> None:
    rows = [
        _sample(at=10.0, ext_name=None, device_config_id=None, rx_delta=1),
        _sample(at=20.0, ext_name="Ext", device_config_id="cfg1", rx_delta=1),
    ]
    out = aggregate_samples(rows, _HOUR, 300)
    agg = out[("s1", "awg", "A", 0)]
    assert agg.ext_name == "Ext" and agg.device_config_id == "cfg1"  # непустое перетирает


def _hourly(**kw):
    base = {
        "server_id": "s1",
        "proto": "awg",
        "client_id": "A",
        "device_config_id": "cfg1",
        "ext_name": "Ext",
        "bucket": 0,
        "rx": 0,
        "tx": 0,
        "samples_total": 0,
        "samples_online": 0,
        "last_handshake": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test__aggregate_rollups__daily_sums_hourly() -> None:
    rows = [
        _hourly(bucket=0, rx=10, tx=20, samples_total=30, samples_online=5, last_handshake=100.0),
        _hourly(bucket=3600, rx=1, tx=2, samples_total=30, samples_online=30, last_handshake=3700.0),
        # следующие сутки
        _hourly(bucket=86400, rx=100, tx=200, samples_total=30, samples_online=0),
    ]
    out = aggregate_rollups(rows, 86400)
    d0 = out[("s1", "awg", "A", 0)]
    assert (d0.rx, d0.tx, d0.samples_total, d0.samples_online) == (11, 22, 60, 35)
    assert d0.last_handshake == 3700.0
    d1 = out[("s1", "awg", "A", 86400)]
    assert (d1.rx, d1.tx) == (100, 200)
