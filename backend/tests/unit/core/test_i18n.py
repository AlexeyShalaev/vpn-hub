"""Гарантии серверной локализации: паритет ru/en и поведение translate/resolve_lang.

Аналог фронтового `satisfies Dict` (там паритет ловит tsc). На бэке компилятор не
поможет — поэтому тест: каждый ключ MESSAGES обязан иметь непустые ru и en.
"""

from __future__ import annotations

import pytest

from vpnhub.core.i18n import LANGS, MESSAGES, resolve_lang, translate

pytestmark = pytest.mark.unit


def test__messages__every_key_covers_all_languages() -> None:
    missing: list[str] = []
    for key, entry in MESSAGES.items():
        for lang in LANGS:
            if not entry.get(lang) or not entry[lang].strip():
                missing.append(f"{key}:{lang}")
    assert not missing, f"ключи без перевода: {missing}"


def test__messages__no_extra_languages() -> None:
    allowed = set(LANGS)
    for key, entry in MESSAGES.items():
        assert set(entry) == allowed, f"{key}: языки {set(entry)} != {allowed}"


def test__translate__interpolates_and_falls_back() -> None:
    # известный ключ на двух языках
    assert translate("error.not_found", "ru") == "Не найдено"
    assert translate("error.not_found", "en") == "Not found"
    # неизвестный ключ → возвращаем сам ключ (ответ не падает)
    assert translate("does.not.exist", "en") == "does.not.exist"


def test__translate__param_placeholders() -> None:
    key = "__test_interp__"
    MESSAGES[key] = {"ru": "Осталось {n} шт.", "en": "{n} left"}
    try:
        assert translate(key, "ru", n=3) == "Осталось 3 шт."
        assert translate(key, "en", n=3) == "3 left"
        # отсутствующий плейсхолдер остаётся как есть
        assert translate(key, "en") == "{n} left"
    finally:
        del MESSAGES[key]


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("en-US,en;q=0.9", "en"),
        ("ru-RU,ru;q=0.9", "ru"),
        ("en", "en"),
        ("ru", "ru"),
        ("fr", "ru"),  # неизвестный → дефолт
        (None, "ru"),
        ("", "ru"),
    ],
)
def test__resolve_lang__from_accept_language(header: str | None, expected: str) -> None:
    assert resolve_lang(header) == expected


def test__resolve_lang__explicit_pref_wins() -> None:
    assert resolve_lang("ru", pref="en") == "en"
    assert resolve_lang("en", pref="bogus") == "en"  # мусорный pref игнорируется


def test__localize_note__translates_conventional_commit_type() -> None:
    from vpnhub.infra.updates import localize_note

    # метка типа локализуется, scope/описание сохраняются
    assert localize_note("feat(ui): superapp launcher", "ru") == "Новое(ui): superapp launcher"
    assert localize_note("feat(ui): superapp launcher", "en") == "New(ui): superapp launcher"
    assert localize_note("fix: race in sync", "ru") == "Исправление: race in sync"
    # неизвестный/непрефиксный текст остаётся как есть
    assert localize_note("Первый релиз VPN Hub", "en") == "Первый релиз VPN Hub"
    assert localize_note("random text", "ru") == "random text"


def test__localize_releases__maps_notes_without_mutating() -> None:
    from vpnhub.infra.updates import localize_releases

    src = [{"v": "1.0.0", "date": "x", "notes": ["feat: a", "fix: b"]}]
    out = localize_releases(src, "en")
    assert out[0]["notes"] == ["New: a", "Fix: b"]
    assert src[0]["notes"] == ["feat: a", "fix: b"]  # исходник не мутирован
