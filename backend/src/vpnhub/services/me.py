"""«Доступно мне» — серверы и VPN из групп участника."""

from __future__ import annotations

import time

from sqlalchemy import func, select

from vpnhub.api.config import Settings
from vpnhub.common.serializers import latency_str, rel_time
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.uow import Uow
from vpnhub.services.access import effective_access
from vpnhub.services.limits import effective_byte_limit, period_start, period_usage


class MeService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow

    async def usage(self, user_id: str) -> list[dict]:
        """Мой трафик за текущий период по доступным серверам: израсходовано / лимит + suspended.

        Лимит per-user применяется к КАЖДОМУ серверу отдельно; показываем сервера, где есть лимит или
        уже накоплен трафик (без лимита и с нулём расхода не засоряем).
        """
        async with self.uow.query() as tx:
            access, _ = await effective_access(tx, user_id)
            limit = await effective_byte_limit(tx.session, user_id)
            out = []
            for sid in access:
                s = await tx.servers.get(sid)
                if not s:
                    continue
                ps = period_start(time.time(), s.billing_day)
                rx, txb = await period_usage(tx.session, sid, user_id, ps)
                used = rx + txb
                if used == 0 and limit is None:
                    continue  # нечего показывать
                suspended = int(
                    (
                        await tx.session.execute(
                            select(func.count())
                            .select_from(m.DeviceConfig)
                            .join(m.Device, m.Device.id == m.DeviceConfig.device_id)
                            .where(
                                m.Device.user_id == user_id,
                                m.DeviceConfig.server_id == sid,
                                m.DeviceConfig.status == "suspended",
                            )
                        )
                    ).scalar()
                    or 0
                )
                out.append(
                    {
                        "serverId": sid,
                        "serverName": s.name,
                        "used": used,
                        "limit": limit,
                        "suspended": bool(suspended),
                        "periodStart": ps,
                    }
                )
            out.sort(key=lambda x: x["serverName"])
            return out

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
