"""Интеграционные тесты AuthService: bootstrap админа, регистрация, вход, сессии, смена пароля."""

from __future__ import annotations

import pytest
from pytest_lazy_fixtures import lf

from tests.factories.orm import (
    add_member,
    make_group,
    make_session_row,
    make_user,
    seed,
)
from vpnhub.core.errors import BadRequest, NotFound, Unauthorized
from vpnhub.infra.security import hash_token, new_session_token
from vpnhub.services.auth import AuthService

pytestmark = pytest.mark.integration

PASSWORD = "Passw0rd!"


# ---- setup_needed --------------------------------------------------------


async def test__setup_needed__no_admins_and_no_admin_phone__returns_true(uow, settings, session_maker):
    """Пустая БД и admin_phone не задан → нужен bootstrap."""
    # Arrange
    svc = AuthService(uow, settings)
    # Act
    result = await svc.setup_needed()
    # Assert
    assert result is True


async def test__setup_needed__after_admin_created__returns_false(uow, settings, session_maker):
    """Появился хотя бы один админ → bootstrap больше не нужен."""
    # Arrange
    async with seed(session_maker) as s:
        await make_user(s, phone="+79001112233", admin=True)
    svc = AuthService(uow, settings)
    # Act
    result = await svc.setup_needed()
    # Assert
    assert result is False


async def test__setup_needed__admin_phone_configured__returns_false(uow, settings, session_maker):
    """admin_phone задан в конфиге → bootstrap не нужен даже без записей в admins."""
    # Arrange
    settings.admin_phone = "+79005556677"
    svc = AuthService(uow, settings)
    # Act
    result = await svc.setup_needed()
    # Assert
    assert result is False


# ---- create_first_admin --------------------------------------------------


async def test__create_first_admin__valid_input__returns_token_and_creates_admin(uow, settings, session_maker):
    """Корректные данные → выдаётся токен и создаётся запись-админ + активный юзер."""
    # Arrange
    svc = AuthService(uow, settings)
    # Act
    token = await svc.create_first_admin("Босс", "+79001112233", PASSWORD, PASSWORD)
    # Assert
    assert token
    async with uow.query() as tx:
        assert await tx.admins.count() == 1
        user = await tx.users.by_phone("+79001112233")
        assert user is not None
        assert user.status == "active"
        assert await tx.admins.is_admin(user.id) is True


async def test__create_first_admin__valid_token__resolves_to_admin_identity(uow, settings, session_maker):
    """Выданный токен админа резолвится в admin-Identity с ролью owner."""
    # Arrange
    svc = AuthService(uow, settings)
    # Act
    token = await svc.create_first_admin("Босс", "+79001112233", PASSWORD, PASSWORD)
    identity = await svc.resolve(token)
    # Assert
    assert identity is not None
    assert identity.kind == "admin"
    assert identity.role == "owner"
    assert identity.name == "Босс"


@pytest.fixture
def cfa_empty_name() -> tuple[str, str, str, str]:
    """Пустое имя."""
    return ("", "+79001112233", PASSWORD, PASSWORD)


@pytest.fixture
def cfa_empty_phone() -> tuple[str, str, str, str]:
    """Пустой телефон."""
    return ("Босс", "", PASSWORD, PASSWORD)


@pytest.fixture
def cfa_empty_password() -> tuple[str, str, str, str]:
    """Пустой пароль."""
    return ("Босс", "+79001112233", "", "")


@pytest.fixture
def cfa_bad_phone() -> tuple[str, str, str, str]:
    """Невалидный телефон (мусорные цифры)."""
    return ("Босс", "12345", PASSWORD, PASSWORD)


@pytest.mark.parametrize(
    "args",
    [
        lf("cfa_empty_name"),
        lf("cfa_empty_phone"),
        lf("cfa_empty_password"),
        lf("cfa_bad_phone"),
    ],
)
async def test__create_first_admin__invalid_input__raises_bad_request(uow, settings, session_maker, args):
    """Пустые поля или невалидный телефон → BadRequest, админ не создаётся."""
    # Arrange
    svc = AuthService(uow, settings)
    name, phone, password, password2 = args
    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        await svc.create_first_admin(name, phone, password, password2)
    assert exc.value.http_status == 400
    async with uow.query() as tx:
        assert await tx.admins.count() == 0


