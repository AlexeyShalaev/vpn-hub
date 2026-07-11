"""Прогон Alembic-миграций «через горнило» (alembic-gauntlet).

Даёт из коробки: единственный head, чистый up/down round-trip, совпадение схемы после `upgrade head`
с ORM-моделями (нет дрейфа миграций от моделей) и соответствие имён индексов/ограничений неймингу.

Требует Postgres (изолированные схемы) — берёт DSN из `DATABASE_URL`; на SQLite/без PG тест пропускается.
В CI гоняется в джобе «Alembic migrations smoke (Postgres)».
"""

from __future__ import annotations

import os

import pytest
from alembic_gauntlet import MigrationTestBase
from sqlalchemy import MetaData

from vpnhub.infra.db.orm import models as m

pytestmark = pytest.mark.integration

_DB_URL = os.environ.get("DATABASE_URL", "")


@pytest.mark.skipif(
    "postgresql" not in _DB_URL,
    reason="migration tests need Postgres — set DATABASE_URL to a postgresql+asyncpg DSN",
)
class TestMigrationsGauntlet(MigrationTestBase):
    # Проект осознанно именует UNIQUE-ограничения суффиксом `_uq` (а не convention-`_key`), индексы — `_idx`.
    # Разрешаем оба; pk/fk/check выводятся из naming_convention моделей автоматически.
    allowed_index_suffixes = ["_idx", "_uq", "_key"]
    allowed_uq_suffixes = ["_uq", "_key"]

    @pytest.fixture
    def migration_db_url(self) -> str:
        return _DB_URL

    @pytest.fixture
    def orm_metadata(self) -> MetaData:
        return m.BaseTable.metadata
