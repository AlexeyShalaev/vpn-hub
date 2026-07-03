"""Юнит-тесты доверия прокси-заголовкам (rate-limit / Secure-cookie).

Без trusted_proxy X-Forwarded-* игнорируются (иначе rate-limit обходится подделкой XFF);
с trusted_proxy берётся правый элемент XFF (его дописал доверенный прокси).
"""

from __future__ import annotations

import pytest
from starlette.requests import Request

from vpnhub.api.config import Settings
from vpnhub.api.deps import _client_ip, _forwarded_https

pytestmark = pytest.mark.unit


def _request(headers: dict[str, str], client_host: str = "10.9.9.9") -> Request:
    raw = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw,
        "query_string": b"",
        "client": (client_host, 12345),
        "server": ("test", 80),
        "scheme": "http",
    }
    return Request(scope)


def _settings(*, trusted_proxy: bool) -> Settings:
    return Settings(_env_file=None, trusted_proxy=trusted_proxy)


def test__client_ip__untrusted__ignores_xff_uses_peer() -> None:
    req = _request({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}, client_host="10.9.9.9")
    assert _client_ip(req, _settings(trusted_proxy=False)) == "10.9.9.9"


def test__client_ip__trusted__takes_rightmost_xff() -> None:
    # левый элемент клиент может подделать; реальный клиент — тот, что дописал доверенный прокси (правый)
    req = _request({"X-Forwarded-For": "1.2.3.4, 203.0.113.7"}, client_host="10.9.9.9")
    assert _client_ip(req, _settings(trusted_proxy=True)) == "203.0.113.7"


def test__client_ip__trusted_no_xff__falls_back_to_peer() -> None:
    req = _request({}, client_host="10.9.9.9")
    assert _client_ip(req, _settings(trusted_proxy=True)) == "10.9.9.9"


def test__forwarded_https__untrusted__false_even_if_header_https() -> None:
    req = _request({"X-Forwarded-Proto": "https"})
    assert _forwarded_https(req, _settings(trusted_proxy=False)) is False


def test__forwarded_https__trusted_https__true() -> None:
    req = _request({"X-Forwarded-Proto": "https"})
    assert _forwarded_https(req, _settings(trusted_proxy=True)) is True


def test__forwarded_https__trusted_http__false() -> None:
    req = _request({"X-Forwarded-Proto": "http"})
    assert _forwarded_https(req, _settings(trusted_proxy=True)) is False
