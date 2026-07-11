"""Юнит-тесты чистого ядра управления Xray-Reality (без SSH/БД).

Покрываем: validate_short_id (hex чётной длины), validate_sni (формат FQDN),
rewrite_reality (переписывает dest/serverNames/shortIds, не трогает clients).
"""

from __future__ import annotations

import pytest

from vpnhub.infra.provisioning import reality
from vpnhub.infra.provisioning.errors import ProvisioningError

pytestmark = pytest.mark.unit


def _server_json() -> dict:
    return {
        "inbounds": [
            {
                "settings": {"clients": [{"id": "uuid-1", "flow": "xtls-rprx-vision"}]},
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "dest": "old.example.com:443",
                        "serverNames": ["old.example.com"],
                        "privateKey": "PK",
                        "shortIds": ["deadbeef"],
                    },
                },
            }
        ]
    }


def test__gen_short_id__is_16_hex() -> None:
    sid = reality.gen_short_id()
    assert len(sid) == 16
    assert reality.validate_short_id(sid) == sid  # свой же вывод проходит валидацию


@pytest.mark.parametrize("value", ["ab", "deadbeef", "0011223344556677"])
def test__validate_short_id__valid(value: str) -> None:
    assert reality.validate_short_id(value) == value


def test__validate_short_id__normalizes_case_and_space() -> None:
    assert reality.validate_short_id("  DEADBEEF ") == "deadbeef"


@pytest.mark.parametrize("value", ["", "a", "abc", "xyz1", "deadbeef00112233ff"])  # нечёт/нехекс/слишком длинный
def test__validate_short_id__invalid(value: str) -> None:
    with pytest.raises(ProvisioningError):
        reality.validate_short_id(value)


@pytest.mark.parametrize("value", ["www.googletagmanager.com", "Example.COM", "a.b.c.example.org", "cdn.example.io."])
def test__validate_sni__valid(value: str) -> None:
    out = reality.validate_sni(value)
    assert out == value.strip().lower().rstrip(".")


@pytest.mark.parametrize("value", ["", "localhost", "no-dot", "-bad.example.com", "bad_.com", "example.123"])
def test__validate_sni__invalid(value: str) -> None:
    with pytest.raises(ProvisioningError):
        reality.validate_sni(value)


def test__rewrite_reality__updates_only_reality_and_keeps_clients() -> None:
    doc = _server_json()
    out = reality.rewrite_reality(doc, short_id="00ff11ee", sni="new.example.net")
    r = reality.reality_of(out)
    assert r["dest"] == "new.example.net:443"
    assert r["serverNames"] == ["new.example.net"]
    assert r["shortIds"] == ["00ff11ee"]
    assert r["privateKey"] == "PK"  # приватный ключ не тронут
    # клиенты (uuid) сохранены — reprovision Reality их не сносит
    assert out["inbounds"][0]["settings"]["clients"] == [{"id": "uuid-1", "flow": "xtls-rprx-vision"}]
