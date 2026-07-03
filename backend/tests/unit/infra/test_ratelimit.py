"""Юнит-тесты для in-memory rate-limiter (скользящее окно)."""

from __future__ import annotations

import pytest

from vpnhub.infra import ratelimit
from vpnhub.infra.ratelimit import RateLimiter, get_limiter

pytestmark = pytest.mark.unit


@pytest.fixture
def limiter() -> RateLimiter:
    """Свежий изолированный лимитер на каждый тест."""
    return RateLimiter()


@pytest.fixture
def frozen_time(monkeypatch: pytest.MonkeyPatch) -> dict[str, float]:
    """Монкипатчит time.time() в модуле ratelimit; текущее время меняется через box['now']."""
    box = {"now": 1_000.0}
    monkeypatch.setattr(ratelimit.time, "time", lambda: box["now"])
    return box


def test__allow__within_limit__returns_true(limiter: RateLimiter) -> None:
    """Попытки в пределах лимита возвращают True."""
    # Arrange
    limit, window = 3, 60.0
    # Act
    results = [limiter.allow("k", limit, window) for _ in range(limit)]
    # Assert
    assert results == [True, True, True]


def test__allow__limit_exhausted__returns_false(limiter: RateLimiter) -> None:
    """При исчерпании лимита следующая попытка возвращает False."""
    # Arrange
    limit, window = 2, 60.0
    limiter.allow("k", limit, window)
    limiter.allow("k", limit, window)
    # Act
    result = limiter.allow("k", limit, window)
    # Assert
    assert result is False


def test__allow__limit_exhausted__stamp_not_added(limiter: RateLimiter) -> None:
    """При исчерпании лимита штамп попытки НЕ добавляется в очередь."""
    # Arrange
    limit, window = 2, 60.0
    limiter.allow("k", limit, window)
    limiter.allow("k", limit, window)
    # Act
    limiter.allow("k", limit, window)
    # Assert
    assert len(limiter._hits["k"]) == limit


def test__allow__separate_keys__independent_counters(limiter: RateLimiter) -> None:
    """Разные ключи считаются независимо — исчерпание одного не влияет на другой."""
    # Arrange
    limit, window = 1, 60.0
    limiter.allow("a", limit, window)
    # Act
    result_b = limiter.allow("b", limit, window)
    # Assert
    assert result_b is True


def test__allow__window_slid__slot_freed(limiter: RateLimiter, frozen_time: dict[str, float]) -> None:
    """После истечения окна старый штамп вытесняется и слот снова доступен."""
    # Arrange
    limit, window = 1, 10.0
    assert limiter.allow("k", limit, window) is True
    assert limiter.allow("k", limit, window) is False
    # Act
    frozen_time["now"] += window + 0.001
    result = limiter.allow("k", limit, window)
    # Assert
    assert result is True


def test__allow__within_window__slot_still_taken(limiter: RateLimiter, frozen_time: dict[str, float]) -> None:
    """Пока окно не истекло, старый штамп сохраняется и слот остаётся занятым."""
    # Arrange
    limit, window = 1, 10.0
    limiter.allow("k", limit, window)
    # Act
    frozen_time["now"] += window - 0.5
    result = limiter.allow("k", limit, window)
    # Assert
    assert result is False


def test__retry_after__no_key__returns_zero(limiter: RateLimiter) -> None:
    """Для неизвестного ключа retry_after равен 0."""
    # Arrange
    window = 60.0
    # Act
    result = limiter.retry_after("unknown", window)
    # Assert
    assert result == 0


def test__retry_after__key_with_hits__returns_positive(limiter: RateLimiter, frozen_time: dict[str, float]) -> None:
    """При наличии свежего штампа retry_after строго положителен и покрывает остаток окна."""
    # Arrange
    window = 60.0
    limiter.allow("k", 1, window)
    # Act
    result = limiter.retry_after("k", window)
    # Assert
    assert result == 61  # int(window - 0) + 1, попытка только что сделана


def test__retry_after__time_advanced__decreases(limiter: RateLimiter, frozen_time: dict[str, float]) -> None:
    """По мере хода времени retry_after уменьшается пропорционально остатку окна."""
    # Arrange
    window = 60.0
    limiter.allow("k", 1, window)
    # Act
    frozen_time["now"] += 40.0
    result = limiter.retry_after("k", window)
    # Assert
    assert result == 21  # int(60 - 40) + 1


def test__retry_after__window_elapsed__returns_one(limiter: RateLimiter, frozen_time: dict[str, float]) -> None:
    """Окно полностью истекло: retry_after НЕ обнуляется до 0, а зажимается в 1 (не вызывает _trim)."""
    # Arrange
    window = 60.0
    limiter.allow("k", 1, window)
    # Act — уходим далеко за окно
    frozen_time["now"] += window + 100.0
    result = limiter.retry_after("k", window)
    # Assert — max(1, int(60 - 160) + 1) == 1 (штамп не подрезается, ключ остаётся в _hits)
    assert result == 1


def test__reset__existing_key__clears_hits(limiter: RateLimiter) -> None:
    """reset удаляет штампы ключа — счётчик обнуляется, попытки снова проходят."""
    # Arrange
    limit, window = 1, 60.0
    limiter.allow("k", limit, window)
    assert limiter.allow("k", limit, window) is False
    # Act
    limiter.reset("k")
    # Assert
    assert limiter.allow("k", limit, window) is True


def test__reset__unknown_key__no_error(limiter: RateLimiter) -> None:
    """reset для отсутствующего ключа не бросает исключение."""
    # Arrange
    # (лимитер пуст)
    # Act
    limiter.reset("nope")
    # Assert
    assert "nope" not in limiter._hits


def test__get_limiter__called_twice__returns_same_instance() -> None:
    """get_limiter() всегда возвращает один и тот же процессный синглтон."""
    # Arrange / Act
    first = get_limiter()
    second = get_limiter()
    # Assert
    assert first is second