async def test__create_first_admin__passwords_mismatch__raises_bad_request(uow, settings, session_maker):
    """Пароль и подтверждение не совпадают → BadRequest «Пароли не совпадают»."""
    # Arrange
    svc = AuthService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest, match="не совпадают"):
        await svc.create_first_admin("Босс", "+79001112233", PASSWORD, "Other1!!")


async def test__create_first_admin__second_call__raises_admin_already_exists(uow, settings, session_maker):
    """Повторный bootstrap при уже существующем админе → BadRequest «Администратор уже создан»."""
    # Arrange
    async with seed(session_maker) as s:
        await make_user(s, phone="+79001112233", admin=True)
    svc = AuthService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest, match="Администратор уже создан"):
        await svc.create_first_admin("Второй", "+79004445566", PASSWORD, PASSWORD)


# ---- register ------------------------------------------------------------


async def test__register__valid_input__creates_pending_user(uow, settings, session_maker):
    """Обычная регистрация (без приглашения) → пользователь в статусе pending."""
    # Arrange
    svc = AuthService(uow, settings)
    # Act
    await svc.register("Гость", "+79007778899", PASSWORD, PASSWORD)
    # Assert
    async with uow.query() as tx:
        user = await tx.users.by_phone("+79007778899")
        assert user is not None
        assert user.status == "pending"


async def test__register__duplicate_phone__raises_bad_request(uow, settings, session_maker):
    """Телефон уже зарегистрирован → BadRequest, второй юзер не создаётся."""
    # Arrange
    async with seed(session_maker) as s:
        await make_user(s, phone="+79007778899", status="active")
    svc = AuthService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest, match="уже зарегистрирован"):
        await svc.register("Дубль", "+79007778899", PASSWORD, PASSWORD)


