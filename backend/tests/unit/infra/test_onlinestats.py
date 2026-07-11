"""Тесты честного online-счётчика: парсеры (xray/hysteria/openvpn) + вывод online из трафика.

Раньше online опрашивался отдельными SSH-запросами (`collect_online_by_proto`); теперь выводится из
уже собранного трафика чистой функцией `online_from_traffic` (без доп. вызовов движка)."""

from __future__ import annotations

import time

from vpnhub.infra.onlinestats import parse_hysteria_online, parse_openvpn_online, parse_xray_online
from vpnhub.services.hostmetrics import _sum_known, online_from_traffic
from vpnhub.services.traffic import (
    TRAFFIC_CONTAINER_DOWN,
    TRAFFIC_OK,
    TRAFFIC_STATS_DISABLED,
    PeerStat,
    ProtoTraffic,
)


def test_parse_xray_online() -> None:
    assert parse_xray_online("") is None  # stats не включён / бинарь недоступен
    assert parse_xray_online("not json") is None
    assert parse_xray_online("{}") == 0  # API жив, онлайна нет
    assert parse_xray_online('{"stat":null}') == 0
    js = (
        '{"stat":[{"name":"user>>>a>>>online","value":"2"},'
        '{"name":"user>>>b>>>online","value":"0"},'
        '{"name":"user>>>c>>>online","value":"1"},'
        '{"name":"user>>>c>>>uplink","value":"999"}]}'
    )
    assert parse_xray_online(js) == 2  # a и c с online>0; uplink-запись не в счёт


def test_parse_hysteria_online() -> None:
    assert parse_hysteria_online("") is None
    assert parse_hysteria_online("nope") is None
    assert parse_hysteria_online("{}") == 0
    assert parse_hysteria_online('{"u1":1,"u2":0,"u3":3}') == 2


def test_parse_openvpn_online() -> None:
    assert parse_openvpn_online("") is None
    v3 = "HEADER,CLIENT_LIST,Common Name\nCLIENT_LIST,alice,1.2.3.4\nCLIENT_LIST,bob,5.6.7.8\n"
    assert parse_openvpn_online(v3) == 2
    v2 = (
        "OpenVPN CLIENT LIST\nUpdated,...\nCommon Name,Real Address\n"
        "alice,1.2.3.4\nbob,5.6.7.8\nROUTING TABLE\n0.0.0.0,alice\n"
    )
    assert parse_openvpn_online(v2) == 2
    assert parse_openvpn_online("random text without section") is None


def test_sum_known() -> None:
    assert _sum_known({}) is None
    assert _sum_known({"a": None, "b": None}) is None  # всё неизвестно → None
    assert _sum_known({"a": 1, "b": None, "c": 2}) == 3  # None не считается
    assert _sum_known({"a": 0}) == 0


# --------------------------------------------------------------------------- online_from_traffic


def test__online_from_traffic__wireguard_counts_fresh_handshakes() -> None:
    now = time.time()
    window = 300
    res = {
        "awg": ProtoTraffic(
            "awg",
            TRAFFIC_OK,
            stats=[
                PeerStat(client_id="A", rx=1, tx=1, last_handshake=now - 10),  # свежий → онлайн
                PeerStat(client_id="B", rx=1, tx=1, last_handshake=now - 999),  # устарел → офлайн
                PeerStat(client_id="C", rx=1, tx=1, last_handshake=None),  # рукопожатий не было
            ],
        )
    }
    assert online_from_traffic(res, now, window) == {"awg": 1}


def test__online_from_traffic__stats_protocols_use_online_flag() -> None:
    now = time.time()
    res = {
        "xray": ProtoTraffic(
            "xray",
            TRAFFIC_OK,
            stats=[
                PeerStat(client_id="U1", rx=1, tx=1, last_handshake=None, online=True),
                PeerStat(client_id="U2", rx=1, tx=1, last_handshake=None, online=False),
            ],
        ),
        "hysteria2": ProtoTraffic(
            "hysteria2", TRAFFIC_OK, stats=[PeerStat(client_id="H", rx=1, tx=1, last_handshake=None, online=True)]
        ),
    }
    out = online_from_traffic(res, now, 300)
    assert out == {"xray": 1, "hysteria2": 1}


def test__online_from_traffic__outline_and_non_ok_are_unknown() -> None:
    now = time.time()
    res = {
        "outline": ProtoTraffic(
            "outline", TRAFFIC_OK, stats=[PeerStat(client_id="K", rx=0, tx=100, last_handshake=None, online=None)]
        ),
        "xray": ProtoTraffic("xray", TRAFFIC_STATS_DISABLED, error="off"),  # не собрано → None
        "awg": ProtoTraffic("awg", TRAFFIC_CONTAINER_DOWN, error="down"),  # контейнер лёг → None
    }
    out = online_from_traffic(res, now, 300)
    assert out == {"outline": None, "xray": None, "awg": None}
    assert _sum_known(out) is None  # всё неизвестно → сумма None


def test__online_from_traffic__mixed_sum_known() -> None:
    now = time.time()
    res = {
        "awg": ProtoTraffic("awg", TRAFFIC_OK, stats=[PeerStat(client_id="A", rx=1, tx=1, last_handshake=now)]),
        "xray": ProtoTraffic("xray", TRAFFIC_STATS_DISABLED, error="off"),
    }
    out = online_from_traffic(res, now, 300)
    assert out == {"awg": 1, "xray": None}
    assert _sum_known(out) == 1  # None-протокол не портит сумму известных
