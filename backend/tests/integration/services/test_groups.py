"""Интеграционные тесты GroupService: группы, участники, доступы, инвайты."""

from __future__ import annotations

import pytest
from pytest_lazy_fixtures import lf

import vpnhub.services.provisioning as prov_mod
from tests.factories.orm import (
    add_member,
    grant_group_server,
    make_group,
    make_pool,
    make_server,
    make_user,
    seed,
)
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.security import normalize_phone
from vpnhub.services.groups import GroupService

pytestmark = pytest.mark.integration


@pytest.fixture
def reconcile_calls(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    """Мок ProvisioningService.reconcile_users: пишет переданные user_ids в список вызовов."""
    calls: list[list[str]] = []

    async def fake_reconcile(self: prov_mod.ProvisioningService, user_ids: list[str]) -> None:
        calls.append(list(user_ids))

    monkeypatch.setattr(prov_mod.ProvisioningService, "reconcile_users", fake_reconcile)
    return calls


# ---- create ----


async def test__create__empty_name__raises_bad_request(uow, settings, session_maker):
    """Пустое название группы → BadRequest (400)."""
    # Arrange
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest) as ei:
        await svc.create("owner-1", "Владелец", "")
    assert ei.value.http_status == 400


async def test__create__valid__adds_owner_as_admin_member(uow, settings, session_maker):
    """Создание группы → владелец добавлен участником с ролью admin и статусом active."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233", name="Хозяин")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.create(owner.id, "Хозяин", "Семья")
    # Assert
    assert result["name"] == "Семья"
    assert len(result["members"]) == 1
    member = result["members"][0]
    assert member["userId"] == owner.id
    assert member["role"] == "admin"
    assert member["status"] == "active"
    assert member["name"] == "Хозяин (вы)"


async def test__create__valid__generates_grp_prefixed_token(uow, settings, session_maker):
    """Создание группы → токен приглашения сгенерирован с префиксом grp-."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
    svc = GroupService(uow, settings)
    # Act
    result = await svc.create(owner.id, "Иван", "Семья")
    # Assert
    assert result["token"].startswith("grp-")


# ---- get / list (ownership) ----


async def test__get__foreign_group__raises_not_found(uow, settings, session_maker):
    """Запрос чужой группы (другой owner_id) → NotFound."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        g = await make_group(s, owner_id=owner.id, token="grp-foreign")
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.get("someone-else", g.id)


async def test__get__own_group__returns_card(uow, settings, session_maker):
    """Запрос своей группы → карточка с id и именем."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        g = await make_group(s, owner_id=owner.id, name="Моя", token="grp-own")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.get(owner.id, g.id)
    # Assert
    assert result["id"] == g.id
    assert result["name"] == "Моя"


async def test__list__returns_only_owners_groups(uow, settings, session_maker):
    """list возвращает только группы запрашивающего владельца, чужие не попадают."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        other = await make_user(s, phone="+79002223344")
        await make_group(s, owner_id=owner.id, name="Своя", token="grp-mine")
        await make_group(s, owner_id=other.id, name="Чужая", token="grp-theirs")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.list(owner.id)
    # Assert
    assert [g["name"] for g in result] == ["Своя"]


# ---- add_member ----


async def test__add_member__empty_name__raises_bad_request(uow, settings, session_maker):
    """Пустое имя участника → BadRequest."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        g = await make_group(s, owner_id=owner.id, token="grp-add")
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest):
        await svc.add_member(owner.id, g.id, "", "member", None)


async def test__add_member__existing_user_phone__active_with_user_id(uow, settings, session_maker):
    """Телефон принадлежит зарегистрированному юзеру → участник active и привязан к user_id."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        member_user = await make_user(s, phone="+79991234567", name="Друг")
        g = await make_group(s, owner_id=owner.id, token="grp-known")
        member_user_id, gid = member_user.id, g.id
    svc = GroupService(uow, settings)
    # Act
    result = await svc.add_member(owner.id, gid, "Друг", "member", "+79991234567")
    # Assert
    added = next(mb for mb in result["members"] if mb["name"] == "Друг")
    assert added["status"] == "active"
    assert added["phone"] == "+79991234567"
    assert added["userId"] == member_user_id
    # реальная привязка к user_id в БД тоже есть
    async with uow.query() as tx:
        group = await tx.groups.get(gid)
        member = next(mb for mb in group.members if mb.phone == normalize_phone("+79991234567"))
        assert member.user_id == member_user_id


async def test__add_member__unknown_phone__invited(uow, settings, session_maker):
    """Телефон неизвестен системе → участник со статусом invited."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        g = await make_group(s, owner_id=owner.id, token="grp-unknown")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.add_member(owner.id, g.id, "Гость", "member", "+79991234567")
    # Assert
    added = next(mb for mb in result["members"] if mb["name"] == "Гость")
    assert added["userId"] is None
    assert added["status"] == "invited"
    assert added["phone"] == "+79991234567"


