"""Application settings (pydantic-settings).

Конфиг читается из env. `DATABASE_URL` — единственная обязательная внешняя зависимость;
остальное — с префиксом `VPNHUB_`. Объект `PostgresConfig` реализует протокол настроек
`sqlalchemy-foundation-kit` (`connection`/`pool`/`query`/`to_dsn`).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from urllib.parse import quote, unquote, urlparse

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


@dataclass
class _Connection:
    host: str
    port: int
    user: str
    password: str
    database: str


@dataclass
class _Pool:
    kind: str = "async_adapted_queue"
    size: int | None = 10
    max_overflow: int | None = 5
    pre_ping: bool = True
    recycle: int | None = 1800
    timeout: float | None = 30.0


@dataclass
class _Query:
    echo: bool = False
    statement_cache_size: int | None = 0
    prepared_statement_cache_size: int | None = 0
    isolation_level: str | None = None


@dataclass
class PostgresConfig:
    """Реализует sqlalchemy_foundation_kit.PostgresSettingsProtocol."""

    connection: _Connection
    pool: _Pool = field(default_factory=_Pool)
    query: _Query = field(default_factory=_Query)
    application_name: str = "vpnhub"
    db_schema: str | None = None
    use_orjson_serialization: bool = False
    jit: str | None = "off"

    def to_dsn(self) -> str:
        c = self.connection
        # user/password переэнкодим: пароли managed-Postgres часто содержат @ ? [ ] / :,
        # без quote() пересобранный DSN парсится с битым host (asyncpg: Name or service not known).
        user = quote(c.user, safe="")
        password = quote(c.password, safe="")
        return f"postgresql+asyncpg://{user}:{password}@{c.host}:{c.port}/{c.database}"


def _parse_dsn(url: str) -> _Connection:
    u = urlparse(url)
    return _Connection(
        host=u.hostname or "localhost",
        port=u.port or 5432,
        user=unquote(u.username or "postgres"),
        password=unquote(u.password or ""),
        database=(u.path or "/postgres").lstrip("/") or "postgres",
    )


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="VPNHUB_", env_file=".env", extra="ignore", case_sensitive=False)

    # Обязателен: строка подключения к PostgreSQL. Пусто по умолчанию — чтобы прод не стартовал
    # молча на dev-кредах; entrypoint падает с понятной ошибкой, если не задан.
    database_url: str = Field(
        default="",
        validation_alias=AliasChoices("DATABASE_URL", "VPNHUB_DATABASE_URL"),
    )
    # мастер-ключ восстановления: из него HKDF-выводятся ключи для секретов и бэкапов.
    # Приоритет: VPNHUB_MASTER_KEY (env) → БД (settings.master_key, задаётся на setup).
    master_key: str | None = None
    # Внутренний data-ключ шифрования секретов/бэкапов. НЕ конфигурируется из env — единственный
    # источник это мастер-ключ, из которого он выводится при старте (infra/keyring.resolve_keys)
    # и присваивается сюда. До вывода держит небезопасный дефолт-sentinel. validation_alias,
    # которого нет в окружении, отключает чтение из env (в т.ч. удалённый legacy VPNHUB_SECRET_KEY).
    secret_key: str = Field(
        default="dev-insecure-secret-change-me-0123456789abcdef",
        validation_alias="vpnhub_data_key_internal_runtime_only",
    )
    base_url: str = "http://localhost:8000"
    # За обратным прокси (Caddy/nginx): доверять X-Forwarded-Proto (флаг Secure у cookie) и
    # X-Forwarded-For (реальный IP клиента для rate-limit/аудита — берётся правый элемент,
    # добавленный прокси). Выкл → заголовки игнорируются, IP = прямой пир (нельзя подделать).
    trusted_proxy: bool = False
    admin_phone: str | None = None
    admin_password: str | None = None
    session_ttl_days: int = 30
    backup_dir: str = "./backups"
    backup_key: str | None = None  # env VPNHUB_BACKUP_KEY: если задан — имеет приоритет над ключом из БД
    providers_file: str = "./data/providers.yaml"
    run_migrations: bool = True
    update_channel: str = "stable"
    log_level: str = "INFO"
    # /metrics: если задан VPNHUB_METRICS_TOKEN — требуется Bearer-токен (или ?token=);
    # пусто → эндпоинт открыт (закрывайте на обратном прокси/сетевой политикой).
    metrics_token: str = ""
    # Swagger/ReDoc/OpenAPI: по умолчанию выключены (в проде не нужны и раскрывают API-поверхность).
    # Для разработки включаются через VPNHUB_DOCS_ENABLED=1 (см. Makefile-цель run).
    docs_enabled: bool = False

    # мониторинг серверов (TCP-зонд по SSH-порту)
    monitor_enabled: bool = True
    monitor_interval: int = 120  # период фоновой проверки, сек
    monitor_timeout: float = 5.0  # таймаут одного зонда, сек
    monitor_concurrency: int = 16  # одновременных зондов в фоновом тике

    # синхронизация состояния Amnezia (контейнеры/клиенты) по SSH — тяжелее монитора
    sync_enabled: bool = True
    sync_interval: int = 300  # период фоновой сверки, сек

    # аудит-лог: сколько дней хранить события (фоновая чистка audit-retention)
    audit_retention_days: int = 90

    # Подтверждение телефона по SMS/OTP не используется: вход по номеру и паролю,
    # а новые самостоятельные регистрации подтверждает администратор вручную.

    # обновления
    # по умолчанию — официальные GitHub Releases (работает из коробки, без настройки);
    # переопределяется под форк/зеркало; `off`/пусто → офлайн-режим (last-known из кэша).
    update_feed_url: str = "https://api.github.com/repos/AlexeyShalaev/vpn-hub/releases"
    # самообновление из панели — три драйвера (см. infra/selfupdate.py и docs/deploy/updates.md):
    update_command: str = ""  # команда применения апдейта ({version} → целевая версия); пусто → следующий драйвер
    update_webhook_url: str = ""  # HTTP-триггер внешнего апдейтера (Watchtower из selfupdate.compose.yaml)
    update_webhook_token: str = ""  # Bearer-токен апдейтера (VPNHUB_UPDATE_TOKEN в compose-оверлее)
    update_k8s: bool = True  # в k8s: патч образа собственного Deployment (нужен RBAC из deploy/k8s/base)
    update_k8s_deployment: str = "vpnhub"  # имя Deployment/контейнера — переопределяйте, если меняли манифесты
    update_k8s_container: str = "vpnhub"
    built: str = ""  # дата сборки (проставляется при build образа: VPNHUB_BUILT); пусто → mtime кода
    # ТОЛЬКО `PORT` (не `VPNHUB_PORT`): в Kubernetes сервис по имени `vpnhub` инжектит legacy-переменную
    # VPNHUB_PORT=tcp://<clusterIP>:<port>, которая ломала бы разбор int (под крашлупил). VPNHUB_PORT и так
    # не влияет на контейнер (uvicorn читает $PORT из entrypoint.sh) — см. docs/deploy/configuration.md.
    port: int = Field(default=8000, validation_alias=AliasChoices("PORT"))

    # app/build info shown in admin → system
    version: str = "0.1.0"
    latest_version: str = "0.1.0"
    image: str = "ghcr.io/alexeyshalaev/vpn-hub"
    edition: str = "Community"

    @field_validator(
        "trusted_proxy",
        "docs_enabled",
        "run_migrations",
        "monitor_enabled",
        "sync_enabled",
        "update_k8s",
        mode="before",
    )
    @classmethod
    def _blank_bool_is_false(cls, v: object) -> object:
        # Пустая строка из env (напр. compose `${VAR:-}`) не парсится pydantic как bool и роняет
        # старт. Трактуем пустое/пробельное значение как False; остальное — обычный разбор bool.
        if isinstance(v, str) and not v.strip():
            return False
        return v

    @property
    def postgres(self) -> PostgresConfig:
        return PostgresConfig(connection=_parse_dsn(self.database_url), application_name="vpnhub")

    @property
    def async_dsn(self) -> str:
        return self.postgres.to_dsn()


@lru_cache
def get_settings() -> Settings:
    return Settings()
