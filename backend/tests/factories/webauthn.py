"""Поддельный WebAuthn-аутентификатор для тестов: настоящий EC P-256 ключ, attestation "none".

Строит ответы navigator.credentials.create()/get() в JSON-форме (как отдаёт фронт), чтобы
сервер проходил полный путь проверки py_webauthn: challenge, origin, rpIdHash, флаги, подпись.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
from typing import Any

import cbor2
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec

FLAG_UP = 0x01
FLAG_UV = 0x04
FLAG_BE = 0x08
FLAG_BS = 0x10
FLAG_AT = 0x40

AAGUID_ICLOUD = "fbfc3007-154e-4ecc-8c0b-6e020557d7bd"


def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


class FakeAuthenticator:
    def __init__(
        self,
        rp_id: str = "vpn.example.com",
        origin: str = "https://vpn.example.com",
        *,
        aaguid: str = AAGUID_ICLOUD,
        counter: bool = True,
    ) -> None:
        self.rp_id = rp_id
        self.origin = origin
        self.key = ec.generate_private_key(ec.SECP256R1())
        self.credential_id = os.urandom(32)
        self.aaguid = bytes.fromhex(aaguid.replace("-", ""))
        self.counter = counter  # False — как у синхронизируемых passkeys (счётчик всегда 0)
        self.sign_count = 0
        self.user_handle: bytes | None = None

    def _cose_key(self) -> bytes:
        nums = self.key.public_key().public_numbers()
        return cbor2.dumps({1: 2, 3: -7, -1: 1, -2: nums.x.to_bytes(32, "big"), -3: nums.y.to_bytes(32, "big")})

    def _client_data(self, type_: str, challenge: str, origin: str | None) -> bytes:
        payload = {"type": type_, "challenge": challenge, "origin": origin or self.origin, "crossOrigin": False}
        return json.dumps(payload).encode()

    def _auth_data(self, flags: int, extra: bytes = b"", rp_id: str | None = None) -> bytes:
        rp_hash = hashlib.sha256((rp_id or self.rp_id).encode()).digest()
        return rp_hash + bytes([flags]) + self.sign_count.to_bytes(4, "big") + extra

    def create(
        self, options: dict[str, Any], *, origin: str | None = None, uv: bool = True, rp_id: str | None = None
    ) -> dict[str, Any]:
        """Ответ navigator.credentials.create() на publicKey-опции сервера."""
        self.user_handle = base64.urlsafe_b64decode(options["user"]["id"] + "==")
        flags = FLAG_UP | FLAG_AT | (FLAG_UV if uv else 0)
        attested = self.aaguid + len(self.credential_id).to_bytes(2, "big") + self.credential_id + self._cose_key()
        auth_data = self._auth_data(flags, attested, rp_id)
        attestation = cbor2.dumps({"fmt": "none", "attStmt": {}, "authData": auth_data})
        client_data = self._client_data("webauthn.create", options["challenge"], origin)
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "attestationObject": b64url(attestation),
                "transports": ["internal", "hybrid"],
            },
            "clientExtensionResults": {},
        }

    def get(
        self,
        options: dict[str, Any],
        *,
        origin: str | None = None,
        uv: bool = True,
        user_handle: bytes | None = None,
        sign_count: int | None = None,
    ) -> dict[str, Any]:
        """Ответ navigator.credentials.get() (подписанный assertion)."""
        if sign_count is not None:
            self.sign_count = sign_count
        elif self.counter:
            self.sign_count += 1
        auth_data = self._auth_data(FLAG_UP | (FLAG_UV if uv else 0))
        client_data = self._client_data("webauthn.get", options["challenge"], origin)
        signature = self.key.sign(auth_data + hashlib.sha256(client_data).digest(), ec.ECDSA(hashes.SHA256()))
        handle = user_handle if user_handle is not None else self.user_handle
        return {
            "id": b64url(self.credential_id),
            "rawId": b64url(self.credential_id),
            "type": "public-key",
            "response": {
                "clientDataJSON": b64url(client_data),
                "authenticatorData": b64url(auth_data),
                "signature": b64url(signature),
                "userHandle": b64url(handle) if handle else None,
            },
            "clientExtensionResults": {},
        }
