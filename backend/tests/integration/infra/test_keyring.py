"""Интеграционные тесты keyring: резолвинг мастер-ключа, apply_master, перешифровка, backup-ключи.

Модуль keyring держит ГЛОБАЛЬНОЕ состояние `_state` (мастер-ключ процесса) — сбрасываем его
autouse-фикстурой, чтобы тесты не влияли друг на друга.
"""

from __future__ import annotations

import pytest

import vpnhub.infra.keyring as kr
from tests.factories.orm import make_server, make_user, seed
from vpnhub.api.config import Settings
from vpnhub.infra.security import (
    DEFAULT_INSECURE_SECRET_KEY,
    backup_secret,
    data_secret,
    decrypt_secret,
    encrypt_secret,
)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def _reset_keyring_state() -> None:
    """Сбрасывает глобальное _state keyring до/после теста (изоляция процессного состояния)."""
    kr._state.update(master=None, insecure=True, source="unset")
    try:
        yield
    finally:
        kr._state.update(master=None, insecure=True, source="unset")


@pytest.fixture
def local_settings() -> Settings:
    """Свежий Settings без мастер-ключа (без чтения env/.env); secret_key = дефолтный sentinel."""
    return Settings(_env_file=None, master_key=None)


async def test__resolve_keys__default_secret_no_master__source_unset(uow, local_settings):
    """Дефолтный secret_key и master_key=None → мастер не задан: source 'unset', has_master False."""
    # Arrange
    # local_settings уже с дефолтным ключом и master_key=None; БД пуста.

    # Act
    await kr.resolve_keys(uow, local_settings)

    # Assert
    assert kr.master_source() == "unset"
    assert kr.has_master() is False
    assert kr.master_insecure() is True
    # secret_key не перезаписан (мастер не выведен)
    assert local_settings.secret_key == DEFAULT_INSECURE_SECRET_KEY


async def test__resolve_keys__secret_key_not_from_env__stays_sentinel(uow, monkeypatch):
    """secret_key НЕ читается из env (легаси VPNHUB_SECRET_KEY удалён): без мастера остаётся sentinel."""
    # Arrange — даже если выставить старую env-переменную, она игнорируется.
    monkeypatch.setenv("VPNHUB_SECRET_KEY", "attacker-supplied-legacy-key")
    settings = Settings(_env_file=None, master_key=None)
    assert settings.secret_key == DEFAULT_INSECURE_SECRET_KEY  # env не подхватился

    # Act
    await kr.resolve_keys(uow, settings)

    # Assert — без мастера: source 'unset', ключ форсированно = sentinel (никакой утечки env-значения)
    assert kr.master_source() == "unset"
    assert kr.master_insecure() is True
    assert kr.has_master() is False
    assert settings.secret_key == DEFAULT_INSECURE_SECRET_KEY


async def test__resolve_keys__env_master_set__applies_master_from_env(uow, local_settings):
    """settings.master_key задан → apply_master с source 'env', secret_key = data_secret(master)."""
    # Arrange
    local_settings.master_key = "topsecret-master-from-env"

    # Act
    await kr.resolve_keys(uow, local_settings)

    # Assert
    assert kr.master_source() == "env"
    assert kr.has_master() is True
    assert local_settings.secret_key == data_secret("topsecret-master-from-env")


async def test__resolve_keys__db_master_set__applies_master_from_db(uow, local_settings, session_maker):
    """Мастер в БД (settings.master_key) при пустом env → apply_master с source 'db'."""
    # Arrange
    async with seed(session_maker) as s:
        s.add(kr.m.Setting(key=kr._MASTER_SETTING, value="master-stored-in-db"))

    # Act
    await kr.resolve_keys(uow, local_settings)

    # Assert
    assert kr.master_source() == "db"
    assert kr.has_master() is True
    assert local_settings.secret_key == data_secret("master-stored-in-db")


async def test__resolve_keys__env_master_takes_priority_over_db(uow, local_settings, session_maker):
    """При заданном env-мастере ключ из БД игнорируется: source 'env', ключ из env."""
    # Arrange
    local_settings.master_key = "env-wins-master"
    async with seed(session_maker) as s:
        s.add(kr.m.Setting(key=kr._MASTER_SETTING, value="db-loser-master"))

    # Act
    await kr.resolve_keys(uow, local_settings)

    # Assert
    assert kr.master_source() == "env"
    assert local_settings.secret_key == data_secret("env-wins-master")


async def test__apply_master__persist_true__saves_master_to_db(uow, local_settings):
    """apply_master(persist=True) сохраняет мастер-ключ в settings.master_key (БД)."""
    # Arrange
    master = "persist-me-master-key"

    # Act
    await kr.apply_master(uow, local_settings, master, source="setup", persist=True)

    # Assert
    async with uow.query() as tx:
        stored = await tx.settings.get_value(kr._MASTER_SETTING)
    assert stored == master


