"""Группы, участники, доступы."""

from __future__ import annotations

from vpnhub.api.config import Settings
from vpnhub.common.serializers import group_to_dict
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.security import gen_token, normalize_phone
from vpnhub.infra.uow import Uow, UowTransaction
from vpnhub.services.provisioning import ProvisioningService


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
            raise NotFound("Группа не найдена")
        return g

    async def list(self, owner_id: str) -> list[dict]:
        async with self.uow.query() as tx:
            return [await self._ser(tx, g) for g in await tx.groups.for_owner(owner_id)]

    async def get(self, owner_id: str, gid: str) -> dict:
        async with self.uow.query() as tx:
            return await self._ser(tx, await self._owned(tx, owner_id, gid))

    async def create(self, owner_id: str, owner_name: str, name: str) -> dict:
        if not name:
            raise BadRequest("Введите название")
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

    async def add_member(self, owner_id: str, gid: str, name: str, role: str, phone: str | None) -> dict:
        if not name:
            raise BadRequest("Введите имя")
        np = normalize_phone(phone) if phone else None
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            # если телефон уже принадлежит зарегистрированному пользователю — сразу активный участник
            # с доступом; если пользователя ещё нет — «приглашён» (привяжется при регистрации/входе)
            user = await tx.users.by_phone(np) if np else None
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
                raise NotFound("Приглашение недействительно или отозвано")
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
                raise NotFound("Приглашение недействительно или отозвано")
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
            return {"id": g.id, "name": g.name, "ok": True}

    async def toggle_member_role(self, owner_id: str, gid: str, mid: str) -> dict:
        async with self.uow.transaction() as tx:
            g = await self._owned(tx, owner_id, gid)
            mb = await tx.groups.member(mid)
            if not mb or mb.group_id != gid:
                raise NotFound("Участник не найден")
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
