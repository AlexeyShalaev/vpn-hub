"""Юнит-тесты SSE-генератора: кадр события, heartbeat при тишине, завершение по disconnect."""

from __future__ import annotations

import asyncio

import pytest

from vpnhub.api.routers import realtime
from vpnhub.infra.events import TOPIC_SERVER, EventBus, format_sse

pytestmark = pytest.mark.unit


class _FakeRequest:
    """Имитация Request.is_disconnected(): возвращает True после `disconnect_after` опросов."""

    def __init__(self, disconnect_after: int = 10) -> None:
        self._left = disconnect_after

    async def is_disconnected(self) -> bool:
        self._left -= 1
        return self._left < 0


async def test__event_stream__emits_connect_then_event_frame(monkeypatch):
    """Первый кадр — открытие стрима, затем корректно отформатированное событие."""
    monkeypatch.setattr(realtime, "_HEARTBEAT_SECONDS", 5.0)
    bus = EventBus()
    req = _FakeRequest(disconnect_after=5)
    gen = realtime.event_stream(bus, req)

    first = await gen.__anext__()
    assert first == ": connected\n\n"

    # публикуем после того, как генератор начал ждать событие
    async def _publish_soon() -> None:
        await asyncio.sleep(0.01)
        bus.publish(TOPIC_SERVER, "sid-1")

    pub = asyncio.ensure_future(_publish_soon())
    frame = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    await pub
    assert frame == format_sse(realtime.Event(topic=TOPIC_SERVER, entity_id="sid-1", ts=_ts(frame)))
    assert frame.startswith("event: server\ndata: ")
    await gen.aclose()


async def test__event_stream__heartbeat_on_silence(monkeypatch):
    """Нет событий в течение heartbeat-таймаута → генератор отдаёт ping-комментарий."""
    monkeypatch.setattr(realtime, "_HEARTBEAT_SECONDS", 0.01)
    bus = EventBus()
    req = _FakeRequest(disconnect_after=5)
    gen = realtime.event_stream(bus, req)

    assert await gen.__anext__() == ": connected\n\n"
    frame = await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert frame == ": ping\n\n"
    await gen.aclose()


async def test__event_stream__stops_on_disconnect(monkeypatch):
    """Клиент отвалился (is_disconnected → True) → генератор завершается, подписка снимается."""
    monkeypatch.setattr(realtime, "_HEARTBEAT_SECONDS", 0.01)
    bus = EventBus()
    req = _FakeRequest(disconnect_after=0)  # сразу disconnected на первой проверке в цикле
    gen = realtime.event_stream(bus, req)

    assert await gen.__anext__() == ": connected\n\n"
    with pytest.raises(StopAsyncIteration):
        await asyncio.wait_for(gen.__anext__(), timeout=1.0)
    assert bus.subscriber_count == 0


def _ts(frame: str) -> float:
    import json

    body = frame.split("data: ", 1)[1].rstrip("\n")
    return json.loads(body)["ts"]
