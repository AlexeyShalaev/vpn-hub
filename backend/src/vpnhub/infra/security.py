"""Безопасность: argon2-пароли, Fernet-шифрование SSH-секретов, токены сессий."""

from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets

import phonenumbers
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from vpnhub.core.errors import BadRequest

_ph = PasswordHasher()

# Дефолтный ключ из репозитория — небезопасен: при нём секреты шифруются известным всем ключом.
DEFAULT_INSECURE_SECRET_KEY = "dev-insecure-secret-change-me-0123456789abcdef"

MIN_PASSWORD_LEN = 8

# Единый мастер-ключ восстановления → HKDF-выводим отдельные под-ключи под каждую задачу
# (domain separation: значения независимы, но пользователь хранит одну строку).
_DATA_LABEL = b"vpnhub/data/v1"  # шифрование SSH-секретов и VPN-материала (Fernet)
_BACKUP_LABEL = b"vpnhub/backup/v1"  # парольная фраза для шифрования бэкапов (AES-GCM)


def hash_password(plain: str) -> str:
    return _ph.hash(plain)


def verify_password(hashed: str, plain: str) -> bool:
    try:
        return _ph.verify(hashed, plain)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def _fernet(secret_key: str) -> Fernet:
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode()).digest())
    return Fernet(key)


def encrypt_secret(secret_key: str, plain: str) -> str:
    return _fernet(secret_key).encrypt(plain.encode()).decode()


def decrypt_secret(secret_key: str, token: str) -> str:
    try:
        return _fernet(secret_key).decrypt(token.encode()).decode()
    except Exception:
        return ""


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# Регион по умолчанию для номеров без "+" (напр. "8 900…" / "9 900…"). Настраивается env.
_DEFAULT_REGION = os.environ.get("VPNHUB_DEFAULT_REGION", "RU")


def _parse_phone(value: str, region: str | None = None) -> phonenumbers.PhoneNumber | None:
    try:
        return phonenumbers.parse(value or "", region or _DEFAULT_REGION)
    except phonenumbers.NumberParseException:
        return None


def normalize_phone(value: str, region: str | None = None) -> str:
    """К E.164 (`+79001234567`). Некорректный номер → фоллбэк «только цифры» (лениво, для поиска)."""
    num = _parse_phone(value, region)
    if num is not None and phonenumbers.is_valid_number(num):
        return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.E164)
    return "".join(ch for ch in (value or "") if ch.isdigit())


def is_valid_phone(value: str, region: str | None = None) -> bool:
    num = _parse_phone(value, region)
    return num is not None and phonenumbers.is_valid_number(num)


def format_phone(value: str, region: str | None = None) -> str:
    """Международный формат для отображения; если номер не валиден — возвращаем как есть."""
    num = _parse_phone(value, region)
    if num is not None and phonenumbers.is_valid_number(num):
        return phonenumbers.format_number(num, phonenumbers.PhoneNumberFormat.INTERNATIONAL)
    return value or ""


def is_default_secret_key(key: str) -> bool:
    return (key or "") == DEFAULT_INSECURE_SECRET_KEY


def gen_secret_key() -> str:
    """Сильный случайный ключ (для генерации при первом старте / подсказки в проде)."""
    return secrets.token_urlsafe(48)


# Мастер-ключ и производные под-ключи -----------------------------------------

is_default_master_key = is_default_secret_key
gen_master_key = gen_secret_key


def _derive(master: str, label: bytes, length: int = 32) -> str:
    raw = HKDF(algorithm=hashes.SHA256(), length=length, salt=None, info=label).derive((master or "").encode())
    return raw.hex()


def data_secret(master: str) -> str:
    """Под-ключ для Fernet-шифрования секретов (SSH/VPN). Возвращается как строка (её и ждёт _fernet)."""
    return _derive(master, _DATA_LABEL)


def backup_secret(master: str) -> str:
    """Под-ключ (парольная фраза) для шифрования файлов бэкапов."""
    return _derive(master, _BACKUP_LABEL)


def validate_password(password: str, *, min_len: int = MIN_PASSWORD_LEN) -> None:
    """Парольная политика: длина + минимум два класса символов. Бросает BadRequest."""
    pwd = password or ""
    if len(pwd) < min_len:
        raise BadRequest(key="security.password_too_short", params={"min_len": min_len})
    classes = sum(bool(re.search(pat, pwd)) for pat in (r"[a-zа-яё]", r"[A-ZА-ЯЁ]", r"\d", r"[^\w\s]"))
    if classes < 2:
        raise BadRequest(key="security.password_too_weak")


def gen_token(prefix: str = "") -> str:
    body = secrets.token_hex(3)
    return f"{prefix}-{body}" if prefix else body