async def test__apply_master__sets_secret_key_to_data_secret(uow, local_settings):
    """apply_master выставляет settings.secret_key = data_secret(master) и source из аргумента."""
    # Arrange
    master = "derive-data-key-master"

    # Act
    await kr.apply_master(uow, local_settings, master, source="setup", persist=False)

    # Assert
    assert local_settings.secret_key == data_secret(master)
    assert kr.master_source() == "setup"
    assert kr.has_master() is True


@pytest.mark.parametrize(
    ("master", "expected_insecure"),
    [
        (DEFAULT_INSECURE_SECRET_KEY, True),
        ("strong-custom-master", False),
    ],
)
async def test__apply_master__insecure_flag__reflects_whether_master_is_default(
    uow, local_settings, master, expected_insecure
):
    """insecure-флаг отражает, является ли применённый мастер-ключ дефолтным (небезопасным)."""
    # Arrange / Act
    await kr.apply_master(uow, local_settings, master, source="setup", persist=False)

    # Assert
    assert kr.master_insecure() is expected_insecure


async def test__apply_master__key_change__reencrypts_existing_server_secret(uow, local_settings, session_maker):
    """При смене data-ключа существующий ssh_secret_encrypted перешифровывается на новый ключ."""
    # Arrange
    old_secret = local_settings.secret_key  # ключ ДО применения мастера
    async with seed(session_maker) as s:
        user = await make_user(s)
        server = await make_server(s, owner_id=user.id)
        server.ssh_secret_encrypted = encrypt_secret(old_secret, "topsecret")
        server_id = server.id

    # Act
    await kr.apply_master(uow, local_settings, "rotate-to-this-master", source="setup", persist=True)

    # Assert
    async with uow.query() as tx:
        migrated = await tx.servers.get(server_id)
    # старым ключом больше не расшифровывается, а новым (settings.secret_key) — даёт исходный секрет
    assert decrypt_secret(old_secret, migrated.ssh_secret_encrypted) == ""
    assert decrypt_secret(local_settings.secret_key, migrated.ssh_secret_encrypted) == "topsecret"


async def test__apply_master__same_master_twice__does_not_reencrypt(uow, local_settings, session_maker):
    """Повторное применение того же мастера (отпечаток data-ключа совпал) не трогает существующие шифры."""
    # Arrange
    old_secret = local_settings.secret_key
    async with seed(session_maker) as s:
        user = await make_user(s)
        server = await make_server(s, owner_id=user.id)
        server.ssh_secret_encrypted = encrypt_secret(old_secret, "topsecret")
        server_id = server.id
    master = "stable-master-key"
    await kr.apply_master(uow, local_settings, master, source="setup", persist=True)
    async with uow.query() as tx:
        after_first = (await tx.servers.get(server_id)).ssh_secret_encrypted

    # Act — второй раз тем же мастером: fp совпадает, _reencrypt_all не вызывается
    await kr.apply_master(uow, local_settings, master, source="setup", persist=True)

    # Assert — шифротекст побайтово не изменился (перешифровки не было) и остаётся валидным
    async with uow.query() as tx:
        after_second = (await tx.servers.get(server_id)).ssh_secret_encrypted
    assert after_second == after_first
    assert decrypt_secret(local_settings.secret_key, after_second) == "topsecret"


async def test__apply_master__persist_true__stores_data_key_fingerprint(uow, local_settings):
    """Первое применение мастера сохраняет отпечаток data-ключа в settings (data_key_fp)."""
    # Arrange
    master = "fp-master-key"

    # Act
    await kr.apply_master(uow, local_settings, master, source="setup", persist=True)

    # Assert
    async with uow.query() as tx:
        fp = await tx.settings.get_value(kr._FP_SETTING)
    assert fp is not None
    assert len(fp) == 16


async def test__backup_key__master_set__returns_backup_subkey(uow, local_settings):
    """После применения мастера backup_key() == backup_secret(master) (детерминированный под-ключ)."""
    # Arrange
    master = "backup-source-master"
    await kr.apply_master(uow, local_settings, master, source="setup", persist=False)

    # Act
    result = kr.backup_key()

    # Assert
    assert result == backup_secret(master)


async def test__backup_key__no_master__returns_none():
    """Без применённого мастера backup_key() возвращает None."""
    # Arrange
    # autouse-фикстура гарантирует _state без мастера.

    # Act
    result = kr.backup_key()

    # Assert
    assert result is None


async def test__derive_backup_key__same_candidate__deterministic():
    """derive_backup_key детерминирован и равен backup_secret для того же кандидата."""
    # Arrange
    candidate = "user-entered-master-on-restore"

    # Act
    first = kr.derive_backup_key(candidate)
    second = kr.derive_backup_key(candidate)

    # Assert
    assert first == second == backup_secret(candidate)
