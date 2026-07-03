"""Юнит-тесты для probe_tcp — TCP health-зонд серверов.

Живой сервер поднимаем через asyncio.start_server на 127.0.0.1:0 (порт выбирает ОС),
берём фактический порт из server.sockets[0].getsockname()[1] и закрываем в конце.
Так проверяем реальный TCP-хендшейк без внешней сети. Таймауты держим маленькими.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable

import pytest

import vpnhub.infra.probe as probe_mod
from vpnhub.infra.probe import ProbeResult, probe_tcp

pytestmark = pytest.mark.unit

_TIMEOUT = 0.5  # маленький таймаут: локальный коннект укладывается мгновенно


async def _run_server(
    on_connect: Callable[[asyncio.StreamReader, asyncio.StreamWriter], None] | None = None,
) -> AsyncIterator[int]:
    """Поднять TCP-сервер на 127.0.0.1:0 и отдать выбранный ОС порт; закрыть на выходе."""

    async def _handler(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        if on_connect is not None:
            on_connect(reader, writer)
            await writer.drain()
        # держим соединение открытым, пока клиент не отвалится
        try:
            await reader.read()
        finally:
            writer.close()

    server = await asyncio.start_server(_handler, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield port
    finally:
        server.close()
        await server.wait_closed()


@pytest.fixture
async def open_port() -> AsyncIterator[int]:
    """Порт живого TCP-сервера, который принимает коннект и молчит (не шлёт баннер)."""
    async for port in _run_server():
        yield port


@pytest.fixture
async def ssh_port() -> AsyncIterator[int]:
    """Порт TCP-сервера, который сразу после коннекта шлёт SSH-баннер."""

    def _send_banner(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        writer.write(b"SSH-2.0-x\r\n")

    async for port in _run_server(_send_banner):
        yield port


@pytest.fixture
async def closed_port() -> AsyncIterator[int]:
    """Порт, на котором заведомо никто не слушает: подняли сервер и сразу закрыли."""
    server = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    server.close()
    await server.wait_closed()
    yield port


@pytest.mark.parametrize("host", ["", "   ", None])
async def test__probe_tcp__empty_host__returns_not_ok_with_address_detail(host: str | None) -> None:
    """Пустой/пробельный/None host → ok=False, latency отсутствует, detail «адрес не задан»."""
    # Arrange
    # host передаётся напрямую из параметра — сеть не задействуется

    # Act
    result = await probe_tcp(host, 22, _TIMEOUT)  # type: ignore[arg-type]

    # Assert
    assert result == ProbeResult(False, None, "адрес не задан")


async def test__probe_tcp__reachable_server__returns_ok_with_positive_latency(open_port: int) -> None:
    """Успешный коннект к локальному серверу → ok=True и latency_ms >= 1."""
    # Arrange
    # сервер уже поднят фикстурой open_port

    # Act
    result = await probe_tcp("127.0.0.1", open_port, _TIMEOUT)

    # Assert
    assert result.ok is True
    assert result.latency_ms is not None
    assert result.latency_ms >= 1


async def test__probe_tcp__silent_open_port__detail_is_port_open(open_port: int) -> None:
    """Порт открыт, но баннер не приходит → detail «порт открыт» (не SSH)."""
    # Arrange
    # open_port принимает коннект и молчит

    # Act
    result = await probe_tcp("127.0.0.1", open_port, _TIMEOUT)

    # Assert
    assert result.ok is True
    assert result.detail == "порт открыт"


async def test__probe_tcp__server_sends_ssh_banner__detail_is_ssh(ssh_port: int) -> None:
    """Сервер шлёт «SSH-2.0-x» при коннекте → ok=True, detail == «SSH»."""
    # Arrange
    # ssh_port шлёт SSH-баннер сразу после установки соединения

    # Act
    result = await probe_tcp("127.0.0.1", ssh_port, _TIMEOUT)

    # Assert
    assert result.ok is True
    assert result.detail == "SSH"


async def test__probe_tcp__closed_port__returns_not_ok(closed_port: int) -> None:
    """Коннект к закрытому порту → ok=False, latency отсутствует."""
    # Arrange
    # closed_port заведомо не слушается

    # Act
    result = await probe_tcp("127.0.0.1", closed_port, _TIMEOUT)

    # Assert
    assert result.ok is False
    assert result.latency_ms is None
    assert result.detail == "соединение отклонено"


async def test__probe_tcp__connection_times_out__returns_not_ok_with_timeout_detail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Коннект не укладывается в timeout → ok=False, detail «таймаут» (ветка TimeoutError)."""

    # Arrange — open_connection «зависает» дольше таймаута
    async def _hang(_host: str, _port: int) -> tuple[object, object]:
        await asyncio.sleep(10)
        raise AssertionError("unreachable")

    monkeypatch.setattr(probe_mod.asyncio, "open_connection", _hang)

    # Act
    result = await probe_tcp("127.0.0.1", 22, 0.01)

    # Assert
    assert result == ProbeResult(False, None, "таймаут")