async def test__add_member__no_phone__active(uow, settings, session_maker):
    """Участник без телефона → сразу active."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        g = await make_group(s, owner_id=owner.id, token="grp-nophone")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.add_member(owner.id, g.id, "Безномера", "member", None)
    # Assert
    added = next(mb for mb in result["members"] if mb["name"] == "Безномера")
    assert added["status"] == "active"
    assert added["phone"] == ""


async def test__add_member__phone_already_in_group__raises_bad_request(uow, settings, session_maker):
    """Повторное приглашение на тот же телефон → BadRequest, второй строки не появляется."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        g = await make_group(s, owner_id=owner.id, token="grp-dup-phone")
        await add_member(s, group_id=g.id, display_name="Гость", phone="+79991234567", status="invited")
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest) as ei:
        await svc.add_member(owner.id, g.id, "Ещё раз", "member", "+79991234567")
    assert ei.value.key == "group.member_already_added"


# ---- candidates / add_user (выбор из зарегистрированных) ----


async def test__candidates__admin__sees_all_active_users_with_full_phones(uow, settings, session_maker):
    """Админ видит всех активных пользователей с полными телефонами, кроме уже состоящих в группе."""
    # Arrange
    async with seed(session_maker) as s:
        admin = await make_user(s, phone="+79000000001", name="Админ", admin=True)
        g = await make_group(s, owner_id=admin.id, token="grp-adm")
        await add_member(s, group_id=g.id, user_id=admin.id, display_name="Админ (вы)", role="admin")
        await make_user(s, phone="+79000000002", name="Борис")
        await make_user(s, phone="+79000000003", name="Анна")
        await make_user(s, phone="+79000000004", name="Блок", status="blocked")
        await make_user(s, phone="+79000000005", name="Ждёт", status="pending")
        await make_user(s, phone="+79000000006", name="Приглашён")
        await add_member(s, group_id=g.id, display_name="Приглашён", phone="+79000000006", status="invited")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.candidates(admin.id, g.id, is_admin=True)
    # Assert
    assert [(c["name"], c["phone"]) for c in result] == [("Анна", "+7 900 000-00-03"), ("Борис", "+7 900 000-00-02")]


async def test__candidates__non_admin_owner__sees_only_shared_group_users_masked(uow, settings, session_maker):
    """Обычный владелец видит только тех, с кем уже в общей группе, и только маску телефона."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79000000001", name="Владелец")
        friend = await make_user(s, phone="+79000001234", name="Друг")
        cousin = await make_user(s, phone="+79000005678", name="Кузен")
        await make_user(s, phone="+79000009999", name="Незнакомец")
        mine = await make_group(s, owner_id=owner.id, token="grp-mine")
        target = await make_group(s, owner_id=owner.id, name="Новая", token="grp-target")
        await add_member(s, group_id=target.id, user_id=owner.id, display_name="Владелец (вы)", role="admin")
        await add_member(s, group_id=mine.id, user_id=friend.id, display_name="Друг")
        # группа чужого владельца, где владелец сам активный участник, — её участники тоже «знакомые»
        foreign = await make_group(s, owner_id=cousin.id, name="Чужая", token="grp-foreign")
        await add_member(s, group_id=foreign.id, user_id=owner.id, display_name="Владелец")
        await add_member(s, group_id=foreign.id, user_id=cousin.id, display_name="Кузен")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.candidates(owner.id, target.id, is_admin=False)
    # Assert
    assert [(c["name"], c["phone"]) for c in result] == [
        ("Друг", "+7 *** ***-12-34"),
        ("Кузен", "+7 *** ***-56-78"),
    ]


async def test__candidates__search__by_name_and_admin_phone_digits(uow, settings, session_maker):
    """Поиск: по имени без учёта регистра; по цифрам телефона — только у админа."""
    # Arrange
    async with seed(session_maker) as s:
        admin = await make_user(s, phone="+79000000001", name="Админ", admin=True)
        g = await make_group(s, owner_id=admin.id, token="grp-search")
        await add_member(s, group_id=g.id, user_id=admin.id, display_name="Админ (вы)", role="admin")
        await make_user(s, phone="+79005550001", name="Мария")
        await make_user(s, phone="+79007770002", name="Пётр")
        own = await make_group(s, owner_id=admin.id, name="Все", token="grp-all")
    svc = GroupService(uow, settings)
    # Act
    by_name = await svc.candidates(admin.id, g.id, "мар", is_admin=True)
    by_digits = await svc.candidates(admin.id, g.id, "777", is_admin=True)
    digits_non_admin = await svc.candidates(admin.id, own.id, "777", is_admin=False)
    # Assert
    assert [c["name"] for c in by_name] == ["Мария"]
    assert [c["name"] for c in by_digits] == ["Пётр"]
    assert digits_non_admin == []


async def test__candidates__foreign_group__raises_not_found(uow, settings, session_maker):
    """Кандидаты для чужой группы → NotFound."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79000000001")
        g = await make_group(s, owner_id=owner.id, token="grp-foreign-cand")
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.candidates("someone-else", g.id, is_admin=True)


