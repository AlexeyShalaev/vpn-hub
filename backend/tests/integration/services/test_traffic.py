"""Интеграционные тесты TrafficService (in-memory SQLite, без SSH).

Покрываем БД-логику дашборда: запись сэмплов с расчётом дельт (в т.ч. рестарт
счётчиков wg), агрегацию overview (онлайн-статус, external-клиенты, имена
устройства/пользователя), guard владельца и ретеншн purge_old.
"""

from __future__ import annotations

import time

import pytest
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

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


# --------------------------------------------------------------------------- peer_state


async def test__record__delta_survives_raw_purge(svc, session_maker, uow):
    """Дельта считается от peer_state: purge сырых сэмплов не даёт ложный всплеск после простоя.

    Регресс-тест бага: раньше дельта бралась от последнего СЫРОГО сэмпла, и после его удаления
    ретеншном следующая дельта равнялась полному кумулятиву (ложные гигабайты за один тик).
    """
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110100")
        srv = await make_server(s, owner_id=owner.id)

    hs = time.time()
    await svc.record(srv.id, "awg", [PeerStat(client_id="P", rx=1000, tx=2000, last_handshake=hs)])
    async with uow.transaction() as tx:  # эмулируем ретеншн: сырьё удалено, peer_state остаётся
        await tx.session.execute(sa_delete(m.TrafficSample))
    await svc.record(srv.id, "awg", [PeerStat(client_id="P", rx=1100, tx=2200, last_handshake=hs)])

    ov = await svc.overview(owner.id, srv.id)
    row = ov["clients"][0]
    assert (row["rxTotal"], row["txTotal"]) == (100, 200)  # прирост, а не полный кумулятив


async def test__record__peer_state_upserted(svc, session_maker, uow):
    """peer_state хранит последний кумулятив, max handshake, скорость и непустое имя clientsTable."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110101")
        srv = await make_server(s, owner_id=owner.id)

    hs = time.time()
    await svc.record(srv.id, "awg", [PeerStat(client_id="P", rx=100, tx=200, last_handshake=hs)])
    time.sleep(0.01)  # ненулевой интервал между замерами — скорость должна стать > 0
    await svc.record(srv.id, "awg", [PeerStat(client_id="P", rx=300, tx=500, last_handshake=hs + 5, name="Ext")])

    async with uow.query() as tx:
        st = (await tx.session.execute(select(m.TrafficPeerState))).scalar_one()
    assert (st.server_id, st.proto, st.client_id) == (srv.id, "awg", "P")
    assert (st.rx_bytes, st.tx_bytes) == (300, 500)
    assert st.last_handshake == pytest.approx(hs + 5)
    assert st.ext_name == "Ext"
    assert st.rx_speed > 0 and st.tx_speed > 0
    assert st.last_at > 0


async def test__record__counter_reset_rewrites_state(svc, session_maker, uow):
    """Рестарт счётчиков (curr<prev) перезаписывает state текущим кумулятивом (не суммой)."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110102")
        srv = await make_server(s, owner_id=owner.id)

    hs = time.time()
    await svc.record(srv.id, "awg", [PeerStat(client_id="P", rx=1000, tx=1000, last_handshake=hs)])
    await svc.record(srv.id, "awg", [PeerStat(client_id="P", rx=50, tx=30, last_handshake=hs)])

    async with uow.query() as tx:
        st = (await tx.session.execute(select(m.TrafficPeerState))).scalar_one()
    assert (st.rx_bytes, st.tx_bytes) == (50, 30)  # следующая дельта пойдёт от нового кумулятива


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
    assert row["extName"] == ""  # имени в clientsTable не было


async def test__overview__external_client_named_from_clients_table(svc, session_maker):
    """external-клиент с именем из Amnezia clientsTable (PeerStat.name) → overview отдаёт extName.

    Эмулируем сбор: PeerStat.name (== clientsTable clientName) сохраняется в ext_name сэмпла;
    overview для external отдаёт его как extName (даже если у части сэмплов имя пусто — берём непустое).
    """
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110021")
        srv = await make_server(s, owner_id=owner.id)

    hs = time.time()
    # первый сэмпл без имени (напр. clientsTable ещё не прочиталась), второй — с именем из clientsTable
    await svc.record(srv.id, "awg", [PeerStat(client_id="EXT1", rx=1, tx=2, last_handshake=hs)])
    await svc.record(
        srv.id, "awg", [PeerStat(client_id="EXT1", rx=5, tx=6, last_handshake=hs, name="Alex · Shalaev Xiaomi")]
    )

    ov = await svc.overview(owner.id, srv.id)
    row = ov["clients"][0]
    assert row["external"] is True
    assert row["extName"] == "Alex · Shalaev Xiaomi"
    # имя пользователя/устройства по-прежнему пустое — это именно external-клиент
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


