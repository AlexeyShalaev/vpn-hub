"""Юнит-тесты разбора Settings — в частности терпимость к пустым bool-env.

Регресс: compose передаёт `VPNHUB_TRUSTED_PROXY: ${VPNHUB_TRUSTED_PROXY:-}` → в контейнер
приходит пустая строка, которую pydantic по умолчанию не парсит как bool и роняет старт.
"""

from __future__ import annotations

from urllib.parse import quote, unquote, urlparse

import pytest

from vpnhub.api.config import Settings

pytestmark = pytest.mark.unit

_DSN = "postgresql+asyncpg://u:p@h:5432/d"


def test__settings__dsn_password_special_chars__roundtrips() -> None:
    """Регресс: пароль managed-Postgres со спецсимволами (@ ? [ ] / :) ломал реконструкцию DSN.

    `_parse_dsn` разбирает DATABASE_URL, а `to_dsn()` собирает его обратно — без quote() сырой
    пароль с `@`/`?` съедал host (asyncpg падал с `Name or service not known`). Проверяем, что
    и разбор, и обратная сборка (`async_dsn`) сохраняют host и пароль.
    """
    pw = "p@ss?w/o:rd[+]="
    dsn = f"postgresql+asyncpg://vpnhub:{quote(pw, safe='')}@pg-host.internal:5432/vpnhub"
    # database_url читается через validation_alias DATABASE_URL (kwarg по имени поля не населяет).
    s = Settings(_env_file=None, **{"DATABASE_URL": dsn})

    conn = s.postgres.connection
    assert conn.password == pw
    assert conn.user == "vpnhub"
    assert conn.host == "pg-host.internal"

    u = urlparse(s.async_dsn)
    assert u.hostname == "pg-host.internal"
    assert u.port == 5432
    assert u.username == "vpnhub"
    # пароль в реконструированном DSN снова корректно декодируется
    assert unquote(u.password or "") == pw


@pytest.mark.parametrize(
    "field", ["trusted_proxy", "docs_enabled", "run_migrations", "monitor_enabled", "sync_enabled"]
)
def test__settings__empty_bool_env__is_false(field: str) -> None:
    s = Settings(_env_file=None, database_url=_DSN, **{field: ""})
    assert getattr(s, field) is False


@pytest.mark.parametrize(
    "field", ["trusted_proxy", "docs_enabled", "run_migrations", "monitor_enabled", "sync_enabled"]
)
def test__settings__whitespace_bool_env__is_false(field: str) -> None:
    s = Settings(_env_file=None, database_url=_DSN, **{field: "  "})
    assert getattr(s, field) is False


@pytest.mark.parametrize(("raw", "expected"), [("1", True), ("true", True), ("0", False), ("false", False)])
def test__settings__valid_bool_env__still_parses(raw: str, expected: bool) -> None:
    s = Settings(_env_file=None, database_url=_DSN, trusted_proxy=raw, docs_enabled=raw)
    assert s.trusted_proxy is expected
    assert s.docs_enabled is expected


def test__settings__bool_defaults() -> None:
    s = Settings(_env_file=None, database_url=_DSN)
    assert s.trusted_proxy is False
    assert s.docs_enabled is False


def test__settings__kubernetes_service_env_vpnhub_port__ignored(monkeypatch: pytest.MonkeyPatch) -> None:
    """Регресс: k8s-сервис `vpnhub` инжектит VPNHUB_PORT=tcp://<ip>:<port>. Поле port читает ТОЛЬКО
    PORT, поэтому эта переменная игнорируется (иначе под крашлупил на int_parsing)."""
    monkeypatch.setenv("VPNHUB_PORT", "tcp://10.96.203.23:80")
    s = Settings(_env_file=None, database_url=_DSN)
    assert s.port == 8000


def test__settings__port_env__parsed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PORT", "9000")
    assert Settings(_env_file=None, database_url=_DSN).port == 9000