async def test__add_user__eligible__active_member_bound_to_user(uow, settings, session_maker):
    """Выбор кандидата → активный участник с user_id, именем и телефоном пользователя, роль из запроса."""
    # Arrange
    async with seed(session_maker) as s:
        admin = await make_user(s, phone="+79000000001", name="Админ", admin=True)
        g = await make_group(s, owner_id=admin.id, token="grp-pick")
        user = await make_user(s, phone="+79991234567", name="Ольга")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.add_user(admin.id, g.id, user.id, "admin", is_admin=True)
    # Assert
    added = next(mb for mb in result["members"] if mb["userId"] == user.id)
    assert added == {**added, "name": "Ольга", "status": "active", "role": "admin", "phone": "+79991234567"}


async def test__add_user__unknown_role__falls_back_to_member(uow, settings, session_maker):
    """Неизвестная роль из запроса → member."""
    # Arrange
    async with seed(session_maker) as s:
        admin = await make_user(s, phone="+79000000001", admin=True)
        g = await make_group(s, owner_id=admin.id, token="grp-role")
        user = await make_user(s, phone="+79991234567")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.add_user(admin.id, g.id, user.id, "owner", is_admin=True)
    # Assert
    assert next(mb for mb in result["members"] if mb["userId"] == user.id)["role"] == "member"


@pytest.mark.parametrize("status", ["blocked", "pending"])
async def test__add_user__inactive_user__raises_not_found(uow, settings, session_maker, status):
    """Заблокированного или неподтверждённого пользователя добавить нельзя даже админу."""
    # Arrange
    async with seed(session_maker) as s:
        admin = await make_user(s, phone="+79000000001", admin=True)
        g = await make_group(s, owner_id=admin.id, token="grp-inactive")
        user = await make_user(s, phone="+79991234567", status=status)
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound) as ei:
        await svc.add_user(admin.id, g.id, user.id, "member", is_admin=True)
    assert ei.value.key == "group.user_not_found"


async def test__add_user__non_admin_stranger__raises_not_found(uow, settings, session_maker):
    """Обычный владелец не может добавить по id пользователя, с которым не делит ни одной группы."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79000000001")
        g = await make_group(s, owner_id=owner.id, token="grp-stranger")
        stranger = await make_user(s, phone="+79991234567")
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.add_user(owner.id, g.id, stranger.id, "member", is_admin=False)


async def test__add_user__unknown_id__raises_not_found(uow, settings, session_maker):
    """Несуществующий user id → NotFound."""
    # Arrange
    async with seed(session_maker) as s:
        admin = await make_user(s, phone="+79000000001", admin=True)
        g = await make_group(s, owner_id=admin.id, token="grp-unknown-id")
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.add_user(admin.id, g.id, "no-such-user", "member", is_admin=True)


async def test__add_user__already_member__raises_bad_request(uow, settings, session_maker):
    """Пользователь уже в группе → BadRequest с понятным ключом."""
    # Arrange
    async with seed(session_maker) as s:
        admin = await make_user(s, phone="+79000000001", admin=True)
        g = await make_group(s, owner_id=admin.id, token="grp-dup")
        user = await make_user(s, phone="+79991234567")
        await add_member(s, group_id=g.id, user_id=user.id, display_name="Уже тут")
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest) as ei:
        await svc.add_user(admin.id, g.id, user.id, "member", is_admin=True)
    assert ei.value.key == "group.member_already_added"


async def test__add_user__foreign_group__raises_not_found(uow, settings, session_maker):
    """Добавление в чужую группу → NotFound, участник не появляется."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79000000001")
        intruder = await make_user(s, phone="+79000000002", admin=True)
        g = await make_group(s, owner_id=owner.id, token="grp-not-yours")
        user = await make_user(s, phone="+79991234567")
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.add_user(intruder.id, g.id, user.id, "member", is_admin=True)
    async with uow.query() as tx:
        group = await tx.groups.get(g.id)
        assert all(mb.user_id != user.id for mb in group.members)