async def test__register__invited_by_phone__activates_and_binds_member(uow, settings, session_maker):
    """Приглашённый по телефону участник → регистрация сразу active и member привязан к юзеру."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233", admin=True)
        group = await make_group(s, owner_id=owner.id)
        member = await add_member(s, group_id=group.id, phone="+79007778899", status="invited")
        member_id = member.id
    svc = AuthService(uow, settings)
    # Act
    await svc.register("Приглашённый", "+79007778899", PASSWORD, PASSWORD)
    # Assert
    async with uow.query() as tx:
        user = await tx.users.by_phone("+79007778899")
        assert user is not None
        assert user.status == "active"
        # приглашение реально привязано к созданному юзеру и активировано
        bound = await tx.groups.member(member_id)
        assert bound.user_id == user.id
        assert bound.status == "active"
        # invited-приглашений по этому телефону больше не осталось
        assert await tx.groups.members_by_phone("+79007778899") == []


# ---- login ---------------------------------------------------------------


async def test__login__correct_credentials__returns_token(uow, settings, session_maker):
    """Верные телефон+пароль активного юзера → выдаётся токен user-сессии."""
    # Arrange
    async with seed(session_maker) as s:
        await make_user(s, phone="+79990001122", password=PASSWORD, status="active")
    svc = AuthService(uow, settings)
    # Act
    token = await svc.login("+79990001122", PASSWORD)
    # Assert
    assert token
    identity = await svc.resolve(token)
    assert identity is not None
    assert identity.kind == "user"
    assert identity.role == "member"


async def test__login__wrong_password__raises_unauthorized(uow, settings, session_maker):
    """Неверный пароль → Unauthorized."""
    # Arrange
    async with seed(session_maker) as s:
        await make_user(s, phone="+79990001122", password=PASSWORD, status="active")
    svc = AuthService(uow, settings)
    # Act / Assert
    with pytest.raises(Unauthorized) as exc:
        await svc.login("+79990001122", "WrongPass1!")
    assert exc.value.http_status == 401


async def test__login__unknown_phone__raises_unauthorized(uow, settings, session_maker):
    """Несуществующий телефон → Unauthorized (без утечки, что юзера нет)."""
    # Arrange
    svc = AuthService(uow, settings)
    # Act / Assert
    with pytest.raises(Unauthorized):
        await svc.login("+79990009988", PASSWORD)


async def test__login__unknown_phone__still_runs_password_verify(uow, settings, session_maker, monkeypatch):
    """Постоянное время: для несуществующего телефона argon2-verify всё равно прогоняется
    (по заглушке-хешу) — иначе по времени ответа можно перечислять пользователей."""
    # Arrange
    import vpnhub.services.auth as auth_mod

    calls: list[str] = []
    monkeypatch.setattr(auth_mod, "verify_password", lambda h, _p: bool(calls.append(h)))
    svc = AuthService(uow, settings)
    # Act / Assert
    with pytest.raises(Unauthorized):
        await svc.login("+79990009988", PASSWORD)
    assert calls == [auth_mod._DUMMY_PASSWORD_HASH]


async def test__login__blocked_user__raises_unauthorized(uow, settings, session_maker):
    """Заблокированный аккаунт при верном пароле → Unauthorized «заблокирован»."""
    # Arrange
    async with seed(session_maker) as s:
        await make_user(s, phone="+79990001122", password=PASSWORD, status="blocked")
    svc = AuthService(uow, settings)
    # Act / Assert
    with pytest.raises(Unauthorized, match="заблокирован"):
        await svc.login("+79990001122", PASSWORD)


async def test__login__pending_without_invite__raises_unauthorized(uow, settings, session_maker):
    """Pending-юзер без приглашения → Unauthorized «ожидает подтверждения»."""
    # Arrange
    async with seed(session_maker) as s:
        await make_user(s, phone="+79990001122", password=PASSWORD, status="pending")
    svc = AuthService(uow, settings)
    # Act / Assert
    with pytest.raises(Unauthorized, match="ожидает подтверждения"):
        await svc.login("+79990001122", PASSWORD)


async def test__login__admin_even_if_blocked__returns_admin_session(uow, settings, session_maker):
    """Админ входит даже будучи blocked → выдаётся admin-сессия (проверка admins приоритетнее статуса)."""
    # Arrange
    async with seed(session_maker) as s:
        await make_user(s, phone="+79001112233", password=PASSWORD, status="blocked", admin=True)
    svc = AuthService(uow, settings)
    # Act
    token = await svc.login("+79001112233", PASSWORD)
    # Assert
    identity = await svc.resolve(token)
    assert identity is not None
    assert identity.kind == "admin"


async def test__login__pending_user_with_invite__activates_and_returns_token(uow, settings, session_maker):
    """Pending-юзер с появившимся позже приглашением → активируется и получает токен."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233", admin=True)
        pending = await make_user(s, phone="+79990001122", password=PASSWORD, status="pending")
        group = await make_group(s, owner_id=owner.id)
        await add_member(s, group_id=group.id, phone="+79990001122", status="invited")
        pending_id = pending.id
    svc = AuthService(uow, settings)
    # Act
    token = await svc.login("+79990001122", PASSWORD)
    # Assert
    assert token
    async with uow.query() as tx:
        user = await tx.users.get(pending_id)
        assert user.status == "active"


# ---- resolve -------------------------------------------------------------


async def test__resolve__none_token__returns_none(uow, settings, session_maker):
    """Пустой токен → None (не бьём в БД)."""
    # Arrange
    svc = AuthService(uow, settings)
    # Act
    result = await svc.resolve(None)
    # Assert
    assert result is None


async def test__resolve__unknown_token__returns_none(uow, settings, session_maker):
    """Токен, которому нет сессии → None."""
    # Arrange
    svc = AuthService(uow, settings)
    # Act
    result = await svc.resolve(new_session_token())
    # Assert
    assert result is None


async def test__resolve__valid_user_session__returns_user_identity(uow, settings, session_maker):
    """Живая user-сессия активного юзера → Identity(kind=user, role=member)."""
    # Arrange
    token = new_session_token()
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79990001122", name="Гость", status="active")
        await make_session_row(s, token=token, subject_kind="user", subject_id=user.id)
    svc = AuthService(uow, settings)
    # Act
    identity = await svc.resolve(token)
    # Assert
    assert identity is not None
    assert identity.kind == "user"
    assert identity.name == "Гость"
    assert identity.role == "member"


