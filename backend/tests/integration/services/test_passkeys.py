"""Интеграционные тесты ключей доступа: регистрация, вход по passkey, управление своими ключами.

Ответы браузера строит FakeAuthenticator (настоящая EC-подпись), так что проходит весь путь
проверки py_webauthn, а не моки.
"""

from __future__ import annotations

import json
import time

import pytest
from sqlalchemy import select, update

from tests.factories.orm import add_member, make_group, make_user, seed
from tests.factories.webauthn import AAGUID_ICLOUD, FakeAuthenticator
from vpnhub.core.errors import BadRequest, NotFound, Unauthorized
from vpnhub.infra.db.orm import models as m
from vpnhub.services.auth import AuthService, Identity
from vpnhub.services.passkeys import PasskeyService

pytestmark = pytest.mark.integration

ORIGIN = "https://vpn.example.com"
UA_MAC_CHROME = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) Chrome/130.0 Safari/537.36"


@pytest.fixture
def https_settings(settings):
    settings.base_url = ORIGIN
    return settings


def _ident(user: m.User, kind: str = "user") -> Identity:
    return Identity(kind, user.id, user.name, user.phone, "owner" if kind == "admin" else "member")


async def _register(
    uow, settings, user: m.User, auth: FakeAuthenticator | None = None, kind: str = "user"
) -> tuple[FakeAuthenticator, dict]:
    auth = auth or FakeAuthenticator()
    svc = PasskeyService(uow, settings)
    opts = await svc.registration_options(user.id)
    pk = await svc.register(_ident(user, kind), opts["challengeId"], auth.create(opts["publicKey"]), ua=UA_MAC_CHROME)
    return auth, pk


async def _login(uow, settings, auth: FakeAuthenticator, **get_kwargs) -> str:
    svc = AuthService(uow, settings)
    opts = await svc.passkey_login_options()
    return await svc.passkey_login(opts["challengeId"], auth.get(opts["publicKey"], **get_kwargs), ip="203.0.113.5")


async def _audit_types(session_maker) -> list[tuple[str, str | None]]:
    async with session_maker() as s:
        rows = (await s.execute(select(m.AuditEvent).order_by(m.AuditEvent.at))).scalars().all()
        return [(e.type, e.meta_json) for e in rows]


# ---- регистрация ------------------------------------------------------------


async def test__register__valid_attestation__stores_passkey_with_default_name(uow, https_settings, session_maker):
    """Корректный ответ create() → ключ сохранён, имя по AAGUID, событие passkey.add в аудите."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
    # Act
    auth, pk = await _register(uow, https_settings, user)
    # Assert
    assert pk["name"] == "iCloud Keychain"
    async with uow.query() as tx:
        stored = await tx.passkeys.by_credential_id(auth.credential_id)
        assert stored is not None
        assert stored.user_id == user.id
        assert stored.aaguid == AAGUID_ICLOUD
        assert stored.transports == ["internal", "hybrid"]
    assert ("passkey.add", json.dumps({"name": "iCloud Keychain"}, ensure_ascii=False)) in await _audit_types(
        session_maker
    )


async def test__register__unknown_aaguid__names_after_browser_and_os(uow, https_settings, session_maker):
    """Неизвестный AAGUID → имя «браузер · ОС» из User-Agent."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    _, pk = await _register(uow, https_settings, user, FakeAuthenticator(aaguid="00000000-0000-0000-0000-000000000000"))
    assert pk["name"] == "Chrome · macOS"


async def test__register_options__excludes_existing_credentials(uow, https_settings, session_maker):
    """Уже добавленный ключ попадает в excludeCredentials — браузер не создаст дубль."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    auth, _ = await _register(uow, https_settings, user)
    opts = await PasskeyService(uow, https_settings).registration_options(user.id)
    excluded = [c["id"] for c in opts["publicKey"]["excludeCredentials"]]
    assert auth.get({"challenge": "x"})["id"] in excluded
    sel = opts["publicKey"]["authenticatorSelection"]
    assert sel["residentKey"] == "required"
    assert sel["userVerification"] == "required"


async def test__register__replayed_response__rejected(uow, https_settings, session_maker):
    """Тот же ответ второй раз: челлендж уже сожжён → BadRequest."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    svc = PasskeyService(uow, https_settings)
    auth = FakeAuthenticator()
    opts = await svc.registration_options(user.id)
    cred = auth.create(opts["publicKey"])
    await svc.register(_ident(user), opts["challengeId"], cred)
    with pytest.raises(BadRequest) as exc:
        await svc.register(_ident(user), opts["challengeId"], cred)
    assert exc.value.key == "passkey.challenge_expired"


