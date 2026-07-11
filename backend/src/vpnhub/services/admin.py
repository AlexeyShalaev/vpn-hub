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
from vpnhub.core.i18n import DEFAULT_LANG, Lang, translate
from vpnhub.infra import keyring, selfupdate, sysprobe
from vpnhub.infra.security import hash_password, normalize_phone
from vpnhub.infra.uow import Uow
from vpnhub.infra.updates import feed_disabled, fetch_feed, is_newer, localize_releases, normalize_feed
from vpnhub.services.backups import BackupService
from vpnhub.services.limits import (
    SETTING_DEFAULT_DEVICES,
    SETTING_DEFAULT_USER_BYTES,
    global_device_limit,
    global_user_bytes,
)
from vpnhub.services.metrics_retention import (
    SETTING_RAW_RETENTION,
    SETTING_SIZE_CAP_GB,
    auto_size_cap_bytes,
    disk_total_bytes,
    metrics_disk_usage,
)

log = structlog.get_logger(__name__)

_START = time.time()
def _fallback_releases(lang: Lang = DEFAULT_LANG) -> list[dict]:
    """Запасные заметки первого релиза (когда фид недоступен) — на языке запроса."""
    return [
        {
            "v": "0.1.0",
            "date": "29.06.2026",
            "notes": [
                translate("changelog.fallback_first_release", lang),
                translate("changelog.fallback_servers", lang),
                translate("changelog.fallback_configs", lang),
            ],
        }
    ]


_CACHE_KEY = "update_feed_cache"


