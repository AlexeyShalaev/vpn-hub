"""SSE-роутер realtime-обновлений: пуш сигналов инвалидации вместо агрессивного поллинга.

`GET /api/v1/stream` держит открытый `text/event-stream`: на каждое событие шины отдаёт кадр
`event: <topic>\\ndata: {"id":..,"ts":..}\\n\\n`, между событиями — heartbeat-комментарий, чтобы
прокси/браузер держали коннект и разрыв замечался быстро. Событие несёт лишь СИГНАЛ — данные
фронт дотягивает через react-query по инвалидации ключей.

Auth — только cookie-сессия (`current_identity`): EventSource не умеет кастомные заголовки, а под
CSRF-middleware GET не попадает. Роль в фильтрацию на MVP не заводим — `server`-события касаются и
member (через `/me/available`); фильтрацию по видимости можно добавить позже.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse

from vpnhub.api.deps import current_identity, service
from vpnhub.core.errors import Unauthorized
from vpnhub.infra.events import Event, EventBus, format_sse
from vpnhub.services.auth import Identity

router = APIRouter(prefix="/api/v1", tags=["stream"])

# как часто слать heartbeat-комментарий при тишине (сек): держит коннект и ловит обрыв
_HEARTBEAT_SECONDS = 15.0

# SSE-заголовки: без кэша, без буферизации у nginx-подобных прокси (для Caddy — flush + heartbeat)
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


async def event_stream(bus: EventBus, request: Request) -> AsyncIterator[str]:
    """Генератор SSE-кадров: события шины + heartbeat; завершается при disconnect клиента.

    Вынесен из хендлера, чтобы тестировать чистой логикой с фейковыми bus/request.
    """
    events: AsyncGenerator[Event] = bus.subscribe()
    try:
        yield ": connected\n\n"  # первый флаш — открываем стрим сразу
        while True:
            if await request.is_disconnected():
                return
            try:
                event = await asyncio.wait_for(events.__anext__(), timeout=_HEARTBEAT_SECONDS)
            except TimeoutError:
                yield ": ping\n\n"  # heartbeat при тишине
                continue
            except StopAsyncIteration:  # pragma: no cover — subscribe() не завершается сам
                return
            yield format_sse(event)
    finally:
        await events.aclose()  # снять подписку (finally в EventBus.subscribe)


@router.get("/stream")
async def stream(
    request: Request,
    bus: EventBus = Depends(service(EventBus)),
) -> StreamingResponse:
    ident: Identity | None = await current_identity(request)
    if not ident:
        raise Unauthorized()
    return StreamingResponse(
        event_stream(bus, request),
        media_type="text/event-stream",
        headers=_SSE_HEADERS,
    )
