"""Интеграционные тесты сервиса bootstrap: ensure_bootstrap_admin и normalize_user_phones."""

from __future__ import annotations

import pytest

from tests.conftest import TEST_SECRET_KEY
from tests.factories.orm import make_user, seed
from vpnhub.api.config import Settings
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.security import normalize_phone
from vpnhub.services.bootstrap import ensure_bootstrap_admin, normalize_user_phones

pytestmark = pytest.mark.integration


def _admin_settings(*, phone: str = "+79001112233", password: str = "Passw0rd!") -> Settings:
    """Settings с заданными admin_phone/admin_password (без чтения env/.env)."""
    return Settings(_env_file=None, admin_phone=phone, admin_password=password, secret_key=TEST_SECRET_KEY)


async def test__ensure_bootstrap_admin__no_env_credentials__does_nothing(uow, settings):
    """Без admin_phone/admin_password (settings по умолчанию) — админ не создаётся (no-op)."""
    # Arrange: пустая БД, ничего не сидим; settings по умолчанию имеет admin_phone=None

    # Act
    await ensure_bootstrap_admin(uow, settings)

    # Assert
    async with uow.transaction() as tx:
        assert await tx.admins.count() == 0
        assert await tx.users.all() == []


async def test__ensure_bootstrap_admin__env_credentials__creates_admin_user(uow):
    """С заданными admin_phone/admin_password создаётся пользователь-администратор."""
    # Arrange
    cfg = _admin_settings(phone="+79001112233", password="Passw0rd!")

    # Act
    await ensure_bootstrap_admin(uow, cfg)

    # Assert
    async with uow.transaction() as tx:
        user = await tx.users.by_phone("+79001112233")
        assert user is not None
        assert user.phone == normalize_phone("+79001112233")
        assert user.status == "active"
        assert await tx.admins.is_admin(user.id) is True
        assert await tx.admins.count() == 1


async def test__ensure_bootstrap_admin__called_twice__is_idempotent(uow):
    """Повторный вызов с теми же кредами не дублирует ни пользователя, ни запись admin."""
    # Arrange
    cfg = _admin_settings(phone="+79001112233", password="Passw0rd!")
    await ensure_bootstrap_admin(uow, cfg)

    # Act
    await ensure_bootstrap_admin(uow, cfg)

    # Assert
    async with uow.transaction() as tx:
        users = await tx.users.all()
        assert len(users) == 1
        assert await tx.admins.count() == 1


async def test__ensure_bootstrap_admin__existing_user__promotes_to_admin(uow, session_maker):
    """Если пользователь с таким телефоном уже есть — он просто становится администратором."""
    # Arrange
    async with seed(session_maker) as s:
        existing = await make_user(s, phone="+79001112233", name="Иван", admin=False)
    existing_id = existing.id
    cfg = _admin_settings(phone="+79001112233", password="Passw0rd!")

    # Act
    await ensure_bootstrap_admin(uow, cfg)

    # Assert
    async with uow.transaction() as tx:
        users = await tx.users.all()
        assert len(users) == 1  # новый пользователь не заведён
        assert users[0].id == existing_id
        assert users[0].name == "Иван"  # существующие данные не перезаписаны
        assert await tx.admins.is_admin(existing_id) is True


async def test__normalize_user_phones__raw_phone__normalized_in_db(uow, session_maker):
    """«Сырой» телефон приводится к нормализованному виду и находится по by_phone."""
    # Arrange: явно вставляем пользователя с сырым телефоном (не через make_user — тот нормализует)
    async with seed(session_maker) as s:
        raw = m.User(phone="8 900 111 22 33", name="Иван", password_hash="x", status="active")
        s.add(raw)
        await s.flush()
        raw_id = raw.id
    async with uow.transaction() as tx:
        assert await tx.users.by_phone("+79001112233") is None  # до нормализации не находится

    # Act
    await normalize_user_phones(uow)

    # Assert
    async with uow.transaction() as tx:
        found = await tx.users.by_phone("+79001112233")
        assert found is not None
        assert found.id == raw_id
        assert found.phone == "+79001112233"


async def test__normalize_user_phones__conflicting_phone__skips_conflicting(uow, session_maker):
    """Конфликт: сырой телефон нормализуется в уже занятый — конфликтующего пропускаем (телефон не меняем)."""
    # Arrange: один уже нормализован, другой — сырой, нормализуемый в тот же номер
    async with seed(session_maker) as s:
        normalized = m.User(phone="+79001112233", name="Норм", password_hash="x", status="active")
        conflicting = m.User(phone="8 900 111 22 33", name="Сырой", password_hash="x", status="active")
        s.add(normalized)
        s.add(conflicting)
        await s.flush()
        normalized_id = normalized.id
        conflicting_id = conflicting.id

    # Act
    await normalize_user_phones(uow)

    # Assert
    async with uow.transaction() as tx:
        norm = await tx.users.get(normalized_id)
        conflict = await tx.users.get(conflicting_id)
        assert norm.phone == "+79001112233"  # нормализованный не тронут
        assert conflict.phone == "8 900 111 22 33"  # конфликтующий пропущен, остался сырым


async def test__normalize_user_phones__already_normalized__no_change(uow, session_maker):
    """Уже нормализованные телефоны остаются без изменений (norm == phone → пропуск)."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79001112233")
        user_id = user.id

    # Act
    await normalize_user_phones(uow)

    # Assert
    async with uow.transaction() as tx:
        found = await tx.users.get(user_id)
        assert found.phone == "+79001112233"