# ---- peek_by_token ----


async def test__peek_by_token__valid__returns_invite_card(uow, settings, session_maker):
    """Валидный токен → карточка приглашения с именем группы, владельцем и числом активных."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, name="Босс")
        g = await make_group(s, owner_id=owner.id, name="Команда", token="grp-peek")
        await add_member(s, group_id=g.id, display_name="Активный", status="active")
        await add_member(s, group_id=g.id, display_name="Приглашённый", status="invited")
    svc = GroupService(uow, settings)
    # Act
    card = await svc.peek_by_token("grp-peek")
    # Assert
    assert card["id"] == g.id
    assert card["name"] == "Команда"
    assert card["ownerName"] == "Босс"
    assert card["memberCount"] == 1  # считаются только active


async def test__peek_by_token__unknown_token__raises_not_found(uow, settings, session_maker):
    """Неизвестный токен → NotFound."""
    # Arrange
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.peek_by_token("grp-does-not-exist")


# ---- join ----


async def test__join__new_member__added_active(uow, settings, session_maker):
    """Присоединение по токену новым юзером → он добавлен активным участником."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        joiner = await make_user(s, phone="+79002223344", name="Новичок")
        g = await make_group(s, owner_id=owner.id, token="grp-join")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.join(joiner.id, "Новичок", "grp-join")
    # Assert
    assert result == {"id": g.id, "name": g.name, "ok": True}
    card = await svc.get(owner.id, g.id)
    joined = next(mb for mb in card["members"] if mb["name"] == "Новичок")
    assert joined["status"] == "active"


async def test__join__repeated__reactivates_existing_member(uow, settings, session_maker):
    """Повторный join уже существующего (не-active) участника → статус снова active."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        joiner = await make_user(s, phone="+79002223344", name="Возврат")
        g = await make_group(s, owner_id=owner.id, token="grp-rejoin")
        await add_member(s, group_id=g.id, user_id=joiner.id, display_name="Возврат", status="invited")
    svc = GroupService(uow, settings)
    # Act
    await svc.join(joiner.id, "Возврат", "grp-rejoin")
    # Assert
    card = await svc.get(owner.id, g.id)
    row = next(mb for mb in card["members"] if mb["name"] == "Возврат")
    assert row["status"] == "active"
    assert len(card["members"]) == 1  # новой строки не создалось


async def test__join__matches_invited_row_by_phone(uow, settings, session_maker):
    """join привязывает приглашённую по телефону строку к присоединяющемуся юзеру."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        joiner = await make_user(s, phone="+79991234567", name="ПоТелефону")
        g = await make_group(s, owner_id=owner.id, token="grp-byphone")
        invited = await add_member(
            s, group_id=g.id, display_name="Приглашённый", phone="+79991234567", status="invited"
        )
    svc = GroupService(uow, settings)
    # Act
    await svc.join(joiner.id, "ПоТелефону", "grp-byphone")
    # Assert
    card = await svc.get(owner.id, g.id)
    assert len(card["members"]) == 1  # использована существующая invited-строка
    row = card["members"][0]
    assert row["id"] == invited.id
    assert row["status"] == "active"


async def test__join__unknown_token__raises_not_found(uow, settings, session_maker):
    """join по несуществующему токену → NotFound."""
    # Arrange
    async with seed(session_maker) as s:
        joiner = await make_user(s)
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.join(joiner.id, "Кто-то", "grp-nope")


# ---- toggle_member_role ----