def _is_num(s: str) -> bool:
    """Строка парсится во float (для чтения size-cap из Setting)."""
    try:
        float(s)
    except ValueError:
        return False
    return True


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
            raise BadRequest(key="admin.name_phone_required")
        async with self.uow.transaction() as tx:
            u = await tx.users.get(uid)
            if not u:
                raise NotFound(key="admin.user_not_found")
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

    async def system(self, lang: Lang = DEFAULT_LANG) -> dict:
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
        async with self.uow.query() as tx:
            default_devices = await global_device_limit(tx.session)
            default_user_bytes = await global_user_bytes(tx.session)
            raw_row = await tx.settings.get_value(SETTING_RAW_RETENTION)
            cap_row = await tx.settings.get_value(SETTING_SIZE_CAP_GB)
            metrics_usage = await metrics_disk_usage(tx.session)
        # хранение метрик (UI-настройка): дни хранения сырья (override; пусто → env-дефолт) + кап по размеру
        # авто-лимит по диску: показываем эффективный кап, когда явный не задан (20% диска ≈ N ГБ)
        auto_cap = auto_size_cap_bytes(self.settings)
        disk_total = disk_total_bytes(self.settings.metrics_disk_path)
        metrics = {
            "rawRetentionDays": int(raw_row) if raw_row and raw_row.strip().isdigit() else None,
            "defaultRawRetentionDays": self.settings.traffic_raw_retention_days,
            "sizeCapGb": float(cap_row) if cap_row and _is_num(cap_row) else 0.0,
            "autoSizeCapGb": round(auto_cap / 1_000_000_000, 1) if auto_cap else 0.0,
            "diskTotalGb": round(disk_total / 1_000_000_000, 1) if disk_total else None,
            "diskCapPct": self.settings.metrics_disk_cap_pct,
            "usage": metrics_usage,
        }
        s = self.settings
        cache = await self._update_cache()
        latest = cache.get("latest") or s.version
        releases = localize_releases(cache.get("releases") or _fallback_releases(lang), lang)
        update_mode = selfupdate.detect_mode(s)
        update_supported = update_mode != "manual"
        update_hint = ""
        # k8s: кнопка активна, только если под реально может патчить свой Deployment (пре-чек прав),
        # иначе честно объясняем про RBAC, а не даём наткнуться на 403 при клике.
        if update_mode == "k8s":
            ready, reason = await selfupdate.k8s_ready(s)
            if not ready:
                update_supported, update_hint = False, reason
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
            "updateSupported": update_supported,
            "updateMode": update_mode,
            "updateHint": update_hint,
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
            "defaultDevicesPerUser": default_devices,
            "defaultUserBytes": default_user_bytes,
            "metrics": metrics,
            "releases": releases,
        }

    async def storage(self) -> dict:
        """Развёртывание + дисковое использование: способ деплоя, рабочие папки, тома, размер БД по таблицам."""
        s = self.settings
        static_dir = Path(vpnhub.__file__).parent / "static"  # тот же путь, что монтирует api/static
        data_dir = Path(s.providers_file).parent

        def _scan() -> tuple[list[dict], list[dict], dict]:
            # синхронные os.walk/stat/disk_usage — уводим в поток, чтобы не блокировать event loop на скане ФС
            dirs = [
                sysprobe.dir_usage("Резервные копии", s.backup_dir, kind="backups"),
                sysprobe.dir_usage("Данные (провайдеры и пр.)", str(data_dir), kind="data"),
                sysprobe.dir_usage("Статика фронтенда", str(static_dir), kind="static"),
            ]
            volumes = sysprobe.volume_usage([s.backup_dir, str(data_dir), str(static_dir)])
            return dirs, volumes, sysprobe.detect_deployment()

        dirs, volumes, deployment = await asyncio.to_thread(_scan)
        async with self.uow.query() as tx:
            db = await sysprobe.db_disk_usage(tx.session)
        deployment.update(image=s.image, edition=s.edition, updateMode=selfupdate.detect_mode(s), baseUrl=s.base_url)
        return {"deployment": deployment, "dirs": dirs, "volumes": volumes, "db": db}

    async def set_default_devices(self, n: int) -> None:
        """Глобальный дефолт лимита устройств на пользователя (>=1)."""
        if n < 1:
            raise BadRequest(key="admin.device_limit_min")
        async with self.uow.transaction() as tx:
            await tx.settings.set_value(SETTING_DEFAULT_DEVICES, str(int(n)))

    async def set_default_user_bytes(self, n: int | None) -> None:
        """Глобальный дефолт лимита трафика на пользователя за период; None/≤0 = без лимита."""
        async with self.uow.transaction() as tx:
            await tx.settings.set_value(SETTING_DEFAULT_USER_BYTES, str(int(n)) if (n and n > 0) else "0")

    async def set_metrics_retention(self, raw_days: int | None, size_cap_gb: float | None) -> None:
        """Хранение метрик из UI: дни хранения сырья (None/≤0 → env-дефолт) и лимит размера, ГБ (0 = без лимита)."""
        if raw_days is not None and raw_days < 0:
            raise BadRequest(key="admin.retention_days_negative")
        if size_cap_gb is not None and size_cap_gb < 0:
            raise BadRequest(key="admin.size_cap_negative")
        raw_val = str(int(raw_days)) if (raw_days and raw_days > 0) else "0"
        cap_val = f"{size_cap_gb:g}" if (size_cap_gb and size_cap_gb > 0) else "0"
        async with self.uow.transaction() as tx:
            await tx.settings.set_value(SETTING_RAW_RETENTION, raw_val)
            await tx.settings.set_value(SETTING_SIZE_CAP_GB, cap_val)

    async def _update_cache(self) -> dict:
        async with self.uow.query() as tx:
            raw = await tx.settings.get_value(_CACHE_KEY)
        if not raw:
            return {}
        try:
            return cast("dict[Any, Any]", json.loads(raw))
        except ValueError:
            return {}

    async def check_updates(self, lang: Lang = DEFAULT_LANG) -> dict:
        """Реальная проверка: тянет фид релизов, сравнивает версии, кэширует результат."""
        current = self.settings.version
        url = self.settings.update_feed_url
        if feed_disabled(url):
            cache = await self._update_cache()
            latest = cache.get("latest") or current
            return {
                "available": is_newer(latest, current),
                "current": current,
                "latest": latest,
                "checked": False,
                "releases": localize_releases(cache.get("releases") or _fallback_releases(lang), lang),
                "reason": translate("update.check_disabled", lang),
            }
        try:
            feed = normalize_feed(await fetch_feed(url))
        except Exception as exc:
            log.warning("update_check_failed", error=str(exc))
            cache = await self._update_cache()
            latest = cache.get("latest") or current
            return {
                "available": is_newer(latest, current),
                "current": current,
                "latest": latest,
                "checked": False,
                "releases": localize_releases(cache.get("releases") or _fallback_releases(lang), lang),
                "reason": translate("update.feed_failed", lang, error=str(exc)),
            }
        latest = str(feed.get("latest") or current)
        releases = feed.get("releases") or _fallback_releases(lang)
        async with self.uow.transaction() as tx:
            await tx.settings.set_value(
                _CACHE_KEY, json.dumps({"latest": latest, "releases": releases, "at": time.time()})
            )
        return {
            "available": is_newer(latest, current),
            "current": current,
            "latest": latest,
            "checked": True,
            "releases": localize_releases(releases, lang),
        }

    async def apply_update(self, lang: Lang = DEFAULT_LANG) -> dict:
        """Применить обновление доступным драйвером (command/webhook/k8s) в фоне.

        Контейнер не может пересоздать сам себя, поэтому применение делегируется
        внешнему механизму (см. infra/selfupdate.py), а ответ уходит сразу:
        UI дальше поллит upgrade_status() до смены версии. Если ни один драйвер
        не настроен — честный ручной путь с инструкцией (без фейкового прогресса).
        """
        s = self.settings
        if selfupdate.detect_mode(s) == "manual":
            return {
                "ok": False,
                "manual": True,
                "message": translate("update.not_configured", lang),
                "instructions": [
                    f"docker pull {s.image}:latest",
                    "docker compose up -d  # или перезапустите контейнер с новым образом",
                ],
            }
        cache = await self._update_cache()
        target = str(cache.get("latest") or "")
        if not target or not is_newer(target, s.version):
            fresh = await self.check_updates(lang)  # кнопку могли нажать до первой проверки фида
            target = str(fresh.get("latest") or "")
            if not target or not is_newer(target, s.version):
                return {"ok": False, "manual": False, "message": translate("update.already_latest", lang)}
        return selfupdate.start(s, target, lang)

    def upgrade_status(self) -> dict:
        """Статус применения обновления + текущая версия (по ней UI понимает успех)."""
        return {**selfupdate.status(), "version": self.settings.version}
