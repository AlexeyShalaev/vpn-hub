"""optimize metric storage: index traffic_samples by (server_id, at) + autovacuum tuning

A5 + C2 из плана оптимизации метрик. Индекс под фактический запрос дашборда/ретеншна
(WHERE server_id IN (...) AND at >= since ORDER BY at); прежний (server_id, proto, client_id)
не использовался ни одним чтением, одиночный server_id покрыт композитом. Плюс агрессивнее
autovacuum на высокочурновых таблицах метрик, чтобы ретеншн-DELETE меньше их раздувал.
Только Postgres (тесты гоняют схему из metadata, миграции не применяют).

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
    "autovacuum_vacuum_scale_factor = 0.02, "
    "autovacuum_analyze_scale_factor = 0.05, "
    "autovacuum_vacuum_cost_limit = 2000"
)
_AUTOVACUUM_KEYS = (
    "autovacuum_vacuum_scale_factor, autovacuum_analyze_scale_factor, autovacuum_vacuum_cost_limit"
)


def upgrade() -> None:
    # A5: индекс под фактический запрос; убираем неиспользуемые
    op.drop_index(op.f("traffic_samples_server_id_idx"), table_name="traffic_samples")
    op.drop_index("traffic_samples_scope_idx", table_name="traffic_samples")
    op.create_index("traffic_samples_time_idx", "traffic_samples", ["server_id", "at"], unique=False)
    # C2: autovacuum-тюнинг (имена таблиц — из константы, не пользовательский ввод)
    for table in _AUTOVACUUM_TABLES:
        op.execute(f"ALTER TABLE {table} SET ({_AUTOVACUUM_SET})")


def downgrade() -> None:
    for table in _AUTOVACUUM_TABLES:
        op.execute(f"ALTER TABLE {table} RESET ({_AUTOVACUUM_KEYS})")
    op.drop_index("traffic_samples_time_idx", table_name="traffic_samples")
    op.create_index(
        "traffic_samples_scope_idx", "traffic_samples", ["server_id", "proto", "client_id"], unique=False
    )
    op.create_index(op.f("traffic_samples_server_id_idx"), "traffic_samples", ["server_id"], unique=False)
