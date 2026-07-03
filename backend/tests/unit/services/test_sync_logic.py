"""Юнит-тесты чистой логики сверки (sync_logic): желаемый статус конфига, внешние клиенты, ledger долга."""

from __future__ import annotations

import pytest
from pytest_lazy_fixtures import lf

from vpnhub.services.sync_logic import (
    ConfigRow,
    ProtocolObservation,
    desired_config_status,
    dump_pending,
    external_client_ids,
    parse_pending,
    plan_drain,
)

pytestmark = pytest.mark.unit


def _obs(
    proto_id: str,
    present: bool = True,
    running: bool = True,
    readable: bool = True,
    ids: tuple[str, ...] = (),
) -> ProtocolObservation:
    """Собрать наблюдение протокола на сервере (билдер для сетапа)."""
    return ProtocolObservation(proto_id, present, running, readable, set(ids))


# ---- desired_config_status -------------------------------------------------


@pytest.fixture
def status_client_present() -> tuple[ConfigRow, dict, str]:
    """Клиент присутствует среди пиров живого протокола → active."""
    return ConfigRow("c1", "awg", "PUBKEY1"), {"awg": _obs("awg", ids=("PUBKEY1", "PUBKEY2"))}, "active"


@pytest.fixture
def status_client_missing() -> tuple[ConfigRow, dict, str]:
    """Протокол прочитан, но нашего клиента среди пиров нет → revoked."""
    return ConfigRow("c1", "awg", "PUBKEY1"), {"awg": _obs("awg", ids=("OTHER",))}, "revoked"


@pytest.fixture
def status_protocol_absent() -> tuple[ConfigRow, dict, str]:
    """Контейнер протокола отсутствует → revoked."""
    return (
        ConfigRow("c1", "awg", "PUBKEY1"),
        {"awg": _obs("awg", present=False, running=False, readable=False)},
        "revoked",
    )


@pytest.fixture
def status_not_readable() -> tuple[ConfigRow, dict, None]:
    """Контейнер есть, но клиентов не прочитали → None (не рискуем ложным revoke)."""
    return ConfigRow("c1", "awg", "PUBKEY1"), {"awg": _obs("awg", readable=False)}, None


@pytest.fixture
def status_not_observed() -> tuple[ConfigRow, dict, None]:
    """Протокол вообще не наблюдался → None (оставляем как есть)."""
    return ConfigRow("c1", "xray", "uuid"), {}, None


@pytest.mark.parametrize(
    "case",
    [
        lf("status_client_present"),
        lf("status_client_missing"),
        lf("status_protocol_absent"),
        lf("status_not_readable"),
        lf("status_not_observed"),
    ],
)
def test__desired_config_status__by_observation__returns_expected_status(
    case: tuple[ConfigRow, dict, str | None],
) -> None:
    """Желаемый статус конфига (active/revoked/None) выводится из наблюдения протокола."""
    # Arrange
    row, observations, expected = case
    # Act
    result = desired_config_status(row, observations)
    # Assert
    assert result == expected


# ---- external_client_ids ---------------------------------------------------


def test__external_client_ids__readable_observation__returns_ids_minus_ours() -> None:
    """Из живого списка пиров вычитаются наши id → остаются только внешние клиенты."""
    # Arrange
    observation = _obs("awg", ids=("OURS", "EXTERNAL1", "EXTERNAL2"))
    # Act
    external = external_client_ids(observation, {"OURS"})
    # Assert
    assert external == {"EXTERNAL1", "EXTERNAL2"}


def test__external_client_ids__not_readable__returns_empty_set() -> None:
    """Клиентов не прочитали → внешних не показываем (пустое множество, а не «все чужие»)."""
    # Arrange
    observation = _obs("awg", readable=False, ids=("X",))
    # Act
    external = external_client_ids(observation, set())
    # Assert
    assert external == set()


# ---- ledger: долг на снятие (parse_pending / dump_pending) ------------------


def test__parse_pending__roundtrip_with_dump__preserves_set() -> None:
    """dump_pending → parse_pending возвращает исходное множество client_id."""
    # Arrange
    pending = {"a", "b"}
    # Act
    restored = parse_pending(dump_pending(pending))
    # Assert
    assert restored == {"a", "b"}


@pytest.fixture
def pending_none() -> str | None:
    """Отсутствующее значение колонки."""
    return None


@pytest.fixture
def pending_empty_string() -> str:
    """Пустая строка."""
    return ""


@pytest.fixture
def pending_broken_json() -> str:
    """Битый JSON."""
    return "not json"


@pytest.mark.parametrize(
    "raw",
    [lf("pending_none"), lf("pending_empty_string"), lf("pending_broken_json")],
)
def test__parse_pending__missing_or_broken__returns_empty_set(raw: str | None) -> None:
    """None / пустая строка / битый JSON → пустое множество (не падаем)."""
    # Arrange / Act
    result = parse_pending(raw)
    # Assert
    assert result == set()


def test__dump_pending__empty_set__returns_none() -> None:
    """Пустой долг сериализуется в None — колонка остаётся чистой."""
    # Arrange / Act
    result = dump_pending(set())
    # Assert
    assert result is None


def test__parse_pending__falsy_elements__are_dropped() -> None:
    """Пустые/None элементы отбрасываются при разборе."""
    # Arrange / Act
    result = parse_pending('["a", "", null]')
    # Assert
    assert result == {"a"}


# ---- plan_drain ------------------------------------------------------------


def test__plan_drain__empty_debt__nothing_to_do() -> None:
    """Пустой долг → ни снимать, ни гасить нечего."""
    # Arrange / Act
    to_revoke, gone = plan_drain(set(), _obs("awg", ids=("X",)))
    # Assert
    assert (to_revoke, gone) == (set(), set())


def test__plan_drain__container_absent__drains_all_without_revoke() -> None:
    """Контейнер снесён (пиры мертвы) → гасим весь долг, ничего не снимаем."""
    # Arrange
    observation = _obs("awg", present=False, running=False, readable=False)
    # Act
    to_revoke, gone = plan_drain({"a", "b"}, observation)
    # Assert
    assert to_revoke == set()
    assert gone == {"a", "b"}


def test__plan_drain__not_readable__tries_to_revoke_all() -> None:
    """Клиентов не прочитали → пробуем снять весь долг (revoke идемпотентен)."""
    # Arrange
    observation = _obs("awg", readable=False)
    # Act
    to_revoke, gone = plan_drain({"a", "b"}, observation)
    # Assert
    assert to_revoke == {"a", "b"}
    assert gone == set()


def test__plan_drain__mixed_live_and_gone__splits_them() -> None:
    """Живой на сервере пир — снять; отсутствующий — погасить без снятия."""
    # Arrange
    observation = _obs("awg", ids=("live", "external"))
    # Act
    to_revoke, gone = plan_drain({"live", "gone"}, observation)
    # Assert
    assert to_revoke == {"live"}
    assert gone == {"gone"}
