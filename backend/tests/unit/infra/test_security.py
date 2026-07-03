"""Юнит-тесты infra.security: пароли, Fernet-шифрование, телефоны, токены, под-ключи."""

from __future__ import annotations

import pytest
from pytest_lazy_fixtures import lf

from vpnhub.core.errors import BadRequest
from vpnhub.infra.security import (
    DEFAULT_INSECURE_SECRET_KEY,
    MIN_PASSWORD_LEN,
    backup_secret,
    data_secret,
    decrypt_secret,
    encrypt_secret,
    format_phone,
    gen_secret_key,
    gen_token,
    hash_password,
    hash_token,
    is_default_secret_key,
    is_valid_phone,
    new_session_token,
    normalize_phone,
    validate_password,
    verify_password,
)

pytestmark = pytest.mark.unit


# --------------------------------------------------------------- пароли (argon2) ---


def test__hash_password__any_plain__returns_argon2_hash():
    """hash_password возвращает argon2-хеш (префикс $argon2), отличный от исходного пароля."""
    # Arrange
    plain = "Passw0rd!"
    # Act
    hashed = hash_password(plain)
    # Assert
    assert hashed.startswith("$argon2")
    assert hashed != plain


def test__hash_password__same_input_twice__gives_different_hashes():
    """Соль делает два хеша одного пароля разными (детерминизма быть не должно)."""
    # Arrange
    plain = "Passw0rd!"
    # Act
    first = hash_password(plain)
    second = hash_password(plain)
    # Assert
    assert first != second


def test__verify_password__correct_password__returns_true():
    """verify_password с верным паролем к своему хешу → True."""
    # Arrange
    plain = "Passw0rd!"
    hashed = hash_password(plain)
    # Act
    result = verify_password(hashed, plain)
    # Assert
    assert result is True


def test__verify_password__wrong_password__returns_false():
    """verify_password с неверным паролем → False (без исключения)."""
    # Arrange
    hashed = hash_password("Passw0rd!")
    # Act
    result = verify_password(hashed, "WrongPass1!")
    # Assert
    assert result is False


def test__verify_password__malformed_hash__returns_false():
    """Битый (не argon2) хеш перехватывается и даёт False, а не падение."""
    # Arrange
    broken_hash = "not-a-real-argon2-hash"
    # Act
    result = verify_password(broken_hash, "Passw0rd!")
    # Assert
    assert result is False


# --------------------------------------------------- Fernet: encrypt/decrypt ---


def test__encrypt_decrypt_secret__round_trip__recovers_plaintext():
    """decrypt_secret возвращает ровно то, что зашифровал encrypt_secret тем же ключом."""
    # Arrange
    key = "master-key-abc"
    plain = "ssh-private-key-material"
    # Act
    token = encrypt_secret(key, plain)
    recovered = decrypt_secret(key, token)
    # Assert
    assert recovered == plain


def test__encrypt_secret__same_plaintext_twice__gives_different_tokens():
    """Fernet использует случайный IV → два шифртекста одного plaintext различаются."""
    # Arrange
    key = "master-key-abc"
    plain = "same-secret"
    # Act
    first = encrypt_secret(key, plain)
    second = encrypt_secret(key, plain)
    # Assert
    assert first != second


def test__decrypt_secret__wrong_key__returns_empty_string():
    """Токен, зашифрованный чужим ключом, не расшифровывается → пустая строка."""
    # Arrange
    token = encrypt_secret("key-one", "top-secret")
    # Act
    recovered = decrypt_secret("key-two", token)
    # Assert
    assert recovered == ""


def test__decrypt_secret__garbage_token__returns_empty_string():
    """Мусорный (не-Fernet) токен обрабатывается без исключения → пустая строка."""
    # Arrange
    garbage = "this-is-not-a-fernet-token"
    # Act
    recovered = decrypt_secret("some-key", garbage)
    # Assert
    assert recovered == ""


# --------------------------------------------------------------- телефоны ---


@pytest.fixture
def phone_ru_local() -> str:
    """RU-локальный номер в формате «8 900 …»."""
    return "8 900 111-22-33"


@pytest.fixture
def phone_e164() -> str:
    """Тот же номер уже в E.164 с «+7»."""
    return "+7 900 111 22 33"


