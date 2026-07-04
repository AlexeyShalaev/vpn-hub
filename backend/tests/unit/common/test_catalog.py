"""Юнит-тесты справочника каталога VPN: клиенты по типу/платформе и инварианты словарей."""

from __future__ import annotations

import pytest
from pytest_lazy_fixtures import lf

from vpnhub.common.catalog import (
    CLIENTS,
    DEFAULT_PORTS,
    PROTOS,
    VPN_DESC,
    VPN_DOT,
    VPN_LABELS,
    clients_for,
)

pytestmark = pytest.mark.unit

# Поддерживаемые типы VPN — эталон для проверки согласованности словарей.
VPN_TYPES = ("amnezia", "openvpn", "outline", "hysteria2")
# Платформы, для которых каталог обязан вернуть непустой список клиентов у каждого типа.
PLATFORMS_WITH_CLIENTS = ("ios", "android", "mac", "windows", "linux")


@pytest.mark.parametrize("vpn_type", VPN_TYPES)
@pytest.mark.parametrize("platform", PLATFORMS_WITH_CLIENTS)
def test__clients_for__known_combo__returns_nonempty_dicts_with_url(vpn_type: str, platform: str) -> None:
    """Известная пара тип+платформа → непустой список словарей, у каждого есть url."""
    # Arrange
    # (входы задаются parametrize — перебираем все валидные комбинации)

    # Act
    result = clients_for(vpn_type, platform)

    # Assert
    assert isinstance(result, list)
    assert result, f"ожидался непустой список клиентов для {vpn_type}/{platform}"
    assert all(isinstance(client, dict) for client in result)
    assert all(client.get("url") for client in result)


@pytest.mark.parametrize("vpn_type", VPN_TYPES)
@pytest.mark.parametrize("platform", PLATFORMS_WITH_CLIENTS)
def test__clients_for__known_combo__each_client_has_name_and_url(vpn_type: str, platform: str) -> None:
    """Каждый клиент известной пары имеет непустые поля name и url."""
    # Arrange
    # (перебор валидных пар через parametrize)

    # Act
    result = clients_for(vpn_type, platform)

    # Assert
    for client in result:
        assert client.get("name"), f"нет name у клиента {client} для {vpn_type}/{platform}"
        assert client.get("url"), f"нет url у клиента {client} для {vpn_type}/{platform}"


def test__clients_for__known_combo__returns_exact_catalog_entry() -> None:
    """Возвращается ровно та запись из CLIENTS, что лежит по ключам тип/платформа."""
    # Arrange
    vpn_type, platform = "amnezia", "ios"

    # Act
    result = clients_for(vpn_type, platform)

    # Assert
    assert result is CLIENTS[vpn_type][platform]
    assert result[0]["name"] == "AmneziaVPN"


def test__clients_for__outline_router__returns_empty_list() -> None:
    """Известный тип, но платформа без клиентов (outline/router) → пустой список."""
    # Arrange
    vpn_type, platform = "outline", "router"

    # Act
    result = clients_for(vpn_type, platform)

    # Assert
    assert result == []


@pytest.fixture
def unknown_type_case() -> tuple[str, str]:
    """Неизвестный тип VPN при валидной платформе."""
    return ("wireguard", "ios")


@pytest.fixture
def unknown_platform_case() -> tuple[str, str]:
    """Валидный тип VPN при неизвестной платформе."""
    return ("amnezia", "playstation")


@pytest.fixture
def both_unknown_case() -> tuple[str, str]:
    """Неизвестны и тип, и платформа."""
    return ("wireguard", "playstation")


@pytest.fixture
def empty_args_case() -> tuple[str, str]:
    """Пустые строки на входе."""
    return ("", "")


@pytest.mark.parametrize(
    "case",
    [
        lf("unknown_type_case"),
        lf("unknown_platform_case"),
        lf("both_unknown_case"),
        lf("empty_args_case"),
    ],
)
def test__clients_for__unknown_combo__returns_empty_list(case: tuple[str, str]) -> None:
    """Неизвестный тип и/или платформа (и пустой ввод) → пустой список без KeyError."""
    # Arrange
    vpn_type, platform = case

    # Act
    result = clients_for(vpn_type, platform)

    # Assert
    assert result == []


def test__default_ports__covers_all_vpn_types__with_numeric_ports() -> None:
    """DEFAULT_PORTS покрывает все типы VPN, значения — числовые строки."""
    # Arrange
    expected = set(VPN_TYPES)

    # Act
    keys = set(DEFAULT_PORTS)

    # Assert
    assert keys == expected
    assert all(port.isdigit() for port in DEFAULT_PORTS.values())


def test__catalog_dicts__share_same_vpn_keys__are_consistent() -> None:
    """PROTOS/VPN_LABELS/VPN_DESC/VPN_DOT/DEFAULT_PORTS согласованы по набору ключей."""
    # Arrange
    expected = set(VPN_TYPES)

    # Act
    key_sets = {
        "PROTOS": set(PROTOS),
        "VPN_LABELS": set(VPN_LABELS),
        "VPN_DESC": set(VPN_DESC),
        "VPN_DOT": set(VPN_DOT),
        "DEFAULT_PORTS": set(DEFAULT_PORTS),
    }

    # Assert
    for name, keys in key_sets.items():
        assert keys == expected, f"ключи {name} разошлись с эталоном: {keys}"


@pytest.mark.parametrize("vpn_type", VPN_TYPES)
def test__protos__each_vpn_type__has_nonempty_protocol_list(vpn_type: str) -> None:
    """У каждого типа VPN в PROTOS непустой список протоколов из строк."""
    # Arrange
    # (тип задаётся parametrize)

    # Act
    protocols = PROTOS[vpn_type]

    # Assert
    assert isinstance(protocols, list)
    assert protocols
    assert all(isinstance(proto, str) and proto for proto in protocols)


@pytest.mark.parametrize("vpn_type", VPN_TYPES)
def test__vpn_labels_and_desc__each_vpn_type__has_nonempty_text(vpn_type: str) -> None:
    """У каждого типа VPN есть непустые человекочитаемые label и description."""
    # Arrange
    # (тип задаётся parametrize)

    # Act
    label = VPN_LABELS[vpn_type]
    desc = VPN_DESC[vpn_type]

    # Assert
    assert label and isinstance(label, str)
    assert desc and isinstance(desc, str)


def test__clients__each_entry__has_name_and_url_for_every_platform() -> None:
    """Каждый клиент во всём каталоге CLIENTS имеет непустые name и url."""
    # Arrange
    # (обходим весь каталог целиком)

    # Act / Assert
    for vpn_type, platforms in CLIENTS.items():
        for platform, clients in platforms.items():
            for client in clients:
                assert client.get("name"), f"нет name: {vpn_type}/{platform} → {client}"
                assert client.get("url"), f"нет url: {vpn_type}/{platform} → {client}"


def test__clients__top_level_keys__match_supported_vpn_types() -> None:
    """Верхние ключи CLIENTS совпадают с поддерживаемыми типами VPN."""
    # Arrange
    expected = set(VPN_TYPES)

    # Act
    keys = set(CLIENTS)

    # Assert
    assert keys == expected
