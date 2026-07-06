"""Тесты честного online-счётчика: парсеры (xray/hysteria/openvpn) + агрегация + диспетч сбора."""

from __future__ import annotations

import time
from dataclasses import dataclass
from types import SimpleNamespace

from vpnhub.infra.onlinestats import parse_hysteria_online, parse_openvpn_online, parse_xray_online
from vpnhub.services.hostmetrics import _sum_known, collect_online_by_proto


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


@dataclass
class _Res:
    stdout: str = ""
    stderr: str = ""
    exit_status: int = 0

    @property
    def output(self) -> str:
        return (self.stdout or "") + (self.stderr or "")


class _FakeSsh:
    """Отдаёт заранее заготовленный вывод по подстроке команды (эмулирует stats-API протоколов)."""

    def __init__(self, now: float) -> None:
        self.now = now

    async def run(self, cmd: str) -> _Res:
        if "statsquery" in cmd:  # xray Stats API
            return _Res(stdout='{"stat":[{"name":"user>>>a>>>online","value":"1"}]}')
        if "trafficStats" in cmd:  # hysteria _read_stats_secret (awk по config.yaml)
            return _Res(stdout="0123456789abcdef0123456789abcdef")
        if "/online" in cmd:  # hysteria trafficStats GET /online
            return _Res(stdout='{"u1":1,"u2":1}')
        if "latest-handshakes" in cmd:  # awg/awg_legacy wg
            return _Res(stdout=f"awg0 PUBKEYAAA {int(self.now)}\n")
        return _Res(stdout="")


async def test_collect_online_by_proto_dispatch() -> None:
    now = time.time()
    ssh = _FakeSsh(now)
    protos = [
        SimpleNamespace(proto="xray", installed=True),
        SimpleNamespace(proto="hysteria2", installed=True),
        SimpleNamespace(proto="awg", installed=True),
        SimpleNamespace(proto="outline", installed=True),
        SimpleNamespace(proto="xray_xhttp", installed=False),  # не installed → пропускается
    ]
    out = await collect_online_by_proto(ssh, protos)  # type: ignore[arg-type]
    assert out["xray"] == 1  # Stats API: один online-пользователь
    assert out["hysteria2"] == 2  # /online: u1,u2 > 0
    assert out["awg"] == 1  # свежий handshake
    assert out["outline"] is None  # Shadowsocks без сессий
    assert "xray_xhttp" not in out  # не installed
    assert _sum_known(out) == 4  # 1 + 2 + 1 (None не считается)