@pytest.fixture
def phone_junk_with_digits() -> str:
    """Мусорная строка, из которой валидный номер не собирается, но есть цифры."""
    return "abc123def456"


@pytest.fixture
def phone_empty() -> str:
    """Пустая строка."""
    return ""


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (lf("phone_ru_local"), "+79001112233"),
        (lf("phone_e164"), "+79001112233"),
    ],
)
def test__normalize_phone__valid_ru_number__to_e164(raw: str, expected: str):
    """Валидный RU-номер (локальный «8…» или «+7…») нормализуется в единый E.164."""
    # Act
    result = normalize_phone(raw)
    # Assert
    assert result == expected


def test__normalize_phone__junk_string__falls_back_to_digits_only():
    """Невалидный ввод → фоллбэк «только цифры» (для ленивого поиска)."""
    # Arrange
    raw = "abc123def456"
    # Act
    result = normalize_phone(raw)
    # Assert
    assert result == "123456"


def test__normalize_phone__empty_string__returns_empty():
    """Пустой ввод → пустая строка (без падения)."""
    # Act
    result = normalize_phone("")
    # Assert
    assert result == ""


@pytest.fixture
def phone_valid_full() -> str:
    """Полностью валидный RU-номер в E.164."""
    return "+79001112233"


@pytest.fixture
def phone_too_short() -> str:
    """Слишком короткий набор цифр — не валиден как номер."""
    return "123"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (lf("phone_valid_full"), True),
        (lf("phone_ru_local"), True),
        (lf("phone_too_short"), False),
        (lf("phone_junk_with_digits"), False),
        (lf("phone_empty"), False),
    ],
)
def test__is_valid_phone__various_inputs__matches_validity(raw: str, expected: bool):
    """is_valid_phone: True только для настоящих номеров, False для мусора/короткого/пустого."""
    # Act
    result = is_valid_phone(raw)
    # Assert
    assert result is expected


def test__format_phone__valid_number__international_display():
    """Валидный номер форматируется в международный вид для отображения."""
    # Arrange
    raw = "+79001112233"
    # Act
    result = format_phone(raw)
    # Assert
    assert result == "+7 900 111-22-33"


def test__format_phone__invalid_number__returned_as_is():
    """Невалидный ввод возвращается без изменений."""
    # Arrange
    raw = "not-a-phone"
    # Act
    result = format_phone(raw)
    # Assert
    assert result == "not-a-phone"


# --------------------------------------------------- парольная политика ---


@pytest.fixture
def pwd_too_short() -> str:
    """Короче MIN_PASSWORD_LEN, но с двумя классами символов."""
    return "Ab1"


@pytest.fixture
def pwd_single_class() -> str:
    """Достаточно длинный, но только один класс символов (строчные буквы)."""
    return "abcdefghij"


@pytest.mark.parametrize(
    "bad_password",
    [
        lf("pwd_too_short"),
        lf("pwd_single_class"),
    ],
)
def test__validate_password__policy_violation__raises_bad_request(bad_password: str):
    """Слишком короткий пароль или один класс символов → BadRequest (http 400)."""
    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        validate_password(bad_password)
    assert exc.value.http_status == 400
    assert exc.value.code == "BAD_REQUEST"


def test__validate_password__short_uses_min_len_message():
    """Слишком короткий пароль → сообщение упоминает минимальную длину."""
    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        validate_password("Ab1")
    assert str(MIN_PASSWORD_LEN) in exc.value.message


def test__validate_password__long_and_exactly_two_classes__passes():
    """Пароль нужной длины ровно с двумя классами символов проходит порог classes >= 2."""
    # Arrange
    good = "password1"  # 9 символов, ровно 2 класса: строчные буквы + цифра
    # Act
    result = validate_password(good)
    # Assert
    assert result is None


def test__validate_password__custom_min_len__enforced():
    """Кастомный min_len применяется: длинный пароль ниже порога → BadRequest."""
    # Arrange
    pwd = "Ab1"  # два класса, но короче 12
    # Act / Assert
    with pytest.raises(BadRequest):
        validate_password(pwd, min_len=12)


# --------------------------------------------------- под-ключи (HKDF) ---


def test__data_secret__same_master__deterministic():
    """data_secret детерминирован: один master → один и тот же под-ключ."""
    # Arrange
    master = "recovery-master-key"
    # Act
    first = data_secret(master)
    second = data_secret(master)
    # Assert
    assert first == second


