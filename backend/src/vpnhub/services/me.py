"""«Доступно мне» — серверы и VPN из групп участника."""

from __future__ import annotations

from vpnhub.api.config import Settings
from vpnhub.common.serializers import latency_str, rel_time
from vpnhub.infra.uow import Uow
from vpnhub.services.access import effective_access


class MeService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow

    async def available(self, user_id: str) -> list[dict]:
        async with self.uow.query() as tx:
            access, from_group = await effective_access(tx, user_id)
            out = []
            for sid, vtypes in access.items():
                s = await tx.servers.get(sid)
                if not s:
                    continue
                order = {"amnezia": 0, "openvpn": 1, "outline": 2, "hysteria2": 3}
                out.append(
                    {
                        "id": s.id,
                        "name": s.name,
                        "provider": s.provider,
                        "location": s.location,
                        "status": s.status,
                        "latency": latency_str(s.latency_ms),
                        "lastCheck": rel_time(s.last_check_at),
                        "fromGroup": from_group.get(sid, ""),
                        "vpns": sorted(vtypes, key=lambda t: order.get(t, 9)),
                    }
                )
            out.sort(key=lambda x: x["name"])
            return out
