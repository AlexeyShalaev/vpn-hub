"""Bootstrap первого администратора из env (VPNHUB_ADMIN_PHONE/PASSWORD).

Никаких демо-данных: на пустой БД без env-админа приложение покажет setup-экран (§5.6).
"""

from __future__ import annotations

import structlog

from vpnhub.api.config import Settings
from vpnhub.core.errors import BadRequest
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.security import hash_password, normalize_phone, validate_password
from vpnhub.infra.uow import Uow

log = structlog.get_logger(__name__)


async def ensure_bootstrap_admin(uow: Uow, settings: Settings) -> None:
    if not (settings.admin_phone and settings.admin_password):
        return
    # env-админ обязан проходить ту же парольную политику, что и UI (иначе VPNHUB_ADMIN_PASSWORD=123
    # заводил бы слабого админа в обход проверок). Падаем на старте с внятным сообщением.
    try:
        validate_password(settings.admin_password)
    except BadRequest as e:
        raise RuntimeError(f"VPNHUB_ADMIN_PASSWORD не проходит парольную политику: {e.message}") from e
    async with uow.transaction() as tx:
        user = await tx.users.by_phone(settings.admin_phone)
        if user is None:
            user = m.User(
                phone=normalize_phone(settings.admin_phone),
                name="Администратор",
                password_hash=hash_password(settings.admin_password),
                status="active",
            )
            tx.users.add(user)
            await tx.session.flush()
        if await tx.admins.is_admin(user.id):
            return
        tx.admins.add(m.Admin(user_id=user.id))


async def normalize_user_phones(uow: Uow) -> None:
    """Одноразово привести телефоны существующих пользователей к нормализованному виду.

    Нужно после перехода на хранение только цифр: иначе вход (нормализованный поиск)
    не найдёт старые записи с телефоном в «сыром» формате. Конфликтующие пропускаем.
    """
    async with uow.transaction() as tx:
        for u in await tx.users.all():
            norm = normalize_phone(u.phone)
            if norm and norm != u.phone:
                dup = await tx.users.by_phone(norm)
                if dup and dup.id != u.id:
                    log.warning("phone_normalize_conflict", user_id=u.id, phone=norm)
                    continue
                u.phone = norm
