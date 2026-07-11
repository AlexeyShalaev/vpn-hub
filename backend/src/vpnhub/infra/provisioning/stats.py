"""Единая точка включения точной статистики протокола (Stats API / trafficStats).

Диспетч по `spec.kind` жил в трёх местах (установка, авто-heal, ручной эндпоинт) — сведён сюда.
"""

from __future__ import annotations

from vpnhub.infra.provisioning import constants as pc
from vpnhub.infra.provisioning.provisioners.hysteria2 import HysteriaProvisioner
from vpnhub.infra.provisioning.provisioners.xray import XrayProvisioner
from vpnhub.infra.provisioning.ssh import SshClient

# протоколы с включаемым stats-API: xray/xray_xhttp — Xray Stats API, hysteria2 — trafficStats.
# awg/awg_legacy считаются по handshakes (включать нечего), outline/openvpn не поддерживают.
STATS_PROTOS = ("xray", "xray_xhttp", "hysteria2")


async def enable_stats(spec: pc.ProtoSpec, ssh: SshClient) -> bool:
    """Идемпотентно включить точную статистику протокола. True — конфиг реально менялся.

    xray → StatsService (True при изменении); hysteria2 → trafficStats (секрет непуст → True).
    Вызывать только для `spec.id in STATS_PROTOS`.
    """
    if spec.kind == "xray":
        return await XrayProvisioner(spec).enable_stats(ssh)
    return bool(await HysteriaProvisioner(spec).enable_stats(ssh))
