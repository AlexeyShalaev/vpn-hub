"""Юнит-тесты для vpnhub.services.backups — чистые (без Postgres) части модуля.

Здесь покрыты только независимые от БД функции и файловые методы BackupService:
- шифрование/дешифрование blob'а (_encrypt/_decrypt) и вывод ключа (_derive);
- человекочитаемый размер (_human_size);
- сериализация/десериализация значений строк (_ser/_deser);
- работа с файлами бэкапов (_path/list_backups/delete_backup/backup_path) через backup_dir=tmp_path.

Методы _dump/_load/create_backup/restore_from_bytes/run_tick завязаны на Postgres
(TRUNCATE ... RESTART IDENTITY CASCADE, таблица alembic_version) и на SQLite не работают —
их здесь НЕ тестируем.
"""

from __future__ import annotations

import base64
import os
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pytest_lazy_fixtures import lf
from sqlalchemy import Date, DateTime, Numeric, String

import vpnhub.services.backups as bk
from vpnhub.api.config import Settings
from vpnhub.core.errors import BadRequest, NotFound

pytestmark = pytest.mark.unit


# --- фикстуры -------------------------------------------------------------


@pytest.fixture
def settings(tmp_path: object) -> Settings:
    """Настройки без чтения env, с backup_dir во временной директории теста."""
    return Settings(_env_file=None, backup_dir=str(tmp_path))


@pytest.fixture
def service(settings: Settings) -> bk.BackupService:
    """BackupService с uow=None — файловые методы uow не трогают."""
    return bk.BackupService(None, settings)


# --- валидация конфига (ветки ошибок срабатывают до обращения к БД, uow не нужен) ---


async def test__set_frequency__invalid_value__raises_bad_request(service: bk.BackupService) -> None:
    """Недопустимая частота отвергается BadRequest ещё до записи в settings (БД не трогается)."""
    # Arrange / Act / Assert
    with pytest.raises(BadRequest, match="частота"):
        await service.set_frequency("hourly")


async def test__set_key__too_short__raises_bad_request(service: bk.BackupService) -> None:
    """Мастер-ключ короче 8 символов отвергается BadRequest до применения (БД не трогается)."""
    # Arrange / Act / Assert
    with pytest.raises(BadRequest, match="минимум 8"):
        await service.set_key("short")


# --- _encrypt / _decrypt (round-trip и ошибки) ----------------------------


def test__encrypt_decrypt__correct_passphrase__round_trips_plaintext() -> None:
    """Зашифрованный blob той же фразой расшифровывается обратно в исходные байты."""
    # Arrange
    plaintext = b"secret payload \x00\x01\xff and unicode \xd0\xbf\xd1\x80"
    passphrase = "correct horse battery staple"
    # Act
    blob = bk._encrypt(plaintext, passphrase)
    recovered = bk._decrypt(blob, passphrase)
    # Assert
    assert recovered == plaintext


def test__encrypt__any_call__prepends_magic_header() -> None:
    """Формат blob'а начинается с магической сигнатуры VHB1."""
    # Arrange
    passphrase = "phrase"
    # Act
    blob = bk._encrypt(b"data", passphrase)
    # Assert
    assert blob[:4] == bk._MAGIC == b"VHB1"


def test__encrypt__two_calls_same_input__differ_by_random_salt_nonce() -> None:
    """Соль и nonce случайны: два шифрования одного и того же дают разные blob'ы."""
    # Arrange
    plaintext, passphrase = b"same", "same-phrase"
    # Act
    first = bk._encrypt(plaintext, passphrase)
    second = bk._encrypt(plaintext, passphrase)
    # Assert
    assert first != second
    assert bk._decrypt(first, passphrase) == bk._decrypt(second, passphrase) == plaintext


def test__decrypt__wrong_passphrase__raises_bad_request() -> None:
    """Неверная парольная фраза → BadRequest про неверный ключ/повреждение."""
    # Arrange
    blob = bk._encrypt(b"payload", "right-phrase")
    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        bk._decrypt(blob, "wrong-phrase")
    assert exc.value.http_status == 400


@pytest.fixture
def blob_foreign_magic() -> bytes:
    """Blob достаточной длины, но с чужой сигнатурой вместо VHB1."""
    good = bk._encrypt(b"payload", "phrase")
    return b"XXXX" + good[4:]


@pytest.fixture
def blob_too_short() -> bytes:
    """Слишком короткий blob (меньше заголовка magic+salt+nonce)."""
    return b"VHB1" + b"\x00" * 5


@pytest.mark.parametrize("blob", [lf("blob_foreign_magic"), lf("blob_too_short")])
def test__decrypt__foreign_magic_or_short_blob__raises_bad_request(blob: bytes) -> None:
    """Чужой магик или слишком короткий blob → BadRequest 'не является бэкапом'."""
    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        bk._decrypt(blob, "phrase")
    assert exc.value.http_status == 400


