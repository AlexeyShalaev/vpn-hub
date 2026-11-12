"""Ключи доступа (passkeys): регистрация и управление своими ключами.

Вход по ключу живёт в AuthService (там же общие правила входа: админ/blocked/pending/аудит).
"""

from __future__ import annotations

import json
import time

from vpnhub.api.config import Settings
from vpnhub.common.serializers import passkey_to_dict, ua_label
from vpnhub.core import audit_types
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra import webauthn
from vpnhub.infra.db.orm import models as m
from vpnhub.infra.uow import Uow, UowTransaction
from vpnhub.services.auth import Identity

MAX_PASSKEYS = 20
NAME_MAX = 120

# AAGUID популярных менеджеров ключей → понятное имя по умолчанию (иначе — браузер · ОС из User-Agent).
# Источник: passkey-authenticator-aaguids (community-реестр). Нули/неизвестный AAGUID — не беда.
KNOWN_AAGUIDS: dict[str, str] = {
    "fbfc3007-154e-4ecc-8c0b-6e020557d7bd": "iCloud Keychain",
    "dd4ec289-e01d-41c9-bb89-70fa845d4bf2": "iCloud Keychain",
    "ea9b8d66-4d01-1d21-3ce4-b6b48cb575d4": "Google Password Manager",
    "adce0002-35bc-c60a-648b-0b25f1f05503": "Chrome on Mac",
    "08987058-cadc-4b81-b6e1-30de50dcbe96": "Windows Hello",
    "9ddd1817-af5a-4672-a2b9-3e3dd95000a9": "Windows Hello",
    "6028b017-b1d4-4c02-b4b3-afcdafc96bb2": "Windows Hello",
    "bada5566-a7aa-401f-bd96-45619a55120d": "1Password",
    "d548826e-79b4-db40-a3d8-11116f7e8349": "Bitwarden",
    "531126d6-e717-415c-9320-3d9aa6981239": "Dashlane",
    "53414d53-554e-4700-0000-000000000000": "Samsung Pass",
}


def default_name(aaguid: str, user_agent: str | None) -> str:
    return KNOWN_AAGUIDS.get(aaguid.lower()) or ua_label(user_agent)


class PasskeyService:
    def __init__(self, uow: Uow, settings: Settings) -> None:
        self.uow = uow
        self.settings = settings

    def _rp(self) -> webauthn.RelyingParty:
        rp = webauthn.relying_party(self.settings.base_url)
        if rp is None:
            raise BadRequest(key="passkey.unavailable")
        return rp

    def config(self) -> dict:
        """Где ключи доступа работают: фронт сравнивает origin со своим и прячет кнопки при расхождении."""
        rp = webauthn.relying_party(self.settings.base_url)
        return {"available": rp is not None, "origin": rp.origin if rp else None, "rpId": rp.id if rp else None}

    async def list(self, user_id: str) -> list[dict]:
        async with self.uow.query() as tx:
            return [passkey_to_dict(pk) for pk in await tx.passkeys.for_user(user_id)]

    async def registration_options(self, user_id: str) -> dict:
        rp = self._rp()
        async with self.uow.transaction() as tx:
            user = await tx.users.get(user_id)
            if user is None:
                raise NotFound(key="passkey.not_found")
            existing = await tx.passkeys.for_user(user_id)
            if len(existing) >= MAX_PASSKEYS:
                raise BadRequest(key="passkey.limit_reached", params={"max": MAX_PASSKEYS})
            challenge_id, challenge = await tx.webauthn_challenges.issue(
                "register", webauthn.REGISTER_TTL, user_id=user_id
            )
            options = webauthn.registration_options(
                rp,
                challenge=challenge,
                user_id=user.id,
                user_name=user.phone,
                display_name=user.name,
                exclude=[pk.credential_id for pk in existing],
            )
        return {"challengeId": challenge_id, "publicKey": options}

    async def register(self, ident: Identity, challenge_id: str, credential: dict, *, ua: str | None = None) -> dict:
        rp = self._rp()
        user_id = ident.id
        # челлендж одноразовый: сжигаем отдельной транзакцией до проверки (см. AuthService.passkey_login)
        async with self.uow.transaction() as tx:
            row = await tx.webauthn_challenges.consume(challenge_id) if challenge_id else None
        if row is None or row[1] != "register" or row[2] != user_id or row[3] < time.time():
            raise BadRequest(key="passkey.challenge_expired")
        cred = webauthn.verify_registration(rp, credential, row[0])
        async with self.uow.transaction() as tx:
            if await tx.passkeys.by_credential_id(cred.credential_id):
                raise BadRequest(key="passkey.already_registered")
            if len(await tx.passkeys.for_user(user_id)) >= MAX_PASSKEYS:
                raise BadRequest(key="passkey.limit_reached", params={"max": MAX_PASSKEYS})
            pk = m.Passkey(
                user_id=user_id,
                credential_id=cred.credential_id,
                public_key=cred.public_key,
                sign_count=cred.sign_count,
                transports=cred.transports,
                aaguid=cred.aaguid,
                backed_up=cred.backed_up,
                name=default_name(cred.aaguid, ua)[:NAME_MAX],
            )
            tx.passkeys.add(pk)
            await tx.session.flush()
            self._audit(tx, audit_types.PASSKEY_ADD, ident, pk)
            await tx.session.refresh(pk)
            return passkey_to_dict(pk)

    async def _own(self, tx: UowTransaction, user_id: str, pid: str) -> m.Passkey:
        pk: m.Passkey | None = await tx.passkeys.get(pid)
        if pk is None or pk.user_id != user_id:
            raise NotFound(key="passkey.not_found")
        return pk

    async def rename(self, user_id: str, pid: str, name: str) -> dict:
        name = (name or "").strip()
        if not name:
            raise BadRequest(key="passkey.name_required")
        async with self.uow.transaction() as tx:
            pk = await self._own(tx, user_id, pid)
            pk.name = name[:NAME_MAX]
            await tx.session.flush()
            await tx.session.refresh(pk)
            return passkey_to_dict(pk)

    async def delete(self, ident: Identity, pid: str) -> None:
        async with self.uow.transaction() as tx:
            pk = await self._own(tx, ident.id, pid)
            self._audit(tx, audit_types.PASSKEY_REMOVE, ident, pk)
            await tx.session.delete(pk)

    @staticmethod
    def _audit(tx: UowTransaction, type_: str, ident: Identity, pk: m.Passkey) -> None:
        # actor_id == владелец ключа → событие видно ему самому (и админу), как и вход
        tx.audit.add_event(
            at=time.time(),
            actor_kind=ident.kind,
            actor_id=ident.id,
            actor_name=ident.name,
            type_=type_,
            target_kind="passkey",
            target_id=pk.id,
            meta_json=json.dumps({"name": pk.name}, ensure_ascii=False),
        )
