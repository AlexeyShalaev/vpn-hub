"""In-memory rate-limiter (скользящее окно).

Хранит штампы попыток в памяти процесса. Приложение работает одним процессом uvicorn
(фоновый планировщик + запросы в одном event-loop), поэтому общего стораджа не требуется.
При масштабировании на несколько воркеров сюда встанет Redis — интерфейс тот же.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _trim(self, dq: deque[float], now: float, window: float) -> None:
        while dq and now - dq[0] > window:
            dq.popleft()

    def allow(self, key: str, limit: int, window: float) -> bool:
        """Зарегистрировать попытку. False — лимит исчерпан (штамп НЕ добавляется)."""
        now = time.time()
        dq = self._hits[key]
        self._trim(dq, now, window)
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True

    def retry_after(self, key: str, window: float) -> int:
        """Сколько секунд ждать до освобождения слота (грубая оценка по старейшей попытке)."""
        dq = self._hits.get(key)
        if not dq:
            return 0
        return max(1, int(window - (time.time() - dq[0])) + 1)

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)


# Один общий лимитер на процесс.
_limiter = RateLimiter()


def get_limiter() -> RateLimiter:
    return _limiter
