"""Юнит-тесты файлового стора каталога провайдеров (`ProviderStore`).

Стор пишет/читает YAML в `settings.providers_file`. Настройки собираем локально на `tmp_path`
(фикстура `settings` из conftest не имеет `providers_file` на tmp), провижининг тут не участвует.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from pytest_lazy_fixtures import lf

from vpnhub.api.config import Settings
from vpnhub.core.errors import BadRequest, NotFound
from vpnhub.infra.providers_store import _DEFAULT, _PRE_MERGE_DEFAULT_IDS, ProviderStore

pytestmark = pytest.mark.unit


def _default_ids() -> list[str]:
    return [p["id"] for p in yaml.safe_load(_DEFAULT.read_text(encoding="utf-8")) if isinstance(p, dict)]


def _seeded_file(providers_path: Path) -> Path:
    return providers_path.with_name(f"{providers_path.stem}.seeded.json")


@pytest.fixture
def providers_path(tmp_path: Path) -> Path:
    """Путь к файлу каталога провайдеров внутри tmp_path."""
    return tmp_path / "providers.yaml"


@pytest.fixture
def local_settings(providers_path: Path) -> Settings:
    """Settings без env, с providers_file на tmp."""
    return Settings(_env_file=None, providers_file=str(providers_path))


@pytest.fixture
def empty_store(local_settings: Settings, providers_path: Path) -> ProviderStore:
    """Стор поверх заведомо пустого каталога (без дефолтного сида)."""
    # Файл уже существует и пуст → _ensure не станет копировать дефолт.
    providers_path.write_text("[]\n", encoding="utf-8")
    return ProviderStore(local_settings)


# --- _ensure --------------------------------------------------------------


def test__ensure__missing_file__creates_it(local_settings: Settings, providers_path: Path) -> None:
    """При отсутствии файла конструктор создаёт его."""
    # Arrange
    assert not providers_path.exists()
    # Act
    ProviderStore(local_settings)
    # Assert
    assert providers_path.exists()


def test__ensure__missing_file__seeds_default_catalog(local_settings: Settings) -> None:
    """Новый файл наполняется дефолтным каталогом (непустой список провайдеров)."""
    # Arrange
    store = ProviderStore(local_settings)
    # Act
    items = store.list()
    # Assert
    assert len(items) > 0
    assert any(p["id"] == "firstbyte" for p in items)


def test__ensure__existing_file__is_not_overwritten(local_settings: Settings, providers_path: Path) -> None:
    """Существующий файл не перезаписывается дефолтом при инициализации."""
    # Arrange
    providers_path.write_text("[]\n", encoding="utf-8")
    # Act
    store = ProviderStore(local_settings)
    # Assert
    assert store.list() == []


# --- _read: устойчивость к битым данным -----------------------------------


def test__list__broken_yaml__returns_empty(local_settings: Settings, providers_path: Path) -> None:
    """Битый YAML в файле не роняет чтение — _read ловит исключение и отдаёт []."""
    # Arrange — файл существует (⇒ _ensure не сидит дефолт), но содержит невалидный YAML
    providers_path.write_text("::: not : valid : yaml :::\n", encoding="utf-8")
    store = ProviderStore(local_settings)
    # Act
    result = store.list()
    # Assert
    assert result == []


def test__list__non_dict_elements__are_filtered_out(local_settings: Settings, providers_path: Path) -> None:
    """Не-dict элементы списка отбрасываются, нормализуются только объекты-провайдеры."""
    # Arrange — валидный YAML-список со скаляром и объектом
    providers_path.write_text(
        yaml.safe_dump(["просто строка", {"id": "ok", "name": "OK"}], allow_unicode=True),
        encoding="utf-8",
    )
    store = ProviderStore(local_settings)
    # Act
    result = store.list()
    # Assert
    assert [p["id"] for p in result] == ["ok"]


# --- create ---------------------------------------------------------------


@pytest.fixture
def blank_name() -> dict:
    """Данные без имени вовсе."""
    return {"url": "https://x"}


@pytest.fixture
def empty_name() -> dict:
    """Данные с пустым именем."""
    return {"name": ""}


@pytest.fixture
def whitespace_name() -> dict:
    """Данные с именем из одних пробелов."""
    return {"name": "   "}


@pytest.mark.parametrize(
    "data",
    [lf("blank_name"), lf("empty_name"), lf("whitespace_name")],
)
def test__create__missing_name__raises_bad_request(empty_store: ProviderStore, data: dict) -> None:
    """Создание без осмысленного имени → BadRequest."""
    # Arrange / Act / Assert
    with pytest.raises(BadRequest) as exc:
        empty_store.create(data)
    assert exc.value.http_status == 400


def test__create__no_id__generates_slug_id_from_name(empty_store: ProviderStore) -> None:
    """Без явного id генерится slug из имени."""
    # Arrange / Act
    item = empty_store.create({"name": "My Cool VPS!"})
    # Assert
    assert item["id"] == "my-cool-vps"


def test__create__duplicate_id__gets_suffix(empty_store: ProviderStore) -> None:
    """Повторный id получает числовой суффикс, а не затирает первый."""
    # Arrange
    first = empty_store.create({"name": "Acme"})
    # Act
    second = empty_store.create({"name": "Acme"})
    # Assert
    assert first["id"] == "acme"
    assert second["id"] == "acme-2"


def test__create__persists_fields_to_file(empty_store: ProviderStore, providers_path: Path) -> None:
    """Созданный провайдер записывается в YAML-файл со всеми полями."""
    # Arrange / Act
    empty_store.create({"name": "Acme", "url": "https://acme.example", "blurb": "хостинг", "tags": ["A"]})
    # Assert
    on_disk = yaml.safe_load(providers_path.read_text(encoding="utf-8"))
    assert on_disk == [{"id": "acme", "name": "Acme", "url": "https://acme.example", "blurb": "хостинг", "tags": ["A"]}]


# --- list -----------------------------------------------------------------


def test__list__after_create__round_trips_item(empty_store: ProviderStore) -> None:
    """Созданный элемент возвращается из list() без потерь."""
    # Arrange
    created = empty_store.create({"name": "RoundTrip", "url": "https://rt", "tags": ["x", "y"]})
    # Act
    items = empty_store.list()
    # Assert
    assert items == [created]


def test__list__reflects_new_store_instance(local_settings: Settings, empty_store: ProviderStore) -> None:
    """Данные читаются с диска: новый экземпляр стора видит созданный элемент."""
    # Arrange
    empty_store.create({"name": "Persisted"})
    # Act
    reopened = ProviderStore(local_settings)
    items = reopened.list()
    # Assert
    assert [p["id"] for p in items] == ["persisted"]


# --- update ---------------------------------------------------------------


def test__update__unknown_id__raises_not_found(empty_store: ProviderStore) -> None:
    """Обновление несуществующего id → NotFound."""
    # Arrange
    empty_store.create({"name": "Acme"})
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        empty_store.update("nope", {"name": "X"})
    assert exc.value.http_status == 404


def test__update__existing_id__changes_fields(empty_store: ProviderStore) -> None:
    """Обновление меняет указанные поля, id остаётся прежним."""
    # Arrange
    empty_store.create({"name": "Acme", "url": "https://old", "blurb": "было"})
    # Act
    updated = empty_store.update("acme", {"url": "https://new", "blurb": "стало"})
    # Assert
    assert updated["id"] == "acme"
    assert updated["url"] == "https://new"
    assert updated["blurb"] == "стало"


def test__update__existing_id__persists_change(empty_store: ProviderStore, providers_path: Path) -> None:
    """Изменение сохраняется в файл (видно при чтении с диска)."""
    # Arrange
    empty_store.create({"name": "Acme", "url": "https://old"})
    # Act
    empty_store.update("acme", {"url": "https://new"})
    # Assert
    on_disk = yaml.safe_load(providers_path.read_text(encoding="utf-8"))
    assert on_disk[0]["url"] == "https://new"


def test__update__ignores_id_override_in_payload(empty_store: ProviderStore) -> None:
    """Попытка сменить id через payload игнорируется — обновляется по адресуемому id."""
    # Arrange
    empty_store.create({"name": "Acme"})
    # Act
    updated = empty_store.update("acme", {"id": "hacked", "name": "Acme 2"})
    # Assert
    assert updated["id"] == "acme"
    assert updated["name"] == "Acme 2"


# --- delete ---------------------------------------------------------------


def test__delete__unknown_id__raises_not_found(empty_store: ProviderStore) -> None:
    """Удаление несуществующего id → NotFound."""
    # Arrange
    empty_store.create({"name": "Acme"})
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        empty_store.delete("nope")
    assert exc.value.http_status == 404


def test__delete__existing_id__removes_item(empty_store: ProviderStore) -> None:
    """Удаление существующего провайдера убирает его из каталога."""
    # Arrange
    empty_store.create({"name": "Keep"})
    empty_store.create({"name": "Drop"})
    # Act
    empty_store.delete("drop")
    # Assert
    assert [p["id"] for p in empty_store.list()] == ["keep"]


# --- _norm ----------------------------------------------------------------


@pytest.fixture
def tags_tuple() -> dict:
    """tags заданы кортежем."""
    return {"name": "T", "tags": ("a", "b")}


@pytest.fixture
def tags_ints() -> dict:
    """tags содержат нестроковые значения."""
    return {"name": "T", "tags": [1, 2]}


@pytest.fixture
def tags_none() -> dict:
    """tags отсутствуют (None)."""
    return {"name": "T", "tags": None}


@pytest.mark.parametrize(
    ("data", "expected_tags"),
    [
        (lf("tags_tuple"), ["a", "b"]),
        (lf("tags_ints"), ["1", "2"]),
        (lf("tags_none"), []),
    ],
)
def test__norm__tags__coerced_to_list_of_str(empty_store: ProviderStore, data: dict, expected_tags: list[str]) -> None:
    """tags любого вида приводятся к list[str]."""
    # Arrange / Act
    item = empty_store.create(data)
    # Assert
    assert item["tags"] == expected_tags
    assert all(isinstance(t, str) for t in item["tags"])


def test__norm__missing_optional_fields__defaults_to_empty_strings(empty_store: ProviderStore) -> None:
    """Отсутствующие url/blurb нормализуются в пустые строки."""
    # Arrange / Act
    item = empty_store.create({"name": "OnlyName"})
    # Assert
    assert item["url"] == ""
    assert item["blurb"] == ""


# --- sync_default_providers (домердж новых дефолтов при обновлении версии) --------------------


def _write_catalog(providers_path: Path, ids: list[str]) -> None:
    providers_path.write_text(
        yaml.safe_dump([{"id": pid, "name": pid} for pid in ids], allow_unicode=True), encoding="utf-8"
    )


def test__sync__existing_install_no_marker__appends_new_defaults(
    local_settings: Settings, providers_path: Path
) -> None:
    """Существующая установка (файл со старыми дефолтами, маркера нет): новые дефолты доливаются."""
    _write_catalog(providers_path, sorted(_PRE_MERGE_DEFAULT_IDS))
    store = ProviderStore(local_settings)

    added = store.sync_default_providers()

    ids = [p["id"] for p in store.list()]
    new_ids = set(_default_ids()) - _PRE_MERGE_DEFAULT_IDS
    assert new_ids  # в дефолтном каталоге реально есть провайдеры новее базового набора
    assert added == len(new_ids)
    assert new_ids.issubset(ids)  # новые провайдеры появились
    assert _PRE_MERGE_DEFAULT_IDS.issubset(set(ids))  # старые сохранены


def test__sync__deleted_baseline_default__not_resurrected(local_settings: Settings, providers_path: Path) -> None:
    """Удалённый пользователем старый дефолт не воскресает, но новые дефолты всё равно доливаются."""
    _write_catalog(providers_path, sorted(_PRE_MERGE_DEFAULT_IDS - {"ufo"}))
    store = ProviderStore(local_settings)

    store.sync_default_providers()

    ids = [p["id"] for p in store.list()]
    assert "ufo" not in ids
    assert (set(_default_ids()) - _PRE_MERGE_DEFAULT_IDS).issubset(set(ids))


def test__sync__fresh_install__no_merge_no_duplicates(local_settings: Settings) -> None:
    """Чистая установка: _ensure насидил полный дефолт → sync ничего не добавляет и не дублирует."""
    store = ProviderStore(local_settings)  # файла нет → сид полного дефолта
    before = [p["id"] for p in store.list()]

    added = store.sync_default_providers()

    after = [p["id"] for p in store.list()]
    assert added == 0
    assert after == before
    assert len(after) == len(set(after))


def test__sync__marker_all_seeded__is_noop(local_settings: Settings, providers_path: Path) -> None:
    """Если все дефолтные id уже в маркере — sync ничего не доливает (даже в пустой пользовательский файл)."""
    providers_path.write_text(yaml.safe_dump([{"id": "mine", "name": "Mine"}], allow_unicode=True), encoding="utf-8")
    _seeded_file(providers_path).write_text(json.dumps(_default_ids()), encoding="utf-8")
    store = ProviderStore(local_settings)

    added = store.sync_default_providers()

    assert added == 0
    assert [p["id"] for p in store.list()] == ["mine"]


def test__sync__preserves_user_edits(local_settings: Settings, providers_path: Path) -> None:
    """Правки пользователя в дефолтном провайдере сохраняются (доливаем только НОВЫЕ по id)."""
    providers_path.write_text(
        yaml.safe_dump([{"id": "firstbyte", "name": "My FB", "url": "https://custom"}], allow_unicode=True),
        encoding="utf-8",
    )
    store = ProviderStore(local_settings)

    store.sync_default_providers()

    fb = next(p for p in store.list() if p["id"] == "firstbyte")
    assert fb["name"] == "My FB" and fb["url"] == "https://custom"


def test__sync__idempotent(local_settings: Settings, providers_path: Path) -> None:
    """Повторный вызов sync ничего не добавляет (маркер уже проставлен)."""
    _write_catalog(providers_path, sorted(_PRE_MERGE_DEFAULT_IDS))
    store = ProviderStore(local_settings)

    first = store.sync_default_providers()
    second = store.sync_default_providers()

    assert first > 0
    assert second == 0