@pytest.mark.parametrize(
    ("start_role", "expected_role"),
    [
        pytest.param("member", "admin", id="member->admin"),
        pytest.param("admin", "member", id="admin->member"),
    ],
)
async def test__toggle_member_role__flips_role(uow, settings, session_maker, start_role, expected_role):
    """toggle_member_role переключает роль участника admin<->member."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        g = await make_group(s, owner_id=owner.id, token="grp-role")
        mb = await add_member(s, group_id=g.id, display_name="Участник", role=start_role)
    svc = GroupService(uow, settings)
    # Act
    result = await svc.toggle_member_role(owner.id, g.id, mb.id)
    # Assert
    row = next(m for m in result["members"] if m["id"] == mb.id)
    assert row["role"] == expected_role


async def test__toggle_member_role__foreign_member__raises_not_found(uow, settings, session_maker):
    """Участник из другой группы → NotFound (проверка group_id)."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        g = await make_group(s, owner_id=owner.id, token="grp-a")
        other_g = await make_group(s, owner_id=owner.id, token="grp-b")
        foreign_mb = await add_member(s, group_id=other_g.id, display_name="Чужой")
    svc = GroupService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.toggle_member_role(owner.id, g.id, foreign_mb.id)


# ---- remove_member ----


async def test__remove_member__deletes_member(uow, settings, session_maker, reconcile_calls):
    """remove_member удаляет участника из группы."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        member_user = await make_user(s, phone="+79002223344")
        g = await make_group(s, owner_id=owner.id, token="grp-rm")
        mb = await add_member(s, group_id=g.id, user_id=member_user.id, display_name="Удаляемый")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.remove_member(owner.id, g.id, mb.id)
    # Assert
    assert all(m["id"] != mb.id for m in result["members"])


async def test__remove_member__calls_reconcile_with_removed_user_id(uow, settings, session_maker, reconcile_calls):
    """remove_member вызывает reconcile_users с user_id удалённого участника."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        member_user = await make_user(s, phone="+79002223344")
        g = await make_group(s, owner_id=owner.id, token="grp-rm2")
        mb = await add_member(s, group_id=g.id, user_id=member_user.id, display_name="Удаляемый")
    svc = GroupService(uow, settings)
    # Act
    await svc.remove_member(owner.id, g.id, mb.id)
    # Assert
    assert reconcile_calls == [[member_user.id]]


async def test__remove_member__member_without_user__skips_reconcile(uow, settings, session_maker, reconcile_calls):
    """Удаление приглашённого без user_id → reconcile_users не вызывается."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        g = await make_group(s, owner_id=owner.id, token="grp-rm3")
        mb = await add_member(s, group_id=g.id, display_name="Приглашённый", status="invited")
    svc = GroupService(uow, settings)
    # Act
    await svc.remove_member(owner.id, g.id, mb.id)
    # Assert
    assert reconcile_calls == []


# ---- regen_token ----


async def test__regen_token__changes_token(uow, settings, session_maker):
    """regen_token заменяет токен приглашения на новый (с префиксом grp-)."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        g = await make_group(s, owner_id=owner.id, token="grp-old")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.regen_token(owner.id, g.id)
    # Assert
    assert result["token"] != "grp-old"
    assert result["token"].startswith("grp-")


# ---- toggle_pool / toggle_server / toggle_server_vpn ----


async def test__toggle_pool__grants_access_and_calls_reconcile(uow, settings, session_maker, reconcile_calls):
    """toggle_pool добавляет доступ к пулу и вызывает reconcile_users с активными юзерами."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        member_user = await make_user(s, phone="+79002223344")
        g = await make_group(s, owner_id=owner.id, token="grp-pool")
        await add_member(s, group_id=g.id, user_id=member_user.id, display_name="Участник")
        pool = await make_pool(s, owner_id=owner.id)
    svc = GroupService(uow, settings)
    # Act
    result = await svc.toggle_pool(owner.id, g.id, pool.id)
    # Assert
    assert pool.id in result["access"]["pools"]
    assert reconcile_calls == [[member_user.id]]


async def test__toggle_pool__second_call_revokes_access(uow, settings, session_maker, reconcile_calls):
    """Повторный toggle_pool снимает ранее выданный доступ к пулу."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        g = await make_group(s, owner_id=owner.id, token="grp-pool2")
        pool = await make_pool(s, owner_id=owner.id)
    svc = GroupService(uow, settings)
    await svc.toggle_pool(owner.id, g.id, pool.id)  # выдали доступ
    # Act
    result = await svc.toggle_pool(owner.id, g.id, pool.id)  # сняли
    # Assert
    assert pool.id not in result["access"]["pools"]


