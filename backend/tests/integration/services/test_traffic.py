"""Интеграционные тесты TrafficService (in-memory SQLite, без SSH).

Покрываем БД-логику дашборда: запись сэмплов с расчётом дельт (в т.ч. рестарт
счётчиков wg), агрегацию overview (онлайн-статус, external-клиенты, имена
устройства/пользователя), guard владельца и ретеншн purge_old.
"""

from __future__ import annotations

import time

import pytest

from tests.factories.orm import (
    make_device,
    make_device_config,
    make_server,
    make_user,
    seed,
)
from vpnhub.core.errors import NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.services.traffic import PeerStat, TrafficService

pytestmark = pytest.mark.integration


@pytest.fixture
def svc(uow, settings) -> TrafficService:
    return TrafficService(uow, settings)


# --------------------------------------------------------------------------- record / дельты


async def test__record__first_sample__delta_equals_cumulative(svc, session_maker):
    """Первый сэмпл клиента → дельта = кумулятивный счётчик (prev=0)."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110001")
        srv = await make_server(s, owner_id=owner.id)

    n = await svc.record(srv.id, "awg", [PeerStat(client_id="PEERA", rx=100, tx=200, last_handshake=time.time())])
    assert n == 1

    ov = await svc.overview(owner.id, srv.id)
    row = ov["clients"][0]
    assert (row["rxTotal"], row["txTotal"]) == (100, 200)
    assert (row["rxBytes"], row["txBytes"]) == (100, 200)


async def test__record__second_sample__delta_is_increment(svc, session_maker):
    """Второй сэмпл (curr>=prev) → дельта = curr-prev; суммарно = последний кумулятив."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110002")
        srv = await make_server(s, owner_id=owner.id)

    hs = time.time()
    await svc.record(srv.id, "awg", [PeerStat(client_id="PEERA", rx=100, tx=200, last_handshake=hs)])
    await svc.record(srv.id, "awg", [PeerStat(client_id="PEERA", rx=350, tx=500, last_handshake=hs)])

    ov = await svc.overview(owner.id, srv.id)
    row = ov["clients"][0]
    # rxTotal = 100 (первая дельта) + 250 (прирост) = 350; кумулятив = 350
    assert (row["rxTotal"], row["txTotal"]) == (350, 500)
    assert (row["rxBytes"], row["txBytes"]) == (350, 500)


async def test__record__counter_reset__delta_equals_current(svc, session_maker):
    """Рестарт счётчиков wg (curr<prev) → дельта = curr (а не отрицательная)."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110003")
        srv = await make_server(s, owner_id=owner.id)

    hs = time.time()
    await svc.record(srv.id, "awg", [PeerStat(client_id="PEERA", rx=1000, tx=1000, last_handshake=hs)])
    await svc.record(srv.id, "awg", [PeerStat(client_id="PEERA", rx=50, tx=30, last_handshake=hs)])

    ov = await svc.overview(owner.id, srv.id)
    row = ov["clients"][0]
    # 1000 (первый) + 50 (после рестарта дельта=curr) = 1050
    assert (row["rxTotal"], row["txTotal"]) == (1050, 1030)


async def test__record__empty_stats__is_noop(svc, session_maker):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110004")
        srv = await make_server(s, owner_id=owner.id)
    assert await svc.record(srv.id, "awg", []) == 0
    ov = await svc.overview(owner.id, srv.id)
    assert ov["clients"] == []


# --------------------------------------------------------------------------- overview


async def test__overview__resolves_device_and_user_names(svc, session_maker):
    """client_id (pubkey) сопоставляется с DeviceConfig → имена устройства/пользователя."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110010", name="Владелец")
        member = await make_user(s, phone="+79001110011", name="Пользователь")
        srv = await make_server(s, owner_id=owner.id)
        dev = await make_device(s, user_id=member.id, name="Мой телефон")
        await make_device_config(s, device_id=dev.id, server_id=srv.id, vpn_type="awg", client_id="PUBKEY1")

    await svc.record(srv.id, "awg", [PeerStat(client_id="PUBKEY1", rx=10, tx=20, last_handshake=time.time())])
    ov = await svc.overview(owner.id, srv.id)
    row = ov["clients"][0]
    assert row["deviceName"] == "Мой телефон"
    assert row["userName"] == "Пользователь"
    assert row["external"] is False


async def test__overview__unknown_client_is_external(svc, session_maker):
    """client_id без DeviceConfig → external=True, имена пустые."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110020")
        srv = await make_server(s, owner_id=owner.id)

    await svc.record(srv.id, "awg", [PeerStat(client_id="STRANGER", rx=1, tx=2, last_handshake=time.time())])
    ov = await svc.overview(owner.id, srv.id)
    row = ov["clients"][0]
    assert row["external"] is True
    assert row["deviceName"] == "" and row["userName"] == ""


async def test__overview__online_status_from_handshake_freshness(svc, session_maker):
    """online=True при свежем last_handshake; False при устаревшем (за окном)."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110030")
        srv = await make_server(s, owner_id=owner.id)

    now = time.time()
    window = svc.settings.traffic_online_window_seconds
    await svc.record(srv.id, "awg", [PeerStat(client_id="FRESH", rx=1, tx=1, last_handshake=now)])
    await svc.record(srv.id, "awg", [PeerStat(client_id="STALE", rx=1, tx=1, last_handshake=now - window - 60)])

    ov = await svc.overview(owner.id, srv.id)
    by_client = {c["clientId"]: c for c in ov["clients"]}
    assert by_client["FRESH"]["online"] is True
    assert by_client["STALE"]["online"] is False


async def test__overview__foreign_server__raises_notfound(svc, session_maker):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110040")
        stranger = await make_user(s, phone="+79001110041")
        srv = await make_server(s, owner_id=stranger.id)
    with pytest.raises(NotFound) as exc:
        await svc.overview(owner.id, srv.id)
    assert exc.value.http_status == 404


async def test__overview__unknown_period_falls_back_to_default(svc, session_maker):
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110050")
        srv = await make_server(s, owner_id=owner.id)
    ov = await svc.overview(owner.id, srv.id, period="bogus")
    assert ov["period"] == "24h"


# --------------------------------------------------------------------------- purge


async def test__purge_old__drops_only_stale_samples(svc, session_maker, uow):
    """purge_old удаляет сэмплы старше traffic_retention_days, свежие остаются."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110060")
        srv = await make_server(s, owner_id=owner.id)

    now = time.time()
    old_at = now - (svc.settings.traffic_retention_days + 1) * 86400
    async with uow.transaction() as tx:
        tx.session.add(m.TrafficSample(server_id=srv.id, proto="awg", client_id="OLD", at=old_at))
        tx.session.add(m.TrafficSample(server_id=srv.id, proto="awg", client_id="NEW", at=now))
        await tx.session.flush()

    removed = await svc.purge_old()
    assert removed == 1
    ov = await svc.overview(owner.id, srv.id, period="7d")
    assert {c["clientId"] for c in ov["clients"]} == {"NEW"}