def test__backup_secret__same_master__deterministic():
    """backup_secret детерминирован: один master → один и тот же под-ключ."""
    # Arrange
    master = "recovery-master-key"
    # Act
    first = backup_secret(master)
    second = backup_secret(master)
    # Assert
    assert first == second


def test__data_secret_vs_backup_secret__same_master__domain_separated():
    """Доменное разделение: из одного master data- и backup-ключи различны."""
    # Arrange
    master = "recovery-master-key"
    # Act
    data = data_secret(master)
    backup = backup_secret(master)
    # Assert
    assert data != backup


def test__data_secret__different_masters__different_subkeys():
    """Разные master дают разные data-под-ключи."""
    # Act
    one = data_secret("master-one")
    two = data_secret("master-two")
    # Assert
    assert one != two


def test__data_secret__derives_fernet_usable_key():
    """Под-ключ data_secret пригоден как ключ для encrypt/decrypt round-trip."""
    # Arrange
    key = data_secret("recovery-master-key")
    plain = "vpn-material"
    # Act
    recovered = decrypt_secret(key, encrypt_secret(key, plain))
    # Assert
    assert recovered == plain


# --------------------------------------------------- токены сессий ---


def test__hash_token__same_token__deterministic_sha256_hex():
    """hash_token детерминирован и возвращает 64-символьный hex (sha256)."""
    # Arrange
    token = "session-token-abc"
    # Act
    first = hash_token(token)
    second = hash_token(token)
    # Assert
    assert first == second
    assert len(first) == 64
    assert all(ch in "0123456789abcdef" for ch in first)


def test__hash_token__different_tokens__different_hashes():
    """Разные токены → разные хеши."""
    # Act
    a = hash_token("token-a")
    b = hash_token("token-b")
    # Assert
    assert a != b


def test__new_session_token__two_calls__are_unique():
    """new_session_token выдаёт непустые и различающиеся между вызовами токены."""
    # Act
    first = new_session_token()
    second = new_session_token()
    # Assert
    assert first
    assert first != second


# --------------------------------------------------- прочие токены/ключи ---


def test__gen_token__with_prefix__prefixed_and_hex_body():
    """gen_token(prefix) → «prefix-<hex>» с непустым hex-телом."""
    # Act
    token = gen_token("inv")
    # Assert
    prefix, _, body = token.partition("-")
    assert prefix == "inv"
    assert body
    assert all(ch in "0123456789abcdef" for ch in body)


def test__gen_token__no_prefix__bare_hex_body():
    """gen_token() без префикса → голое hex-тело без дефиса."""
    # Act
    token = gen_token()
    # Assert
    assert "-" not in token
    assert all(ch in "0123456789abcdef" for ch in token)


def test__gen_token__two_calls__are_unique():
    """Два вызова gen_token дают разные значения (случайность)."""
    # Act
    first = gen_token("inv")
    second = gen_token("inv")
    # Assert
    assert first != second


def test__is_default_secret_key__default_value__returns_true():
    """Дефолтный небезопасный ключ распознаётся как дефолтный."""
    # Act
    result = is_default_secret_key(DEFAULT_INSECURE_SECRET_KEY)
    # Assert
    assert result is True


def test__is_default_secret_key__custom_value__returns_false():
    """Любой не-дефолтный ключ → False."""
    # Act
    result = is_default_secret_key("my-strong-custom-key")
    # Assert
    assert result is False


def test__is_default_secret_key__none__returns_false():
    """None не приравнивается к дефолтному ключу (безопасная нормализация)."""
    # Act
    result = is_default_secret_key(None)  # type: ignore[arg-type]
    # Assert
    assert result is False


def test__gen_secret_key__two_calls__are_unique_and_nonempty():
    """gen_secret_key возвращает непустые и различающиеся сильные ключи."""
    # Act
    first = gen_secret_key()
    second = gen_secret_key()
    # Assert
    assert first
    assert first != second


def test__gen_secret_key__result__is_not_default_key():
    """Сгенерированный ключ не совпадает с дефолтным небезопасным."""
    # Act
    key = gen_secret_key()
    # Assert
    assert is_default_secret_key(key) is False
