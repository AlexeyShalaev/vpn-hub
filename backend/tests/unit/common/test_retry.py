"""Юнит-тесты для with_retries — ретрай с backoff для транзиентных сбоев.

Реальный asyncio.sleep глушим монкипатчем на модуле retry, чтобы тесты не ждали.
Число вызовов fn считаем через счётчик в замыкании.
"""

from __future__ import annotations

import pytest

import vpnhub.common.retry as retry_mod
from vpnhub.common.retry import with_retries

pytestmark = pytest.mark.unit


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    """Глушим asyncio.sleep в модуле retry — паузы backoff мгновенны."""

    async def _noop(*_a: object, **_kw: object) -> None:
        pass

    monkeypatch.setattr(retry_mod.asyncio, "sleep", _noop)


async def test__with_retries__succeeds_first_try__calls_fn_once() -> None:
    """Успех с первой попытки → fn вызвана ровно 1 раз, вернулся её результат."""
    # Arrange
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        return "ok"

    # Act
    result = await with_retries(fn, attempts=3, base_delay=0.5)

    # Assert
    assert result == "ok"
    assert calls == 1


async def test__with_retries__fails_then_succeeds__retries_until_success() -> None:
    """Падение N-1 раз, затем успех → fn вызвана N раз, вернулся успешный результат."""
    # Arrange
    calls = 0
    attempts = 3

    async def fn() -> str:
        nonlocal calls
        calls += 1
        if calls < attempts:
            raise ValueError("transient")
        return "recovered"

    # Act
    result = await with_retries(fn, attempts=attempts, base_delay=0.5)

    # Assert
    assert result == "recovered"
    assert calls == attempts


async def test__with_retries__attempts_exhausted__reraises_last_exception() -> None:
    """Все попытки упали → пробрасывается последнее исключение, fn вызвана attempts раз."""
    # Arrange
    calls = 0
    attempts = 3

    async def fn() -> str:
        nonlocal calls
        calls += 1
        raise ValueError(f"boom-{calls}")

    # Act / Assert
    with pytest.raises(ValueError, match="boom-3"):
        await with_retries(fn, attempts=attempts, base_delay=0.5)
    assert calls == attempts


async def test__with_retries__error_not_in_retry_on__reraises_without_retry() -> None:
    """Исключение НЕ из retry_on пробрасывается сразу, без ретраев (fn вызвана 1 раз)."""
    # Arrange
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        raise KeyError("not-retryable")

    # Act / Assert
    with pytest.raises(KeyError):
        await with_retries(fn, attempts=3, base_delay=0.5, retry_on=(ValueError,))
    assert calls == 1


async def test__with_retries__retry_on_matches__retries_matching_error() -> None:
    """retry_on содержит тип ошибки → ретраи выполняются, затем успех."""
    # Arrange
    calls = 0

    async def fn() -> int:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ConnectionError("net")
        return 42

    # Act
    result = await with_retries(fn, attempts=3, base_delay=0.5, retry_on=(ConnectionError,))

    # Assert
    assert result == 42
    assert calls == 2


async def test__with_retries__single_attempt_fails__reraises_immediately() -> None:
    """attempts=1 и падение → сразу проброс без пауз, fn вызвана ровно 1 раз."""
    # Arrange
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        raise RuntimeError("once")

    # Act / Assert
    with pytest.raises(RuntimeError, match="once"):
        await with_retries(fn, attempts=1, base_delay=0.5)
    assert calls == 1


async def test__with_retries__retries_with_backoff__sleeps_with_exponential_delays(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Между попытками backoff = base_delay·2^i: паузы 0.5 и 1.0 перед 2-й и 3-й попыткой."""
    # Arrange
    delays: list[float] = []

    async def _record(delay: float, *_a: object, **_kw: object) -> None:
        delays.append(delay)

    monkeypatch.setattr(retry_mod.asyncio, "sleep", _record)
    calls = 0

    async def fn() -> str:
        nonlocal calls
        calls += 1
        if calls < 3:
            raise ValueError("transient")
        return "ok"

    # Act
    result = await with_retries(fn, attempts=3, base_delay=0.5)

    # Assert
    assert result == "ok"
    assert delays == [0.5, 1.0]