async def test__toggle_server__grants_installed_vpns_and_calls_reconcile(uow, settings, session_maker, reconcile_calls):
    """toggle_server открывает доступ ко всем installed VPN сервера и зовёт reconcile_users."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        member_user = await make_user(s, phone="+79002223344")
        g = await make_group(s, owner_id=owner.id, token="grp-srv")
        await add_member(s, group_id=g.id, user_id=member_user.id, display_name="Участник")
        srv = await make_server(s, owner_id=owner.id, installed_vpns=("amnezia", "outline"))
    svc = GroupService(uow, settings)
    # Act
    result = await svc.toggle_server(owner.id, g.id, srv.id)
    # Assert
    assert sorted(result["access"]["servers"][srv.id]) == ["amnezia", "outline"]
    assert reconcile_calls == [[member_user.id]]


async def test__toggle_server__second_call_revokes_access(uow, settings, session_maker, reconcile_calls):
    """Повторный toggle_server полностью снимает доступ к серверу."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        g = await make_group(s, owner_id=owner.id, token="grp-srv2")
        srv = await make_server(s, owner_id=owner.id, installed_vpns=("amnezia",))
    svc = GroupService(uow, settings)
    await svc.toggle_server(owner.id, g.id, srv.id)  # открыли доступ
    # Act
    result = await svc.toggle_server(owner.id, g.id, srv.id)  # сняли
    # Assert
    assert srv.id not in result["access"]["servers"]


async def test__toggle_server_vpn__adds_single_vpn_and_calls_reconcile(uow, settings, session_maker, reconcile_calls):
    """toggle_server_vpn добавляет конкретный тип VPN и вызывает reconcile_users."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001112233")
        member_user = await make_user(s, phone="+79002223344")
        g = await make_group(s, owner_id=owner.id, token="grp-vpn")
        await add_member(s, group_id=g.id, user_id=member_user.id, display_name="Участник")
        srv = await make_server(s, owner_id=owner.id, installed_vpns=("amnezia", "outline"))
    svc = GroupService(uow, settings)
    # Act
    result = await svc.toggle_server_vpn(owner.id, g.id, srv.id, "amnezia")
    # Assert
    assert result["access"]["servers"][srv.id] == ["amnezia"]
    assert reconcile_calls == [[member_user.id]]


async def test__toggle_server_vpn__removes_existing_vpn(uow, settings, session_maker, reconcile_calls):
    """toggle_server_vpn для уже выданного типа снимает именно его, остальные остаются."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s)
        g = await make_group(s, owner_id=owner.id, token="grp-vpn2")
        srv = await make_server(s, owner_id=owner.id, installed_vpns=("amnezia", "outline"))
        await grant_group_server(s, group_id=g.id, server_id=srv.id, vpn_type="amnezia")
        await grant_group_server(s, group_id=g.id, server_id=srv.id, vpn_type="outline")
    svc = GroupService(uow, settings)
    # Act
    result = await svc.toggle_server_vpn(owner.id, g.id, srv.id, "amnezia")
    # Assert
    assert result["access"]["servers"][srv.id] == ["outline"]


@pytest.mark.parametrize(
    "action",
    [
        pytest.param(lf("toggle_pool_action"), id="toggle_pool"),
        pytest.param(lf("toggle_server_action"), id="toggle_server"),
    ],
)
async def test__toggle_access__always_calls_reconcile(uow, settings, session_maker, reconcile_calls, action):
    """Любое переключение доступа (пул/сервер) идемпотентно зовёт reconcile_users."""
    # Arrange / Act — сетап и вызов инкапсулированы в фикстуре-действии
    await action(uow, settings, session_maker)
    # Assert
    assert len(reconcile_calls) == 1


@pytest.fixture
def toggle_pool_action():
    """Фабрика действия: создать группу+пул и переключить доступ к пулу."""

    async def _run(uow, settings, session_maker):
        async with seed(session_maker) as s:
            owner = await make_user(s)
            g = await make_group(s, owner_id=owner.id, token="grp-act-pool")
            pool = await make_pool(s, owner_id=owner.id)
        await GroupService(uow, settings).toggle_pool(owner.id, g.id, pool.id)

    return _run


@pytest.fixture
def toggle_server_action():
    """Фабрика действия: создать группу+сервер и переключить доступ к серверу."""

    async def _run(uow, settings, session_maker):
        async with seed(session_maker) as s:
            owner = await make_user(s)
            g = await make_group(s, owner_id=owner.id, token="grp-act-srv")
            srv = await make_server(s, owner_id=owner.id, installed_vpns=("amnezia",))
        await GroupService(uow, settings).toggle_server(owner.id, g.id, srv.id)

    return _run
