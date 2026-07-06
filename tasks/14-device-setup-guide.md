# Задача №14 — Страница «Настрой устройство»

Пошаговые справочные инструкции для участника (member): по каждой платформе — какое
приложение поставить (ссылка в стор/на сайт), как импортировать конфиг, плюс deep-link
«Открыть в приложении» в модалке выдачи конфига по формату выданного конфига.

## Что сделано

### Данные как структура — `frontend/src/lib/deviceGuide.ts`
Инструкции хранятся ДАННЫМИ (а не разбросанным JSX), чтобы упростить i18n и поддержку.

- `GuidePlatform` = `ios | android | windows | mac | linux | router`; `GUIDE_PLATFORMS` — порядок вывода.
- `PlatformGuide`: `platform`, `labelKey` (i18n), `app` (рекомендованное приложение),
  `stepKeys` (массив i18n-ключей шагов по порядку).
- `GuideApp`: `name` (бренд, не переводится), `storeKey` (i18n: App Store / Google Play /
  Официальный сайт), `url` (реальная официальная ссылка).
- `PLATFORM_GUIDES` — по всем 6 платформам. Универсальные клиенты (vless/hy2):
  Streisand на Apple, Hiddify на Android/desktop; роутер — AmneziaWG/WireGuard + инструкция OpenWrt.
- `AMNEZIA_APP`, `OUTLINE_APP` — вендорные приложения по формату (vpn:// и ss://).
- `deepLinkFor(config, vpn): DeepLink | null` — определяет deep-link «Открыть в приложении»
  по СХЕМЕ строки конфига:
  - `vpn://` → AmneziaVPN
  - `vless://` → Hiddify (универсальный)
  - `hy2://` / `hysteria2://` → Hiddify
  - `ss://` → Outline
  - прочее (.ovpn/.conf) → `null` (только импорт файлом).
  Сам URI и есть deep-link — ОС передаёт схему зарегистрированному приложению.

Реальные официальные ссылки: Streisand (App Store), Hiddify (Google Play + hiddify.com),
AmneziaVPN (amnezia.org/downloads), Outline (getoutline.org), инструкция роутера (docs.amnezia.org).

### Экран — `frontend/src/screens/Setup.tsx`
`SetupScreen`: выбор платформы (чипы с иконками) → карточка с рекомендованным приложением
(ссылка «Открыть в сторе») и нумерованными шагами. Ниже — карточка «Приложения по формату
конфига» (Amnezia / Outline). Все тексты через `t()` (`setup.*`).

### Навигация
- `frontend/src/nav.ts`: экран `setup`, путь `/setup` (screenToPath + pathToState).
- `frontend/src/app/App.tsx`: импорт `SetupScreen as DeviceSetupScreen` (во избежание
  коллизии с локальным `SetupScreen` первичной настройки админа), `NAV_META.setup`,
  добавлен в `memberItems` (рядом с «Устройства»), в `renderScreen`.

### Deep-link в модалке выдачи — `frontend/src/screens/Available.tsx`
В `GetConfigModal` (шаг «готовый конфиг») добавлена кнопка «Открыть в приложении · <app>»,
когда `deepLinkFor(selected.text, target.vpn)` вернул ссылку. Ссылка = сам URI конфига.

### i18n — `frontend/src/lib/i18n.ts`
Группа ключей `setup.*` + `nav.setup` добавлена в `ru` и `en` СИНХРОННО (иначе tsc падает
на `satisfies Dict`): заголовки, платформы, источники, шаги, `setup.openInApp`.

## Зелёное
- `make front-lint` (`npx tsc --noEmit`) — OK
- `cd frontend && npm run build` — OK (осталось только пред-существующее предупреждение о размере чанка)

## Осталось (remaining)
- Видеогайды / скриншоты по шагам — не входило в минимальный скоуп.
- Deep-link для Windows/Linux desktop может не сработать, если схема не зарегистрирована в ОС —
  тогда работает импорт файлом/буфером (описано в шагах).
- Тесты компонентов React намеренно отложены (как и по остальным экранам панели).
- Можно связать шаг «Настрой устройство» из пустого состояния Devices/Available (кросс-ссылка) — опционально.
