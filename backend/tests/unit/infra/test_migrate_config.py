"""Alembic Config для наката миграций: DSN с URL-кодированным паролем (issue #66)."""

from __future__ import annotations

from urllib.parse import quote

import pytest

from vpnhub.infra.db.migrate import _config

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("password", ["hYbY6(|-c|HF8}VsZ?6Ttu5+", "p@ss%word(|}", "100%", "plain"])
def test__config__dsn_with_encoded_password__round_trips_unchanged(password: str) -> None:
    dsn = f"postgresql+asyncpg://vpnhub:{quote(password, safe='')}@db:5432/vpnhub"

    cfg = _config(dsn)

    assert cfg.get_main_option("sqlalchemy.url") == dsn