async def test__resolve__valid_admin_session__returns_admin_identity(uow, settings, session_maker):
    """Живая admin-сессия → Identity(kind=admin, role=owner)."""
    # Arrange
    token = new_session_token()
    async with seed(session_maker) as s:
        admin = await make_user(s, phone="+79001112233", name="Босс", admin=True)
        await make_session_row(s, token=token, subject_kind="admin", subject_id=admin.id)
    svc = AuthService(uow, settings)
    # Act
    identity = await svc.resolve(token)
    # Assert
    assert identity is not None
    assert identity.kind == "admin"
    assert identity.role == "owner"


async def test__resolve__expired_session__returns_none(uow, settings, session_maker):
    """Истёкшая сессия (expires_at в прошлом) → None."""
    # Arrange
    token = new_session_token()
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79990001122", status="active")
        await make_session_row(s, token=token, subject_kind="user", subject_id=user.id, ttl_seconds=-10.0)
    svc = AuthService(uow, settings)
    # Act
    result = await svc.resolve(token)
    # Assert
    assert result is None


async def test__resolve__user_no_longer_active__returns_none(uow, settings, session_maker):
    """Сессия жива, но юзер стал не-active (blocked) → None."""
    # Arrange
    token = new_session_token()
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79990001122", status="blocked")
        await make_session_row(s, token=token, subject_kind="user", subject_id=user.id)
    svc = AuthService(uow, settings)
    # Act
    result = await svc.resolve(token)
    # Assert
    assert result is None


# ---- logout --------------------------------------------------------------


async def test__logout__existing_session__deletes_it(uow, settings, session_maker):
    """logout по токену → сессия удалена, повторный resolve → None."""
    # Arrange
    token = new_session_token()
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79990001122", status="active")
        await make_session_row(s, token=token, subject_kind="user", subject_id=user.id)
    svc = AuthService(uow, settings)
    # Act
    await svc.logout(token)
    # Assert
    async with uow.query() as tx:
        assert await tx.sessions.get(hash_token(token)) is None


async def test__logout__none_token__is_noop(uow, settings, session_maker):
    """logout(None) → ничего не падает и существующие сессии не трогает."""
    # Arrange
    token = new_session_token()
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79990001122", status="active")
        await make_session_row(s, token=token, subject_kind="user", subject_id=user.id)
    svc = AuthService(uow, settings)
    # Act
    await svc.logout(None)
    # Assert
    async with uow.query() as tx:
        assert await tx.sessions.get(hash_token(token)) is not None


# ---- list_sessions -------------------------------------------------------


async def test__list_sessions__marks_current_and_skips_expired(uow, settings, session_maker):
    """Список сессий субъекта: текущая помечена current=True, истёкшие отфильтрованы."""
    # Arrange
    current = new_session_token()
    other = new_session_token()
    expired = new_session_token()
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79990001122", status="active")
        uid = user.id
        await make_session_row(s, token=current, subject_kind="user", subject_id=uid)
        await make_session_row(s, token=other, subject_kind="user", subject_id=uid)
        await make_session_row(s, token=expired, subject_kind="user", subject_id=uid, ttl_seconds=-5.0)
    svc = AuthService(uow, settings)
    # Act
    rows = await svc.list_sessions(current, uid)
    # Assert
    assert len(rows) == 2  # истёкшая не попала
    current_flags = {r["id"]: r["current"] for r in rows}
    assert current_flags[hash_token(current)] is True
    assert current_flags[hash_token(other)] is False


# ---- revoke_session ------------------------------------------------------


async def test__revoke_session__own_session__deletes_it(uow, settings, session_maker):
    """Отзыв своей сессии по id → она удалена."""
    # Arrange
    victim = new_session_token()
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79990001122", status="active")
        uid = user.id
        row = await make_session_row(s, token=victim, subject_kind="user", subject_id=uid)
        victim_id = row.id
    svc = AuthService(uow, settings)
    # Act
    await svc.revoke_session(None, uid, victim_id)
    # Assert
    async with uow.query() as tx:
        assert await tx.sessions.get(victim_id) is None


