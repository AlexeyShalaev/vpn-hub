"""Администрирование: пользователи и система (раздел админа)."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any, cast

import structlog
from sqlalchemy import text

import vpnhub
from vpnhub.api.config import Settings
from vpnhub.common.serializers import user_to_dict
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra import keyring
from vpnhub.infra.security import hash_password, normalize_phone
from vpnhub.infra.uow import Uow
from vpnhub.infra.updates import fetch_feed, is_newer
from vpnhub.services.backups import BackupService

log = structlog.get_logger(__name__)

_START = time.time()
_FALLBACK_RELEASES = [
    {
        "v": "0.1.0",
        "date": "29.06.2026",
        "notes": [
            "Первый релиз VPN Hub",
            "Серверы, пулы, группы и выдача доступов",
            "Получение конфигов Amnezia / OpenVPN / Outline",
        ],
    }
]
_CACHE_KEY = "update_feed_cache"


def _built(settings: Settings) -> str:
    """Дата сборки: из VPNHUB_BUILT, иначе mtime установленного пакета."""
    if settings.built:
        return settings.built
    try:
        pkg_dir = Path(vpnhub.__file__).parent
        return time.strftime("%d.%m.%Y", time.localtime(pkg_dir.stat().st_mtime))
    except OSError:
        return "—"


def _uptime() -> str:
    s = int(time.time() - _START)
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    mnt = s // 60
    if d:
        return f"{d} дн {h} ч"
    if h:
        return f"{h} ч {mnt} мин"
    return f"{mnt} мин"


class AdminService:
    def __init__(self, uow: Uow, settings: Settings, backups: BackupService) -> None:
        self.uow = uow
        self.settings = settings
        self.backups = backups

    async def users(self) -> list[dict]:
        async with self.uow.query() as tx:
            admin_ids = set(await tx.admins.user_ids())
            return [{**user_to_dict(u), "isAdmin": u.id in admin_ids} for u in await tx.users.all()]

    async def update_user(self, uid: str, name: str, phone: str, status: str, new_password: str | None) -> dict:
        if not name or not phone:
            raise BadRequest("Имя и телефон обязательны")
        async with self.uow.transaction() as tx:
            u = await tx.users.get(uid)
            if not u:
                raise NotFound("Пользователь не найден")
            u.name, u.phone, u.status = name, normalize_phone(phone), status
            if new_password:
                u.password_hash = hash_password(new_password)
            # блокировка или смена пароля админом → немедленно гасим все сессии пользователя
            if status == "blocked" or new_password:
                await tx.sessions.delete_for_subject(uid)
            await tx.session.flush()
            await tx.session.refresh(u)
            return user_to_dict(u)

    async def delete_user(self, uid: str) -> None:
        async with self.uow.transaction() as tx:
            u = await tx.users.get(uid)
            if u:
                await tx.session.delete(u)

    async def system(self) -> dict:
        pg = self.settings.postgres.connection
        db_status, db_latency, engine = "disconnected", None, "PostgreSQL"
        async with self.uow.query() as tx:
            t0 = time.time()
            try:
                row = (await tx.session.execute(text("SELECT version()"))).scalar()
                db_status = "connected"
                db_latency = f"{int((time.time() - t0) * 1000)} мс"
                if row:
                    engine = row.split(" on ")[0].replace("PostgreSQL", "PostgreSQL")
            except Exception:
                db_status = "error"
        backups = self.backups.list_backups()
        backup_frequency = await self.backups.frequency()
        backup_key_set = await self.backups.key_set()
        s = self.settings
        cache = await self._update_cache()
        latest = cache.get("latest") or s.version
        releases = cache.get("releases") or _FALLBACK_RELEASES
        return {
            "version": s.version,
            "latest": latest,
            "updateAvailable": is_newer(latest, s.version),
            "channel": s.update_channel,
            "image": s.image,
            "edition": s.edition,
            "built": _built(s),
            "uptime": _uptime(),
            "baseUrl": s.base_url,
            "masterKeyInsecure": keyring.master_insecure(),
            "masterKeyFromEnv": keyring.master_source() == "env",
            "updateSupported": bool(s.update_command),
            "db": {
                "engine": engine,
                "host": f"{pg.host}:{pg.port}",
                "name": pg.database,
                "status": db_status,
                "latency": db_latency,
            },
            "lastBackup": backups[0]["at"] if backups else "—",
            "backups": backups,
            "backupFrequency": backup_frequency,
            "masterKeySet": backup_key_set,
            "releases": releases,
        }

    async def _update_cache(self) -> dict:
        async with self.uow.query() as tx:
            raw = await tx.settings.get_value(_CACHE_KEY)
        if not raw:
            return {}
        try:
            return cast("dict[Any, Any]", json.loads(raw))
        except ValueError:
            return {}

    async def check_updates(self) -> dict:
        """Реальная проверка: тянет фид релизов, сравнивает версии, кэширует результат."""
        current = self.settings.version
        url = self.settings.update_feed_url
        if not url:
            cache = await self._update_cache()
            latest = cache.get("latest") or current
            return {
                "available": is_newer(latest, current),
                "current": current,
                "latest": latest,
                "checked": False,
                "releases": cache.get("releases") or _FALLBACK_RELEASES,
                "reason": "Фид обновлений не настроен (VPNHUB_UPDATE_FEED_URL)",
            }
        try:
            feed = await fetch_feed(url)
        except Exception as exc:
            log.warning("update_check_failed", error=str(exc))
            cache = await self._update_cache()
            latest = cache.get("latest") or current
            return {
                "available": is_newer(latest, current),
                "current": current,
                "latest": latest,
                "checked": False,
                "releases": cache.get("releases") or _FALLBACK_RELEASES,
                "reason": f"Не удалось получить фид обновлений: {exc}",
            }
        latest = str(feed.get("latest") or current)
        releases = feed.get("releases") if isinstance(feed.get("releases"), list) else _FALLBACK_RELEASES
        async with self.uow.transaction() as tx:
            await tx.settings.set_value(
                _CACHE_KEY, json.dumps({"latest": latest, "releases": releases, "at": time.time()})
            )
        return {
            "available": is_newer(latest, current),
            "current": current,
            "latest": latest,
            "checked": True,
            "releases": releases,
        }

    async def apply_update(self) -> dict:
        """Применить обновление: выполнить настроенную команду, иначе — честный ручной путь.

        Самообновление контейнера изнутри невозможно без доступа к docker-сокету/оркестратору,
        поэтому «магической» кнопки нет: если задан VPNHUB_UPDATE_COMMAND — запускаем его,
        иначе возвращаем инструкцию по ручному апдейту (без фейкового прогресса).
        """
        cmd = self.settings.update_command
        image = self.settings.image
        if not cmd:
            return {
                "ok": False,
                "manual": True,
                "message": "Автообновление не настроено. Обновите образ вручную.",
                "instructions": [
                    f"docker pull {image}:latest",
                    "docker compose up -d  # или перезапустите контейнер с новым образом",
                ],
            }
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT
        )
        out, _ = await proc.communicate()
        tail = out.decode("utf-8", "replace")[-2000:] if out else ""
        ok = proc.returncode == 0
        log.info("update_apply", ok=ok, code=proc.returncode)
        return {"ok": ok, "manual": False, "code": proc.returncode, "log": tail}
