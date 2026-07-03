"""Мастер-ключ и его применение (резолвинг при старте + ротация в рантайме).

Один мастер-ключ восстановления → HKDF даёт под-ключи (data / backup). Источники по приоритету:
env `VPNHUB_MASTER_KEY` → БД `settings.master_key`. Fresh-инсталл задаёт ключ на setup-экране.

`data`-под-ключ кладём в `settings.secret_key`, откуда его синхронно читают все сервисы шифрования
(servers/configs/provisioning) — их код трогать не нужно. При смене data-ключа существующие
`*_encrypted`-поля перешифровываются (миграция), результат помечается «отпечатком», чтобы не
сканировать заново на каждом старте.
"""

from __future__ import annotations

import structlog
from sqlalchemy import select

from vpnhub.api.config import Settings
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.security import (
    DEFAULT_INSECURE_SECRET_KEY,
    backup_secret,
    data_secret,
    decrypt_secret,
    encrypt_secret,
    hash_token,
    is_default_master_key,
)
from vpnhub.infra.uow import Uow

log = structlog.get_logger(__name__)

_MASTER_SETTING = "master_key"
_FP_SETTING = "data_key_fp"

# Состояние процесса: резолвнутый мастер-ключ и метаданные.
_state: dict = {"master": None, "insecure": True, "source": "unset"}


def has_master() -> bool:
    return _state["master"] is not None


def master_insecure() -> bool:
    return bool(_state["insecure"])


def master_source() -> str:
    return str(_state["source"])


def backup_key() -> str | None:
    """Под-ключ для шифрования бэкапов (или None, если мастер ещё не задан)."""
    master = _state["master"]
    return backup_secret(master) if master else None


def derive_backup_key(candidate: str) -> str:
    """Backup-под-ключ из произвольного мастер-ключа (для restore: пользователь вводит мастер)."""
    return backup_secret(candidate)


async def _reencrypt_all(uow: Uow, old_secret: str, new_secret: str) -> int:
    """Перешифровать все Fernet-поля со старого data-ключа на новый. Токены, что не расшифровались
    старым ключом, пропускаем (значит они уже под новым ключом или чужие)."""
    n = 0
    async with uow.transaction() as tx:
        for s in await tx.servers.all():
            if s.ssh_secret_encrypted:
                plain = decrypt_secret(old_secret, s.ssh_secret_encrypted)
                if plain:
                    s.ssh_secret_encrypted = encrypt_secret(new_secret, plain)
                    n += 1
        for dc in (await tx.session.execute(select(m.DeviceConfig))).scalars().all():
            if dc.client_secret_encrypted:
                plain = decrypt_secret(old_secret, dc.client_secret_encrypted)
                if plain:
                    dc.client_secret_encrypted = encrypt_secret(new_secret, plain)
                    n += 1
        for sp in (await tx.session.execute(select(m.ServerProtocol))).scalars().all():
            if sp.material_encrypted:
                plain = decrypt_secret(old_secret, sp.material_encrypted)
                if plain:
                    sp.material_encrypted = encrypt_secret(new_secret, plain)
                    n += 1
    return n


async def apply_master(uow: Uow, settings: Settings, master: str, *, source: str, persist: bool) -> None:
    """Применить мастер-ключ: (опц.) сохранить в БД, вывести data-ключ, при смене — перешифровать."""
    old_secret = settings.secret_key
    new_secret = data_secret(master)
    fp = hash_token(new_secret)[:16]

    if persist:
        async with uow.transaction() as tx:
            await tx.settings.set_value(_MASTER_SETTING, master)

    async with uow.query() as tx:
        saved_fp = await tx.settings.get_value(_FP_SETTING)

    if saved_fp != fp:
        migrated = await _reencrypt_all(uow, old_secret, new_secret)
        async with uow.transaction() as tx:
            await tx.settings.set_value(_FP_SETTING, fp)
        if migrated:
            log.info("secrets_reencrypted", count=migrated)

    settings.secret_key = new_secret
    _state.update(master=master, insecure=is_default_master_key(master), source=source)


def startup_key_action(*, insecure: bool, setup_pending: bool, is_https: bool) -> str:
    """Решение на старте по состоянию мастер-ключа (чистая логика, отдельно тестируется).

    - ``ok``    — задан безопасный мастер-ключ;
    - ``setup`` — ключ дефолтный, но админа ещё нет: setup-экран задаст ключ до первых секретов;
    - ``block`` — дефолтный ключ на боевом (https) с уже существующим админом: отказ старта,
      иначе секреты шифровались бы известным всем ключом из репозитория;
    - ``warn``  — дефолтный ключ на http (dev/локально) с существующим админом: предупреждение.
    """
    if not insecure:
        return "ok"
    if setup_pending:
        return "setup"
    return "block" if is_https else "warn"


async def resolve_keys(uow: Uow, settings: Settings) -> None:
    """Определить мастер-ключ при старте: env → БД → (не задан → setup)."""
    if settings.master_key:
        await apply_master(uow, settings, settings.master_key, source="env", persist=False)
        return
    async with uow.query() as tx:
        db_master = await tx.settings.get_value(_MASTER_SETTING)
    if db_master:
        await apply_master(uow, settings, db_master, source="db", persist=False)
        return
    # Мастер не задан: свежая установка задаст его на setup-экране (тогда выведется data-ключ).
    # Единственный источник ключа шифрования — мастер; защитно держим небезопасный sentinel,
    # чтобы никакое значение не «протекло» в data-ключ до настройки мастера.
    settings.secret_key = DEFAULT_INSECURE_SECRET_KEY
    _state.update(master=None, insecure=True, source="unset")
