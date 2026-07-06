"""Юнит-тесты чистого парсера хост-метрик (`parse_host_metrics` / `parse_online_clients`), без SSH."""

from __future__ import annotations

from vpnhub.infra.hostmetrics import parse_host_metrics, parse_online_clients

# Реальный блок вывода HOST_METRICS_CMD (значения памяти/диска — уже в БАЙТАХ).
# CPUA→CPUB: idle (4-е число) вырос на 90 из total-прироста 100 → CPU% = (1-0.9)*100 = 10.0.
_BLOCK = (
    "UPTIME=123456.78\n"
    "LOADAVG=0.15 0.30 0.42\n"
    "NPROC=4\n"
    "MemTotal=8589934592\n"  # 8 ГиБ — заведомо >int32
    "MemAvailable=2147483648\n"  # 2 ГиБ доступно
    "DISK_USED=10737418240\n"  # 10 ГиБ занято
    "DISK_TOTAL=53687091200\n"  # 50 ГиБ всего
    "TCP_ESTAB=42\n"
    "CPUA=cpu 100 0 50 800 0 0 0 0 0 0\n"
    "CPUB=cpu 110 0 50 890 0 0 0 0 0 0\n"
)


def test__parse_host_metrics__parses_all_fields() -> None:
    hm = parse_host_metrics(_BLOCK)
    assert hm.uptime_s == 123456
    assert hm.load1 == 0.15
    assert hm.tcp_estab == 42
    # used = total - available = 8Gi - 2Gi = 6Gi; проверяем именно вычитание и BigInteger-размер
    assert hm.mem_total == 8589934592
    assert hm.mem_used == 8589934592 - 2147483648
    assert hm.disk_used == 10737418240
    assert hm.disk_total == 53687091200


def test__parse_host_metrics__cpu_pct_from_two_stat_snapshots() -> None:
    hm = parse_host_metrics(_BLOCK)
    # idle_delta=90, total_delta=100 → (1-0.9)*100 = 10.0
    assert hm.cpu_pct == 10.0


def test__parse_host_metrics__mem_used_survives_int32_overflow() -> None:
    # реальный крупный хост: 64 ГиБ RAM, доступно 1 ГиБ → used ~63 ГиБ (много >2^31)
    block = "MemTotal=68719476736\nMemAvailable=1073741824\n"
    hm = parse_host_metrics(block)
    assert hm.mem_total == 68719476736
    assert hm.mem_used == 68719476736 - 1073741824
    assert hm.mem_used > 2**31  # именно то, что ловил BigInteger в traffic


def test__parse_host_metrics__cpu_zero_when_no_total_delta() -> None:
    block = "CPUA=cpu 100 0 50 800 0 0\nCPUB=cpu 100 0 50 800 0 0\n"
    assert parse_host_metrics(block).cpu_pct == 0.0


def test__parse_host_metrics__missing_and_malformed_fields_are_none() -> None:
    hm = parse_host_metrics("UPTIME=notanumber\nLOADAVG=\nGARBAGE\n")
    assert hm.uptime_s is None
    assert hm.load1 is None
    assert hm.mem_total is None and hm.mem_used is None
    assert hm.cpu_pct is None
    assert hm.tcp_estab is None


def test__parse_host_metrics__empty_input_all_none() -> None:
    hm = parse_host_metrics("")
    assert hm == parse_host_metrics("   \n  \n")
    assert hm.cpu_pct is None and hm.mem_total is None and hm.online_clients is None


def test__parse_online_clients__counts_fresh_handshakes() -> None:
    now = 1_000_000.0
    # формат `wg show all latest-handshakes`: <iface> <pubkey> <epoch>
    text = (
        "awg0\tPEERA\t999950\n"  # 50с назад → онлайн
        "awg0\tPEERB\t999000\n"  # 1000с назад → офлайн (за окном 180)
        "awg0\tPEERC\t0\n"  # рукопожатий не было → не онлайн
        "awg0\tPEERD\t999900\n"  # 100с назад → онлайн
    )
    assert parse_online_clients(text, now) == 2


def test__parse_online_clients__robust_to_garbage_and_empty() -> None:
    assert parse_online_clients("", 1_000_000.0) == 0
    assert parse_online_clients("short line\nawg0 PEER notint\n", 1_000_000.0) == 0