# --- _derive --------------------------------------------------------------


def test__derive__same_passphrase_and_salt__is_deterministic() -> None:
    """Один и тот же (passphrase, salt) → один и тот же 32-байтовый ключ."""
    # Arrange
    salt = b"0123456789abcdef"
    # Act
    first = bk._derive("pass", salt)
    second = bk._derive("pass", salt)
    # Assert
    assert first == second
    assert len(first) == 32


def test__derive__different_salt__yields_different_key() -> None:
    """Разная соль при одной фразе → разные производные ключи."""
    # Arrange
    passphrase = "pass"
    # Act
    key_a = bk._derive(passphrase, b"salt-aaaaaaaaaaa")
    key_b = bk._derive(passphrase, b"salt-bbbbbbbbbbb")
    # Assert
    assert key_a != key_b


# --- _human_size (границы Б/КБ/МБ) ----------------------------------------


@pytest.mark.parametrize(
    ("size", "expected"),
    [
        (0, "0 Б"),
        (512, "512 Б"),
        (1023, "1023 Б"),
        (1024, "1.0 КБ"),
        (1536, "1.5 КБ"),
        (1024 * 1024 - 1, "1024.0 КБ"),
        (1024 * 1024, "1.0 МБ"),
        (3 * 1024 * 1024, "3.0 МБ"),
    ],
)
def test__human_size__various_sizes__formats_with_expected_unit(size: int, expected: str) -> None:
    """_human_size форматирует байты в Б/КБ/МБ по границам 1024 и 1024^2."""
    # Act
    result = bk._human_size(size)
    # Assert
    assert result == expected


# --- _ser (сериализация значений строки) ----------------------------------


def test__ser__datetime__returns_iso_string() -> None:
    """datetime сериализуется в ISO-строку."""
    # Arrange
    dt = datetime(2026, 7, 2, 13, 45, 30, tzinfo=UTC)
    # Act
    result = bk._ser(dt)
    # Assert
    assert result == dt.isoformat()


def test__ser__date__returns_iso_string() -> None:
    """date сериализуется в ISO-строку."""
    # Arrange
    d = date(2026, 7, 2)
    # Act
    result = bk._ser(d)
    # Assert
    assert result == "2026-07-02"


def test__ser__decimal__returns_str() -> None:
    """Decimal сериализуется в строку (без потери точности)."""
    # Arrange
    value = Decimal("12345.67")
    # Act
    result = bk._ser(value)
    # Assert
    assert result == "12345.67"


def test__ser__bytes__returns_b64_wrapper() -> None:
    """bytes сериализуются в словарь-обёртку {'__b64__': ...}."""
    # Arrange
    raw = b"\x00\x01\x02binary"
    # Act
    result = bk._ser(raw)
    # Assert
    assert result == {"__b64__": base64.b64encode(raw).decode()}


def test__ser__plain_value__returned_unchanged() -> None:
    """Обычные значения (int/str/None) сериализатор не трогает."""
    # Act / Assert
    assert bk._ser(42) == 42
    assert bk._ser("hello") == "hello"
    assert bk._ser(None) is None


# --- _deser (десериализация с учётом типа колонки) ------------------------


def test__deser__none_value__returns_none() -> None:
    """None остаётся None независимо от типа колонки."""
    # Act / Assert
    assert bk._deser(DateTime(), None) is None


def test__deser__datetime_column__parses_iso_string() -> None:
    """Строка ISO при колонке DateTime → объект datetime (round-trip с _ser)."""
    # Arrange
    dt = datetime(2026, 7, 2, 13, 45, 30, tzinfo=UTC)
    serialized = bk._ser(dt)
    # Act
    result = bk._deser(DateTime(), serialized)
    # Assert
    assert result == dt


def test__deser__date_column__parses_iso_string() -> None:
    """Строка ISO при колонке Date → объект date (round-trip с _ser)."""
    # Arrange
    d = date(2026, 7, 2)
    serialized = bk._ser(d)
    # Act
    result = bk._deser(Date(), serialized)
    # Assert
    assert result == d


def test__deser__numeric_column__parses_decimal() -> None:
    """Строка при колонке Numeric → Decimal (round-trip с _ser)."""
    # Arrange
    value = Decimal("12345.67")
    serialized = bk._ser(value)
    # Act
    result = bk._deser(Numeric(), serialized)
    # Assert
    assert result == value
    assert isinstance(result, Decimal)


def test__deser__b64_wrapper__decodes_to_bytes() -> None:
    """Обёртка {'__b64__': ...} → исходные bytes независимо от типа колонки."""
    # Arrange
    raw = b"\x00\x01\x02binary"
    serialized = bk._ser(raw)
    # Act
    result = bk._deser(String(), serialized)
    # Assert
    assert result == raw


def test__deser__string_column__returns_value_unchanged() -> None:
    """Строковая колонка со строковым значением — без преобразований."""
    # Act
    result = bk._deser(String(), "plain-text")
    # Assert
    assert result == "plain-text"


