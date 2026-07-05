"""Юнит-тесты чистого парсера `wg show dump` (без SSH)."""

from __future__ import annotations

from vpnhub.services.traffic import parse_wg_dump

# Реальный формат `wg show <iface> dump`: TSV, первая строка — интерфейс.
# Пир: pubkey  psk  endpoint  allowed-ips  latest-handshake(epoch)  rx  tx  keepalive
_DUMP = (
    "SRVPRIV\tSRVPUB\t51820\toff\n"
    "PEERA\tPSKA\t1.2.3.4:5555\t10.8.1.2/32\t1720180000\t1024\t2048\t0\n"
    "PEERB\tPSKB\t(none)\t10.8.1.3/32\t0\t0\t0\toff\n"
)


def test__parse_wg_dump__parses_peers_and_skips_interface_line() -> None:
    stats = parse_wg_dump(_DUMP)
    assert len(stats) == 2
    a, b = stats
    assert a.client_id == "PEERA"
    assert (a.rx, a.tx) == (1024, 2048)
    assert a.last_handshake == 1720180000.0
    assert b.client_id == "PEERB"
    assert b.last_handshake is None  # handshake=0 → None (рукопожатий не было)


def test__parse_wg_dump__empty_and_interface_only__return_empty() -> None:
    assert parse_wg_dump("") == []
    assert parse_wg_dump("   ") == []
    assert parse_wg_dump("SRVPRIV\tSRVPUB\t51820\toff") == []  # только интерфейс


def test__parse_wg_dump__malformed_lines_are_skipped() -> None:
    text = "IFACE\tX\nPEERA\ttoo\tshort\nPEERB\tp\te\ta\tNOTINT\t1\t2\t0\n"
    assert parse_wg_dump(text) == []  # обе строки битые → пусто
