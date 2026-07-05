"""Аудит-лог: запись значимых действий и чтение с ролевой видимостью.

Запись — в ТОЙ ЖЕ транзакции, что и действие (`record_tx(tx, ...)`), чтобы аудит и мутация были
атомарны (при откате действия событие не сохраняется). Актор берётся из `Identity`; при его
отсутствии пишется `actor_kind="system"`. Чтение — `list_for(ident, ...)`: admin видит всё,
owner — только события своих ресурсов (или свои собственные действия).
"""

from __future__ import annotations

import json
import time

from vpnhub.api.config import Settings
from vpnhub.common.serializers import event_to_dict
from vpnhub.infra.uow import Uow, UowTransaction
from vpnhub.services.auth import Identity


class AuditService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    @staticmethod
    def record_tx(
        tx: UowTransaction,
        *,
        actor: Identity | None,
        type: str,
        target_kind: str | None = None,
        target_id: str | None = None,
        owner_user_id: str | None = None,
        meta: dict | None = None,
    ) -> None:
        """Записать событие в текущей транзакции. Ставить ПОСЛЕ основной мутации/flush."""
        actor_kind = actor.kind if actor else "system"
        actor_id = actor.id if actor else None
        actor_name = actor.name if actor else ""
        tx.audit.add_event(
            at=time.time(),
            actor_kind=actor_kind,
            actor_id=actor_id,
            actor_name=actor_name,
            type_=type,
            target_kind=target_kind,
            target_id=target_id,
            owner_user_id=owner_user_id,
            meta_json=json.dumps(meta, ensure_ascii=False) if meta else None,
        )

    async def list_for(
        self,
        ident: Identity,
        *,
        type: str | None = None,
        since: float | None = None,
        until: float | None = None,
        limit: int = 100,
    ) -> list:
        """События, видимые `ident`. admin — все; owner — свои ресурсы или свои действия."""
        limit = max(1, min(limit, 500))
        async with self.uow.query() as tx:
            if ident.kind == "admin":
                rows = await tx.audit.list(type_=type, since=since, until=until, limit=limit)
            else:
                rows = await tx.audit.list(type_=type, owner_or_actor=ident.id, since=since, until=until, limit=limit)
            return [event_to_dict(ev) for ev in rows]

    async def purge_old(self) -> int:
        """Удалить события старше `audit_retention_days` (идемпотентно)."""
        cutoff = time.time() - self.settings.audit_retention_days * 86400
        async with self.uow.transaction() as tx:
            return await tx.audit.purge_old(cutoff)