# --- _path (защита от path traversal) -------------------------------------


def test__path__valid_vhb_name__joins_with_backup_dir(service: bk.BackupService, settings: Settings) -> None:
    """Корректное имя '*.vhb' → путь внутри backup_dir."""
    # Act
    path = service._path("a.vhb")
    # Assert
    assert path == os.path.join(settings.backup_dir, "a.vhb")


@pytest.fixture
def name_traversal() -> str:
    """Имя с попыткой выхода из каталога."""
    return "../x.vhb"


@pytest.fixture
def name_not_vhb() -> str:
    """Имя без расширения .vhb."""
    return "a.txt"


@pytest.mark.parametrize("name", [lf("name_traversal"), lf("name_not_vhb")])
def test__path__traversal_or_wrong_extension__raises_bad_request(service: bk.BackupService, name: str) -> None:
    """Path-traversal или не-.vhb имя → BadRequest 'Некорректное имя бэкапа'."""
    # Act / Assert
    with pytest.raises(BadRequest) as exc:
        service._path(name)
    assert exc.value.http_status == 400


# --- list_backups ---------------------------------------------------------


def test__list_backups__empty_dir__returns_empty_list(service: bk.BackupService) -> None:
    """Пустая (или отсутствующая) директория бэкапов → пустой список."""
    # Act
    result = service.list_backups()
    # Assert
    assert result == []


def test__list_backups__manual_vhb_file__returns_entry_with_manual_kind(
    service: bk.BackupService, settings: Settings
) -> None:
    """Файл '*.vhb' без '-auto-' → одна запись вида «ручной» с id=имя файла."""
    # Arrange
    name = "vpnhub-manual-2026-07-02_10-00-00.vhb"
    with open(os.path.join(settings.backup_dir, name), "wb") as f:
        f.write(b"x" * 2048)
    # Act
    result = service.list_backups()
    # Assert
    assert len(result) == 1
    assert result[0]["id"] == name
    assert result[0]["kind"] == "ручной"
    assert result[0]["size"] == "2.0 КБ"


def test__list_backups__auto_named_file__marked_as_auto(service: bk.BackupService, settings: Settings) -> None:
    """Файл с '-auto-' в имени → запись помечается как «авто»."""
    # Arrange
    name = "vpnhub-auto-2026-07-02_10-00-00.vhb"
    with open(os.path.join(settings.backup_dir, name), "wb") as f:
        f.write(b"data")
    # Act
    result = service.list_backups()
    # Assert
    assert len(result) == 1
    assert result[0]["kind"] == "авто"


def test__list_backups__non_vhb_files_present__ignored(service: bk.BackupService, settings: Settings) -> None:
    """Не-.vhb файлы в каталоге игнорируются."""
    # Arrange
    with open(os.path.join(settings.backup_dir, "readme.txt"), "wb") as f:
        f.write(b"noise")
    with open(os.path.join(settings.backup_dir, "good.vhb"), "wb") as f:
        f.write(b"ok")
    # Act
    result = service.list_backups()
    # Assert
    assert [e["id"] for e in result] == ["good.vhb"]


# --- delete_backup --------------------------------------------------------


def test__delete_backup__existing_file__removes_it(service: bk.BackupService, settings: Settings) -> None:
    """Существующий файл бэкапа удаляется с диска."""
    # Arrange
    name = "gone.vhb"
    path = os.path.join(settings.backup_dir, name)
    with open(path, "wb") as f:
        f.write(b"bye")
    # Act
    service.delete_backup(name)
    # Assert
    assert not os.path.exists(path)


def test__delete_backup__missing_file__silently_ok(service: bk.BackupService) -> None:
    """Удаление отсутствующего файла не бросает исключение."""
    # Act
    result = service.delete_backup("nope.vhb")
    # Assert
    assert result is None


def test__delete_backup__invalid_name__raises_bad_request(service: bk.BackupService) -> None:
    """Некорректное имя (не .vhb) при удалении → BadRequest от _path."""
    # Act / Assert
    with pytest.raises(BadRequest):
        service.delete_backup("../evil")


# --- backup_path ----------------------------------------------------------


def test__backup_path__existing_file__returns_full_path(service: bk.BackupService, settings: Settings) -> None:
    """Существующий бэкап → полный путь к файлу."""
    # Arrange
    name = "present.vhb"
    path = os.path.join(settings.backup_dir, name)
    with open(path, "wb") as f:
        f.write(b"here")
    # Act
    result = service.backup_path(name)
    # Assert
    assert result == path


def test__backup_path__missing_file__raises_not_found(service: bk.BackupService) -> None:
    """Отсутствующий бэкап → NotFound 'Бэкап не найден'."""
    # Act / Assert
    with pytest.raises(NotFound) as exc:
        service.backup_path("missing.vhb")
    assert exc.value.http_status == 404
