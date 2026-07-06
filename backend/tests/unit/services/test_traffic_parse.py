"""Юнит-тесты чистого парсера `wg show dump` + диспетча TrafficCollector (fake SSH)."""

from __future__ import annotations

from dataclasses import dataclass

from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.provisioners.base import ServerMaterial
from vpnhub.infra.provisioning.provisioners.outline import OutlineProvisioner
from vpnhub.services.traffic import TrafficCollector, parse_wg_dump

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


# --------------------------------------------------------------------------- collector dispatch


@dataclass
class _Res:
    stdout: str = ""
    stderr: str = ""
    exit_status: int = 0

    @property
    def output(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


class _FakeSsh:
    """Отдаёт заготовленный вывод по подстроке команды (эмулирует stats-API каждого протокола)."""

    async def run(self, cmd: str) -> _Res:
        if "statsquery" in cmd:  # xray Stats API
            return _Res(
                stdout='{"stat":[{"name":"user>>>UU>>>traffic>>>uplink","value":"10"},'
                '{"name":"user>>>UU>>>traffic>>>downlink","value":"20"},'
                '{"name":"user>>>UU>>>online","value":"1"}]}'
            )
        if "trafficStats" in cmd:  # hysteria _read_stats_secret (awk по config.yaml)
            return _Res(stdout="0123456789abcdef0123456789abcdef")
        if "/metrics/transfer" in cmd:  # outline Management API
            return _Res(stdout='{"bytesTransferredByUserId":{"0":9000}}')
        if "/traffic" in cmd:  # hysteria trafficStats GET /traffic
            return _Res(stdout='{"AUTH":{"tx":50,"rx":5}}')
        if "/online" in cmd:  # hysteria trafficStats GET /online
            return _Res(stdout='{"AUTH":1}')
        if "openvpn-status.log" in cmd:  # openvpn status-лог (первый кандидат — корень)
            if "/openvpn-status.log" in cmd and "/opt/" not in cmd:
                return _Res(
                    stdout="HEADER,CLIENT_LIST,Common Name,Real Address,Virtual Address,"
                    "Virtual IPv6 Address,Bytes Received,Bytes Sent,Connected Since\n"
                    "CLIENT_LIST,CN1,1.2.3.4:1,10.8.0.2,,333,444,x\n"
                )
            return _Res(stdout="")  # второй кандидат пуст
        if "show" in cmd and "dump" in cmd:  # wg dump (через container_exec → run)
            return _Res(stdout="IFACE\tX\nPEERA\tPSK\tep\tips\t1720180000\t111\t222\t0\n")
        return _Res(stdout="")

    async def container_exec(self, container: str, command: str, *, detach: bool = False) -> _Res:
        return await self.run(f"docker exec {container} {command}")


async def test__collect__wireguard_dispatch() -> None:
    stats = await TrafficCollector.collect(_FakeSsh(), pc.spec_by_id("awg"))
    assert len(stats) == 1
    assert (stats[0].client_id, stats[0].rx, stats[0].tx) == ("PEERA", 111, 222)


async def test__collect__xray_dispatch__per_uuid_with_online() -> None:
    stats = await TrafficCollector.collect(_FakeSsh(), pc.spec_by_id("xray"))
    assert len(stats) == 1
    s = stats[0]
    assert (s.client_id, s.rx, s.tx, s.online) == ("UU", 10, 20, True)
    assert s.last_handshake is None  # у xray handshake нет


async def test__collect__hysteria_dispatch__per_authid_with_online() -> None:
    stats = await TrafficCollector.collect(_FakeSsh(), pc.spec_by_id("hysteria2"))
    assert len(stats) == 1
    s = stats[0]
    assert (s.client_id, s.rx, s.tx, s.online) == ("AUTH", 5, 50, True)


async def test__collect__openvpn_dispatch__per_cn_from_status_log() -> None:
    stats = await TrafficCollector.collect(_FakeSsh(), pc.spec_by_id("openvpn"))
    assert len(stats) == 1
    s = stats[0]
    assert (s.client_id, s.rx, s.tx, s.online) == ("CN1", 333, 444, True)
    assert s.last_handshake is None  # у openvpn handshake-эпоху не читаем


async def test__collect__outline_dispatch__per_key_total_bytes() -> None:
    prov = OutlineProvisioner(
        pc.spec_by_id("outline"), material=ServerMaterial(outline_api_url="https://1.2.3.4:9000/x")
    )
    stats = await TrafficCollector.collect(_FakeSsh(), pc.spec_by_id("outline"), prov)
    assert len(stats) == 1
    s = stats[0]
    # Outline: суммарный трафик в tx, rx=0, online не поддержан (None)
    assert (s.client_id, s.rx, s.tx, s.online) == ("0", 0, 9000, None)


async def test__collect__outline_without_provisioner__returns_empty() -> None:
    # без провизионера (нет apiUrl) → пусто, не падаем
    assert await TrafficCollector.collect(_FakeSsh(), pc.spec_by_id("outline")) == []
