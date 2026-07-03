"""Репозитории доступа к данным (тонкие, на AsyncSession)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import delete as sa_delete
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from vpnhub.infra.db.orm import models as m
from vpnhub.infra.security import normalize_phone


class _Repo:
    model: type[Any]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get(self, id_: str) -> Any:
        return await self.session.get(self.model, id_)

    async def all(self) -> list[Any]:
        res = await self.session.execute(select(self.model))
        return list(res.scalars().all())

    def add(self, obj: Any) -> Any:
        self.session.add(obj)
        return obj

    async def delete(self, obj: Any) -> None:
        await self.session.delete(obj)


class AdminRepo(_Repo):
    model = m.Admin

    async def is_admin(self, user_id: str) -> bool:
        return (await self.session.get(m.Admin, user_id)) is not None

    async def user_ids(self) -> list[str]:
        res = await self.session.execute(select(m.Admin.user_id))
        return [r[0] for r in res.all()]

    async def count(self) -> int:
        res = await self.session.execute(select(func.count()).select_from(m.Admin))
        return int(res.scalar_one())


class UserRepo(_Repo):
    model = m.User

    async def by_phone(self, phone: str) -> m.User | None:
        res = await self.session.execute(select(m.User).where(m.User.phone == normalize_phone(phone)))
        return res.scalar_one_or_none()


class SessionRepo(_Repo):
    model = m.Session

    async def for_subject(self, subject_id: str) -> list[m.Session]:
        res = await self.session.execute(
            select(m.Session).where(m.Session.subject_id == subject_id).order_by(m.Session.created_at.desc())
        )
        return list(res.scalars().all())

    async def delete_for_subject(self, subject_id: str, except_id: str | None = None) -> int:
        stmt = sa_delete(m.Session).where(m.Session.subject_id == subject_id)
        if except_id is not None:
            stmt = stmt.where(m.Session.id != except_id)
        res = await self.session.execute(stmt)
        return int(res.rowcount or 0)  # type: ignore[attr-defined]


class ServerRepo(_Repo):
    model = m.Server

    async def for_owner(self, owner_id: str) -> list[m.Server]:
        res = await self.session.execute(
            select(m.Server).where(m.Server.owner_user_id == owner_id).order_by(m.Server.created_at)
        )
        return list(res.scalars().all())


class PoolRepo(_Repo):
    model = m.Pool

    async def for_owner(self, owner_id: str) -> list[m.Pool]:
        res = await self.session.execute(select(m.Pool).where(m.Pool.owner_user_id == owner_id))
        return list(res.scalars().all())

    async def server_ids(self, pool_id: str) -> list[str]:
        res = await self.session.execute(select(m.PoolServer.server_id).where(m.PoolServer.pool_id == pool_id))
        return [r[0] for r in res.all()]

    async def set_servers(self, pool_id: str, server_ids: list[str]) -> None:
        await self.session.execute(sa_delete(m.PoolServer).where(m.PoolServer.pool_id == pool_id))
        for sid in server_ids:
            self.session.add(m.PoolServer(pool_id=pool_id, server_id=sid))

    async def pools_with_server(self, server_id: str) -> list[str]:
        res = await self.session.execute(select(m.PoolServer.pool_id).where(m.PoolServer.server_id == server_id))
        return [r[0] for r in res.all()]


class GroupRepo(_Repo):
    model = m.Group

    async def for_owner(self, owner_id: str) -> list[m.Group]:
        res = await self.session.execute(select(m.Group).where(m.Group.owner_user_id == owner_id))
        return list(res.scalars().all())

    async def by_token(self, token: str) -> m.Group | None:
        res = await self.session.execute(select(m.Group).where(m.Group.token == token))
        return res.scalar_one_or_none()

    async def pool_ids(self, group_id: str) -> list[str]:
        res = await self.session.execute(
            select(m.GroupPoolAccess.pool_id).where(m.GroupPoolAccess.group_id == group_id)
        )
        return [r[0] for r in res.all()]

    async def server_access(self, group_id: str) -> dict[str, list[str]]:
        res = await self.session.execute(
            select(m.GroupServerAccess.server_id, m.GroupServerAccess.vpn_type).where(
                m.GroupServerAccess.group_id == group_id
            )
        )
        out: dict[str, list[str]] = {}
        for sid, vt in res.all():
            out.setdefault(sid, []).append(vt)
        return out

    async def toggle_pool(self, group_id: str, pool_id: str) -> None:
        res = await self.session.execute(
            select(m.GroupPoolAccess).where(
                m.GroupPoolAccess.group_id == group_id, m.GroupPoolAccess.pool_id == pool_id
            )
        )
        row = res.scalar_one_or_none()
        if row:
            await self.session.delete(row)
        else:
            self.session.add(m.GroupPoolAccess(group_id=group_id, pool_id=pool_id))

    async def set_server_vpns(self, group_id: str, server_id: str, vpn_types: list[str]) -> None:
        await self.session.execute(
            sa_delete(m.GroupServerAccess).where(
                m.GroupServerAccess.group_id == group_id,
                m.GroupServerAccess.server_id == server_id,
            )
        )
        for vt in vpn_types:
            self.session.add(m.GroupServerAccess(group_id=group_id, server_id=server_id, vpn_type=vt))

    async def groups_for_user(self, user_id: str) -> list[m.Group]:
        res = await self.session.execute(
            select(m.Group)
            .join(m.GroupMember, m.GroupMember.group_id == m.Group.id)
            .where(m.GroupMember.user_id == user_id, m.GroupMember.status == "active")
        )
        return list(res.scalars().unique().all())

    async def members_by_phone(self, phone: str) -> list[m.GroupMember]:
        res = await self.session.execute(
            select(m.GroupMember).where(m.GroupMember.phone == phone, m.GroupMember.status == "invited")
        )
        return list(res.scalars().all())

    async def member(self, member_id: str) -> m.GroupMember | None:
        return await self.session.get(m.GroupMember, member_id)


class DeviceRepo(_Repo):
    model = m.Device

    async def for_user(self, user_id: str) -> list[m.Device]:
        res = await self.session.execute(select(m.Device).where(m.Device.user_id == user_id))
        return list(res.scalars().all())


class SettingRepo(_Repo):
    model = m.Setting

    async def get_value(self, key: str) -> str | None:
        row = await self.session.get(m.Setting, key)
        return row.value if row else None

    async def set_value(self, key: str, value: str) -> None:
        row = await self.session.get(m.Setting, key)
        if row:
            row.value = value
        else:
            self.session.add(m.Setting(key=key, value=value))