async def test__revoke_session__foreign_session__raises_not_found(uow, settings, session_maker):
    """Попытка отозвать чужую сессию (иной subject_id) → NotFound, сессия жива."""
    # Arrange
    foreign = new_session_token()
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79990001122", status="active")
        other = await make_user(s, phone="+79993334455", status="active")
        row = await make_session_row(s, token=foreign, subject_kind="user", subject_id=other.id)
        owner_id = owner.id
        foreign_id = row.id
    svc = AuthService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.revoke_session(None, owner_id, foreign_id)
    async with uow.query() as tx:
        assert await tx.sessions.get(foreign_id) is not None


async def test__revoke_session__missing_session__raises_not_found(uow, settings, session_maker):
    """Отзыв несуществующей сессии → NotFound."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79990001122", status="active")
        uid = user.id
    svc = AuthService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.revoke_session(None, uid, "no-such-session-id")


# ---- revoke_others -------------------------------------------------------


async def test__revoke_others__keeps_current_deletes_rest(uow, settings, session_maker):
    """revoke_others гасит все сессии субъекта, кроме текущей."""
    # Arrange
    current = new_session_token()
    a = new_session_token()
    b = new_session_token()
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79990001122", status="active")
        uid = user.id
        await make_session_row(s, token=current, subject_kind="user", subject_id=uid)
        await make_session_row(s, token=a, subject_kind="user", subject_id=uid)
        await make_session_row(s, token=b, subject_kind="user", subject_id=uid)
    svc = AuthService(uow, settings)
    # Act
    deleted = await svc.revoke_others(current, uid)
    # Assert
    assert deleted == 2
    async with uow.query() as tx:
        remaining = await tx.sessions.for_subject(uid)
        assert [r.id for r in remaining] == [hash_token(current)]


# ---- change_password -----------------------------------------------------


async def test__change_password__correct_current__updates_and_revokes_others(uow, settings, session_maker):
    """Верный старый пароль → хэш обновлён, вход по новому паролю работает, прочие сессии погашены."""
    # Arrange
    current = new_session_token()
    other = new_session_token()
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79990001122", password=PASSWORD, status="active")
        uid = user.id
        await make_session_row(s, token=current, subject_kind="user", subject_id=uid)
        await make_session_row(s, token=other, subject_kind="user", subject_id=uid)
    svc = AuthService(uow, settings)
    new_pwd = "NewPass1!"
    # Act
    await svc.change_password(uid, PASSWORD, new_pwd, current)
    # Assert
    # прочие сессии погашены, текущая жива
    async with uow.query() as tx:
        remaining = {r.id for r in await tx.sessions.for_subject(uid)}
        assert remaining == {hash_token(current)}
    # новый пароль действителен
    token = await svc.login("+79990001122", new_pwd)
    assert token


async def test__change_password__weak_new_password__raises_before_touching_db(uow, settings, session_maker):
    """Слабый новый пароль → BadRequest раньше проверки текущего; хэш и сессии не тронуты."""
    # Arrange
    keep = new_session_token()
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79990001122", password=PASSWORD, status="active")
        uid = user.id
        original_hash = user.password_hash
        await make_session_row(s, token=keep, subject_kind="user", subject_id=uid)
    svc = AuthService(uow, settings)
    # Act / Assert — new_password не проходит политику (validate_password до всего остального)
    with pytest.raises(BadRequest):
        await svc.change_password(uid, PASSWORD, "short", keep)
    async with uow.query() as tx:
        user = await tx.users.get(uid)
        assert user.password_hash == original_hash
        assert len(await tx.sessions.for_subject(uid)) == 1


async def test__change_password__wrong_current__raises_bad_request(uow, settings, session_maker):
    """Неверный текущий пароль → BadRequest, хэш не меняется, сессии не гасятся."""
    # Arrange
    keep = new_session_token()
    async with seed(session_maker) as s:
        user = await make_user(s, phone="+79990001122", password=PASSWORD, status="active")
        uid = user.id
        original_hash = user.password_hash
        await make_session_row(s, token=keep, subject_kind="user", subject_id=uid)
    svc = AuthService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest, match="Текущий пароль неверен"):
        await svc.change_password(uid, "WrongOld1!", "NewPass1!", keep)
    async with uow.query() as tx:
        user = await tx.users.get(uid)
        assert user.password_hash == original_hash
        assert len(await tx.sessions.for_subject(uid)) == 1
