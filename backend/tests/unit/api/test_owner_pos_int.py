"""Санитайзер лимитов из недоверенного тела запроса (owner._pos_int).

Гарантирует, что кривой JSON (строка/булево/список/float/≤0) не долетает до сравнения `> 0`
(иначе TypeError → 500) и до Integer-колонки, а превращается в корректный int|None (None = снять).
"""

from __future__ import annotations

import pytest

from vpnhub.api.routers.owner import _pos_int

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (5, 5),  # обычный положительный int
        (3.9, 3),  # float усекается к int
        (0, None),  # ноль — снять лимит
        (-4, None),  # отрицательное — снять
        (None, None),  # явный null
        ("10", None),  # строка НЕ парсится (иначе бы TypeError на сравнении) → снять
        (True, None),  # булево не считается числом лимита
        (False, None),
        ([1], None),  # список
        ({"a": 1}, None),  # объект
    ],
)
def test__pos_int__coerces_untrusted_input(value: object, expected: int | None) -> None:
    assert _pos_int({"maxDevices": value}, "maxDevices") == expected


def test__pos_int__missing_key_and_non_dict() -> None:
    assert _pos_int({}, "maxDevices") is None
    assert _pos_int({"other": 5}, "maxDevices") is None