async def test__overview__totals_tier_by_period(svc, session_maker, uow):
    """1h/24h читают суммы из сырья, 7d/30d/90d — из hourly, 365d — из daily (суммы различимы)."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110072")
        srv = await make_server(s, owner_id=owner.id)

    now = time.time()
    async with uow.transaction() as tx:
        # клиент в peer_state (источник списка), активен только что
        tx.session.add(m.TrafficPeerState(server_id=srv.id, proto="awg", client_id="C", last_at=now, online=True))
        # сырьё за последний час: сумма дельт = 11
        tx.session.add(
            m.TrafficSample(server_id=srv.id, proto="awg", client_id="C", at=now - 100, rx_delta=1, tx_delta=10)
        )
        # hourly-бакет: суммарно 200
        tx.session.add(
            m.TrafficHourly(
                server_id=srv.id,
                proto="awg",
                client_id="C",
                bucket=int(now - 100),
                rx=100,
                tx=100,
                samples_total=1,
                samples_online=1,
            )
        )
        # daily-бакет: суммарно 5000
        tx.session.add(
            m.TrafficDaily(
                server_id=srv.id,
                proto="awg",
                client_id="C",
                bucket=int(now - 100),
                rx=2000,
                tx=3000,
                samples_total=1,
                samples_online=1,
            )
        )
        await tx.session.flush()

    raw = await svc.overview(owner.id, srv.id, period="1h")
    assert raw["seriesBucketSeconds"] == 0
    assert (raw["clients"][0]["rxTotal"], raw["clients"][0]["txTotal"]) == (1, 10)

    hourly = await svc.overview(owner.id, srv.id, period="7d")
    assert hourly["seriesBucketSeconds"] == 3600
    assert (hourly["clients"][0]["rxTotal"], hourly["clients"][0]["txTotal"]) == (100, 100)

    daily = await svc.overview(owner.id, srv.id, period="365d")
    assert daily["seriesBucketSeconds"] == 86400
    assert (daily["clients"][0]["rxTotal"], daily["clients"][0]["txTotal"]) == (2000, 3000)


async def test__overview__online_and_speed_from_state_regardless_of_period(svc, session_maker, uow):
    """Онлайн/скорость всегда из peer_state — даже для длинного периода 365d."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110073")
        srv = await make_server(s, owner_id=owner.id)

    now = time.time()
    async with uow.transaction() as tx:
        tx.session.add(
            m.TrafficPeerState(server_id=srv.id, proto="xray", client_id="C", last_at=now, online=True, rx_speed=50.0)
        )
        await tx.session.flush()

    ov = await svc.overview(owner.id, srv.id, period="365d")
    row = ov["clients"][0]
    assert row["online"] is True and row["rxSpeed"] == pytest.approx(50.0)


async def test__overview__idle_client_shown_dead_client_hidden(svc, session_maker, uow):
    """Живой клиент без трафика за период виден с нулями; давно снятый (last_at до периода) скрыт."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110074")
        srv = await make_server(s, owner_id=owner.id)

    now = time.time()
    async with uow.transaction() as tx:
        tx.session.add(m.TrafficPeerState(server_id=srv.id, proto="awg", client_id="IDLE", last_at=now, online=False))
        tx.session.add(
            m.TrafficPeerState(server_id=srv.id, proto="awg", client_id="DEAD", last_at=now - 2 * 86400, online=False)
        )
        await tx.session.flush()

    ov = await svc.overview(owner.id, srv.id, period="24h")
    ids = {c["clientId"] for c in ov["clients"]}
    assert ids == {"IDLE"}  # DEAD (last_at 2 дня назад, без трафика) отсеян
    idle = next(c for c in ov["clients"] if c["clientId"] == "IDLE")
    assert (idle["rxTotal"], idle["txTotal"]) == (0, 0)


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


# --------------------------------------------------------------------------- online-флаг (xray/hysteria)


async def test__overview__online_from_stats_flag_overrides_handshake(svc, session_maker):
    """Для xray/hysteria2 (last_handshake=None) онлайн берётся из stats-флага `online`, не из handshake."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110070")
        srv = await make_server(s, owner_id=owner.id)

    await svc.record(srv.id, "xray", [PeerStat(client_id="UUON", rx=1, tx=1, last_handshake=None, online=True)])
    await svc.record(srv.id, "xray", [PeerStat(client_id="UUOFF", rx=1, tx=1, last_handshake=None, online=False)])

    ov = await svc.overview(owner.id, srv.id)
    by_client = {c["clientId"]: c for c in ov["clients"]}
    assert by_client["UUON"]["online"] is True  # флаг движка, хотя handshake нет
    assert by_client["UUOFF"]["online"] is False


