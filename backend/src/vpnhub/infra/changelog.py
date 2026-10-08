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
        "v": "0.13.0",
        "date": "2026-10-08",
        "notes": [
            {
                "ru": "Каталог провайдеров — 762 VPS-хостинга в 115 странах: добавлены местные хостеры Филиппин, Шри-Ланки, Непала, Камбоджи, Монголии, Ганы, Грузии, Азербайджана и Киргизии, а способы оплаты для клиентов из России сверены с сайтами провайдеров",  # noqa: E501
                "en": "The provider catalog now lists 762 VPS hosts in 115 countries: local hosts from the Philippines, Sri Lanka, Nepal, Cambodia, Mongolia, Ghana, Georgia, Azerbaijan and Kyrgyzstan are in, and payment methods for customers from Russia were checked against the providers' sites",  # noqa: E501
            },
            {
                "ru": "Провайдеры, которые не принимают клиентов из России (AWS, Hetzner, OVH, Oracle, Azure и другие), помечены тегом «Не принимает клиентов из РФ»; хостеры, чьи правила запрещают VPN или прокси, из каталога убраны",  # noqa: E501
                "en": 'Providers that refuse customers from Russia (AWS, Hetzner, OVH, Oracle, Azure and others) carry a "Refuses customers from Russia" tag; hosts whose terms ban VPN or proxy use are gone from the catalog',  # noqa: E501
            },
            {
                "ru": "На уже работающей панели новые провайдеры добавятся в каталог сами, а записи, которые в нём уже есть, остаются как были",  # noqa: E501
                "en": "On a running panel the new providers are added to the catalog automatically; entries already in it stay as they are",  # noqa: E501
            },
            {
                "ru": "Живые тарифы теперь у 80 провайдеров вместо 51: GreenCloud, AdminVPS, ITLDC, Rusonyx, SmokyHosts, WORLDBUS, iON Cloud by Krypt, Mynymbox и другие",  # noqa: E501
                "en": "Live plans now come from 80 providers instead of 51: GreenCloud, AdminVPS, ITLDC, Rusonyx, SmokyHosts, WORLDBUS, iON Cloud by Krypt, Mynymbox and more",  # noqa: E501
            },
            {
                "ru": "Если провайдер продаёт в одной линейке тарифы из разных дата-центров (GreenCloud, SmokyHosts, ITLDC), у каждого тарифа указан его город",  # noqa: E501
                "en": "When a provider sells plans from several datacenters in one line (GreenCloud, SmokyHosts, ITLDC), each plan shows its own city",  # noqa: E501
            },
        ],
    },
    {
        "v": "0.12.0",
        "date": "2026-10-08",
        "notes": [
            {
                "ru": "Каталог провайдеров вырос с 7 до 600 с лишним VPS-хостингов в России и по всему миру: у каждого — локации, способы оплаты (карта РФ, СБП, крипта…), страна компании и описание на двух языках",  # noqa: E501
                "en": "The provider catalog grows from 7 to 600+ VPS hosts in Russia and worldwide, each with locations, payment methods (Russian card, SBP, crypto…), company country and a bilingual description",  # noqa: E501
            },
            {
                "ru": "Поиск и фильтры в каталоге: по названию и странам, локациям, способам оплаты, стране компании и наличию живых тарифов; на карточках — флаги локаций и способы оплаты",  # noqa: E501
                "en": "Catalog search and filters: by name and country, locations, payment methods, company country and live plans; cards show location flags and payment methods",  # noqa: E501
            },
            {
                "ru": "Живые тарифы теперь у 51 провайдера вместо 7: Timeweb Cloud, Beget, Hetzner, Vultr, Akamai (Linode), 4VPS, FirstVDS, ProfitServer, EDIS, FlokiNET и другие",  # noqa: E501
                "en": "Live plans now come from 51 providers instead of 7: Timeweb Cloud, Beget, Hetzner, Vultr, Akamai (Linode), 4VPS, FirstVDS, ProfitServer, EDIS, FlokiNET and more",  # noqa: E501
            },
            {
                "ru": "Подбор тарифа: поиск по тарифу, городу и провайдеру, фильтры по vCPU, диску, типу диска, порту и безлимитному трафику, сортировка по цене за 1 ГБ RAM и прогресс загрузки по провайдерам",  # noqa: E501
                "en": "Plan finder: search by plan, city and provider, filters for vCPU, disk, disk type, port speed and unmetered traffic, sorting by price per GB of RAM, and per-provider load progress",  # noqa: E501
            },
            {
                "ru": "В форме сервера провайдера можно найти поиском по всему каталогу",
                "en": "The server form can search the whole catalog for a provider",
            },
            {
                "ru": "Если провайдер не публикует квоту трафика, тариф помечен «трафик не указан», а не «безлимит»",
                "en": 'Plans whose provider doesn\'t publish a traffic quota now say "traffic not specified" instead of "unlimited"',  # noqa: E501
            },
            {
                "ru": "Каталог и тарифы грузятся быстрее и расходуют меньше памяти, ответы каталога сжимаются",
                "en": "The catalog and plans load faster and use less memory, and catalog responses are compressed",
            },
            {
                "ru": "Безопасность: обновлены anyio и cryptography с исправлениями уязвимостей (в т.ч. критической), из образа убран ненужный pip",  # noqa: E501
                "en": "Security: anyio and cryptography updated with vulnerability fixes (including a critical one); the unneeded pip is removed from the image",  # noqa: E501
            },
        ],
    },
    {
        "v": "0.11.0",
        "date": "2026-07-12",
        "notes": [
            {
                "ru": "Иконка сайта (favicon) во вкладке браузера — раньше её не было",
                "en": "Site favicon in the browser tab — previously missing",
            },
            {
                "ru": "Документация дополнена скриншотами всех экранов и обзорным видео продукта",
                "en": "Documentation now includes screenshots of every screen and a product overview video",
            },
        ],
    },
    {
        "v": "0.10.1",
        "date": "2026-07-12",
        "notes": [
            {
                "ru": "Полировка интерфейса: доработаны вёрстка и стили экранов «Система», «Профиль» и «Серверы»",
                "en": "UI polish: refined layout and styling on the System, Profile and Servers screens",
            },
        ],
    },
    {
        "v": "0.10.0",
        "date": "2026-07-12",
        "notes": [
            {
                "ru": "Новые провайдеры UltaHost и 62YUN в каталоге; новые дефолтные провайдеры теперь доезжают до существующих пользователей после обновления, а их правки и удаления сохраняются",  # noqa: E501
                "en": "New providers UltaHost and 62YUN in the catalog; new default providers now reach existing users after an update, while their edits and deletions are kept",  # noqa: E501
            },
            {
                "ru": "Раздел «Финансы» переделан: единая валюта для всех серверов (конвертация по курсу ЦБ), графики трендов расходов и трафика, разбивка «кто использует» с приписанной себестоимостью и калькулятор цены продажи (за ГБ и за устройство в месяц)",  # noqa: E501
                "en": "Reworked Finance section: a single display currency for all servers (CBR conversion), spend and traffic trend charts, a who-uses-it breakdown with imputed cost, and a sale-price calculator (per GB and per device/month)",  # noqa: E501
            },
            {
                "ru": "Мультихоп Xray теперь работает и с Xray XHTTP — и на входе, и на выходе, в любой комбинации с обычным Xray; карточка мультихопа показывается всегда, с подсказкой поставить Xray",  # noqa: E501
                "en": "Xray multi-hop now supports Xray XHTTP too — as entry and as exit, in any combination with plain Xray; the multi-hop card is always shown, with a hint to install Xray",  # noqa: E501
            },
            {
                "ru": "При выдаче одного протокола Amnezia имя конфига содержит протокол (например «Сервер · Xray XHTTP») — конфиги одного сервера больше не путаются",  # noqa: E501
                "en": "When issuing a single Amnezia protocol, the config name now includes the protocol (e.g. Server · Xray XHTTP), so a server's configs are no longer easy to mix up",  # noqa: E501
            },
            {
                "ru": "Надёжная установка Docker на Ubuntu: ставим docker-ce при наличии containerd.io (раньше конфликтующий docker.io молча не устанавливался), с внятной ошибкой при неудаче",  # noqa: E501
                "en": "Reliable Docker install on Ubuntu: docker-ce is used when containerd.io is present (previously the conflicting docker.io failed silently), with a clear error on failure",  # noqa: E501
            },
        ],
    },
    {
        "v": "0.9.0",
        "date": "2026-07-12",
        "notes": [
            {
                "ru": "Полная двуязычность: весь интерфейс и ответы сервера переключаются между русским и английским",
                "en": "Full bilingual support: the entire UI and server responses switch between Russian and English",
            },
            {
                "ru": "Мониторинг: дашборды трафика, ресурсы серверов по SSH (CPU/RAM/диск/аптайм) и честный онлайн по протоколам",  # noqa: E501
                "en": "Monitoring: traffic dashboards, server resources over SSH (CPU/RAM/disk/uptime) and accurate per-protocol online counts",  # noqa: E501
            },
            {
                "ru": "Помесячный мониторинг клиентов и ярусное хранение метрик с ретеншеном и лимитом по диску",
                "en": "Per-client monitoring and tiered metrics storage with retention and a disk-usage cap",
            },
            {
                "ru": "Финансы: учёт стоимости серверов, сводка расходов и подбор тарифов провайдеров с приведением валют к одной по курсу ЦБ",  # noqa: E501
                "en": "Finance: server cost accounting, a spend overview, and a provider tariff finder with single-currency conversion at CBR rates",  # noqa: E501
            },
            {
                "ru": "Лимиты: на устройства, на конфиги по каждому протоколу и на трафик за период — с реальной приостановкой доступа при превышении",  # noqa: E501
                "en": "Limits: on devices, on configs per protocol, and on traffic per period — with a real access cutoff when exceeded",  # noqa: E501
            },
            {
                "ru": "Протоколы: добавлены Hysteria2 и Xray XHTTP, мультихоп-цепочки через Xray, установка и выдача протоколов Amnezia по одному, настройка обфускации/Reality в UI",  # noqa: E501
                "en": "Protocols: added Hysteria2 and Xray XHTTP, multi-hop chains via Xray, per-protocol Amnezia install and single-protocol issuance, and obfuscation/Reality settings in the UI",  # noqa: E501
            },
            {
                "ru": "Обновления из панели во всех режимах развёртывания (compose/scripts/k8s) с подсказками и автоисправлением ошибок установки",  # noqa: E501
                "en": "In-panel updates across all deploy modes (compose/scripts/k8s), with hints and auto-fix for provisioning errors",  # noqa: E501
            },
            {
                "ru": "Аудит-лог действий, обновления в реальном времени (SSE), чеклист онбординга, «Главная» как супер-апп и гид по настройке устройств",  # noqa: E501
                "en": "An action audit log, real-time updates (SSE), an onboarding checklist, a super-app home screen, and a device setup guide",  # noqa: E501
            },
            {
                "ru": "Двуязычный курируемый список изменений в панели и выбор темы: системная, тёмная или светлая",
                "en": "A curated bilingual changelog in the panel and a theme selector: system, dark, or light",
            },
            {
                "ru": "Администрирование: раздел «Система» с методом развёртывания и использованием диска, а также резервные копии",  # noqa: E501
                "en": "Administration: a System section showing the deployment method and disk usage, plus backups",
            },
            {
                "ru": "Инфраструктура: тестирование миграций, arm64-образ, упрочнение безопасности (сессии, rate-limit, CSRF/CSP, шифрование секретов мастер-ключом) и переход фронтенда на TypeScript 6 и Vite 8",  # noqa: E501
                "en": "Infrastructure: migration testing, an arm64 image, security hardening (sessions, rate limiting, CSRF/CSP, master-key secret encryption), and moving the frontend to TypeScript 6 and Vite 8",  # noqa: E501
            },
        ],
    },
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
