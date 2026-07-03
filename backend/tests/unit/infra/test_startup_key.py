"""Юнит-тесты keyring.startup_key_action: решение по мастер-ключу при старте."""

from __future__ import annotations

import pytest

from vpnhub.infra.keyring import startup_key_action

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("insecure", "setup_pending", "is_https", "expected"),
    [
        (False, False, True, "ok"),  # безопасный ключ — всегда ok
        (False, True, False, "ok"),
        (True, True, True, "setup"),  # дефолт, но админа ещё нет → setup-экран задаст ключ
        (True, True, False, "setup"),
        (True, False, True, "block"),  # дефолт на https с существующим админом → отказ старта
        (True, False, False, "warn"),  # дефолт на http с админом → предупреждение (dev)
    ],
)
def test__startup_key_action__matrix(insecure, setup_pending, is_https, expected):
    """Матрица (insecure × setup_pending × https) → действие; ключевой кейс — 'block' на боевом."""
    # Act
    action = startup_key_action(insecure=insecure, setup_pending=setup_pending, is_https=is_https)
    # Assert
    assert action == expected
