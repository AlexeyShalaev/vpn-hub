"""Резервные копии: логический дамп на уровне приложения (не зависит от версии Postgres).

Бэкап = строки всех наших таблиц (через SQLAlchemy) + текущая alembic-ревизия, сериализованные в
JSON, сжатые gzip и зашифрованные парольной фразой (выводится из мастер-ключа). Файлы лежат в
`settings.backup_dir` (смонтированный том). Ключ резолвится из keyring/мастер-ключа, иначе из env
`VPNHUB_BACKUP_KEY` / таблицы `settings` (`backup_key`). Частота авто-бэкапа — там же
(`backup_frequency`: off|daily|weekly|monthly).

В отличие от pg_dump-подхода, логический бэкап **не требует совпадения версий Postgres** и вообще
не нуждается в `pg_dump`/`psql`: мы владеем схемой (модели + миграции). Restore возможен только на
совпадающей alembic-ревизии (иначе — понятная ошибка).

Формат файла `vpnhub-<kind>-<ts>.vhb`: `VHB1` + salt(16) + nonce(12) + AES-256-GCM(gzip(json)).
"""

from __future__ import annotations

import base64
import gzip
import json
import os
import time
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import structlog
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from sqlalchemy import Date, DateTime, Numeric, select, text
from sqlalchemy_foundation_kit import Base

from vpnhub.api.config import Settings
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra import keyring
from vpnhub.infra.db.orm import models as _models  # noqa: F401  (регистрирует таблицы в Base.metadata)
from vpnhub.infra.security import is_default_master_key
from vpnhub.infra.uow import Uow

log = structlog.get_logger(__name__)

_MAGIC = b"VHB1"
_SALT_LEN = 16
_NONCE_LEN = 12
_SCRYPT_N = 2**14
_SCRYPT_R = 8
_SCRYPT_P = 1

_FREQ_DAYS = {"daily": 1, "weekly": 7, "monthly": 30}
_DEFAULT_FREQ = "weekly"
_KEEP_AUTO = 8  # сколько последних авто-бэкапов держим; старые удаляем

_KEY_SETTING = "backup_key"
_FREQ_SETTING = "backup_frequency"


def _derive(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return kdf.derive(passphrase.encode("utf-8"))


def _encrypt(plaintext: bytes, passphrase: str) -> bytes:
    salt = os.urandom(_SALT_LEN)
    nonce = os.urandom(_NONCE_LEN)
    ct = AESGCM(_derive(passphrase, salt)).encrypt(nonce, plaintext, _MAGIC)
    return _MAGIC + salt + nonce + ct


def _decrypt(blob: bytes, passphrase: str) -> bytes:
    head = 4 + _SALT_LEN + _NONCE_LEN
    if len(blob) < head or blob[:4] != _MAGIC:
        raise BadRequest(key="backup.not_a_backup_file")
    salt = blob[4 : 4 + _SALT_LEN]
    nonce = blob[4 + _SALT_LEN : head]
    try:
        return AESGCM(_derive(passphrase, salt)).decrypt(nonce, blob[head:], _MAGIC)
    except InvalidTag:
        raise BadRequest(key="backup.wrong_key_or_corrupted") from None


def _ser(v: object) -> object:
    if isinstance(v, datetime | date):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, bytes | bytearray | memoryview):
        return {"__b64__": base64.b64encode(bytes(v)).decode()}
    return v


def _deser(col_type: object, v: object) -> object:
    if v is None:
        return None
    if isinstance(v, dict) and "__b64__" in v:
        return base64.b64decode(v["__b64__"])
    if isinstance(col_type, DateTime) and isinstance(v, str):
        return datetime.fromisoformat(v)
    if isinstance(col_type, Date) and isinstance(v, str):
        return date.fromisoformat(v)
    if isinstance(col_type, Numeric) and not isinstance(v, Decimal):
        return Decimal(str(v))
    return v


