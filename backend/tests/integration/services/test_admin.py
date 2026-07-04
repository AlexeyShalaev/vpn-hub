"""Интеграционные тесты AdminService: пользователи, обновления, системная сводка."""

from __future__ import annotations

import json

import pytest
from pytest_lazy_fixtures import lf

import vpnhub.services.admin as admin_mod
from tests.conftest import TEST_SECRET_KEY
from tests.factories.orm import make_session_row, make_user, seed
from vpnhub.api.config import Settings
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.security import hash_token, normalize_phone
from vpnhub.services.admin import _FALLBACK_RELEASES, AdminService
from vpnhub.services.backups import BackupService

pytestmark = pytest.mark.integration


@pytest.fixture
def settings(tmp_path) -> Settings:
    """Настройки с backup_dir на tmp — чтобы BackupService/system() не трогали реальную ФС."""
    return Settings(
        _env_file=None,
        secret_key=TEST_SECRET_KEY,
        master_key=None,
        admin_phone=None,
        session_ttl_days=30,
        monitor_timeout=0.05,
        monitor_concurrency=4,
        backup_dir=str(tmp_path),
        update_feed_url="",  # офлайн в тестах: не ходить в сеть (дефолт продукта — GitHub Releases)
    )


@pytest.fixture
def admin_service(uow, settings) -> AdminService:
    """AdminService с реальным BackupService (тем же uow/settings)."""
    return AdminService(uow, settings, BackupService(uow, settings))


# --- users ---------------------------------------------------------------


async def test__users__mixed_admin_and_regular__marks_isadmin_flag(admin_service, session_maker):
    """Список пользователей помечает isAdmin=True только для записей в admins."""
    # Arrange
    async with seed(session_maker) as s:
        admin = await make_user(s, phone="+79001110001", name="Админ", admin=True)
        regular = await make_user(s, phone="+79001110002", name="Юзер", admin=False)
    # Act
    users = await admin_service.users()
    # Assert
    by_id = {u["id"]: u for u in users}
    assert by_id[admin.id]["isAdmin"] is True
    assert by_id[regular.id]["isAdmin"] is False


async def test__users__serialized_row__exposes_public_fields(admin_service, session_maker):
    """Каждый пользователь сериализуется с ключами id/phone/name/status/isAdmin."""
    # Arrange
    async with seed(session_maker) as s:
        await make_user(s, phone="+79001110003", name="Пётр", status="active")
    # Act
    users = await admin_service.users()
    # Assert
    assert len(users) == 1
    row = users[0]
    assert row["name"] == "Пётр"
    assert row["phone"] == normalize_phone("+79001110003")
    assert row["status"] == "active"
    assert set(row) >= {"id", "phone", "name", "status", "isAdmin"}


# --- update_user: валидация ---------------------------------------------


@pytest.fixture
def empty_name() -> tuple[str, str]:
    """Кейс: пустое имя при валидном телефоне."""
    return "", "+79001112233"


@pytest.fixture
def empty_phone() -> tuple[str, str]:
    """Кейс: пустой телефон при валидном имени."""
    return "Иван", ""


@pytest.mark.parametrize("name_phone", [lf("empty_name"), lf("empty_phone")])
async def test__update_user__blank_name_or_phone__raises_badrequest(admin_service, session_maker, name_phone):
    """Пустое имя или телефон → BadRequest (проверка до обращения к БД)."""
    # Arrange
    name, phone = name_phone
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79002220001")
    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        await admin_service.update_user(user.id, name, phone, "active", None)
    assert exc.value.http_status == 400


async def test__update_user__unknown_user__raises_notfound(admin_service):
    """Несуществующий пользователь → NotFound (404)."""
    # Arrange
    # (никого не сидим — БД пуста)
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        await admin_service.update_user("no-such-id", "Имя", "+79003330001", "active", None)
    assert exc.value.http_status == 404


# --- update_user: успешные сценарии -------------------------------------


async def test__update_user__valid_fields__updates_and_normalizes_phone(admin_service, session_maker):
    """Валидный апдейт меняет name/phone/status и нормализует телефон в БД."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79004440001", name="Старое", status="active")
    # Act
    result = await admin_service.update_user(user.id, "Новое имя", "89004440002", "active", None)
    # Assert
    assert result["name"] == "Новое имя"
    assert result["phone"] == normalize_phone("89004440002")
    async with session_maker() as check:
        fresh = await check.get(m.User, user.id)
        assert fresh.name == "Новое имя"
        assert fresh.phone == normalize_phone("89004440002")


async def test__update_user__status_blocked__kills_all_user_sessions(admin_service, session_maker):
    """status='blocked' немедленно гасит все сессии пользователя."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79005550001")
        await make_session_row(s, token="tok-a", subject_kind="user", subject_id=user.id)
        await make_session_row(s, token="tok-b", subject_kind="user", subject_id=user.id)
    # Act
    await admin_service.update_user(user.id, "Иван", "+79005550001", "blocked", None)
    # Assert
    async with session_maker() as check:
        assert await check.get(m.Session, hash_token("tok-a")) is None
        assert await check.get(m.Session, hash_token("tok-b")) is None
        fresh = await check.get(m.User, user.id)
        assert fresh.status == "blocked"


