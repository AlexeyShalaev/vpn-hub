"""Бэкфиллы данных для Alembic-миграций (sync Core; вызываются из upgrade() и юнит-тестов).

Вынесены из файлов миграций, чтобы логику можно было тестировать без прогона Alembic.
Работают через синхронный Connection (`op.get_bind()`), SQL портабельный (PG прод / SQLite тесты).
"""

from __future__ import annotations

import uuid
from typing import Any, cast

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from vpnhub.infra.db.orm import models as m


def backfill_traffic_peer_state(bind: Connection) -> int:
    """Заполнить `traffic_peer_state` последним сэмплом per (server, proto, client).

    Идемпотентно: уже существующие ключи пропускаются (повторный прогон не дублирует).
    Скорости = 0 (посчитаются на первом же новом сэмпле). Сэмплы с NULL client_id (агрегаты)
    пропускаются; коллизии по `at` схлопываются на стороне Python (последняя строка выигрывает).
    """
    ts = cast(sa.Table, m.TrafficSample.__table__)
    st = cast(sa.Table, m.TrafficPeerState.__table__)
    existing = {
        (r.server_id, r.proto, r.client_id) for r in bind.execute(sa.select(st.c.server_id, st.c.proto, st.c.client_id))
    }
    latest = (
        sa.select(ts.c.server_id, ts.c.proto, ts.c.client_id, sa.func.max(ts.c.at).label("at"))
        .where(ts.c.client_id.is_not(None))
        .group_by(ts.c.server_id, ts.c.proto, ts.c.client_id)
        .subquery()
    )
    rows = bind.execute(
        sa.select(
            ts.c.server_id,
            ts.c.proto,
            ts.c.client_id,
            ts.c.at,
            ts.c.rx_bytes,
            ts.c.tx_bytes,
            ts.c.last_handshake,
            ts.c.online,
            ts.c.ext_name,
            ts.c.device_config_id,
        ).join(
            latest,
            sa.and_(
                ts.c.server_id == latest.c.server_id,
                ts.c.proto == latest.c.proto,
                ts.c.client_id == latest.c.client_id,
                ts.c.at == latest.c.at,
            ),
        )
    ).all()
    picked: dict[tuple[str, str, str], Any] = {}
    for r in rows:
        key = (r.server_id, r.proto, r.client_id)
        if key not in existing:
            picked[key] = r  # тай-брейк по одинаковому at: последняя строка выигрывает
    if not picked:
        return 0
    bind.execute(
        st.insert(),
        [
            {
                "id": uuid.uuid4().hex[:16],
                "server_id": r.server_id,
                "proto": r.proto,
                "client_id": r.client_id,
                "device_config_id": r.device_config_id,
                "ext_name": r.ext_name,
                "rx_bytes": r.rx_bytes,
                "tx_bytes": r.tx_bytes,
                "rx_speed": 0.0,
                "tx_speed": 0.0,
                "last_at": r.at,
                "last_handshake": r.last_handshake,
                "online": r.online,
            }
            for r in picked.values()
        ],
    )
    return len(picked)