class BackupService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    # --- конфиг в таблице settings (key/value) ---

    async def _setting(self, key: str) -> str | None:
        async with self.uow.query() as tx:
            return await tx.settings.get_value(key)

    async def _set_setting(self, key: str, value: str) -> None:
        async with self.uow.transaction() as tx:
            await tx.settings.set_value(key, value)

    async def _key(self) -> str | None:
        # мастер-ключ задан → парольная фраза бэкапа выводится из него; иначе legacy-ключ
        mk = keyring.backup_key()
        if mk:
            return mk
        return self.settings.backup_key or await self._setting(_KEY_SETTING)

    async def key_set(self) -> bool:
        return bool(await self._key())

    async def set_key(self, key: str) -> None:
        """Задать/сменить мастер-ключ (из него выводятся ключи секретов и бэкапов)."""
        if not key or len(key) < 8:
            raise BadRequest(key="backup.master_key_too_short")
        if is_default_master_key(key):
            raise BadRequest(key="backup.master_key_too_simple")
        if self.settings.master_key:
            raise BadRequest(key="backup.master_key_env_immutable")
        # apply_master: сохранит в БД, перешифрует существующие секреты под новый ключ
        await keyring.apply_master(self.uow, self.settings, key, source="db", persist=True)

    async def frequency(self) -> str:
        return await self._setting(_FREQ_SETTING) or _DEFAULT_FREQ

    async def set_frequency(self, freq: str) -> None:
        if freq not in ("off", *_FREQ_DAYS):
            raise BadRequest(key="backup.invalid_frequency")
        await self._set_setting(_FREQ_SETTING, freq)

    # --- логический дамп/восстановление (независимо от версии Postgres) ---

    async def _dump(self) -> dict:
        tables = Base.metadata.sorted_tables  # родители раньше детей
        async with self.uow.query() as tx:
            rev = (await tx.session.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            data: dict[str, list[dict]] = {}
            for t in tables:
                rows = (await tx.session.execute(select(t))).mappings().all()
                data[t.name] = [{k: _ser(v) for k, v in row.items()} for row in rows]
        return {"app_version": self.settings.version, "alembic_revision": rev, "tables": data}

    async def _load(self, payload: dict) -> None:
        tables = Base.metadata.sorted_tables
        rev = payload.get("alembic_revision")
        tdata: dict = payload.get("tables") or {}
        async with self.uow.transaction() as tx:
            cur = (await tx.session.execute(text("SELECT version_num FROM alembic_version"))).scalar()
            if rev != cur:
                raise BadRequest(
                    key="backup.schema_version_mismatch",
                    params={"backup_rev": rev, "current_rev": cur},
                )
            names = ", ".join(f'"{t.name}"' for t in tables)
            await tx.session.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
            for t in tables:  # родители раньше детей — FK соблюдены
                rows = tdata.get(t.name) or []
                if not rows:
                    continue
                converted = [{k: _deser(t.columns[k].type, v) for k, v in r.items() if k in t.columns} for r in rows]
                await tx.session.execute(t.insert(), converted)

    # --- файлы бэкапов ---

    @property
    def _dir(self) -> str:
        return self.settings.backup_dir

    def _path(self, name: str) -> str:
        # защита от path traversal: только basename с расширением .vhb внутри backup_dir
        if name != Path(name).name or not name.endswith(".vhb"):
            raise BadRequest(key="backup.invalid_backup_name")
        return str(Path(self._dir) / name)

    def _files(self) -> list[tuple[str, float, int, str]]:
        """(name, mtime, size_bytes, kind) — свежие первыми."""
        base = Path(self._dir)
        if not base.is_dir():
            return []
        out: list[tuple[str, float, int, str]] = []
        for entry in base.iterdir():
            name = entry.name
            if not name.endswith(".vhb"):
                continue
            try:
                st = entry.stat()
            except OSError:
                continue
            out.append((name, st.st_mtime, st.st_size, "auto" if "-auto-" in name else "manual"))
        out.sort(key=lambda x: x[1], reverse=True)
        return out

    def list_backups(self) -> list[dict]:
        return [
            {
                "id": name,
                "at": time.strftime("%d.%m.%Y %H:%M", time.localtime(mtime)),
                "size": _human_size(size),
                "kind": "авто" if kind == "auto" else "ручной",
            }
            for name, mtime, size, kind in self._files()
        ]

    def backup_path(self, bid: str) -> str:
        path = self._path(bid)
        if not Path(path).is_file():
            raise NotFound(key="backup.not_found")
        return path

    def delete_backup(self, bid: str) -> None:
        Path(self._path(bid)).unlink(missing_ok=True)

    async def create_backup(self, kind: str = "manual") -> dict:
        key = await self._key()
        if not key:
            raise BadRequest(key="backup.encryption_key_not_set")
        payload = json.dumps(await self._dump(), ensure_ascii=False, separators=(",", ":")).encode()
        blob = _encrypt(gzip.compress(payload), key)
        Path(self._dir).mkdir(parents=True, exist_ok=True)
        name = f"vpnhub-{kind}-{time.strftime('%Y-%m-%d_%H-%M-%S')}.vhb"
        with (Path(self._dir) / name).open("wb") as f:
            f.write(blob)
        log.info("backup created", name=name, size=len(blob), kind=kind)
        return {"ok": True, "id": name, "size": len(blob)}

    async def restore_from_bytes(self, data: bytes, key: str) -> dict:
        if not key:
            raise BadRequest(key="backup.enter_master_key")
        # пользователь вводит мастер-ключ → пробуем производную парольную фразу, затем сам ключ
        # как «сырой» (legacy-бэкапы, сделанные старым backup-ключом напрямую).
        raw: bytes | None = None
        for passphrase in (keyring.derive_backup_key(key), key):
            try:
                raw = _decrypt(data, passphrase)
                break
            except BadRequest:
                continue
        if raw is None:
            raise BadRequest(key="backup.wrong_key_or_corrupted")
        try:
            payload = json.loads(gzip.decompress(raw))
        except Exception:
            raise BadRequest(key="backup.corrupted_file") from None
        await self._load(payload)
        log.info("backup restored", size=len(data))
        return {"ok": True}

    def _prune(self) -> None:
        autos = [name for name, _, _, kind in self._files() if kind == "auto"]
        for name in autos[_KEEP_AUTO:]:
            try:
                (Path(self._dir) / name).unlink()
            except OSError:
                pass

    async def run_tick(self) -> None:
        """Вызывается планировщиком раз в час: создаёт авто-бэкап, если подошёл срок."""
        freq = await self.frequency()
        if freq == "off" or not await self._key():
            return
        interval = _FREQ_DAYS.get(freq, _FREQ_DAYS[_DEFAULT_FREQ]) * 86400
        files = self._files()
        if files and time.time() - files[0][1] < interval:
            return
        try:
            await self.create_backup(kind="auto")
            self._prune()
        except Exception as exc:  # планировщик не должен падать
            log.warning("auto backup failed", error=str(exc))


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} Б"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} КБ"
    return f"{size / 1024 / 1024:.1f} МБ"
