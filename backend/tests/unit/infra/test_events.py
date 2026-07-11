"""Юнит-тесты шины realtime-событий: publish/subscribe, format_sse, дроп при переполнении."""

from __future__ import annotations

import asyncio
import json

import pytest

from vpnhub.infra.events import (
    TOPIC_SERVER,
    EventBus,
    format_sse,
    get_event_bus,
)

pytestmark = pytest.mark.unit


async def test__publish_subscribe__delivers_event_to_subscriber():
    """publish кладёт событие в очередь активного подписчика с верными topic/entity_id."""
    bus = EventBus()
    sub = bus.subscribe()
    # активируем подписку (первый __anext__ регистрирует очередь) через фоновую задачу
    getter = asyncio.ensure_future(sub.__anext__())
    await asyncio.sleep(0)  # дать подписке зарегистрироваться

    bus.publish(TOPIC_SERVER, "sid-1")

    event = await asyncio.wait_for(getter, timeout=1.0)
    assert event.topic == TOPIC_SERVER
    assert event.entity_id == "sid-1"
    await sub.aclose()
    assert bus.subscriber_count == 0


async def test__publish__no_subscribers__is_noop():
    """publish без подписчиков не падает (сигнал просто теряется)."""
    bus = EventBus()
    bus.publish(TOPIC_SERVER, "sid")  # не должно бросить
    assert bus.subscriber_count == 0


async def test__subscribers_are_isolated__each_gets_its_own_copy():
    """Два подписчика получают одно и то же событие независимо друг от друга."""
    bus = EventBus()
    a, b = bus.subscribe(), bus.subscribe()
    ga = asyncio.ensure_future(a.__anext__())
    gb = asyncio.ensure_future(b.__anext__())
    await asyncio.sleep(0)

    bus.publish(TOPIC_SERVER, "x")

    ea = await asyncio.wait_for(ga, timeout=1.0)
    eb = await asyncio.wait_for(gb, timeout=1.0)
    assert ea.entity_id == eb.entity_id == "x"
    await a.aclose()
    await b.aclose()


async def test__queue_overflow__drops_oldest_keeps_newest():
    """При переполнении очереди дропается старейшее событие, новейшее сохраняется."""
    bus = EventBus(queue_max=2)
    sub = bus.subscribe()
    # припарковать генератор на await q.get(): очередь зарегистрирована, но не читается
    getter = asyncio.ensure_future(sub.__anext__())
    await asyncio.sleep(0)
    assert bus.subscriber_count == 1

    for i in range(5):
        bus.publish(TOPIC_SERVER, str(i))
    # публикации синхронны (getter ещё не резюмировался): очередь maxsize=2 переполняется,
    # каждое переполнение дропает старейшее → остаются два последних, "3" и "4".

    first = await asyncio.wait_for(getter, timeout=1.0)
    second = await asyncio.wait_for(sub.__anext__(), timeout=1.0)
    assert (first.entity_id, second.entity_id) == ("3", "4")
    await sub.aclose()


def test__format_sse__exact_frame_and_json_data():
    """format_sse формирует кадр 'event: <topic>\\ndata: <json>\\n\\n' с корректным JSON."""
    from vpnhub.infra.events import Event

    frame = format_sse(Event(topic="server", entity_id="sid", ts=1.5))
    assert frame.startswith("event: server\ndata: ")
    assert frame.endswith("\n\n")
    body = frame[len("event: server\ndata: ") : -2]
    assert json.loads(body) == {"id": "sid", "ts": 1.5}


def test__format_sse__null_entity_id():
    """entity_id=None сериализуется как JSON null."""
    from vpnhub.infra.events import Event

    frame = format_sse(Event(topic="sync", entity_id=None, ts=2.0))
    body = frame.split("data: ", 1)[1].rstrip("\n")
    assert json.loads(body)["id"] is None


def test__get_event_bus__is_singleton():
    """get_event_bus возвращает один и тот же инстанс (publisher и subscriber делят шину)."""
    assert get_event_bus() is get_event_bus()
