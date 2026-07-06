"""Юнит-тесты чистых парсеров per-client трафика (xray statsquery / hysteria trafficStats)."""

from __future__ import annotations

from vpnhub.infra.trafficstats import parse_hysteria_traffic, parse_xray_stats


def _by_id(rows):
    return {r.client_id: r for r in rows}


# --------------------------------------------------------------------------- xray


def test__parse_xray_stats__empty_and_broken__return_empty() -> None:
    assert parse_xray_stats("") == []
    assert parse_xray_stats("   ") == []
    assert parse_xray_stats("not json") == []
    assert parse_xray_stats("{}") == []
    assert parse_xray_stats('{"stat":null}') == []


def test__parse_xray_stats__uplink_downlink_online_per_uuid() -> None:
    js = (
        '{"stat":['
        '{"name":"user>>>UUID_A>>>traffic>>>uplink","value":"100"},'
        '{"name":"user>>>UUID_A>>>traffic>>>downlink","value":"200"},'
        '{"name":"user>>>UUID_A>>>online","value":"1"},'
        '{"name":"user>>>UUID_B>>>traffic>>>uplink","value":"5"},'
        '{"name":"user>>>UUID_B>>>online","value":"0"}]}'
    )
    rows = _by_id(parse_xray_stats(js))
    assert set(rows) == {"UUID_A", "UUID_B"}
    a = rows["UUID_A"]
    assert (a.rx, a.tx, a.online) == (100, 200, True)  # rx=uplink(client→server), tx=downlink
    b = rows["UUID_B"]
    assert (b.rx, b.tx, b.online) == (5, 0, False)  # только uplink + online=0 → офлайн


def test__parse_xray_stats__separate_online_response_is_merged() -> None:
    traffic = '{"stat":[{"name":"user>>>U>>>traffic>>>uplink","value":"10"}]}'
    online = '{"stat":[{"name":"user>>>U>>>online","value":"2"}]}'
    rows = _by_id(parse_xray_stats(traffic, online))
    assert rows["U"].rx == 10
    assert rows["U"].online is True


def test__parse_xray_stats__ignores_non_user_and_bad_values() -> None:
    js = (
        '{"stat":['
        '{"name":"inbound>>>api>>>traffic>>>uplink","value":"999"},'
        '{"name":"user>>>U>>>traffic>>>uplink","value":"notint"},'
        '{"name":"user>>>U>>>online","value":"1"}]}'
    )
    rows = _by_id(parse_xray_stats(js))
    assert set(rows) == {"U"}  # inbound-стат отброшен
    assert rows["U"].rx == 0  # битое value пропущено, но online дал строку
    assert rows["U"].online is True


# --------------------------------------------------------------------------- hysteria2


def test__parse_hysteria_traffic__empty_and_broken__return_empty() -> None:
    assert parse_hysteria_traffic("") == []
    assert parse_hysteria_traffic("nope") == []
    assert parse_hysteria_traffic("{}") == []


def test__parse_hysteria_traffic__rx_tx_and_online() -> None:
    traffic = '{"AUTH1":{"tx":500,"rx":100},"AUTH2":{"tx":0,"rx":0}}'
    online = '{"AUTH1":1,"AUTH2":0}'
    rows = _by_id(parse_hysteria_traffic(traffic, online))
    assert set(rows) == {"AUTH1", "AUTH2"}
    # rx=upload(client→server), tx=download(server→client) — семантика как у wg/xray
    assert (rows["AUTH1"].rx, rows["AUTH1"].tx, rows["AUTH1"].online) == (100, 500, True)
    assert (rows["AUTH2"].rx, rows["AUTH2"].tx, rows["AUTH2"].online) == (0, 0, False)


def test__parse_hysteria_traffic__online_only_client_added_with_zero_bytes() -> None:
    # клиент онлайн, но трафика ещё нет в /traffic → добавляется с rx=tx=0
    rows = _by_id(parse_hysteria_traffic("{}", '{"NEW":1}'))
    assert set(rows) == {"NEW"}
    assert (rows["NEW"].rx, rows["NEW"].tx, rows["NEW"].online) == (0, 0, True)


def test__parse_hysteria_traffic__online_none_when_no_online_response() -> None:
    rows = _by_id(parse_hysteria_traffic('{"A":{"tx":1,"rx":2}}'))
    assert rows["A"].online is None  # /online не читался → неизвестно