async def test__register__challenge_of_other_user__rejected(uow, https_settings, session_maker):
    """Челлендж, выданный одному пользователю, не годится для регистрации ключа другому."""
    async with seed(session_maker) as s:
        alice = await make_user(s, phone="+79001112233")
        bob = await make_user(s, phone="+79002223344", name="Боб")
    svc = PasskeyService(uow, https_settings)
    opts = await svc.registration_options(alice.id)
    with pytest.raises(BadRequest) as exc:
        await svc.register(_ident(bob), opts["challengeId"], FakeAuthenticator().create(opts["publicKey"]))
    assert exc.value.key == "passkey.challenge_expired"


async def test__register__wrong_origin__rejected(uow, https_settings, session_maker):
    """Ответ, подписанный для чужого origin (фишинговый сайт), не принимается."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    svc = PasskeyService(uow, https_settings)
    opts = await svc.registration_options(user.id)
    cred = FakeAuthenticator().create(opts["publicKey"], origin="https://evil.example.net")
    with pytest.raises(BadRequest) as exc:
        await svc.register(_ident(user), opts["challengeId"], cred)
    assert exc.value.key == "passkey.verification_failed"


async def test__register__without_user_verification__rejected(uow, https_settings, session_maker):
    """Ключ заменяет пароль, поэтому без user verification (только касание) не регистрируем."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    svc = PasskeyService(uow, https_settings)
    opts = await svc.registration_options(user.id)
    with pytest.raises(BadRequest):
        await svc.register(_ident(user), opts["challengeId"], FakeAuthenticator().create(opts["publicKey"], uv=False))


async def test__register__expired_challenge__rejected(uow, https_settings, session_maker):
    """Просроченный челлендж → BadRequest, даже если ответ корректный."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    svc = PasskeyService(uow, https_settings)
    opts = await svc.registration_options(user.id)
    async with seed(session_maker) as s:
        await s.execute(update(m.WebauthnChallenge).values(expires_at=time.time() - 1))
    with pytest.raises(BadRequest) as exc:
        await svc.register(_ident(user), opts["challengeId"], FakeAuthenticator().create(opts["publicKey"]))
    assert exc.value.key == "passkey.challenge_expired"


async def test__registration_options__base_url_on_plain_http_ip__unavailable(uow, settings, session_maker):
    """http://<IP> — не secure context и не годится как RP ID → ключи недоступны."""
    settings.base_url = "http://203.0.113.10:8000"
    async with seed(session_maker) as s:
        user = await make_user(s)
    with pytest.raises(BadRequest) as exc:
        await PasskeyService(uow, settings).registration_options(user.id)
    assert exc.value.key == "passkey.unavailable"
    assert PasskeyService(uow, settings).config() == {"available": False, "origin": None, "rpId": None}


# ---- вход ---------------------------------------------------------------------


async def test__passkey_login__registered_key__issues_user_session(uow, https_settings, session_maker):
    """Зарегистрированный ключ → сессия пользователя, счётчик и last_used обновлены, вход в аудите."""
    # Arrange
    async with seed(session_maker) as s:
        user = await make_user(s)
    auth, _ = await _register(uow, https_settings, user)
    # Act
    token = await _login(uow, https_settings, auth)
    # Assert
    ident = await AuthService(uow, https_settings).resolve(token)
    assert ident is not None
    assert (ident.kind, ident.id) == ("user", user.id)
    async with uow.query() as tx:
        pk = await tx.passkeys.by_credential_id(auth.credential_id)
        assert pk.sign_count == 1
        assert pk.last_used_at is not None
    events = await _audit_types(session_maker)
    login_meta = [json.loads(meta) for t, meta in events if t == "auth.login"]
    assert login_meta == [{"ip": "203.0.113.5", "method": "passkey"}]


async def test__passkey_login__admin__issues_admin_session(uow, https_settings, session_maker):
    """Ключ администратора → admin-сессия, как и при входе по паролю."""
    async with seed(session_maker) as s:
        admin = await make_user(s, admin=True)
    auth, _ = await _register(uow, https_settings, admin, kind="admin")
    token = await _login(uow, https_settings, auth)
    ident = await AuthService(uow, https_settings).resolve(token)
    assert ident is not None
    assert ident.kind == "admin"


