"""Лимиты панели (мягкие, задаёт владелец) — Этап 1: лимит числа конфигов на server-protocol.

Занятость протокола (`used_clients`) = активные выданные `DeviceConfig` (status=active, с
материалом) + `ServerProtocol.external_clients` (клиенты, заведённые мимо панели). Это оценка
для отображения и для запрета выдачи сверх `ServerProtocol.max_clients` (NULL = без лимита).

ВАЖНО: это НЕ физический потолок. У AmneziaWG адресное пространство растёт за /24 намеренно
(см. ipalloc — не трогаем); у OpenVPN реальный предел — его пул /24 (держит сам openvpn).
Здесь — панельный soft-cap владельца, применимый к любому протоколу.
"""

from __future__ import annotations

import calendar
import time
from typing import Any

from sqlalchemy import func, select
from sqlalchemy import update as sa_update
from sqlalchemy.exc import IntegrityError

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


# ---- Этап 3: лимит байт per (user, server) за биллинг-период + квота трафика сервера ----
#
# Иерархия пер-user лимита (байт за период): самый щедрый ЯВНО заданный лимит среди активных
# членств (member override > group override), иначе глобальный дефолт (setting default_user_bytes).
# NULL везде = без лимита (у трафика дефолт — безлимит). Учёт — накопитель TrafficUsage, который
# инкрементится из тех же дельт, что и traffic_samples (add_period_usage), и переживает purge сэмплов.

SETTING_DEFAULT_USER_BYTES = "default_user_bytes"


def fmt_bytes(n: int | float) -> str:
    """Человекочитаемый размер (для сообщений об ошибке лимита)."""
    f = float(n)
    for unit in ("Б", "КБ", "МБ", "ГБ", "ТБ"):
        if f < 1024 or unit == "ТБ":
            return f"{f:.0f} {unit}" if unit == "Б" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} ТБ"


def period_start(now: float, billing_day: int | None) -> float:
    """Epoch начала текущего биллинг-периода для дня сброса billing_day (1..31; None/вне → 1).

    Период сбрасывается в день billing_day каждого месяца; день клампится к длине месяца
    (напр. 31 в феврале → 28/29). Границы считаются в локальном времени (как «1-е число»).
    """
    day = billing_day if (billing_day and 1 <= billing_day <= 31) else 1
    lt = time.localtime(now)
    y, mo = lt.tm_year, lt.tm_mon
    anchor = min(day, calendar.monthrange(y, mo)[1])
    if lt.tm_mday >= anchor:
        sy, sm = y, mo
    else:  # ещё не наступил день сброса в этом месяце → период начался в прошлом
        sm = mo - 1 or 12
        sy = y if mo > 1 else y - 1
    sday = min(day, calendar.monthrange(sy, sm)[1])
    return time.mktime((sy, sm, sday, 0, 0, 0, 0, 0, -1))


async def global_user_bytes(session: Any) -> int | None:
    """Глобальный дефолт лимита байт на пользователя (setting; None/0/мусор = без лимита)."""
    row = await session.get(m.Setting, SETTING_DEFAULT_USER_BYTES)
    if row and (row.value or "").strip().isdigit():
        n = int(row.value)
        return n if n > 0 else None
    return None


async def effective_byte_limit(session: Any, user_id: str) -> int | None:
    """Лимит байт per (user, server) за период; None = без лимита (см. иерархию выше)."""
    rows = (
        await session.execute(
            select(m.GroupMember.max_bytes, m.Group.max_bytes)
            .join(m.Group, m.Group.id == m.GroupMember.group_id)
            .where(m.GroupMember.user_id == user_id, m.GroupMember.status == "active")
        )
    ).all()
    explicit = [(mm if mm is not None else gm) for mm, gm in rows]
    explicit = [x for x in explicit if x is not None]
    if explicit:
        return int(max(explicit))
    return await global_user_bytes(session)


async def period_usage(session: Any, server_id: str, user_id: str | None, ps: float) -> tuple[int, int]:
    """(rx, tx) байт из накопителя за период ps. user_id=None → суммарный трафик сервера."""
    cond = m.TrafficUsage.user_id.is_(None) if user_id is None else m.TrafficUsage.user_id == user_id
    row = (
        await session.execute(
            select(m.TrafficUsage.rx_bytes, m.TrafficUsage.tx_bytes).where(
                m.TrafficUsage.server_id == server_id,
                cond,
                m.TrafficUsage.period_start == ps,
            )
        )
    ).first()
    return (int(row[0]), int(row[1])) if row else (0, 0)


async def add_period_usage(
    session: Any, server_id: str, ps: float, by_user: dict[str | None, tuple[int, int]], now: float
) -> None:
    """Инкремент накопителя за период ps. by_user: {user_id|None: (rx_delta, tx_delta)}.

    Атомарный upsert: сперва инкрементим существующую строку одним UPDATE (SET x = x + delta — без
    read-modify-write гонок); если строки нет — INSERT в savepoint, а при гонке (параллельный тик уже
    вставил строку → IntegrityError по traffic_usage_uq) откатываем savepoint и повторяем инкремент.
    Портируемо на SQLite (тесты) и Postgres (прод).
    """
    for uid, (rx, tx) in by_user.items():
        if not rx and not tx:
            continue
        cond = m.TrafficUsage.user_id.is_(None) if uid is None else m.TrafficUsage.user_id == uid
        bump = (
            sa_update(m.TrafficUsage)
            .where(m.TrafficUsage.server_id == server_id, cond, m.TrafficUsage.period_start == ps)
            .values(
                rx_bytes=m.TrafficUsage.rx_bytes + rx,
                tx_bytes=m.TrafficUsage.tx_bytes + tx,
                updated_at=now,
            )
        )
        res = await session.execute(bump)
        if (res.rowcount or 0) > 0:
            continue  # строка была — атомарно инкрементнули (без read-modify-write гонок)
        try:  # строки нет — вставляем; savepoint изолирует возможный IntegrityError от гонки
            async with session.begin_nested():
                session.add(
                    m.TrafficUsage(
                        server_id=server_id, user_id=uid, period_start=ps, rx_bytes=rx, tx_bytes=tx, updated_at=now
                    )
                )
        except IntegrityError:
            await session.execute(bump)  # параллельный тик успел вставить — просто инкрементим
