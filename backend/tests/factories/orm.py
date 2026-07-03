"""Фабрики ORM-строк для интеграционных тестов.

`seed(session_maker)` — контекст, который открывает сессию, отдаёт её билдерам и
коммитит на выходе (сервис-под-тестом откроет уже свою транзакцию и увидит данные).
Билдеры делают add + flush, поэтому сгенерированные id доступны сразу.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from vpnhub.infra.db.orm import models as m
from vpnhub.infra.security import hash_password, hash_token, normalize_phone


@asynccontextmanager
async def seed(session_maker: async_sessionmaker[AsyncSession]) -> AsyncIterator[AsyncSession]:
    """Открыть сессию для наполнения БД; коммит + закрытие на выходе из блока."""
    async with session_maker() as session:
        yield session
        await session.commit()


async def make_user(
    session: AsyncSession,
    *,
    phone: str = "+79001112233",
    name: str = "Иван",
    password: str = "Passw0rd!",
    status: str = "active",
    admin: bool = False,
) -> m.User:
    """Пользователь (нормализованный телефон). admin=True — плюс запись в admins."""
    user = m.User(phone=normalize_phone(phone), name=name, password_hash=hash_password(password), status=status)
    session.add(user)
    await session.flush()
    if admin:
        session.add(m.Admin(user_id=user.id))
        await session.flush()
    return user


async def make_session_row(
    session: AsyncSession,
    *,
    token: str,
    subject_kind: str,
    subject_id: str,
    ttl_seconds: float = 86400.0,
) -> m.Session:
    """Строка сессии (id = hash токена, как в проде)."""
    row = m.Session(
        id=hash_token(token),
        subject_kind=subject_kind,
        subject_id=subject_id,
        expires_at=time.time() + ttl_seconds,
    )
    session.add(row)
    await session.flush()
    return row


async def make_server(
    session: AsyncSession,
    *,
    owner_id: str,
    name: str = "srv",
    ip: str = "203.0.113.10",
    status: str = "unknown",
    installed_vpns: tuple[str, ...] = (),
) -> m.Server:
    """Сервер владельца; installed_vpns — типы VPN, помеченные installed=True."""
    server = m.Server(owner_user_id=owner_id, name=name, provider="Другой", ip=ip, status=status)
    for vtype in installed_vpns:
        server.vpns.append(m.ServerVpn(type=vtype, installed=True, running=True, port="51820"))
    session.add(server)
    await session.flush()
    return server


async def make_pool(
    session: AsyncSession, *, owner_id: str, name: str = "Пул", server_ids: tuple[str, ...] = ()
) -> m.Pool:
    pool = m.Pool(owner_user_id=owner_id, name=name)
    session.add(pool)
    await session.flush()
    for sid in server_ids:
        session.add(m.PoolServer(pool_id=pool.id, server_id=sid))
    await session.flush()
    return pool


async def make_group(session: AsyncSession, *, owner_id: str, name: str = "Семья", token: str = "grp-test") -> m.Group:
    group = m.Group(owner_user_id=owner_id, name=name, token=token)
    session.add(group)
    await session.flush()
    return group


async def add_member(
    session: AsyncSession,
    *,
    group_id: str,
    display_name: str = "Гость",
    user_id: str | None = None,
    phone: str | None = None,
    role: str = "member",
    status: str = "active",
) -> m.GroupMember:
    member = m.GroupMember(
        group_id=group_id,
        user_id=user_id,
        display_name=display_name,
        phone=normalize_phone(phone) if phone else None,
        role=role,
        status=status,
    )
    session.add(member)
    await session.flush()
    return member


async def grant_group_server(session: AsyncSession, *, group_id: str, server_id: str, vpn_type: str) -> None:
    session.add(m.GroupServerAccess(group_id=group_id, server_id=server_id, vpn_type=vpn_type))
    await session.flush()


async def grant_group_pool(session: AsyncSession, *, group_id: str, pool_id: str) -> None:
    session.add(m.GroupPoolAccess(group_id=group_id, pool_id=pool_id))
    await session.flush()


async def make_device(session: AsyncSession, *, user_id: str, name: str = "iPhone", platform: str = "ios") -> m.Device:
    device = m.Device(user_id=user_id, name=name, platform=platform)
    session.add(device)
    await session.flush()
    return device


async def make_server_protocol(
    session: AsyncSession,
    *,
    server_id: str,
    proto: str,
    vendor: str = "amnezia",
    container: str = "",
    port: str = "",
    state: str = "absent",
    installed: bool = False,
    running: bool = False,
    external_clients: int = 0,
    material_encrypted: str | None = None,
    params_json: str | None = None,
    pending_revoke_json: str | None = None,
) -> m.ServerProtocol:
    """Строка ServerProtocol (один протокол-контейнер на сервере)."""
    sp = m.ServerProtocol(
        server_id=server_id,
        vendor=vendor,
        proto=proto,
        container=container,
        port=port,
        state=state,
        installed=installed,
        running=running,
        external_clients=external_clients,
        material_encrypted=material_encrypted,
        params_json=params_json,
        pending_revoke_json=pending_revoke_json,
    )
    session.add(sp)
    await session.flush()
    return sp


async def make_device_config(
    session: AsyncSession,
    *,
    device_id: str,
    server_id: str,
    vpn_type: str,
    proto: str | None = None,
    status: str = "active",
    client_id: str | None = None,
    client_ip: str | None = None,
) -> m.DeviceConfig:
    """Строка DeviceConfig (выданный на устройство конфиг)."""
    cfg = m.DeviceConfig(
        device_id=device_id,
        server_id=server_id,
        vpn_type=vpn_type,
        proto=proto,
        status=status,
        client_id=client_id,
        client_ip=client_ip,
    )
    session.add(cfg)
    await session.flush()
    return cfg
