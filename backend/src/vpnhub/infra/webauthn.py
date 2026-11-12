"""WebAuthn-церемонии ключей доступа (passkeys) поверх py_webauthn.

Relying Party выводится из `VPNHUB_BASE_URL`: RP ID — хост, ожидаемый origin — схема+хост+порт.
Браузер привязывает ключ к RP ID и подписывает origin страницы, поэтому панель должна открываться
ровно по адресу из base_url. На IP-адресе и на http (кроме localhost) WebAuthn не работает —
тогда ключи доступа просто недоступны (`relying_party()` → None).

Ошибки py_webauthn превращаем в доменные (`BadRequest`/`Unauthorized`) с i18n-ключами.
"""

from __future__ import annotations

import ipaddress
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers import parse_authentication_credential_json, parse_registration_credential_json
from webauthn.helpers.exceptions import WebAuthnException
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticationCredential,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    RegistrationCredential,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from vpnhub.core.errors import BadRequest, Unauthorized

RP_NAME = "VPN Hub"
TIMEOUT_MS = 120_000
# Вход: conditional UI (автозаполнение) может висеть на форме долго — даём челленджу запас.
LOGIN_TTL = 600.0
REGISTER_TTL = 300.0

_DEFAULT_PORTS = {"http": 80, "https": 443}


@dataclass(frozen=True)
class RelyingParty:
    id: str
    origin: str
    name: str = RP_NAME


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def relying_party(base_url: str) -> RelyingParty | None:
    """RP из base_url; None — если ключи доступа на таком адресе невозможны (IP, http не на localhost)."""
    parts = urlsplit((base_url or "").strip())
    scheme = parts.scheme.lower()
    host = (parts.hostname or "").lower().rstrip(".")
    if scheme not in _DEFAULT_PORTS or not host:
        return None
    if _is_ip(host):
        return None  # RP ID не может быть IP-адресом
    is_local = host == "localhost" or host.endswith(".localhost")
    if scheme != "https" and not is_local:
        return None  # WebAuthn требует secure context
    try:
        port = parts.port
    except ValueError:
        return None
    origin = f"{scheme}://{host}" if port in (None, _DEFAULT_PORTS[scheme]) else f"{scheme}://{host}:{port}"
    return RelyingParty(id=host, origin=origin)


def _options_dict(options: Any) -> dict[str, Any]:
    return dict(json.loads(options_to_json(options)))


def registration_options(
    rp: RelyingParty,
    *,
    challenge: bytes,
    user_id: str,
    user_name: str,
    display_name: str,
    exclude: list[bytes],
) -> dict[str, Any]:
    # resident key обязателен: вход без логина (usernameless + автозаполнение) находит ключ только так.
    # user verification обязательна: ключ доступа заменяет пароль целиком, одного «касания» мало.
    options = generate_registration_options(
        rp_id=rp.id,
        rp_name=rp.name,
        user_id=user_id.encode(),
        user_name=user_name,
        user_display_name=display_name,
        challenge=challenge,
        timeout=TIMEOUT_MS,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            resident_key=ResidentKeyRequirement.REQUIRED,
            require_resident_key=True,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
        exclude_credentials=[PublicKeyCredentialDescriptor(id=c) for c in exclude],
    )
    return _options_dict(options)


def authentication_options(rp: RelyingParty, *, challenge: bytes) -> dict[str, Any]:
    # allowCredentials пустой — браузер сам предложит ключи этого сайта (discoverable credentials)
    options = generate_authentication_options(
        rp_id=rp.id,
        challenge=challenge,
        timeout=TIMEOUT_MS,
        user_verification=UserVerificationRequirement.REQUIRED,
    )
    return _options_dict(options)


@dataclass(frozen=True)
class NewCredential:
    credential_id: bytes
    public_key: bytes
    sign_count: int
    aaguid: str
    backed_up: bool
    transports: list[str]


def parse_registration(credential: dict[str, Any]) -> RegistrationCredential:
    try:
        return parse_registration_credential_json(credential)
    except (WebAuthnException, KeyError, TypeError, ValueError) as exc:
        raise BadRequest(key="passkey.verification_failed") from exc


def verify_registration(rp: RelyingParty, credential: dict[str, Any], challenge: bytes) -> NewCredential:
    parsed = parse_registration(credential)
    try:
        verified = verify_registration_response(
            credential=parsed,
            expected_challenge=challenge,
            expected_rp_id=rp.id,
            expected_origin=rp.origin,
            require_user_verification=True,
        )
    except (WebAuthnException, KeyError, TypeError, ValueError) as exc:
        raise BadRequest(key="passkey.verification_failed") from exc
    transports = [str(t.value) for t in (parsed.response.transports or [])]
    return NewCredential(
        credential_id=verified.credential_id,
        public_key=verified.credential_public_key,
        sign_count=verified.sign_count,
        aaguid=verified.aaguid,
        backed_up=verified.credential_backed_up,
        transports=transports,
    )


def parse_assertion(credential: dict[str, Any]) -> AuthenticationCredential:
    try:
        return parse_authentication_credential_json(credential)
    except (WebAuthnException, KeyError, TypeError, ValueError) as exc:
        raise Unauthorized(key="passkey.verification_failed") from exc


@dataclass(frozen=True)
class VerifiedAssertion:
    new_sign_count: int
    backed_up: bool


def verify_assertion(
    rp: RelyingParty,
    credential: AuthenticationCredential,
    challenge: bytes,
    *,
    public_key: bytes,
    sign_count: int,
) -> VerifiedAssertion:
    # py_webauthn сам отклоняет откат sign count (если хоть один из счётчиков ненулевой) — признак клона
    try:
        verified = verify_authentication_response(
            credential=credential,
            expected_challenge=challenge,
            expected_rp_id=rp.id,
            expected_origin=rp.origin,
            credential_public_key=public_key,
            credential_current_sign_count=sign_count,
            require_user_verification=True,
        )
    except (WebAuthnException, KeyError, TypeError, ValueError) as exc:
        raise Unauthorized(key="passkey.verification_failed") from exc
    return VerifiedAssertion(new_sign_count=verified.new_sign_count, backed_up=verified.credential_backed_up)


def user_handle_matches(credential: AuthenticationCredential, user_id: str) -> bool:
    """userHandle из ответа (если есть) должен совпадать с владельцем ключа."""
    handle = credential.response.user_handle
    return handle is None or bytes(handle) == user_id.encode()


__all__ = [
    "LOGIN_TTL",
    "REGISTER_TTL",
    "NewCredential",
    "RelyingParty",
    "VerifiedAssertion",
    "authentication_options",
    "parse_assertion",
    "registration_options",
    "relying_party",
    "user_handle_matches",
    "verify_assertion",
    "verify_registration",
]