async def test__passkey_login__replayed_assertion__rejected(uow, https_settings, session_maker):
    """Повтор того же подписанного ответа: челлендж уже потрачен → Unauthorized."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    auth, _ = await _register(uow, https_settings, user)
    svc = AuthService(uow, https_settings)
    opts = await svc.passkey_login_options()
    cred = auth.get(opts["publicKey"])
    await svc.passkey_login(opts["challengeId"], cred)
    with pytest.raises(Unauthorized) as exc:
        await svc.passkey_login(opts["challengeId"], cred)
    assert exc.value.key == "passkey.challenge_expired"


async def test__passkey_login__failed_attempt_still_burns_challenge(uow, https_settings, session_maker):
    """Неудачная проверка тоже расходует челлендж — перебор на одном челлендже невозможен."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    auth, _ = await _register(uow, https_settings, user)
    svc = AuthService(uow, https_settings)
    opts = await svc.passkey_login_options()
    with pytest.raises(Unauthorized):
        await svc.passkey_login(opts["challengeId"], auth.get(opts["publicKey"], origin="https://evil.example.net"))
    with pytest.raises(Unauthorized) as exc:
        await svc.passkey_login(opts["challengeId"], auth.get(opts["publicKey"]))
    assert exc.value.key == "passkey.challenge_expired"


async def test__passkey_login__unknown_credential__rejected(uow, https_settings, session_maker):
    """Ключ, которого нет в базе → Unauthorized(unknown_credential)."""
    stranger = FakeAuthenticator()
    stranger.user_handle = b"nobody"
    with pytest.raises(Unauthorized) as exc:
        await _login(uow, https_settings, stranger)
    assert exc.value.key == "passkey.unknown_credential"


async def test__passkey_login__user_handle_mismatch__rejected(uow, https_settings, session_maker):
    """userHandle в ответе не совпадает с владельцем ключа → отказ."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    auth, _ = await _register(uow, https_settings, user)
    with pytest.raises(Unauthorized) as exc:
        await _login(uow, https_settings, auth, user_handle=b"someone-else")
    assert exc.value.key == "passkey.unknown_credential"


async def test__passkey_login__sign_count_regression__rejected(uow, https_settings, session_maker):
    """Счётчик подписи откатился (признак клона ключа) → вход отклонён."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    auth, _ = await _register(uow, https_settings, user)
    await _login(uow, https_settings, auth, sign_count=5)
    with pytest.raises(Unauthorized) as exc:
        await _login(uow, https_settings, auth, sign_count=3)
    assert exc.value.key == "passkey.verification_failed"


async def test__passkey_login__synced_passkey_zero_counter__allowed_repeatedly(uow, https_settings, session_maker):
    """Синхронизируемые passkeys всегда шлют счётчик 0 — это не клон, вход разрешён каждый раз."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    auth, _ = await _register(uow, https_settings, user, FakeAuthenticator(counter=False))
    assert await _login(uow, https_settings, auth)
    assert await _login(uow, https_settings, auth)


async def test__passkey_login__without_user_verification__rejected(uow, https_settings, session_maker):
    """Assertion без user verification не заменяет пароль → отказ."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    auth, _ = await _register(uow, https_settings, user)
    with pytest.raises(Unauthorized) as exc:
        await _login(uow, https_settings, auth, uv=False)
    assert exc.value.key == "passkey.verification_failed"


async def test__passkey_login__blocked_user__rejected(uow, https_settings, session_maker):
    """Заблокированный пользователь не войдёт и по ключу."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    auth, _ = await _register(uow, https_settings, user)
    async with seed(session_maker) as s:
        await s.execute(update(m.User).where(m.User.id == user.id).values(status="blocked"))
    with pytest.raises(Unauthorized) as exc:
        await _login(uow, https_settings, auth)
    assert exc.value.key == "auth.account_blocked"


async def test__passkey_login__pending_user_without_invite__rejected(uow, https_settings, session_maker):
    """Неподтверждённая учётка без приглашения → «ожидает подтверждения»."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    auth, _ = await _register(uow, https_settings, user)
    async with seed(session_maker) as s:
        await s.execute(update(m.User).where(m.User.id == user.id).values(status="pending"))
    with pytest.raises(Unauthorized) as exc:
        await _login(uow, https_settings, auth)
    assert exc.value.key == "auth.account_pending"


