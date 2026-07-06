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


# ---- Этап 2: лимит числа устройств на пользователя ----
#
# Иерархия: глобальный дефолт (DB setting `default_devices_per_user`) → override группы
# (`Group.max_devices`) → персональный override участника (`GroupMember.max_devices`).
# Эффективный лимит пользователя = МАКСИМУМ по его активным членствам (доступ к серверам
# аддитивный, поэтому берём самый щедрый применимый лимит). Без членств — глобальный дефолт.

DEFAULT_DEVICES_PER_USER = 5
SETTING_DEFAULT_DEVICES = "default_devices_per_user"


async def global_device_limit(session: Any) -> int:
    """Глобальный дефолт лимита устройств (админ-настройка из DB settings; фолбэк — 5)."""
    row = await session.get(m.Setting, SETTING_DEFAULT_DEVICES)
    if row and (row.value or "").strip().isdigit():
        n = int(row.value)
        if n > 0:
            return n
    return DEFAULT_DEVICES_PER_USER


async def effective_device_limit(session: Any, user_id: str) -> int:
    """Эффективный лимит устройств пользователя (см. иерархию выше)."""
    default = await global_device_limit(session)
    rows = (
        await session.execute(
            select(m.GroupMember.max_devices, m.Group.max_devices)
            .join(m.Group, m.Group.id == m.GroupMember.group_id)
            .where(m.GroupMember.user_id == user_id, m.GroupMember.status == "active")
        )
    ).all()
    # member override → group override → глобал; затем самый щедрый по всем группам
    limits = [(mm if mm is not None else (gm if gm is not None else default)) for mm, gm in rows]
    return max(limits) if limits else default


async def used_devices(session: Any, user_id: str) -> int:
    """Сколько устройств уже заведено у пользователя (все устройства считаются)."""
    res = await session.execute(select(func.count()).select_from(m.Device).where(m.Device.user_id == user_id))
    return int(res.scalar() or 0)
