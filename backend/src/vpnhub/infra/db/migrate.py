"""Накат миграций самим приложением при старте.

Одновременный запуск нескольких инстансов (k8s multi-replica, rolling-деплой) сериализуется
транзакционным advisory-lock в `migrations/env.py` — гонок по `alembic_version` нет.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import structlog
from alembic import command
from alembic.config import Config

from vpnhub.api.config import Settings

log = structlog.get_logger(__name__)
_BACKEND_DIR = Path(__file__).resolve().parents[4]  # .../backend (src/vpnhub/infra/db/migrate.py)


def _config(dsn: str) -> Config:
    cfg = Config(str(_BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_DIR / "migrations"))
    cfg.set_main_option("sqlalchemy.url", dsn)
    return cfg


def _upgrade(dsn: str) -> None:
    command.upgrade(_config(dsn), "head")


async def run_migrations(settings: Settings) -> None:
    if not settings.run_migrations:
        log.info("migrations skipped (VPNHUB_RUN_MIGRATIONS=false)")
        return
    log.info("running migrations")
    await asyncio.to_thread(_upgrade, settings.async_dsn)
    log.info("migrations up to date")
