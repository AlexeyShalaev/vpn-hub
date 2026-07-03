"""Генерация ключей (порт genClientKeys из wireguardConfigurator + xray).

WireGuard/AmneziaWG клиентский ключ — X25519 (Curve25519), как в Amnezia:
32 случайных байта → приватный ключ, публичный = X25519(priv, base). base64 (std, с '=').
Amnezia НЕ клампит клиентский приватник (см. `genClientKeys`), wg/awg клампят при загрузке —
результат идентичен, поэтому повторяем поведение клиента 1:1.

Серверный keypair и PSK генерятся на сервере внутри контейнера (`awg genkey/pubkey/genpsk`),
здесь не нужны. Xray-клиент — это UUID; reality-ключи тоже генерятся в контейнере (`xray x25519`).
"""

from __future__ import annotations

import base64
import secrets
import string
import uuid

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
from cryptography.x509.oid import NameOID


def gen_wg_keypair() -> tuple[str, str]:
    """Возвращает (private_key_b64, public_key_b64) для WireGuard/AmneziaWG."""
    raw = secrets.token_bytes(32)
    priv = X25519PrivateKey.from_private_bytes(raw)
    pub = priv.public_key().public_bytes_raw()
    return base64.b64encode(raw).decode(), base64.b64encode(pub).decode()


def wg_pubkey(private_key_b64: str) -> str:
    """Выводит публичный ключ WireGuard из base64-приватника."""
    raw = base64.b64decode(private_key_b64)
    priv = X25519PrivateKey.from_private_bytes(raw)
    return base64.b64encode(priv.public_key().public_bytes_raw()).decode()


def gen_psk() -> str:
    """PSK WireGuard — 32 случайных байта в base64 (аналог `wg genpsk`)."""
    return base64.b64encode(secrets.token_bytes(32)).decode()


def gen_uuid() -> str:
    """UUID клиента Xray (без фигурных скобок), аналог `xray uuid`."""
    return str(uuid.uuid4())


def gen_short_id() -> str:
    """Xray Reality shortId — 16 hex-символов (аналог `openssl rand -hex 8`)."""
    return secrets.token_hex(8)


# ------------------------------------------------------------------- openvpn ---

# charset Utils::getRandomString: A-Za-z0-9 (62 символа). Метасимволов shell нет —
# CN безопасно подставляется в docker exec (плюс отдельная валидация в провизионере).
_CN_ALPHABET = string.ascii_letters + string.digits


def gen_client_cn(length: int = 32) -> str:
    """clientId/CN клиента OpenVPN — 32 символа [A-Za-z0-9] (порт Utils::getRandomString(32))."""
    return "".join(secrets.choice(_CN_ALPHABET) for _ in range(length))


def gen_openvpn_client_request(cn: str) -> tuple[str, str]:
    """(private_key_pem, csr_pem) клиента OpenVPN — RSA-2048, подпись SHA-256, subject C=ORG/CN=<cn>.

    Порт OpenVpnConfigurator::createCertRequest: ключ и CSR генерятся локально в панели,
    наружу (в контейнер) уходит только .req; приватный ключ клиента сервер никогда не видит.
    Приватник — PKCS#8 PEM (`BEGIN PRIVATE KEY`), как `PEM_write_bio_PrivateKey`.

    Amnezia кладёт в subject C=ORG/O=""/CN=<cn>, но C=ORG невалиден (страна ≠ 2 симв.),
    а O="" запрещён. Оставляем только CN — для аутентификации OpenVPN значим лишь он
    (сертификат подписывается CA, easyrsa policy_anything принимает CSR только с CN).
    """
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    csr = x509.CertificateSigningRequestBuilder().subject_name(subject).sign(key, hashes.SHA256())
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    csr_pem = csr.public_bytes(serialization.Encoding.PEM).decode()
    return priv_pem, csr_pem
