"""Выделение IP клиенту WireGuard/AmneziaWG (порт getIpsFromConf + nextIp).

Amnezia НЕ ведёт реестр IP: следующий адрес вычисляется по живому серверному конфигу —
берутся все `AllowedIPs = x.x.x.x` из [Peer]-блоков, последний по порядку, и к нему
прибавляется 1 (с особыми случаями для последнего октета 254→+3, 255→+2).
Арифметика — на полном 32-битном адресе (wireguardConfigurator.cpp:155-159).
"""

from __future__ import annotations

import ipaddress
import re

from vpnhub.infra.provisioning import constants as c

_ALLOWED_IPS_RE = re.compile(r"AllowedIPs\s*=\s*(\d+\.\d+\.\d+\.\d+)")


def ips_from_conf(text: str) -> list[str]:
    """Все IPv4 из строк AllowedIPs (в порядке появления)."""
    return _ALLOWED_IPS_RE.findall(text)


def next_client_ip(server_conf_text: str, subnet_address: str = c.DEFAULT_SUBNET_ADDRESS) -> str:
    """Следующий свободный IP клиента по тексту серверного конфига."""
    ips = ips_from_conf(server_conf_text)
    last = int(ipaddress.IPv4Address(ips[-1] if ips else subnet_address))
    last_octet = last & 0xFF
    if last_octet == 254:
        nxt = last + 3
    elif last_octet == 255:
        nxt = last + 2
    else:
        nxt = last + 1
    return str(ipaddress.IPv4Address(nxt))
