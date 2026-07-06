"""Чистый парсер блока хост-метрик сервера (без SSH/IO — легко тестируется).

Сбор идёт одной SSH-командой (см. `HOST_METRICS_CMD`), которая печатает построчно
`KEY=VALUE` из /proc и утилит (uptime/loadavg/nproc/meminfo/df/ss/stat). Здесь только
разбор этого текста в структуру `HostMetrics`. Всё best-effort: если строки нет или она
не парсится — поле остаётся None (тик сбора не должен падать из-за одного кривого поля).

CPU% считается по двум снимкам /proc/stat (CPUA до sleep 1, CPUB после): доля не-idle
времени за секунду. Это тот же принцип, что использует top/htop.
"""

from __future__ import annotations

from dataclasses import dataclass

# Одна SSH-команда: печатает блок KEY=VALUE (значения памяти/диска — в БАЙТАХ).
# Отлажена на живом сервере; порядок и имена ключей фиксированы — парсер ниже на них завязан.
HOST_METRICS_CMD = (
    "echo \"UPTIME=$(cut -d' ' -f1 /proc/uptime)\"\n"
    "echo \"LOADAVG=$(cut -d' ' -f1-3 /proc/loadavg)\"\n"
    'echo "NPROC=$(nproc)"\n'
    'awk \'/MemTotal|MemAvailable/{sub(/:/,"",$1); printf "%s=%s\\n",$1,$2*1024}\' /proc/meminfo\n'
    'df -B1 --output=used,size / | tail -1 | awk \'{print "DISK_USED="$1"\\nDISK_TOTAL="$2}\'\n'
    'echo "TCP_ESTAB=$(ss -tan state established 2>/dev/null | tail -n +2 | wc -l)"\n'
    'A=$(head -1 /proc/stat); sleep 1; B=$(head -1 /proc/stat); echo "CPUA=$A"; echo "CPUB=$B"\n'
)


@dataclass(frozen=True)
class HostMetrics:
    """Замер ресурсов хоста за один тик. Все поля best-effort (None — не удалось прочитать)."""

    cpu_pct: float | None = None  # загрузка CPU, % (0..100) по двум снимкам /proc/stat
    load1: float | None = None  # 1-минутный load average
    mem_used: int | None = None  # использовано RAM, байт (total - available)
    mem_total: int | None = None  # всего RAM, байт
    disk_used: int | None = None  # занято на / , байт
    disk_total: int | None = None  # всего на / , байт
    tcp_estab: int | None = None  # число TCP-соединений в состоянии established
    uptime_s: int | None = None  # аптайм хоста, сек
    online_clients: int | None = None  # онлайн-VPN-пиров (опционально; заполняется отдельно)


def _to_kv(text: str) -> dict[str, str]:
    """Разобрать блок `KEY=VALUE` (по одной паре на строку) в словарь; кривые строки пропускаются."""
    kv: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or "=" not in line:
            continue
        key, _, value = line.partition("=")
        kv[key.strip()] = value.strip()
    return kv


def _f(kv: dict[str, str], key: str) -> float | None:
    try:
        return float(kv[key])
    except (KeyError, ValueError):
        return None


def _i(kv: dict[str, str], key: str) -> int | None:
    v = _f(kv, key)
    return int(v) if v is not None else None


def _cpu_pct(kv: dict[str, str]) -> float | None:
    """CPU% из двух снимков /proc/stat (`cpu user nice system idle iowait irq softirq steal ...`).

    idle_delta = idle(B) - idle(A) (4-е число после `cpu`); total_delta = сумма всех полей B - A.
    cpu_pct = (1 - idle_delta/total_delta) * 100. При total_delta<=0 → 0.
    """
    a, b = kv.get("CPUA"), kv.get("CPUB")
    if not a or not b:
        return None
    try:
        fa = [int(x) for x in a.split()[1:]]  # отбрасываем префикс "cpu"
        fb = [int(x) for x in b.split()[1:]]
    except ValueError:
        return None
    if len(fa) < 4 or len(fb) < 4:
        return None
    idle_delta = fb[3] - fa[3]
    total_delta = sum(fb) - sum(fa)
    if total_delta <= 0:
        return 0.0
    pct = (1.0 - idle_delta / total_delta) * 100.0
    return round(max(0.0, min(100.0, pct)), 1)


def parse_host_metrics(text: str) -> HostMetrics:
    """Разобрать вывод `HOST_METRICS_CMD` в `HostMetrics` (робастно к пустым/битым полям)."""
    kv = _to_kv(text)

    load1: float | None = None
    loadavg = kv.get("LOADAVG")
    if loadavg:
        try:
            load1 = float(loadavg.split()[0])
        except (ValueError, IndexError):
            load1 = None

    mem_total = _i(kv, "MemTotal")
    mem_avail = _i(kv, "MemAvailable")
    mem_used = mem_total - mem_avail if mem_total is not None and mem_avail is not None else None

    uptime = _f(kv, "UPTIME")

    return HostMetrics(
        cpu_pct=_cpu_pct(kv),
        load1=load1,
        mem_used=mem_used,
        mem_total=mem_total,
        disk_used=_i(kv, "DISK_USED"),
        disk_total=_i(kv, "DISK_TOTAL"),
        tcp_estab=_i(kv, "TCP_ESTAB"),
        uptime_s=int(uptime) if uptime is not None else None,
    )


# --- онлайн-VPN-клиенты (опционально) ---------------------------------------

# amnezia-wireguard-контейнеры, где считаем свежие handshakes как «онлайн-пиров».
AMNEZIA_WG_CONTAINERS = ("amnezia-awg2", "amnezia-awg")
# пир считается онлайн, если последний handshake свежее этого окна (сек) — как traffic online-window.
ONLINE_HANDSHAKE_WINDOW = 180


def parse_online_clients(text: str, now: float, *, window: int = ONLINE_HANDSHAKE_WINDOW) -> int:
    """Число онлайн-пиров из `wg show all latest-handshakes` (строки `<iface> <pubkey> <epoch>`).

    Пир онлайн, если `now - handshake < window`. Робастно к пустому/битому выводу
    (нечисловые/короткие строки пропускаются). handshake==0 (рукопожатий не было) — не онлайн.
    """
    online = 0
    for line in text.splitlines():
        fields = line.split()
        if len(fields) < 3:
            continue
        try:
            hs = int(fields[-1])
        except ValueError:
            continue
        if hs > 0 and (now - hs) < window:
            online += 1
    return online
