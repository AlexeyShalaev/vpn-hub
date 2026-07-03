"""Юнит-тесты для vpnhub.infra.updates: парсинг версий, сравнение и разбор фида."""

from __future__ import annotations

import json

import pytest
from pytest_lazy_fixtures import lf

import vpnhub.infra.updates as updates_mod
from vpnhub.infra.updates import fetch_feed, is_newer, parse_version

pytestmark = pytest.mark.unit


# --- фикстуры кейсов для parse_version -------------------------------------


@pytest.fixture
def version_plain() -> tuple[str, tuple[int, ...]]:
    """Обычная семверная строка «1.2.3»."""
    return "1.2.3", (1, 2, 3)


@pytest.fixture
def version_v_prefixed() -> tuple[str, tuple[int, ...]]:
    """Строка с префиксом «v» и двумя частями."""
    return "v1.2", (1, 2)


@pytest.fixture
def version_empty() -> tuple[str, tuple[int, ...]]:
    """Пустая строка → одна нулевая часть."""
    return "", (0,)


@pytest.fixture
def version_prerelease() -> tuple[str, tuple[int, ...]]:
    """Пререлиз «1.0.0-rc1» → из каждой части берутся только цифры."""
    return "1.0.0-rc1", (1, 0, 1)


# --- parse_version ----------------------------------------------------------


@pytest.mark.parametrize(
    "case",
    [
        lf("version_plain"),
        lf("version_v_prefixed"),
        lf("version_empty"),
        lf("version_prerelease"),
    ],
)
def test__parse_version__various_inputs__returns_int_tuple(case: tuple[str, tuple[int, ...]]) -> None:
    """parse_version переводит строку версии в кортеж целых по описанным правилам."""
    # Arrange
    raw, expected = case
    # Act
    result = parse_version(raw)
    # Assert
    assert result == expected


def test__parse_version__uppercase_v_prefix__is_stripped() -> None:
    """Префикс «V» в верхнем регистре также срезается перед разбором."""
    # Arrange
    raw = "V2.5"
    # Act
    result = parse_version(raw)
    # Assert
    assert result == (2, 5)


def test__parse_version__surrounding_whitespace__is_trimmed() -> None:
    """Пробелы по краям строки не мешают разбору версии."""
    # Arrange
    raw = "  1.4.9  "
    # Act
    result = parse_version(raw)
    # Assert
    assert result == (1, 4, 9)


def test__parse_version__non_numeric_part__becomes_zero() -> None:
    """Часть без цифр («beta») превращается в 0, а не отбрасывается."""
    # Arrange
    raw = "1.beta.3"
    # Act
    result = parse_version(raw)
    # Assert
    assert result == (1, 0, 3)


# --- is_newer ---------------------------------------------------------------


@pytest.fixture
def pair_newer() -> tuple[str, str]:
    """latest строго новее current."""
    return "1.2.4", "1.2.3"


@pytest.fixture
def pair_older() -> tuple[str, str]:
    """latest строго старее current."""
    return "1.2.2", "1.2.3"


@pytest.fixture
def pair_longer_newer() -> tuple[str, str]:
    """Более длинная версия (доп. компонент) считается новее равного префикса."""
    return "1.2.3.1", "1.2.3"


def test__is_newer__latest_greater__returns_true(pair_newer: tuple[str, str]) -> None:
    """Когда latest больше current — обновление есть."""
    # Arrange
    latest, current = pair_newer
    # Act
    result = is_newer(latest, current)
    # Assert
    assert result is True


@pytest.mark.parametrize(
    "case",
    [
        lf("pair_older"),
    ],
)
def test__is_newer__latest_smaller__returns_false(case: tuple[str, str]) -> None:
    """Когда latest меньше current — обновления нет."""
    # Arrange
    latest, current = case
    # Act
    result = is_newer(latest, current)
    # Assert
    assert result is False


def test__is_newer__equal_versions__returns_false() -> None:
    """Одинаковые версии не считаются обновлением."""
    # Arrange
    latest, current = "1.2.3", "1.2.3"
    # Act
    result = is_newer(latest, current)
    # Assert
    assert result is False


def test__is_newer__longer_latest_with_extra_component__returns_true(pair_longer_newer: tuple[str, str]) -> None:
    """Версия с дополнительным компонентом (1.2.3.1) новее короткой (1.2.3)."""
    # Arrange
    latest, current = pair_longer_newer
    # Act
    result = is_newer(latest, current)
    # Assert
    assert result is True


def test__is_newer__shorter_latest_same_prefix__returns_false() -> None:
    """Более короткая версия (1.2) не новее длинной с тем же префиксом (1.2.0)."""
    # Arrange
    latest, current = "1.2", "1.2.0"
    # Act
    result = is_newer(latest, current)
    # Assert
    assert result is False


def test__is_newer__ignores_v_prefix__compares_by_numbers() -> None:
    """Префикс «v» не влияет на сравнение: v1.3 новее 1.2."""
    # Arrange
    latest, current = "v1.3", "1.2"
    # Act
    result = is_newer(latest, current)
    # Assert
    assert result is True


# --- fetch_feed -------------------------------------------------------------


class _FakeResponse:
    """Минимальный заменитель http-ответа: поддерживает .read() и контекст-менеджер."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return self._payload

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *exc: object) -> bool:
        return False


def _patch_urlopen(monkeypatch: pytest.MonkeyPatch, payload: bytes) -> list[float]:
    """Подменяет urllib.request.urlopen в модуле updates фейком; возвращает список пойманных таймаутов."""
    seen_timeouts: list[float] = []

    def fake_urlopen(req: object, timeout: float = 0.0) -> _FakeResponse:
        seen_timeouts.append(timeout)
        return _FakeResponse(payload)

    monkeypatch.setattr(updates_mod.urllib.request, "urlopen", fake_urlopen)
    return seen_timeouts


async def test__fetch_feed__valid_json_object__returns_dict(monkeypatch: pytest.MonkeyPatch) -> None:
    """Валидный JSON-объект из фида возвращается как dict без изменений."""
    # Arrange
    feed = {"latest": "1.2.3", "releases": [{"v": "1.2.3"}]}
    _patch_urlopen(monkeypatch, json.dumps(feed).encode("utf-8"))
    # Act
    result = await fetch_feed("https://example.test/feed.json")
    # Assert
    assert result == feed


async def test__fetch_feed__non_dict_payload__raises_value_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Если фид отдаёт не объект (например, список) — поднимается ValueError."""
    # Arrange
    _patch_urlopen(monkeypatch, json.dumps(["1.2.3"]).encode("utf-8"))
    # Act / Assert
    with pytest.raises(ValueError, match="feed is not an object"):
        await fetch_feed("https://example.test/feed.json")


async def test__fetch_feed__malformed_json__raises_json_decode_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Невалидный JSON в теле фида → json.JSONDecodeError (не проглатывается)."""
    # Arrange
    _patch_urlopen(monkeypatch, b"<<not json>>")
    # Act / Assert
    with pytest.raises(json.JSONDecodeError):
        await fetch_feed("https://example.test/feed.json")


async def test__fetch_feed__custom_timeout__passed_to_urlopen(monkeypatch: pytest.MonkeyPatch) -> None:
    """Переданный timeout прокидывается в urlopen."""
    # Arrange
    seen_timeouts = _patch_urlopen(monkeypatch, json.dumps({"latest": "1.0.0"}).encode("utf-8"))
    # Act
    await fetch_feed("https://example.test/feed.json", timeout=3.5)
    # Assert
    assert seen_timeouts == [3.5]
