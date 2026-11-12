"""Группы, участники, доступы."""

from __future__ import annotations

import builtins
import json
import time

from vpnhub.api.config import Settings
from vpnhub.common.serializers import group_to_dict
from vpnhub.core import audit_types
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.security import format_phone, gen_token, mask_phone, normalize_phone
from vpnhub.infra.uow import Uow, UowTransaction
from vpnhub.services.provisioning import ProvisioningService

CANDIDATES_LIMIT = 50
_ROLES = ("admin", "member")


def _already_in_group(g: m.Group, user: m.User) -> bool:
    """Пользователь уже в группе: привязан по user_id или висит приглашением на его телефон."""
    phone = normalize_phone(user.phone)
    return any(mb.user_id == user.id or (phone and mb.phone == phone) for mb in g.members)


class GroupService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    def _prov(self) -> ProvisioningService:
        return ProvisioningService(self.uow, self.settings)

    async def _ser(self, tx: UowTransaction, g: m.Group) -> dict:
        pools = await tx.groups.pool_ids(g.id)
        servers = await tx.groups.server_access(g.id)
        return group_to_dict(g, pools, servers)

    async def _owned(self, tx: UowTransaction, owner_id: str, gid: str) -> m.Group:
        g: m.Group | None = await tx.groups.get(gid)
        if not g or g.owner_user_id != owner_id:
            raise NotFound(key="group.not_found")
        return g

    async def list(self, owner_id: str) -> list[dict]:
        async with self.uow.query() as tx:
            return [await self._ser(tx, g) for g in await tx.groups.for_owner(owner_id)]

    async def get(self, owner_id: str, gid: str) -> dict:
        async with self.uow.query() as tx:
            return await self._ser(tx, await self._owned(tx, owner_id, gid))

    async def create(self, owner_id: str, owner_name: str, name: str) -> dict:
        if not name:
            raise BadRequest(key="group.name_required")
        async with self.uow.transaction() as tx:
            g = m.Group(owner_user_id=owner_id, name=name, token=gen_token("grp"))
            tx.groups.add(g)
            await tx.session.flush()
            tx.session.add(
                m.GroupMember(
                    group_id=g.id,
                    user_id=owner_id,
                    display_name=f"{owner_name} (вы)",
                    role="admin",
                    status="active",
                )
            )
            await tx.session.flush()
            await tx.session.refresh(g)
            return await self._ser(tx, g)

    async def update(self, owner_id: str, gid: str, name: str) -> dict:
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            if name:
                g.name = name
            await tx.session.flush()
            await tx.session.refresh(g)
            return await self._ser(tx, g)

    async def set_group_limit(self, owner_id: str, gid: str, max_devices: int | None) -> dict:
        """Override лимита устройств для участников группы (None/≤0 — снять, наследовать глобал)."""
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            g.max_devices = max_devices if (max_devices is not None and max_devices > 0) else None
            await tx.session.flush()
            await tx.session.refresh(g)
            return await self._ser(tx, g)

    async def set_member_limit(self, owner_id: str, gid: str, mid: str, max_devices: int | None) -> dict:
        """Персональный override лимита устройств участника (None/≤0 — снять, наследовать группу/глобал)."""
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            mb = next((x for x in g.members if x.id == mid), None)
            if mb is None:
                raise NotFound(key="group.member_not_found")
            mb.max_devices = max_devices if (max_devices is not None and max_devices > 0) else None
            await tx.session.flush()
            await tx.session.refresh(g)
            return await self._ser(tx, g)

    async def set_group_bytes(self, owner_id: str, gid: str, max_bytes: int | None) -> dict:
        """Override лимита трафика (байт per user/сервер за период) для участников группы (None/≤0 — снять)."""
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            g.max_bytes = max_bytes if (max_bytes is not None and max_bytes > 0) else None
            await tx.session.flush()
            await tx.session.refresh(g)
            return await self._ser(tx, g)

    async def set_member_bytes(self, owner_id: str, gid: str, mid: str, max_bytes: int | None) -> dict:
        """Персональный override лимита трафика участника (None/≤0 — снять, наследовать группу/глобал)."""
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            mb = next((x for x in g.members if x.id == mid), None)
            if mb is None:
                raise NotFound(key="group.member_not_found")
            mb.max_bytes = max_bytes if (max_bytes is not None and max_bytes > 0) else None
            await tx.session.flush()
            await tx.session.refresh(g)
            return await self._ser(tx, g)

    async def delete(self, owner_id: str, gid: str) -> None:
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            member_ids = [mb.user_id for mb in g.members if mb.user_id]
            await tx.session.delete(g)
        await self._prov().reconcile_users(member_ids)

    async def regen_token(self, owner_id: str, gid: str) -> dict:
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            g.token = gen_token("grp")
            await tx.session.flush()
            await tx.session.refresh(g)
            return await self._ser(tx, g)

    # ---- участники ----

    async def _eligible_users(
        self, tx: UowTransaction, owner_id: str, g: m.Group, *, is_admin: bool
    ) -> builtins.list[m.User]:
        """Кого владелец может добавить в группу из уже зарегистрированных.

        Админ панели видит всех активных пользователей. Обычный владелец группы — только тех,
        с кем уже состоит в общей группе: иначе любой пользователь получил бы справочник всех
        телефонов панели. Уже состоящие в группе (и приглашённые на их телефон) исключаются.
        """
        users = await tx.users.active(None if is_admin else await tx.groups.known_user_ids(owner_id))
        return [u for u in users if not _already_in_group(g, u)]

    async def candidates(self, owner_id: str, gid: str, q: str = "", *, is_admin: bool) -> builtins.list[dict]:
        """Список пользователей для выбора в диалоге «Добавить участника».

        Телефоны админ видит целиком, остальные — маскированными. Поиск: по имени, а у админа
        ещё и по цифрам телефона (по маске искать бессмысленно, а по полному номеру — утечка).
        """
        needle = (q or "").strip().casefold()
        digits = "".join(ch for ch in needle if ch.isdigit())
        async with self.uow.query() as tx:
            g = await self._owned(tx, owner_id, gid)
            users = await self._eligible_users(tx, owner_id, g, is_admin=is_admin)
        if needle:
            users = [
                u
                for u in users
                if needle in u.name.casefold() or (is_admin and digits and digits in normalize_phone(u.phone))
            ]
        users.sort(key=lambda u: (u.name.casefold(), u.phone))
        return [
            {"id": u.id, "name": u.name, "phone": format_phone(u.phone) if is_admin else mask_phone(u.phone)}
            for u in users[:CANDIDATES_LIMIT]
        ]

    async def add_user(self, owner_id: str, gid: str, user_id: str, role: str, *, is_admin: bool) -> dict:
        """Добавить в группу уже зарегистрированного пользователя (выбор из списка кандидатов)."""
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            user: m.User | None = await tx.users.get(user_id)
            if user and _already_in_group(g, user):
                raise BadRequest(key="group.member_already_added")
            # повторная проверка на сервере: id приходит от клиента, добавить можно только кандидата
            if not user or user.id not in {
                u.id for u in await self._eligible_users(tx, owner_id, g, is_admin=is_admin)
            }:
                raise NotFound(key="group.user_not_found")
            tx.session.add(
                m.GroupMember(
                    group_id=g.id,
                    user_id=user.id,
                    display_name=user.name,
                    role=role if role in _ROLES else "member",
                    status="active",
                    phone=normalize_phone(user.phone) or None,
                )
            )
            await tx.session.flush()
            await tx.session.refresh(g)
            return await self._ser(tx, g)

    async def add_member(self, owner_id: str, gid: str, name: str, role: str, phone: str | None) -> dict:
        if not name:
            raise BadRequest(key="group.member_name_required")
        np = normalize_phone(phone) if phone else None
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            # если телефон уже принадлежит зарегистрированному пользователю — сразу активный участник
            # с доступом; если пользователя ещё нет — «приглашён» (привяжется при регистрации/входе)
            user = await tx.users.by_phone(np) if np else None
            if (user and _already_in_group(g, user)) or (np and any(mb.phone == np for mb in g.members)):
                raise BadRequest(key="group.member_already_added")
            status = "active" if (user or not np) else "invited"
            tx.session.add(
                m.GroupMember(
                    group_id=g.id,
                    user_id=user.id if user else None,
                    display_name=name,
                    role=role or "member",
                    status=status,
                    phone=np,
                )
            )
            await tx.session.flush()
            await tx.session.refresh(g)
            return await self._ser(tx, g)

    # ---- присоединение по инвайт-ссылке ----

    async def peek_by_token(self, token: str) -> dict:
        """Публичная карточка приглашения (что за группа) — для экрана присоединения."""
        async with self.uow.query() as tx:
            g = await tx.groups.by_token(token)
            if not g:
                raise NotFound(key="group.invite_invalid")
            owner = await tx.users.get(g.owner_user_id)
            return {
                "id": g.id,
                "name": g.name,
                "ownerName": owner.name if owner else "",
                "memberCount": sum(1 for mb in g.members if mb.status == "active"),
            }

    async def join(self, user_id: str, user_name: str, token: str) -> dict:
        async with self.uow.transaction() as tx:
            g = await tx.groups.by_token(token)
            if not g:
                raise NotFound(key="group.invite_invalid")
            existing = next((mb for mb in g.members if mb.user_id == user_id), None)
            if existing:
                existing.status = "active"
            else:
                user = await tx.users.get(user_id)
                np = normalize_phone(user.phone) if user else None
                invited = next((mb for mb in g.members if mb.user_id is None and np and mb.phone == np), None)
                if invited:
                    invited.user_id = user_id
                    invited.status = "active"
                    if not invited.display_name:
                        invited.display_name = user_name
                else:
                    tx.session.add(
                        m.GroupMember(
                            group_id=g.id,
                            user_id=user_id,
                            display_name=user_name,
                            role="member",
                            status="active",
                            phone=np,
                        )
                    )
            await tx.session.flush()
            tx.audit.add_event(
                at=time.time(),
                actor_kind="user",
                actor_id=user_id,
                actor_name=user_name,
                type_=audit_types.GROUP_JOIN,
                target_kind="group",
                target_id=g.id,
                owner_user_id=g.owner_user_id,
                meta_json=json.dumps({"group": g.name}, ensure_ascii=False),
            )
            return {"id": g.id, "name": g.name, "ok": True}

    async def toggle_member_role(self, owner_id: str, gid: str, mid: str) -> dict:
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            mb = await tx.groups.member(mid)
            if not mb or mb.group_id != gid:
                raise NotFound(key="group.member_not_found")
            mb.role = "member" if mb.role == "admin" else "admin"
            await tx.session.flush()
            await tx.session.refresh(g)
            return await self._ser(tx, g)

    async def remove_member(self, owner_id: str, gid: str, mid: str) -> dict:
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            mb = await tx.groups.member(mid)
            removed_uid = None
            if mb and mb.group_id == gid:
                removed_uid = mb.user_id
                await tx.session.delete(mb)
            await tx.session.flush()
            await tx.session.refresh(g)
            result = await self._ser(tx, g)
        if removed_uid:
            await self._prov().reconcile_users([removed_uid])
        return result

    # ---- access ----
    # После сужения доступа reconcile снимает конфиги, к которым юзер потерял доступ.
    # Вызов идемпотентен (при расширении доступа reconcile — no-op), поэтому зовём всегда.
    async def toggle_pool(self, owner_id: str, gid: str, pool_id: str) -> dict:
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            await tx.groups.toggle_pool(gid, pool_id)
            await tx.session.flush()
            await tx.session.refresh(g)
            result = await self._ser(tx, g)
            member_ids = [mb.user_id for mb in g.members if mb.user_id]
        await self._prov().reconcile_users(member_ids)
        return result

    async def toggle_server(self, owner_id: str, gid: str, server_id: str) -> dict:
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            current = await tx.groups.server_access(gid)
            if server_id in current:
                await tx.groups.set_server_vpns(gid, server_id, [])
            else:
                srv = await tx.servers.get(server_id)
                installed = [v.type for v in srv.vpns if v.installed] if srv else []
                await tx.groups.set_server_vpns(gid, server_id, installed)
            await tx.session.flush()
            await tx.session.refresh(g)
            result = await self._ser(tx, g)
            member_ids = [mb.user_id for mb in g.members if mb.user_id]
        await self._prov().reconcile_users(member_ids)
        return result

    async def toggle_server_vpn(self, owner_id: str, gid: str, server_id: str, vtype: str) -> dict:
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            current = await tx.groups.server_access(gid)
            vpns = set(current.get(server_id, []))
            if vtype in vpns:
                vpns.discard(vtype)
            else:
                vpns.add(vtype)
            await tx.groups.set_server_vpns(gid, server_id, list(vpns))
            await tx.session.flush()
            await tx.session.refresh(g)
            result = await self._ser(tx, g)
            member_ids = [mb.user_id for mb in g.members if mb.user_id]
        await self._prov().reconcile_users(member_ids)
        return result
