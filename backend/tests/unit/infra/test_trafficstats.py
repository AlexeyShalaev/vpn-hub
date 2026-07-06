"""Юнит-тесты чистых парсеров per-client трафика (xray statsquery / hysteria trafficStats)."""

from __future__ import annotations

from vpnhub.infra.trafficstats import (
    parse_hysteria_traffic,
    parse_openvpn_traffic,
    parse_outline_transfer,
    parse_xray_stats,
)


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


# --------------------------------------------------------------------------- openvpn


def test__parse_openvpn_traffic__empty_and_no_section__return_empty() -> None:
    assert parse_openvpn_traffic("") == []
    assert parse_openvpn_traffic("   ") == []
    # лог есть, но без секции CLIENT_LIST (например, только заголовок) → пусто
    assert parse_openvpn_traffic("GLOBAL STATS\nMax bcast/mcast queue length,0\nEND\n") == []


def test__parse_openvpn_traffic__v3_machine_readable() -> None:
    # v3: CLIENT_LIST,<CN>,<real>,<virt>,<virt6>,<bytesRecv>,<bytesSent>,<since>,...
    text = (
        "TITLE,OpenVPN 2.5.0\n"
        "TIME,Mon Jul  6 12:00:00 2026,1751803200\n"
        "HEADER,CLIENT_LIST,Common Name,Real Address,Virtual Address,Virtual IPv6 Address,"
        "Bytes Received,Bytes Sent,Connected Since,Connected Since (time_t),Username,Client ID,Peer ID\n"
        "CLIENT_LIST,AbC123def456,1.2.3.4:5555,10.8.0.2,,1024,2048,Mon Jul  6 11:00:00 2026,1751799600,UNDEF,0,0\n"
        "CLIENT_LIST,Zzz999,5.6.7.8:6666,10.8.0.3,,100,200,Mon Jul  6 11:30:00 2026,1751801400,UNDEF,1,1\n"
        "ROUTING TABLE\n"
        "HEADER,ROUTING_TABLE,Virtual Address,Common Name,Real Address,Last Ref,Last Ref (time_t)\n"
    )
    rows = _by_id(parse_openvpn_traffic(text))
    assert set(rows) == {"AbC123def456", "Zzz999"}
    a = rows["AbC123def456"]
    assert (a.rx, a.tx, a.online) == (1024, 2048, True)  # rx=Bytes Received, tx=Bytes Sent
    assert rows["Zzz999"].rx == 100


def test__parse_openvpn_traffic__v2_human_readable() -> None:
    # v2: секция OpenVPN CLIENT LIST, строки после заголовка Common Name,...
    text = (
        "OpenVPN CLIENT LIST\n"
        "Updated,Mon Jul  6 12:00:00 2026\n"
        "Common Name,Real Address,Bytes Received,Bytes Sent,Connected Since\n"
        "AbC123def456,1.2.3.4:5555,1024,2048,Mon Jul  6 11:00:00 2026\n"
        "ROUTING TABLE\n"
        "Virtual Address,Common Name,Real Address,Last Ref\n"
        "10.8.0.2,AbC123def456,1.2.3.4:5555,Mon Jul  6 12:00:00 2026\n"
        "GLOBAL STATS\n"
        "Max bcast/mcast queue length,0\n"
        "END\n"
    )
    rows = _by_id(parse_openvpn_traffic(text))
    assert set(rows) == {"AbC123def456"}
    c = rows["AbC123def456"]
    assert (c.rx, c.tx, c.online) == (1024, 2048, True)


def test__parse_openvpn_traffic__duplicate_cn_is_summed() -> None:
    # duplicate-cn: одна CN в двух сессиях → трафик суммируется в одну строку
    text = (
        "HEADER,CLIENT_LIST,Common Name,Real Address,Virtual Address,Virtual IPv6 Address,"
        "Bytes Received,Bytes Sent,Connected Since\n"
        "CLIENT_LIST,DUP,1.2.3.4:1,10.8.0.2,,10,20,x\n"
        "CLIENT_LIST,DUP,1.2.3.4:2,10.8.0.3,,5,7,x\n"
    )
    rows = _by_id(parse_openvpn_traffic(text))
    assert set(rows) == {"DUP"}
    assert (rows["DUP"].rx, rows["DUP"].tx) == (15, 27)


def test__parse_openvpn_traffic__malformed_rows_skipped() -> None:
    text = (
        "HEADER,CLIENT_LIST,Common Name,Real Address,Virtual Address,Virtual IPv6 Address,"
        "Bytes Received,Bytes Sent,Connected Since\n"
        "CLIENT_LIST,BAD,1.2.3.4:1,10.8.0.2,,notint,20,x\n"  # нечисловой recv → пропуск
        "CLIENT_LIST,,1.2.3.4:2,10.8.0.3,,5,7,x\n"  # пустой CN → пропуск
        "CLIENT_LIST,short,1.2.3.4\n"  # слишком мало полей → пропуск
    )
    assert parse_openvpn_traffic(text) == []


# --------------------------------------------------------------------------- outline


def test__parse_outline_transfer__empty_and_broken__return_empty() -> None:
    assert parse_outline_transfer("") == []
    assert parse_outline_transfer("nope") == []
    assert parse_outline_transfer("{}") == []  # нет bytesTransferredByUserId
    assert parse_outline_transfer('{"bytesTransferredByUserId":{}}') == []  # секция есть, но пусто


def test__parse_outline_transfer__per_key_total_bytes() -> None:
    text = '{"bytesTransferredByUserId":{"0":123456,"7":42}}'
    rows = _by_id(parse_outline_transfer(text))
    assert set(rows) == {"0", "7"}
    # суммарный трафик кладём в tx; rx=0; online не поддержан (None)
    assert (rows["0"].rx, rows["0"].tx, rows["0"].online) == (0, 123456, None)
    assert (rows["7"].rx, rows["7"].tx, rows["7"].online) == (0, 42, None)


def test__parse_outline_transfer__non_int_values_skipped() -> None:
    text = '{"bytesTransferredByUserId":{"0":"bad","1":50}}'
    rows = _by_id(parse_outline_transfer(text))
    assert set(rows) == {"1"}
    assert rows["1"].tx == 50
