"""optimize metric storage: autovacuum tuning for high-churn metric tables

C2 из плана оптимизации метрик: агрессивнее autovacuum на высокочурновых таблицах, чтобы
ретеншн-DELETE меньше их раздувал. Индекс (server_id, at) у traffic_samples теперь создаётся сразу
в его create-миграции (squash), поэтому здесь только autovacuum. Только Postgres.

Revision ID: b1c2d3e4f5a6
Revises: a0b1c2d3e4f5
Create Date: 2026-07-11 01:00:00.000000
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "b1c2d3e4f5a6"
down_revision: str | None = "a0b1c2d3e4f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# высокочурновые таблицы метрик (ретеншн-DELETE + rollup-перезапись) — autovacuum должен срабатывать чаще
_AUTOVACUUM_TABLES = ("traffic_samples", "server_metrics", "metric_samples", "traffic_hourly")
_AUTOVACUUM_SET = (
    "autovacuum_vacuum_scale_factor = 0.02, autovacuum_analyze_scale_factor = 0.05, autovacuum_vacuum_cost_limit = 2000"
)
_AUTOVACUUM_KEYS = "autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor, autovacuum_vacuum_cost_limit"


def upgrade() -> None:
    # autovacuum-тюнинг (имена таблиц — из константы, не пользовательский ввод)
    for table in _AUTOVACUUM_TABLES:
        op.execute(f"ALTER TABLE {table} SET ({_AUTOVACUUM_SET})")


def downgrade() -> None:
    for table in _AUTOVACUUM_TABLES:
        op.execute(f"ALTER TABLE {table} RESET ({_AUTOVACUUM_KEYS})")
