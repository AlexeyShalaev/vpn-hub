"""Движок БД и session-manager на sqlalchemy-foundation-kit."""

from __future__ import annotations

from sqlalchemy_foundation_kit import AsyncSessionManager, create_async_session_manager

from vpnhub.api.config import Settings

# модули с ORM-моделями — для load_orm_metadata в alembic
MODELS_MODULES = ["vpnhub.infra.db.orm.models"]


def build_session_manager(settings: Settings) -> AsyncSessionManager:
    return create_async_session_manager(settings.postgres, application_name="vpnhub")  # type: ignore[arg-type]
