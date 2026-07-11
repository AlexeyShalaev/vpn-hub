"""Курируемый двуязычный changelog — единственный источник заметок релизов.

Раньше ноты тянулись из GitHub Releases (авто-генерация release-please из коммитов,
только англ.). Теперь пишем их вручную и двуязычно: панель отдаёт `notes` на языке
запроса (см. services/admin.check_updates/system), а человекочитаемый CHANGELOG.md для
GitHub генерится ОТСЮДА скриптом `scripts/gen_changelog.py` (`make changelog`).

release-please по-прежнему бампит версию и ставит тег — но заметки ведём здесь.

Новый релиз: добавьте запись СВЕРХУ (первая = самая свежая), с `ru` и `en` в каждом
пункте, затем `make changelog`. Версию в записи держите равной версии релиза.
"""

from __future__ import annotations

from typing import TypedDict

from vpnhub.core.i18n import DEFAULT_LANG, Lang


class Release(TypedDict):
    v: str
    date: str  # YYYY-MM-DD
    notes: list[dict[str, str]]  # каждый пункт: {"ru": …, "en": …}


# Самая свежая версия — первая. Пункты: пользовательские формулировки (не commit-стиль).
RELEASES: list[Release] = [
    {
        "v": "0.8.0",
        "date": "2026-07-05",
        "notes": [
            {
                "ru": "Выданные конфиги устройства сгруппированы по серверам",
                "en": "A device's issued configs are grouped by server",
            },
            {
                "ru": "Исправлено: в ссылках-приглашениях больше не появляются %5B/%5D из имён серверов",
                "en": "Fixed: server names no longer show %5B/%5D in share links",
            },
        ],
    },
    {
        "v": "0.7.0",
        "date": "2026-07-05",
        "notes": [
            {
                "ru": "Кнопка обновления в Kubernetes показывается только при наличии прав на patch (пре-чек RBAC)",
                "en": "The Kubernetes update button appears only when patch permission is granted (RBAC pre-check)",
            },
            {
                "ru": "Конфиги Xray XHTTP помечаются «XHTTP» в имени сервера",
                "en": 'Xray XHTTP configs are tagged "XHTTP" in the server name',
            },
        ],
    },
    {
        "v": "0.6.0",
        "date": "2026-07-05",
        "notes": [
            {
                "ru": "Совместимые протоколы Amnezia выдаются одним выбором",
                "en": "Bundlable Amnezia protocols are issued as a single choice",
            },
            {
                "ru": "Исправлено: при выборе Xray XHTTP бандл больше не идёт первым",
                "en": "Fixed: the bundle no longer leads when Xray XHTTP is chosen",
            },
            {
                "ru": "Исправлено: каждый выданный конфиг — в одну строку",
                "en": "Fixed: each issued config stays on one line",
            },
            {
                "ru": "Официальные иконки платформ Android, Linux и Windows",
                "en": "Official Android, Linux and Windows platform icons",
            },
        ],
    },
    {
        "v": "0.5.0",
        "date": "2026-07-05",
        "notes": [
            {
                "ru": "Обновление из панели во всех режимах развёртывания",
                "en": "Apply updates from the panel across all deploy modes",
            },
            {
                "ru": "Своя иконка для каждой платформы устройства",
                "en": "A distinct icon per device platform",
            },
            {
                "ru": "Официальные логотипы вендоров на карточках VPN-софта",
                "en": "Official vendor logos on VPN software cards",
            },
            {
                "ru": "Исправлено: бейдж пула больше не перекрывает имя сервера на мобильном",
                "en": "Fixed: the pool badge no longer overlaps the server name on mobile",
            },
            {
                "ru": "Управление протоколами сервера — в аккуратной вертикальной карточке",
                "en": "Server protocol management redesigned into a clean vertical card",
            },
            {
                "ru": "Исправлено: акцентная точка Hysteria2 в карточках протоколов",
                "en": "Fixed: the Hysteria2 accent dot in protocol cards",
            },
        ],
    },
    {
        "v": "0.4.0",
        "date": "2026-07-04",
        "notes": [
            {
                "ru": "Участники могут отзывать свои выданные конфиги",
                "en": "Members can revoke their own issued configs",
            },
            {
                "ru": "Протоколы Amnezia сервера объединяются в один vpn://",
                "en": "A server's Amnezia protocols bundle into one vpn://",
            },
            {
                "ru": "Протоколы Amnezia ставятся по одному, с добавлением и удалением",
                "en": "Install Amnezia protocols individually, with add/remove",
            },
            {
                "ru": "Запуск и остановка отдельных протоколов Amnezia",
                "en": "Start/stop individual Amnezia protocols",
            },
            {
                "ru": "Исправлено: перед выдачей конфига нужно явно выбрать устройство и протокол",
                "en": "Fixed: require an explicit device and protocol before issuing a config",
            },
        ],
    },
    {
        "v": "0.3.0",
        "date": "2026-07-04",
        "notes": [
            {
                "ru": "Проверка обновлений по официальным GitHub Releases из коробки (без настройки)",
                "en": "Check official GitHub Releases for updates by default (zero-config)",
            },
        ],
    },
    {
        "v": "0.2.0",
        "date": "2026-07-04",
        "notes": [
            {
                "ru": "Добавлены протоколы Hysteria2 и Xray XHTTP",
                "en": "Added the Hysteria2 and Xray XHTTP protocols",
            },
            {
                "ru": "Автоисправление неудачных установок VPN",
                "en": "Auto-fix for failed VPN installs",
            },
            {
                "ru": "Обязательная локация с выбором из списка и автоименование серверов",
                "en": "Required location with a picker, plus auto-named servers",
            },
        ],
    },
    {
        "v": "0.1.1",
        "date": "2026-07-04",
        "notes": [
            {
                "ru": "Исправлен внешний Postgres за PgBouncer: миграции в transaction-mode и кодирование учётных данных в DSN",  # noqa: E501
                "en": "Fixed external Postgres behind PgBouncer: transaction-mode migrations and DSN credential encoding",  # noqa: E501
            },
        ],
    },
    {
        "v": "0.1.0",
        "date": "2026-07-03",
        "notes": [
            {"ru": "Первый публичный релиз", "en": "Initial public release"},
            {
                "ru": "Исправлен crashloop в Kubernetes из-за внедряемого VPNHUB_PORT; укреплён stdin в install-smoke",
                "en": "Fixed the Kubernetes crashloop from an injected VPNHUB_PORT; hardened install-smoke stdin",
            },
        ],
    },
]


def local_releases(lang: Lang = DEFAULT_LANG) -> list[dict]:
    """Свести к формату панели: {v, date, notes:[str на языке lang]}."""
    return [{"v": r["v"], "date": r["date"], "notes": [n[lang] for n in r["notes"]]} for r in RELEASES]
