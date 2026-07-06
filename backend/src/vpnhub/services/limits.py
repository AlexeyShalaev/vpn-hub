"""Лимиты панели (мягкие, задаёт владелец) — Этап 1: лимит числа конфигов на server-protocol.

Занятость протокола (`used_clients`) = активные выданные `DeviceConfig` (status=active, с
материалом) + `ServerProtocol.external_clients` (клиенты, заведённые мимо панели). Это оценка
для отображения и для запрета выдачи сверх `ServerProtocol.max_clients` (NULL = без лимита).

ВАЖНО: это НЕ физический потолок. У AmneziaWG адресное пространство растёт за /24 намеренно
(см. ipalloc — не трогаем); у OpenVPN реальный предел — его пул /24 (держит сам openvpn).
Здесь — панельный soft-cap владельца, применимый к любому протоколу.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select

from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import constants as pc


async def used_clients(session: Any, sp: m.ServerProtocol) -> int:
    """Сколько клиентов занято на этом протоколе сервера = активные конфиги + внешние."""
    spec = pc.spec_by_id(sp.proto)
    label = spec.label if spec else sp.proto  # DeviceConfig.proto хранит label протокола
    res = await session.execute(
        select(func.count())
        .select_from(m.DeviceConfig)
        .where(
            m.DeviceConfig.server_id == sp.server_id,
            m.DeviceConfig.proto == label,
            m.DeviceConfig.status == "active",
            m.DeviceConfig.client_id.isnot(None),
        )
    )
    return int(res.scalar() or 0) + (sp.external_clients or 0)


def over_limit(used: int, max_clients: int | None) -> bool:
    """True, если выдавать НОВЫЙ конфиг нельзя (лимит задан и уже достигнут/превышен)."""
    return max_clients is not None and used >= max_clients
