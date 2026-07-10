"""Авторизация: регистрация, вход, сессии, bootstrap первого админа."""

from __future__ import annotations

import contextlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from vpnhub.api.config import Settings
from vpnhub.common.serializers import session_to_dict
from vpnhub.core import audit_types
from vpnhub.core.errors import BadRequest, NotFound, Unauthorized
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.security import (
    hash_password,
    hash_token,
    is_valid_phone,
    new_session_token,
    normalize_phone,
    validate_password,
    verify_password,
)
from vpnhub.infra.uow import Uow, UowTransaction

_SEEN_THROTTLE = 60  # не чаще раза в минуту обновляем «последняя активность» сессии

# Заглушка-хеш для входа постоянного времени: argon2-verify прогоняется даже когда телефон
# не найден — иначе по времени ответа отличить «нет такого телефона» от «неверный пароль».
_DUMMY_PASSWORD_HASH = hash_password("vpnhub-timing-equalizer")


@dataclass
class Identity:
    kind: str  # admin|user
    id: str
    name: str
    phone: str
    role: str  # owner|member (для user → member; admin → owner)


class AuthService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    async def setup_needed(self) -> bool:
        async with self.uow.query() as tx:
            return (await tx.admins.count()) == 0 and not self.settings.admin_phone

    async def create_first_admin(
        self, name: str, phone: str, password: str, password2: str = "", *, ip: str | None = None, ua: str | None = None
    ) -> str:
        np = normalize_phone(phone)
        if not name or not np or not password:
            raise BadRequest("Заполните имя, телефон и пароль")
        if not is_valid_phone(phone):
            raise BadRequest("Введите корректный номер телефона")
        validate_password(password)
        if password != password2:
            raise BadRequest("Пароли не совпадают")
        async with self.uow.transaction() as tx:
            if (await tx.admins.count()) > 0:
                raise BadRequest("Администратор уже создан")
            if await tx.users.by_phone(np):
                raise BadRequest("Этот номер уже зарегистрирован")
            # админ — это обычный пользователь + запись-признак в admins
            user = m.User(phone=np, name=name, password_hash=hash_password(password), status="active")
            tx.users.add(user)
            await tx.session.flush()
            tx.admins.add(m.Admin(user_id=user.id))
            return await self._make_session(tx, "admin", user.id, ip, ua)

    async def register(self, name: str, phone: str, password: str, password2: str) -> None:
        np = normalize_phone(phone)
        if not name or not np or not password:
            raise BadRequest("Заполните имя, телефон и пароль")
        if not is_valid_phone(phone):
            raise BadRequest("Введите корректный номер телефона")
        validate_password(password)
        if password != password2:
            raise BadRequest("Пароли не совпадают")
        async with self.uow.transaction() as tx:
            # админы тоже лежат в users, так что одной проверки достаточно
            if await tx.users.by_phone(np):
                raise BadRequest("Этот номер уже зарегистрирован")
            user = m.User(phone=np, name=name, password_hash=hash_password(password), status="pending")
            tx.users.add(user)
            await tx.session.flush()
            # приглашённого владельцем подтверждать не нужно — сразу активен
            if await self._bind_invites(tx, user):
                user.status = "active"

    async def login(self, phone: str, password: str, *, ip: str | None = None, ua: str | None = None) -> str:
        np = normalize_phone(phone)
        if not np or not password:
            raise BadRequest("Введите телефон и пароль")
        async with self.uow.transaction() as tx:
            user = await tx.users.by_phone(np)
            # verify() всегда, даже без пользователя (заглушка-хеш) → постоянное время ответа.
            password_ok = verify_password(user.password_hash if user else _DUMMY_PASSWORD_HASH, password)
            if not user or not password_ok:
                raise Unauthorized("Неверный телефон или пароль")
            if await tx.admins.is_admin(user.id):
                token = await self._make_session(tx, "admin", user.id, ip, ua)
                self._audit_login(tx, "admin", user, ip)
                return token
            if user.status == "blocked":
                raise Unauthorized("Аккаунт заблокирован. Обратитесь к администратору.")
            # подхватить приглашения, появившиеся уже после регистрации
            if user.status == "pending" and await self._bind_invites(tx, user):
                user.status = "active"
            if user.status == "pending":
                raise Unauthorized("Аккаунт ожидает подтверждения администратора.")
            token = await self._make_session(tx, "user", user.id, ip, ua)
            self._audit_login(tx, "user", user, ip)
            return token

    @staticmethod
    def _audit_login(tx: UowTransaction, kind: str, user: m.User, ip: str | None) -> None:
        """Записать событие входа в той же транзакции (актор = сам пользователь)."""
        # actor_id == user.id → owner увидит собственные login-события даже без owner_user_id
        tx.audit.add_event(
            at=time.time(),
            actor_kind=kind,
            actor_id=user.id,
            actor_name=user.name,
            type_=audit_types.AUTH_LOGIN,
            meta_json=json.dumps({"ip": ip}, ensure_ascii=False) if ip else None,
        )

    async def _bind_invites(self, tx: UowTransaction, user: m.User) -> bool:
        """Привязать приглашённых участников (по телефону) к пользователю и активировать их."""
        matched = False
        for mb in await tx.groups.members_by_phone(normalize_phone(user.phone)):
            mb.user_id = user.id
            mb.status = "active"
            matched = True
        return matched

    async def _make_session(
        self, tx: UowTransaction, kind: str, subject_id: str, ip: str | None = None, ua: str | None = None
    ) -> str:
        token = new_session_token()
        expires = time.time() + self.settings.session_ttl_days * 86400
        tx.sessions.add(
            m.Session(
                id=hash_token(token),
                subject_kind=kind,
                subject_id=subject_id,
                expires_at=expires,
                ip=ip,
                user_agent=(ua or "")[:500] or None,
            )
        )
        return token

    def _touch(self, sess: m.Session) -> None:
        """Обновить «последняя активность» сессии (throttled), не роняя запрос при сбое."""
        with contextlib.suppress(Exception):
            if not sess.updated_at or time.time() - sess.updated_at.timestamp() > _SEEN_THROTTLE:
                sess.updated_at = datetime.now(UTC)

    async def resolve(self, token: str | None) -> Identity | None:
        if not token:
            return None
        async with self.uow.transaction() as tx:
            sess = await tx.sessions.get(hash_token(token))
            if not sess or sess.expires_at < time.time():
                return None
            self._touch(sess)
            if sess.subject_kind == "admin":
                admin = await tx.admins.get(sess.subject_id)
                if not admin or not admin.user:
                    return None
                u = admin.user
                return Identity("admin", u.id, u.name, u.phone, "owner")
            user = await tx.users.get(sess.subject_id)
            if not user or user.status != "active":
                return None
            return Identity("user", user.id, user.name, user.phone, "member")

    async def logout(self, token: str | None) -> None:
        if not token:
            return
        async with self.uow.transaction() as tx:
            sess = await tx.sessions.get(hash_token(token))
            if sess:
                await tx.session.delete(sess)

    # ---- управление сессиями (устройствами) ----

    async def list_sessions(self, token: str | None, subject_id: str) -> list[dict]:
        current_id = hash_token(token) if token else ""
        async with self.uow.query() as tx:
            rows = await tx.sessions.for_subject(subject_id)
            return [session_to_dict(s, s.id == current_id) for s in rows if s.expires_at >= time.time()]

    async def revoke_session(self, token: str | None, subject_id: str, session_id: str) -> None:
        async with self.uow.transaction() as tx:
            sess = await tx.sessions.get(session_id)
            if not sess or sess.subject_id != subject_id:
                raise NotFound("Сессия не найдена")
            await tx.session.delete(sess)

    async def revoke_others(self, token: str | None, subject_id: str) -> int:
        current_id = hash_token(token) if token else None
        async with self.uow.transaction() as tx:
            return await tx.sessions.delete_for_subject(subject_id, except_id=current_id)

    async def change_password(self, user_id: str, current_password: str, new_password: str, token: str | None) -> None:
        """Смена пароля самим пользователем: проверяем старый, применяем политику, гасим прочие сессии."""
        validate_password(new_password)
        async with self.uow.transaction() as tx:
            user = await tx.users.get(user_id)
            if not user or not verify_password(user.password_hash, current_password):
                raise BadRequest("Текущий пароль неверен")
            user.password_hash = hash_password(new_password)
            # оставляем только текущую сессию
            await tx.sessions.delete_for_subject(user_id, except_id=hash_token(token) if token else None)
