"""Юнит-тесты вывода Relying Party (RP ID + ожидаемый origin) из VPNHUB_BASE_URL."""

from __future__ import annotations

import pytest

from vpnhub.infra.webauthn import RelyingParty, relying_party

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("base_url", "rp_id", "origin"),
    [
        ("https://vpn.example.com", "vpn.example.com", "https://vpn.example.com"),
        ("https://VPN.Example.com/", "vpn.example.com", "https://vpn.example.com"),
        ("https://vpn.example.com:443/panel", "vpn.example.com", "https://vpn.example.com"),
        ("https://vpn.example.com:8443", "vpn.example.com", "https://vpn.example.com:8443"),
        ("http://localhost:8000", "localhost", "http://localhost:8000"),
        ("http://panel.localhost", "panel.localhost", "http://panel.localhost"),
    ],
)
def test__relying_party__secure_or_local_host__derives_rp(base_url: str, rp_id: str, origin: str) -> None:
    assert relying_party(base_url) == RelyingParty(id=rp_id, origin=origin)


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "vpn.example.com",
        "http://vpn.example.com",  # не secure context
        "https://203.0.113.10",  # RP ID не может быть IP
        "http://[::1]:8000",
        "ftp://vpn.example.com",
        "https://vpn.example.com:99999",
    ],
)
def test__relying_party__unusable_base_url__returns_none(base_url: str) -> None:
    assert relying_party(base_url) is None
