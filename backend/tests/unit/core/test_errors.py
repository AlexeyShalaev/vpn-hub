"""Юнит-тесты доменных ошибок (`vpnhub.core.errors`)."""

from __future__ import annotations

import pytest
from pytest_lazy_fixtures import lf

from vpnhub.core.errors import (
    BadRequest,
    DomainError,
    Forbidden,
    NotFound,
    TooManyRequests,
    Unauthorized,
)

pytestmark = pytest.mark.unit


# --- Фикстуры-экземпляры для parametrize по подклассам --------------------


@pytest.fixture
def not_found() -> NotFound:
    """Экземпляр NotFound со стандартным сообщением."""
    return NotFound()


@pytest.fixture
def unauthorized() -> Unauthorized:
    """Экземпляр Unauthorized со стандартным сообщением."""
    return Unauthorized()


@pytest.fixture
def forbidden() -> Forbidden:
    """Экземпляр Forbidden со стандартным сообщением."""
    return Forbidden()


@pytest.fixture
def bad_request() -> BadRequest:
    """Экземпляр BadRequest с явным сообщением и дефолтным кодом."""
    return BadRequest("Плохой запрос")


@pytest.fixture
def too_many_requests() -> TooManyRequests:
    """Экземпляр TooManyRequests со стандартным сообщением."""
    return TooManyRequests()


# --- DomainError (базовый класс) ------------------------------------------


def test__domain_error__init__stores_all_fields() -> None:
    """DomainError сохраняет переданные code, message и http_status."""
    # Arrange
    code, message, http_status = "MY_CODE", "что-то пошло не так", 418

    # Act
    err = DomainError(code, message, http_status)

    # Assert
    assert err.code == code
    assert err.message == message
    assert err.http_status == http_status


def test__domain_error__init__default_http_status_is_400() -> None:
    """DomainError без явного http_status использует 400 по умолчанию."""
    # Arrange / Act
    err = DomainError("CODE", "msg")

    # Assert
    assert err.http_status == 400


def test__domain_error__str__equals_message() -> None:
    """str(DomainError) возвращает message (передан в Exception)."""
    # Arrange
    message = "человекочитаемое сообщение"

    # Act
    err = DomainError("CODE", message, 400)

    # Assert
    assert str(err) == message


def test__domain_error__is_exception__can_be_raised_and_caught() -> None:
    """DomainError — наследник Exception и ловится через pytest.raises."""
    # Arrange / Act / Assert
    with pytest.raises(DomainError) as exc_info:
        raise DomainError("CODE", "boom", 500)
    assert exc_info.value.http_status == 500


# --- Подклассы: тип, http_status и code -----------------------------------


@pytest.mark.parametrize(
    ("err", "expected_status", "expected_code"),
    [
        (lf("not_found"), 404, "NOT_FOUND"),
        (lf("unauthorized"), 401, "UNAUTHORIZED"),
        (lf("forbidden"), 403, "FORBIDDEN"),
        (lf("bad_request"), 400, "BAD_REQUEST"),
        (lf("too_many_requests"), 429, "TOO_MANY_REQUESTS"),
    ],
)
def test__error_subclass__default_init__has_expected_status_and_code(
    err: DomainError, expected_status: int, expected_code: str
) -> None:
    """Каждый подкласс задаёт свои http_status и code."""
    # Arrange (err создан фикстурой)
    # Act
    status, code = err.http_status, err.code

    # Assert
    assert status == expected_status
    assert code == expected_code


@pytest.mark.parametrize(
    "err",
    [
        lf("not_found"),
        lf("unauthorized"),
        lf("forbidden"),
        lf("bad_request"),
        lf("too_many_requests"),
    ],
)
def test__error_subclass__any__is_domain_error_instance(err: DomainError) -> None:
    """Любой подкласс является экземпляром DomainError."""
    # Arrange / Act / Assert
    assert isinstance(err, DomainError)


@pytest.mark.parametrize(
    "err",
    [
        lf("not_found"),
        lf("unauthorized"),
        lf("forbidden"),
        lf("bad_request"),
        lf("too_many_requests"),
    ],
)
def test__error_subclass__str__equals_message(err: DomainError) -> None:
    """У любого подкласса str(err) совпадает с его message."""
    # Arrange / Act
    text = str(err)

    # Assert
    assert text == err.message
    assert text != ""


# --- Дефолтные сообщения подклассов ---------------------------------------


def test__not_found__no_message__uses_default_message() -> None:
    """NotFound без аргумента подставляет дефолтное сообщение."""
    # Arrange / Act
    err = NotFound()

    # Assert
    assert err.message == "Не найдено"


def test__unauthorized__no_message__uses_default_message() -> None:
    """Unauthorized без аргумента подставляет дефолтное сообщение."""
    # Arrange / Act
    err = Unauthorized()

    # Assert
    assert err.message == "Требуется вход"


def test__forbidden__no_message__uses_default_message() -> None:
    """Forbidden без аргумента подставляет дефолтное сообщение."""
    # Arrange / Act
    err = Forbidden()

    # Assert
    assert err.message == "Недостаточно прав"


def test__too_many_requests__no_message__uses_default_message() -> None:
    """TooManyRequests без аргумента подставляет дефолтное сообщение."""
    # Arrange / Act
    err = TooManyRequests()

    # Assert
    assert err.message == "Слишком много попыток, попробуйте позже"


def test__not_found__custom_message__overrides_default() -> None:
    """NotFound принимает пользовательское сообщение вместо дефолтного."""
    # Arrange
    message = "Устройство не найдено"

    # Act
    err = NotFound(message)

    # Assert
    assert err.message == message
    assert str(err) == message


# --- BadRequest: кастомный code -------------------------------------------


def test__bad_request__no_code__defaults_to_bad_request() -> None:
    """BadRequest без кода использует code=BAD_REQUEST."""
    # Arrange / Act
    err = BadRequest("Неверные данные")

    # Assert
    assert err.code == "BAD_REQUEST"
    assert err.http_status == 400


def test__bad_request__custom_code__stores_that_code() -> None:
    """BadRequest сохраняет переданный кастомный code, но статус остаётся 400."""
    # Arrange
    custom_code = "PHONE_TAKEN"

    # Act
    err = BadRequest("Телефон занят", code=custom_code)

    # Assert
    assert err.code == custom_code
    assert err.http_status == 400
    assert err.message == "Телефон занят"


# --- TooManyRequests: retry_after -----------------------------------------


def test__too_many_requests__no_retry_after__defaults_to_zero() -> None:
    """TooManyRequests без retry_after хранит 0."""
    # Arrange / Act
    err = TooManyRequests()

    # Assert
    assert err.retry_after == 0


def test__too_many_requests__custom_retry_after__stores_value() -> None:
    """TooManyRequests сохраняет переданный retry_after."""
    # Arrange
    retry_after = 42

    # Act
    err = TooManyRequests("Подождите", retry_after=retry_after)

    # Assert
    assert err.retry_after == retry_after
    assert err.message == "Подождите"
    assert err.http_status == 429