async def test__passkey_login__pending_user_with_invite__activated(uow, https_settings, session_maker):
    """Pending + приглашение по телефону → приглашение привязано, учётка активна, вход успешен."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79009998877", name="Владелец")
        user = await make_user(s)
    auth, _ = await _register(uow, https_settings, user)
    async with seed(session_maker) as s:
        await s.execute(update(m.User).where(m.User.id == user.id).values(status="pending"))
        group = await make_group(s, owner_id=owner.id)
        await add_member(s, group_id=group.id, phone=user.phone, status="invited")
    token = await _login(uow, https_settings, auth)
    ident = await AuthService(uow, https_settings).resolve(token)
    assert ident is not None
    assert ident.id == user.id


async def test__password_login__audit_meta_unchanged(uow, https_settings, session_maker):
    """Рефакторинг общих правил входа не меняет аудит входа по паролю (метода в meta нет)."""
    async with seed(session_maker) as s:
        await make_user(s)
    await AuthService(uow, https_settings).login("+79001112233", "Passw0rd!", ip="198.51.100.1")
    events = await _audit_types(session_maker)
    assert [json.loads(meta) for t, meta in events if t == "auth.login"] == [{"ip": "198.51.100.1"}]


# ---- управление ключами -------------------------------------------------------


async def test__list__returns_only_own_passkeys(uow, https_settings, session_maker):
    async with seed(session_maker) as s:
        alice = await make_user(s, phone="+79001112233")
        bob = await make_user(s, phone="+79002223344", name="Боб")
    await _register(uow, https_settings, alice)
    svc = PasskeyService(uow, https_settings)
    assert len(await svc.list(alice.id)) == 1
    assert await svc.list(bob.id) == []


async def test__rename__own_passkey__updates_name(uow, https_settings, session_maker):
    async with seed(session_maker) as s:
        user = await make_user(s)
    _, pk = await _register(uow, https_settings, user)
    renamed = await PasskeyService(uow, https_settings).rename(user.id, pk["id"], "  Рабочий ноутбук  ")
    assert renamed["name"] == "Рабочий ноутбук"


async def test__rename__empty_name__rejected(uow, https_settings, session_maker):
    async with seed(session_maker) as s:
        user = await make_user(s)
    _, pk = await _register(uow, https_settings, user)
    with pytest.raises(BadRequest):
        await PasskeyService(uow, https_settings).rename(user.id, pk["id"], "   ")


async def test__rename_and_delete__someone_elses_passkey__not_found(uow, https_settings, session_maker):
    """Чужой ключ нельзя ни переименовать, ни удалить — для постороннего его просто нет."""
    async with seed(session_maker) as s:
        alice = await make_user(s, phone="+79001112233")
        bob = await make_user(s, phone="+79002223344", name="Боб")
    _, pk = await _register(uow, https_settings, alice)
    svc = PasskeyService(uow, https_settings)
    with pytest.raises(NotFound):
        await svc.rename(bob.id, pk["id"], "Мой")
    with pytest.raises(NotFound):
        await svc.delete(_ident(bob), pk["id"])
    assert len(await svc.list(alice.id)) == 1


async def test__delete__own_passkey__removed_and_login_no_longer_works(uow, https_settings, session_maker):
    """Удалённый ключ больше не пускает; событие passkey.remove в аудите."""
    async with seed(session_maker) as s:
        user = await make_user(s)
    auth, pk = await _register(uow, https_settings, user)
    await PasskeyService(uow, https_settings).delete(_ident(user), pk["id"])
    assert await PasskeyService(uow, https_settings).list(user.id) == []
    assert "passkey.remove" in [t for t, _ in await _audit_types(session_maker)]
    with pytest.raises(Unauthorized) as exc:
        await _login(uow, https_settings, auth)
    assert exc.value.key == "passkey.unknown_credential"


async def test__issue_challenge__purges_expired_rows(uow, https_settings, session_maker):
    """Выдача нового челленджа подчищает протухшие — таблица не растёт от брошенных попыток."""
    svc = AuthService(uow, https_settings)
    await svc.passkey_login_options()
    async with seed(session_maker) as s:
        await s.execute(update(m.WebauthnChallenge).values(expires_at=time.time() - 1))
    await svc.passkey_login_options()
    async with session_maker() as s:
        rows = (await s.execute(select(m.WebauthnChallenge))).scalars().all()
    assert len(rows) == 1
