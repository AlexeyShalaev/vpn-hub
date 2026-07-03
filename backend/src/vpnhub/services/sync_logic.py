"""Чистая логика сверки состояния сервера с нашей БД (без SSH/БД — легко тестируется)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class ProtocolObservation:
    """Наблюдаемое состояние одного протокола на сервере."""

    proto_id: str
    present: bool  # контейнер существует (в т.ч. остановленный)
    running: bool
    readable_clients: bool  # удалось ли прочитать список клиентов
    client_ids: set[str] = field(default_factory=set)


@dataclass
class ConfigRow:
    """Наш выданный конфиг (строка DeviceConfig)."""

    config_id: str
    proto_id: str
    client_id: str


def desired_config_status(row: ConfigRow, obs_by_proto: dict[str, ProtocolObservation]) -> str | None:
    """Каким должен стать статус конфига: 'active' | 'revoked' | None (не трогать).

    - протокол не наблюдался или клиентов не прочитали → None (не рискуем ложным revoke);
    - протокол отсутствует (контейнер снесён) → revoked;
    - клиент есть в живом наборе → active, иначе → revoked (отозван внешне).
    """
    obs = obs_by_proto.get(row.proto_id)
    if obs is None:
        return None
    if not obs.present:
        return "revoked"
    if not obs.readable_clients:
        return None
    return "active" if row.client_id in obs.client_ids else "revoked"


def external_client_ids(obs: ProtocolObservation, our_ids: set[str]) -> set[str]:
    """Клиенты на сервере, которых нет у нас (заведены внешним клиентом Amnezia)."""
    if not obs.readable_clients:
        return set()
    return {cid for cid in obs.client_ids if cid and cid not in our_ids}


# ── долг на снятие (ledger ServerProtocol.pending_revoke_json) ──


def parse_pending(raw: str | None) -> set[str]:
    """Разобрать pending_revoke_json в множество client_id (пусто при None/битом JSON)."""
    if not raw:
        return set()
    try:
        return {c for c in json.loads(raw) if c}
    except (ValueError, TypeError):
        return set()


def dump_pending(ids: set[str]) -> str | None:
    """Сериализовать множество client_id; пустое → None (колонка остаётся чистой)."""
    return json.dumps(sorted(ids)) if ids else None


def plan_drain(pending: set[str], obs: ProtocolObservation) -> tuple[set[str], set[str]]:
    """Как гасить долг на снятие для одного протокола → (to_revoke, already_gone).

    - контейнер снесён → пиры заведомо мертвы → гасим весь долг без снятия;
    - клиентов не прочитали → пробуем снять всё (revoke идемпотентен — снятие отсутствующего no-op);
    - иначе: живые на сервере → снять; отсутствующие (сняты нами быстро/внешне) → погасить без снятия.
    """
    if not pending:
        return set(), set()
    if not obs.present:
        return set(), set(pending)
    if not obs.readable_clients:
        return set(pending), set()
    to_revoke = {c for c in pending if c in obs.client_ids}
    return to_revoke, pending - to_revoke
