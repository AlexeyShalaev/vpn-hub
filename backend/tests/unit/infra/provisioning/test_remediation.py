"""Юнит-тесты реестра подсказок-ремедиаций (infra.provisioning.remediation).

Проверяем матчинг код→подсказка, разбор легаси-строки 'code: message' (для строк без
error_code), приоритет специфичной записи над общей для перегруженного кода 'internal',
и корректность fix_id/FIXES-инвариантов.
"""

from __future__ import annotations

import pytest

from vpnhub.infra.provisioning import remediation as rem
from vpnhub.infra.provisioning import templates
from vpnhub.infra.provisioning.errors import MESSAGES

pytestmark = pytest.mark.unit


def test__resolve__fuser_case__matches_auto_psmisc() -> None:
    # Arrange — реальный кейс со скриншота: код internal + деталь про fuser/cat
    code = "internal"
    text = "internal: Внутренняя ошибка provisioning: нет fuser/cat для проверки блокировки"
    # Act
    r = rem.resolve(code, text)
    # Assert
    assert r is not None
    assert r.kind == "auto"
    assert r.fix_id == "install_psmisc"
    assert r.detail_contains == "fuser"


def test__resolve__internal_without_fuser__falls_back_to_generic_none() -> None:
    # Arrange — другой internal (валидация), не про fuser
    r = rem.resolve("internal", "internal: Внутренняя ошибка provisioning: недопустимый clientId")
    # Assert — берётся общая запись (detail_contains=None), она kind='none'
    assert r is not None
    assert r.detail_contains is None
    assert r.kind == "none"
    assert r.fix_id is None


def test__resolve__legacy_row_without_error_code__parses_prefix() -> None:
    # Arrange — старая строка без сохранённого error_code (code=None), fuser-кейс
    r = rem.resolve(None, "internal: ... нет fuser/cat ...")
    # Assert — код достаётся из префикса строки
    assert r is not None
    assert r.fix_id == "install_psmisc"


def test__resolve__prefer_error_code_over_text_prefix() -> None:
    # Arrange — код задан явно, а текст без распознаваемого префикса
    r = rem.resolve("docker_service_not_running", "докер не поднялся")
    # Assert
    assert r is not None
    assert r.kind == "auto"
    assert r.fix_id == "start_docker"


def test__resolve__manual_code__no_autofix() -> None:
    r = rem.resolve("server_busy", "server_busy: ...")
    assert r is not None
    assert r.kind == "manual"
    assert r.fix_id is None
    assert r.manual_steps  # непустые шаги для пользователя


def test__resolve__unknown_code__returns_none() -> None:
    assert rem.resolve("totally_unknown_code", "totally_unknown_code: boom") is None


def test__resolve__none_and_unparseable__returns_none() -> None:
    assert rem.resolve(None, None) is None
    assert rem.resolve(None, "просто текст без кода") is None


def test__to_dict__auto__sets_canautofix_true_and_camelcase() -> None:
    r = rem.resolve("internal", "нет fuser/cat")
    assert r is not None
    d = rem.to_dict(r)
    assert d["canAutoFix"] is True
    assert set(d.keys()) == {"kind", "title", "explanation", "canAutoFix", "fixLabel", "manualSteps"}
    assert isinstance(d["manualSteps"], list)


def test__to_dict__manual__canautofix_false() -> None:
    r = rem.resolve("ssh", "ssh: не удалось подключиться")
    assert r is not None
    assert rem.to_dict(r)["canAutoFix"] is False


def test__registry__auto_entries_reference_known_fix_or_reinstall() -> None:
    # инвариант: каждая auto-запись ссылается на существующий FIXES-скрипт либо на 'reinstall'
    for entry in rem.REMEDIATIONS:
        if entry.kind == "auto":
            assert entry.fix_id is not None
            assert entry.fix_id == "reinstall" or entry.fix_id in rem.FIXES


def test__registry__every_code_is_known_provisioning_code() -> None:
    # каждый code в реестре — реальный код ошибки provisioning (иначе подсказка мертва)
    for entry in rem.REMEDIATIONS:
        assert entry.code in MESSAGES


def test__resolve__all_fixes_have_scripts_and_markers() -> None:
    # FIXES-скрипты заданы непустыми именами и маркерами
    for fix in rem.FIXES.values():
        assert fix.script.endswith(".sh")
        assert fix.ok_marker
        assert fix.fail_hint


def test__fixes__scripts_load_and_echo_their_ok_marker() -> None:
    # каждый фикс-скрипт физически существует, загружается и печатает свой маркер успеха
    for fix in rem.FIXES.values():
        body = templates.load_shared(fix.script)
        assert body.strip()
        assert fix.ok_marker in body
