"""Юнит-тесты чистых функций-сериализаторов ORM → dict (camelCase) и форматтеров.

Все ORM-объекты конструируются БЕЗ БД — как обычные python-объекты; коллекции-relationship
(vpns/protocols/members/configs) по умолчанию пустые списки и присваиваются напрямую.
Время (`rel_time`) детерминируется через monkeypatch `time.time` на модуле serializers.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pytest_lazy_fixtures import lf

from vpnhub.common import serializers as s
from vpnhub.infra.db.orm import models as m

pytestmark = pytest.mark.unit

# зафиксированный "сейчас" для детерминированного rel_time
NOW = 1_000_000.0


@pytest.fixture
def frozen_now(monkeypatch: pytest.MonkeyPatch) -> float:
    """Замораживает time.time() в модуле serializers на NOW."""
    monkeypatch.setattr(s.time, "time", lambda: NOW)
    return NOW


# --------------------------------------------------------------------------- #
# rel_time
# --------------------------------------------------------------------------- #


def test__rel_time__none__returns_none() -> None:
    """None (нет отметки времени) → None."""
    # Arrange / Act
    result = s.rel_time(None)
    # Assert
    assert result is None


def test__rel_time__zero_epoch__returns_none() -> None:
    """Falsy-epoch (0.0) трактуется как отсутствие времени → None."""
    # Arrange / Act
    result = s.rel_time(0.0)
    # Assert
    assert result is None


# «сейчас минус delta» → ожидаемая человекочитаемая строка
@pytest.fixture
def just_now_epoch(frozen_now: float) -> tuple[float, str]:
    return frozen_now - 10, "только что"


@pytest.fixture
def minutes_ago_epoch(frozen_now: float) -> tuple[float, str]:
    return frozen_now - 120, "2 мин назад"


@pytest.fixture
def sub_minute_epoch(frozen_now: float) -> tuple[float, str]:
    # 30с < 45с попадает в «только что»; берём 50с — уже минуты, но diff//60==0 → max(1,0)=1
    return frozen_now - 50, "1 мин назад"


@pytest.fixture
def hours_ago_epoch(frozen_now: float) -> tuple[float, str]:
    return frozen_now - 3 * 3600, "3 ч назад"


@pytest.fixture
def days_ago_epoch(frozen_now: float) -> tuple[float, str]:
    return frozen_now - 2 * 86400, "2 дн назад"


@pytest.mark.parametrize(
    "case",
    [
        lf("just_now_epoch"),
        lf("sub_minute_epoch"),
        lf("minutes_ago_epoch"),
        lf("hours_ago_epoch"),
        lf("days_ago_epoch"),
    ],
)
def test__rel_time__past_epoch__formats_relative(case: tuple[float, str]) -> None:
    """Прошедший epoch форматируется в ru-строку по диапазону (сек/мин/ч/дн)."""
    # Arrange
    epoch, expected = case
    # Act
    result = s.rel_time(epoch)
    # Assert
    assert result == expected


def test__rel_time__future_epoch__clamped_to_just_now(frozen_now: float) -> None:
    """Будущий epoch (отрицательная разница) зажимается в 0 → «только что»."""
    # Arrange
    future = frozen_now + 500
    # Act
    result = s.rel_time(future)
    # Assert
    assert result == "только что"


# --------------------------------------------------------------------------- #
# latency_str
# --------------------------------------------------------------------------- #


def test__latency_str__none__returns_none() -> None:
    """Нет измеренной латентности → None."""
    # Arrange / Act
    result = s.latency_str(None)
    # Assert
    assert result is None


def test__latency_str__value__appends_ms_suffix() -> None:
    """Число миллисекунд форматируется с суффиксом «мс»."""
    # Arrange / Act
    result = s.latency_str(12)
    # Assert
    assert result == "12 мс"


def test__latency_str__zero__is_rendered_not_dropped() -> None:
    """Ноль мс — валидное значение (не None), должен рендериться."""
    # Arrange / Act
    result = s.latency_str(0)
    # Assert
    assert result == "0 мс"


# --------------------------------------------------------------------------- #
# _ua_label
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("ua", "expected"),
    [
        ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120 Edg/120", "Edge · Windows"),
        ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15) Safari/605", "Safari · macOS"),
        ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0) Safari/604", "Safari · iOS"),
        ("Mozilla/5.0 (Linux; Android 14) Chrome/120 Mobile", "Chrome · Android"),
        ("Mozilla/5.0 (X11; Linux x86_64) Firefox/119", "Firefox · Linux"),
        ("Mozilla/5.0 (Windows NT 10.0) Chrome/120", "Chrome · Windows"),
    ],
)
def test__ua_label__known_agent__maps_browser_and_os(ua: str, expected: str) -> None:
    """Известные UA раскладываются в «Браузер · ОС» (edge важнее chrome, android важнее linux)."""
    # Arrange / Act
    result = s._ua_label(ua)
    # Assert
    assert result == expected


@pytest.mark.parametrize("ua", ["", None])
def test__ua_label__empty__returns_unknown_device(ua: str | None) -> None:
    """Пустой/отсутствующий UA → «Неизвестное устройство»."""
    # Arrange / Act
    result = s._ua_label(ua)
    # Assert
    assert result == "Неизвестное устройство"


def test__ua_label__unrecognized_agent__uses_dash_placeholders() -> None:
    """Нераспознанный UA (без известной ОС/браузера) → «— · —»."""
    # Arrange / Act
    result = s._ua_label("curl/8.0")
    # Assert
    assert result == "— · —"


# --------------------------------------------------------------------------- #
# session_to_dict
# --------------------------------------------------------------------------- #


def _make_session(**over: object) -> m.Session:
    sess = m.Session(
        id=over.get("id", "tok1"),
        subject_kind="user",
        subject_id="u1",
        expires_at=0.0,
        ip=over.get("ip", "203.0.113.9"),
        user_agent=over.get("user_agent", "Mozilla/5.0 (Windows NT 10.0) Chrome/120"),
    )
    sess.created_at = over.get("created_at", datetime(2026, 7, 1, 12, 30, 0))  # type: ignore[assignment]
    sess.updated_at = over.get("updated_at")  # type: ignore[assignment]
    return sess


def test__session_to_dict__populated__maps_camelcase_fields(frozen_now: float) -> None:
    """Заполненная сессия → dict с camelCase-ключами, device из UA, createdAt из даты."""
    # Arrange
    sess = _make_session(updated_at=datetime.fromtimestamp(NOW - 60))
    # Act
    result = s.session_to_dict(sess, current=True)
    # Assert
    assert result == {
        "id": "tok1",
        "ip": "203.0.113.9",
        "device": "Chrome · Windows",
        "userAgent": "Mozilla/5.0 (Windows NT 10.0) Chrome/120",
        "createdAt": "01.07.2026 12:30",
        "lastSeen": "1 мин назад",
        "current": True,
    }


def test__session_to_dict__no_ip__uses_dash_placeholder(frozen_now: float) -> None:
    """Отсутствие ip → плейсхолдер «—»."""
    # Arrange
    sess = _make_session(ip=None)
    # Act
    result = s.session_to_dict(sess, current=False)
    # Assert
    assert result["ip"] == "—"


def test__session_to_dict__no_timestamps__empty_created_and_none_lastseen() -> None:
    """Без created_at/updated_at → createdAt="" и lastSeen=None."""
    # Arrange
    sess = _make_session(created_at=None, updated_at=None)
    # Act
    result = s.session_to_dict(sess, current=False)
    # Assert
    assert result["createdAt"] == ""
    assert result["lastSeen"] is None


def test__session_to_dict__current_flag__is_passed_through() -> None:
    """Флаг current прокидывается в поле current как есть."""
    # Arrange
    sess = _make_session()
    # Act
    result = s.session_to_dict(sess, current=True)
    # Assert
    assert result["current"] is True


# --------------------------------------------------------------------------- #
# vpn_to_dict / protocol_to_dict
# --------------------------------------------------------------------------- #


def test__vpn_to_dict__maps_all_fields() -> None:
    """ServerVpn → плоский dict с type/installed/running/port."""
    # Arrange
    vpn = m.ServerVpn(id="v1", server_id="s1", type="amnezia", installed=True, running=False, port="443")
    # Act
    result = s.vpn_to_dict(vpn)
    # Assert
    assert result == {"type": "amnezia", "installed": True, "running": False, "port": "443"}


def test__protocol_to_dict__maps_external_clients_to_camelcase() -> None:
    """ServerProtocol → dict; external_clients переименован в externalClients."""
    # Arrange
    proto = m.ServerProtocol(
        id="p1",
        server_id="s1",
        vendor="amnezia",
        proto="awg",
        container="amnezia-awg",
        port="30500",
        state="installed",
        installed=True,
        running=True,
        error=None,
        external_clients=3,
    )
    # Act
    result = s.protocol_to_dict(proto)
    # Assert
    assert result == {
        "vendor": "amnezia",
        "proto": "awg",
        "container": "amnezia-awg",
        "port": "30500",
        "state": "installed",
        "installed": True,
        "running": True,
        "error": None,
        "errorCode": None,
        "remediation": None,
        "externalClients": 3,
    }


# --------------------------------------------------------------------------- #
# server_to_dict
# --------------------------------------------------------------------------- #


def _make_server(**over: object) -> m.Server:
    return m.Server(
        id=over.get("id", "s1"),
        owner_user_id="u1",
        name=over.get("name", "srv-de"),
        provider=over.get("provider", "hetzner"),
        ip=over.get("ip", "203.0.113.10"),
        ssh_user=over.get("ssh_user", "root"),
        ssh_port=over.get("ssh_port", "22"),
        ssh_auth=over.get("ssh_auth", "key"),
        location=over.get("location", "DE"),
        status=over.get("status", "online"),
        latency_ms=over.get("latency_ms", 12),  # type: ignore[arg-type]
        last_check_at=over.get("last_check_at"),  # type: ignore[arg-type]
    )


def test__server_to_dict__base_fields__mapped_to_camelcase(frozen_now: float) -> None:
    """Базовые поля сервера → camelCase (sshUser/sshPort/auth), latency форматируется."""
    # Arrange
    srv = _make_server(latency_ms=12, last_check_at=NOW - 3600)
    # Act
    result = s.server_to_dict(srv)
    # Assert
    assert result["sshUser"] == "root"
    assert result["sshPort"] == "22"
    assert result["auth"] == "key"
    assert result["latency"] == "12 мс"
    assert result["lastCheck"] == "1 ч назад"


def test__server_to_dict__no_secret__defaults_to_empty_string() -> None:
    """Без переданного secret поле secret == "" (не None)."""
    # Arrange
    srv = _make_server()
    # Act
    result = s.server_to_dict(srv)
    # Assert
    assert result["secret"] == ""


def test__server_to_dict__with_secret__uses_provided_value() -> None:
    """Явно переданный secret попадает в результат как есть."""
    # Arrange
    srv = _make_server()
    # Act
    result = s.server_to_dict(srv, secret="s3cr3t")
    # Assert
    assert result["secret"] == "s3cr3t"


def test__server_to_dict__vpns__sorted_by_type() -> None:
    """Вложенные vpns сортируются по type (alphabetically)."""
    # Arrange
    srv = _make_server()
    srv.vpns = [
        m.ServerVpn(id="v2", server_id="s1", type="outline", installed=True, running=True, port="443"),
        m.ServerVpn(id="v1", server_id="s1", type="amnezia", installed=True, running=True, port="500"),
        m.ServerVpn(id="v3", server_id="s1", type="openvpn", installed=True, running=True, port="1194"),
    ]
    # Act
    result = s.server_to_dict(srv)
    # Assert
    assert [v["type"] for v in result["vpns"]] == ["amnezia", "openvpn", "outline"]


def test__server_to_dict__protocols__sorted_by_proto() -> None:
    """Вложенные protocols сортируются по proto."""
    # Arrange
    srv = _make_server()
    srv.protocols = [
        m.ServerProtocol(id="p2", server_id="s1", vendor="amnezia", proto="xray"),
        m.ServerProtocol(id="p1", server_id="s1", vendor="amnezia", proto="awg"),
        m.ServerProtocol(id="p3", server_id="s1", vendor="amnezia", proto="awg_legacy"),
    ]
    # Act
    result = s.server_to_dict(srv)
    # Assert
    assert [p["proto"] for p in result["protocols"]] == ["awg", "awg_legacy", "xray"]


def test__server_to_dict__no_latency__latency_none() -> None:
    """Нет измеренной латентности → latency=None."""
    # Arrange
    srv = _make_server(latency_ms=None)
    # Act
    result = s.server_to_dict(srv)
    # Assert
    assert result["latency"] is None


# --------------------------------------------------------------------------- #
# pool_to_dict / member_to_dict / group_to_dict
# --------------------------------------------------------------------------- #


def test__pool_to_dict__maps_server_ids_camelcase() -> None:
    """Pool → dict с serverIds из переданного списка (порядок сохраняется)."""
    # Arrange
    pool = m.Pool(id="p1", owner_user_id="u1", name="Европа")
    # Act
    result = s.pool_to_dict(pool, ["s1", "s2"])
    # Assert
    assert result == {"id": "p1", "name": "Европа", "serverIds": ["s1", "s2"]}


def test__member_to_dict__with_phone__maps_display_name_to_name() -> None:
    """GroupMember → dict: display_name → name, phone сохраняется."""
    # Arrange
    member = m.GroupMember(
        id="mb1", group_id="g1", display_name="Мама", role="member", status="active", phone="+79001112233"
    )
    # Act
    result = s.member_to_dict(member)
    # Assert
    assert result == {"id": "mb1", "name": "Мама", "role": "member", "status": "active", "phone": "+79001112233"}


def test__member_to_dict__no_phone__defaults_to_empty_string() -> None:
    """Отсутствие phone → пустая строка."""
    # Arrange
    member = m.GroupMember(id="mb2", group_id="g1", display_name="Гость", role="member", status="invited", phone=None)
    # Act
    result = s.member_to_dict(member)
    # Assert
    assert result["phone"] == ""


def test__group_to_dict__maps_members_and_access() -> None:
    """Group → dict: members через member_to_dict, access={pools, servers}."""
    # Arrange
    group = m.Group(id="g1", owner_user_id="u1", name="Семья", token="grp-tok")
    group.members = [
        m.GroupMember(id="mb1", group_id="g1", display_name="Папа", role="admin", status="active", phone=None),
    ]
    # Act
    result = s.group_to_dict(group, ["p1"], {"s1": ["amnezia", "openvpn"]})
    # Assert
    assert result == {
        "id": "g1",
        "name": "Семья",
        "token": "grp-tok",
        "members": [{"id": "mb1", "name": "Папа", "role": "admin", "status": "active", "phone": ""}],
        "access": {"pools": ["p1"], "servers": {"s1": ["amnezia", "openvpn"]}},
    }


def test__group_to_dict__no_members__empty_members_list() -> None:
    """Группа без участников → members=[]."""
    # Arrange
    group = m.Group(id="g2", owner_user_id="u1", name="Пусто", token="tok2")
    # Act
    result = s.group_to_dict(group, [], {})
    # Assert
    assert result["members"] == []


# --------------------------------------------------------------------------- #
# device_to_dict
# --------------------------------------------------------------------------- #


def test__device_to_dict__maps_configs_to_camelcase() -> None:
    """Device → dict: конфиги раскладываются в serverId/type/proto/status."""
    # Arrange
    dev = m.Device(id="d1", user_id="u1", name="iPhone 15", platform="ios")
    dev.configs = [
        m.DeviceConfig(id="c1", device_id="d1", server_id="s1", vpn_type="amnezia", proto="awg", status="active"),
    ]
    # Act
    result = s.device_to_dict(dev)
    # Assert
    assert result == {
        "id": "d1",
        "name": "iPhone 15",
        "platform": "ios",
        "configs": [{"serverId": "s1", "type": "amnezia", "proto": "awg", "status": "active"}],
    }


def test__device_to_dict__no_configs__empty_configs_list() -> None:
    """Устройство без конфигов → configs=[]."""
    # Arrange
    dev = m.Device(id="d2", user_id="u1", name="Router", platform="router")
    # Act
    result = s.device_to_dict(dev)
    # Assert
    assert result["configs"] == []


# --------------------------------------------------------------------------- #
# user_to_dict
# --------------------------------------------------------------------------- #


def test__user_to_dict__with_created_at__formats_date_only() -> None:
    """User → dict; created_at форматируется как дд.мм.гггг (без времени)."""
    # Arrange
    user = m.User(id="u1", phone="+79001112233", name="Иван", password_hash="x", status="active")
    user.created_at = datetime(2026, 7, 1, 15, 45, 0)  # type: ignore[assignment]
    # Act
    result = s.user_to_dict(user)
    # Assert
    assert result == {
        "id": "u1",
        "phone": "+79001112233",
        "name": "Иван",
        "status": "active",
        "createdAt": "01.07.2026",
    }


def test__user_to_dict__no_created_at__empty_string() -> None:
    """Без created_at → createdAt=""."""
    # Arrange
    user = m.User(id="u2", phone="+70000000000", name="Гость", password_hash="x", status="pending")
    user.created_at = None  # type: ignore[assignment]
    # Act
    result = s.user_to_dict(user)
    # Assert
    assert result["createdAt"] == ""