async def test__overview__reports_speed_for_active_client(svc, session_maker, uow):
    """Скорость (rxSpeed/txSpeed) берётся из peer_state и показывается только у активных клиентов."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110071")
        srv = await make_server(s, owner_id=owner.id)

    now = time.time()
    # peer_state с известной скоростью: активный клиент (online) и офлайн — скорость гасится
    async with uow.transaction() as tx:
        tx.session.add(
            m.TrafficPeerState(
                server_id=srv.id,
                proto="xray",
                client_id="ON",
                rx_bytes=1000,
                rx_speed=100.0,
                tx_speed=5.0,
                last_at=now,
                online=True,
            )
        )
        tx.session.add(
            m.TrafficPeerState(
                server_id=srv.id,
                proto="xray",
                client_id="OFF",
                rx_bytes=1000,
                rx_speed=100.0,
                tx_speed=5.0,
                last_at=now,
                online=False,
            )
        )
        await tx.session.flush()

    ov = await svc.overview(owner.id, srv.id, period="1h")
    by_client = {c["clientId"]: c for c in ov["clients"]}
    assert by_client["ON"]["rxSpeed"] == pytest.approx(100.0) and by_client["ON"]["txSpeed"] == pytest.approx(5.0)
    assert by_client["OFF"]["rxSpeed"] == 0.0 and by_client["OFF"]["txSpeed"] == 0.0  # офлайн → скорость 0


# --------------------------------------------------------------------------- global_overview


async def test__global_overview__aggregates_across_servers_with_summary(svc, session_maker):
    """Глобальный мониторинг сшивает клиентов всех серверов владельца + считает сводку."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110080", name="Владелец")
        member = await make_user(s, phone="+79001110081", name="Аня")
        srv1 = await make_server(s, owner_id=owner.id, name="DE-1")
        srv2 = await make_server(s, owner_id=owner.id, name="NL-2")
        dev = await make_device(s, user_id=member.id, name="Ноутбук")
        await make_device_config(s, device_id=dev.id, server_id=srv1.id, vpn_type="amnezia", client_id="C1")

    await svc.record(srv1.id, "xray", [PeerStat(client_id="C1", rx=100, tx=200, last_handshake=None, online=True)])
    await svc.record(srv2.id, "hysteria2", [PeerStat(client_id="C2", rx=10, tx=20, last_handshake=None, online=False)])

    ov = await svc.global_overview(owner.id)
    assert ov["summary"]["serversTotal"] == 2
    assert ov["summary"]["clientsTotal"] == 2
    assert ov["summary"]["clientsOnline"] == 1  # только C1 онлайн
    assert ov["summary"]["rxTotal"] == 110 and ov["summary"]["txTotal"] == 220

    by_client = {c["clientId"]: c for c in ov["clients"]}
    assert by_client["C1"]["serverName"] == "DE-1"
    assert by_client["C1"]["userName"] == "Аня" and by_client["C1"]["deviceName"] == "Ноутбук"
    assert by_client["C2"]["serverName"] == "NL-2" and by_client["C2"]["external"] is True


async def test__global_overview__ignores_other_owners_servers(svc, session_maker):
    """Чужие серверы/клиенты не попадают в глобальный мониторинг владельца."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110090")
        stranger = await make_user(s, phone="+79001110091")
        mine = await make_server(s, owner_id=owner.id, name="MINE")
        theirs = await make_server(s, owner_id=stranger.id, name="THEIRS")

    await svc.record(mine.id, "awg", [PeerStat(client_id="M", rx=1, tx=1, last_handshake=time.time())])
    await svc.record(theirs.id, "awg", [PeerStat(client_id="T", rx=9, tx=9, last_handshake=time.time())])

    ov = await svc.global_overview(owner.id)
    assert {c["clientId"] for c in ov["clients"]} == {"M"}
    assert ov["summary"]["serversTotal"] == 1
    # ретеншн сырья/агрегатов теперь в TrafficRollupService (см. test_traffic_rollup)
