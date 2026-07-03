"""Небольшой ретрай с экспоненциальным backoff для транзиентных сбоев (SSH/сеть).

Намеренно не зависит от provisioning: типы исключений и параметры передаёт вызывающий.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable


async def with_retries[T](
    fn: Callable[[], Awaitable[T]],
    *,
    attempts: int = 3,
    base_delay: float = 0.5,
    retry_on: tuple[type[BaseException], ...] = (Exception,),
) -> T:
    """Вызвать `fn` до `attempts` раз, ретраить на `retry_on` с паузой base_delay·2^i.

    Последняя попытка пробрасывает исключение наружу. `fn` должна быть идемпотентной.
    """
    for i in range(attempts):
        try:
            return await fn()
        except retry_on:
            if i == attempts - 1:
                raise
            await asyncio.sleep(base_delay * (2**i))
    raise AssertionError("unreachable")  # attempts >= 1
