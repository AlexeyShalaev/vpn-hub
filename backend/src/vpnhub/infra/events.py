"""In-process asyncio pub/sub для realtime-сигналов (SSE вместо поллинга).

Крупнозернистые топики-«сущности» (`server`, `sync`, `system`): событие несёт лишь СИГНАЛ
инвалидации (`{topic, id}`), не полезную нагрузку — данные фронт дотягивает через react-query.

Одна реплика (планировщик без лидер-элекшена) — шина внутрипроцессная; при масштабировании
>1 реплики события не долетят до чужих подписчиков (осознанное ограничение продукта, не Redis).

Publisher (фоновые задачи/сервисы) и subscriber (SSE-эндпоинт) видят ОДИН инстанс через
модульный синглтон `get_event_bus()` — сервисы создаются и через DI, и ad-hoc (без DI), а
scheduler-джобы делят контейнер с запросами.
"""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field

# крупнозернистые топики (см. модуль-docstring)
TOPIC_SERVER = "server"
TOPIC_SYNC = "sync"
TOPIC_SYSTEM = "system"

# размер очереди подписчика: событие — лишь сигнал, при переполнении дропаем старейшее
_QUEUE_MAX = 64


@dataclass(frozen=True)
class Event:
    topic: str
    entity_id: str | None = None
    ts: float = field(default_factory=time.time)


def format_sse(event: Event) -> str:
    """SSE-кадр: `event: <topic>\\ndata: <json>\\n\\n` (тестируется как чистая функция)."""
    data = json.dumps({"id": event.entity_id, "ts": event.ts}, separators=(",", ":"))
    return f"event: {event.topic}\ndata: {data}\n\n"


class EventBus:
    """Fan-out очередей: publish кладёт событие всем подписчикам, subscribe отдаёт свой поток.

    Потокобезопасность не нужна — весь доступ из одного event loop.
    """

    def __init__(self, queue_max: int = _QUEUE_MAX) -> None:
        self._queue_max = queue_max
        self._subscribers: set[asyncio.Queue[Event]] = set()

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def publish(self, topic: str, entity_id: str | None = None) -> None:
        """Разослать событие всем подписчикам. При переполнении очереди — дропнуть старейшее."""
        event = Event(topic=topic, entity_id=entity_id)
        for q in self._subscribers:
            if q.full():
                try:
                    q.get_nowait()  # дропаем старейшее — сигнал, потеря не критична
                except asyncio.QueueEmpty:  # pragma: no cover — гонок нет (один loop)
                    pass
            q.put_nowait(event)

    async def subscribe(self) -> AsyncGenerator[Event]:
        """Асинхронный поток событий для одного подписчика; снимает подписку в finally."""
        q: asyncio.Queue[Event] = asyncio.Queue(maxsize=self._queue_max)
        self._subscribers.add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subscribers.discard(q)


_bus: EventBus | None = None


def get_event_bus() -> EventBus:
    """Модульный синглтон шины (общий для DI и ad-hoc-конструируемых сервисов)."""
    global _bus  # noqa: PLW0603 — намеренный ленивый модульный синглтон (одна реплика)
    if _bus is None:
        _bus = EventBus()
    return _bus