async def test__update_user__new_password__kills_all_user_sessions(admin_service, session_maker):
    """Смена пароля админом гасит активные сессии и меняет password_hash."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79006660001")
        old_hash = user.password_hash
        await make_session_row(s, token="tok-p", subject_kind="user", subject_id=user.id)
    # Act
    await admin_service.update_user(user.id, "Иван", "+79006660001", "active", "NewPassw0rd!")
    # Assert
    async with session_maker() as check:
        assert await check.get(m.Session, hash_token("tok-p")) is None
        fresh = await check.get(m.User, user.id)
        assert fresh.password_hash != old_hash


async def test__update_user__active_without_password__keeps_sessions(admin_service, session_maker):
    """Обычный апдейт (status active, без пароля) НЕ трогает существующие сессии."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79007770001", status="active")
        await make_session_row(s, token="tok-keep", subject_kind="user", subject_id=user.id)
    # Act
    await admin_service.update_user(user.id, "Иван", "+79007770001", "active", None)
    # Assert
    async with session_maker() as check:
        assert await check.get(m.Session, hash_token("tok-keep")) is not None


# --- delete_user ---------------------------------------------------------


async def test__delete_user__existing__removes_row(admin_service, session_maker):
    """delete_user удаляет пользователя из БД."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79008880001")
    # Act
    await admin_service.delete_user(user.id)
    # Assert
    async with session_maker() as check:
        assert await check.get(m.User, user.id) is None


async def test__delete_user__unknown_id__is_silent_noop(admin_service, session_maker):
    """Удаление несуществующего id проходит тихо (без исключения)."""
    # Arrange
    async with seed(session_maker) as s:
        keep = await make_user(s, phone="+79009990001")
    # Act
    await admin_service.delete_user("no-such-id")
    # Assert
    async with session_maker() as check:
        assert await check.get(m.User, keep.id) is not None


# --- check_updates -------------------------------------------------------


async def test__check_updates__no_feed_url_no_cache__falls_back_to_current(admin_service):
    """Без фида и без кэша: checked=False, latest=current, releases=fallback."""
    # Arrange
    # (update_feed_url="" по умолчанию; кэш в settings отсутствует)
    # Act
    result = await admin_service.check_updates()
    # Assert
    assert result["checked"] is False
    assert result["latest"] == "0.1.0"
    assert result["current"] == "0.1.0"
    assert result["available"] is False
    assert result["releases"] == _FALLBACK_RELEASES


async def test__check_updates__cached_newer_version__reports_from_cache(admin_service, session_maker):
    """Кэш update_feed_cache с более новой версией → latest из кэша, available=True."""
    # Arrange
    cached = {"latest": "9.9.9", "releases": [{"v": "9.9.9", "date": "01.01.2030", "notes": ["новое"]}]}
    async with seed(session_maker) as s:
        s.add(m.Setting(key="update_feed_cache", value=json.dumps(cached)))
    # Act
    result = await admin_service.check_updates()
    # Assert
    assert result["checked"] is False
    assert result["latest"] == "9.9.9"
    assert result["available"] is True
    assert result["releases"] == cached["releases"]


async def test__check_updates__corrupt_cache__falls_back_to_current(admin_service, session_maker):
    """Битый JSON в кэше игнорируется → latest=current, releases=fallback."""
    # Arrange
    async with seed(session_maker) as s:
        s.add(m.Setting(key="update_feed_cache", value="{not-json"))
    # Act
    result = await admin_service.check_updates()
    # Assert
    assert result["latest"] == "0.1.0"
    assert result["releases"] == _FALLBACK_RELEASES


async def test__check_updates__feed_configured_but_unreachable__falls_back_with_reason(
    admin_service, settings, monkeypatch
):
    """URL фида задан, но fetch_feed падает → checked=False и заполнен reason (ветка обработки ошибки)."""
    # Arrange — фид настроен, но недоступен
    monkeypatch.setattr(settings, "update_feed_url", "https://feed.invalid/releases.json")

    async def _boom(url, timeout=6.0):
        raise OSError("connection refused")

    monkeypatch.setattr(admin_mod, "fetch_feed", _boom)
    # Act
    result = await admin_service.check_updates()
    # Assert
    assert result["checked"] is False
    assert result["latest"] == "0.1.0"  # нет кэша → текущая версия
    assert result.get("reason")


# --- system --------------------------------------------------------------


async def test__system__on_sqlite__returns_core_keys_and_db_error(admin_service):
    """system() на SQLite: есть version/db/backups; db.status='error' (SELECT version() падает)."""
    # Arrange
    # (пустая БД; backup_dir указывает на tmp — бэкапов нет)
    # Act
    info = await admin_service.system()
    # Assert
    assert info["version"] == "0.1.0"
    assert info["db"]["status"] == "error"
    assert info["backups"] == []
    assert info["lastBackup"] == "—"


async def test__system__cached_release__surfaces_latest_in_summary(admin_service, session_maker):
    """system() поднимает latest/releases из кэша update_feed_cache."""
    # Arrange
    cached = {"latest": "2.0.0", "releases": [{"v": "2.0.0", "date": "01.01.2027", "notes": ["x"]}]}
    async with seed(session_maker) as s:
        s.add(m.Setting(key="update_feed_cache", value=json.dumps(cached)))
    # Act
    info = await admin_service.system()
    # Assert
    assert info["latest"] == "2.0.0"
    assert info["updateAvailable"] is True
    assert info["releases"] == cached["releases"]
