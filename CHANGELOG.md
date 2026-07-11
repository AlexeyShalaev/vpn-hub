# Changelog

All notable changes to this project are documented here.

Generated from `backend/src/vpnhub/infra/changelog.py` via `make changelog` — do not edit by hand.
Release notes are hand-written and bilingual (RU/EN); the panel shows them in the selected language.

## [0.9.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.8.0...v0.9.0) (2026-07-11)


### Features

* **access:** ручная пауза/старт конфигов (страница сервера + мониторинг) ([42ae1c6](https://github.com/AlexeyShalaev/vpn-hub/commit/42ae1c6816716efc76737e36b9b657d4162c0be4))
* **admin:** show deployment method and disk usage in the System screen ([a389d93](https://github.com/AlexeyShalaev/vpn-hub/commit/a389d93ce207d5055a324c2068c9f6128f27666e))
* **amnezia:** Настройка обфускации AmneziaWG из UI ([b8b2c0f](https://github.com/AlexeyShalaev/vpn-hub/commit/b8b2c0ff7e6eb1d8a071aac5684650b79dda35fc))
* **audit:** Аудит-лог и страница «События» ([0cdea00](https://github.com/AlexeyShalaev/vpn-hub/commit/0cdea0020264a571b42145baff901f3752a0cf41))
* **catalog:** merge equivalent locations and prefill the picked tariff ([fbb22f5](https://github.com/AlexeyShalaev/vpn-hub/commit/fbb22f5637ac5eb49f88652cb0a6b8a48e1d427e))
* **catalog:** tariff finder with searchable filters and single-currency monthly pricing ([6191a72](https://github.com/AlexeyShalaev/vpn-hub/commit/6191a729262da07dacf152a5220555811bfbe225))
* **changelog:** hand-written bilingual release notes, served by the panel ([e2987a3](https://github.com/AlexeyShalaev/vpn-hub/commit/e2987a3a39c974217a0a384dc76fa7950a5306bc))
* **configs:** issue a single Amnezia protocol, not only the bundle ([37bdd13](https://github.com/AlexeyShalaev/vpn-hub/commit/37bdd13ba82e5531a5d8a42f79680e3e168e0074))
* **devices:** страница настройки устройства с инструкциями ([470e54e](https://github.com/AlexeyShalaev/vpn-hub/commit/470e54e850fb529fff61068eca666ab33a6a0828))
* **finance:** add financial analytics overview ([3295e93](https://github.com/AlexeyShalaev/vpn-hub/commit/3295e93a53ba59abe95f90eb6c0d45ac59e340d9))
* **finance:** учёт стоимости серверов (история цен, accrual-расход, отчёт) ([6d80311](https://github.com/AlexeyShalaev/vpn-hub/commit/6d803115600dcb5ff63dc820bdac215b3d186544))
* **frontend:** apply parsed FirstByte tariff ([37fd658](https://github.com/AlexeyShalaev/vpn-hub/commit/37fd65831f6ab945dc8ccc10d9f17c2b3087cb8f))
* **frontend:** choose traffic limit units ([71243c8](https://github.com/AlexeyShalaev/vpn-hub/commit/71243c826552cd995179e04093906b74ed17535a))
* **frontend:** edit server cost and traffic quota in form ([c2818cf](https://github.com/AlexeyShalaev/vpn-hub/commit/c2818cf72122ef3a1676c5f29590c6c7e66c2461))
* **frontend:** explicit bulk-pause labels by scope ([0eac6b1](https://github.com/AlexeyShalaev/vpn-hub/commit/0eac6b16f8dd9e058b093b3ee7d37278e0307fee))
* **frontend:** group server clients by device with bulk pause/resume ([f03c8eb](https://github.com/AlexeyShalaev/vpn-hub/commit/f03c8eb54cb2b73d76bf768eaed7bbc1dfd7820d))
* **frontend:** group server details into tabs ([9c2c1b6](https://github.com/AlexeyShalaev/vpn-hub/commit/9c2c1b67b2b8900457e9a548f97bdcd61ecdf007))
* **frontend:** make server page tabs addressable via URL ([69ad6b4](https://github.com/AlexeyShalaev/vpn-hub/commit/69ad6b471fe05816db95fa4d9d7b84c2eb09313b))
* **frontend:** redesign catalog cards + cross-provider plan finder ([e40b0b2](https://github.com/AlexeyShalaev/vpn-hub/commit/e40b0b2d488b15c98fc6ec8335bed96183b6230d))
* **frontend:** view provider plans from the catalog ([41456c7](https://github.com/AlexeyShalaev/vpn-hub/commit/41456c784c34f8813241a68c9598056c8c6c5251))
* **home:** главная-сводка для владельца ([6e6d406](https://github.com/AlexeyShalaev/vpn-hub/commit/6e6d406a95dc0f687720ff68f5373c8666c23411))
* **i18n:** full RU/EN coverage across the frontend ([7dd1779](https://github.com/AlexeyShalaev/vpn-hub/commit/7dd177917951e613de9e6478298408786d87ef0d))
* **i18n:** localize all backend responses by request language ([59eb931](https://github.com/AlexeyShalaev/vpn-hub/commit/59eb931a2e81509ded114bce42837afc5301bf96))
* **i18n:** server-side i18n engine + key-based DomainError + Accept-Language plumbing ([b6d1e0a](https://github.com/AlexeyShalaev/vpn-hub/commit/b6d1e0a8b16bda728fef1a9de6adf7477b59f937))
* **i18n:** инфраструктура локализации + английский (каркас, профиль) ([518dd11](https://github.com/AlexeyShalaev/vpn-hub/commit/518dd11973034b093687cda9ca0dd1758130ba01))
* **limits:** member-facing «мой трафик за период» (GET /me/usage) ([b5e0d88](https://github.com/AlexeyShalaev/vpn-hub/commit/b5e0d88e617f3b81deb40c4d7ed9fc7793aa5993))
* **limits:** байт-лимиты — учёт трафика, квота сервера, пер-user лимиты ([8f9b756](https://github.com/AlexeyShalaev/vpn-hub/commit/8f9b756b00d90891c25b7568cc91a8ab7434c23f))
* **limits:** лимит числа устройств на пользователя с иерархией override ([da0dd10](https://github.com/AlexeyShalaev/vpn-hub/commit/da0dd103d15f91453d9ca8a4845243e433bc880c))
* **limits:** настраиваемый лимит числа конфигов на протоколе сервера ([6201c2a](https://github.com/AlexeyShalaev/vpn-hub/commit/6201c2a30a2381b268da4bb94382498077cdc165))
* **limits:** честная отсечка по трафику — механизм suspend/resume + реконсиляция ([813f9b0](https://github.com/AlexeyShalaev/vpn-hub/commit/813f9b0fcefe2674ea072061b2d96bbebeb7f43a))
* **metrics:** auto-cap metrics size at a share of disk when no explicit cap ([6829c34](https://github.com/AlexeyShalaev/vpn-hub/commit/6829c34aac57c51ec37319c96452b7980fcd9d25))
* **metrics:** UI-configurable metrics retention by time and disk size ([c8bf781](https://github.com/AlexeyShalaev/vpn-hub/commit/c8bf781b8332cf2bcab11fb5ac1ad9a865013505))
* **monitoring:** collect traffic in monitor tick with health status ([b59f8ed](https://github.com/AlexeyShalaev/vpn-hub/commit/b59f8edd618f0dde0710544d0394dc893fad76a8))
* **monitoring:** complete monitoring on dashboard access ([5fa5c9b](https://github.com/AlexeyShalaev/vpn-hub/commit/5fa5c9bd55c05db3b57c8ad4632cf7816f6e3866))
* **monitoring:** long periods (30d/90d/365d) with tiered reads ([585757c](https://github.com/AlexeyShalaev/vpn-hub/commit/585757cf9bc2e4150f3535495b6e8f5bca603737))
* **monitoring:** tiered host-metrics storage with rollup ([d57c1c3](https://github.com/AlexeyShalaev/vpn-hub/commit/d57c1c383852832d3dea814442afa72bb52b8e6a))
* **monitoring:** Админ-дашборды внутри панели (без Grafana) ([9d30300](https://github.com/AlexeyShalaev/vpn-hub/commit/9d30300607a90cae81e02bf18d3c0b853782bf9c))
* **monitoring:** график трафика клиента по клику на странице сервера ([9b22512](https://github.com/AlexeyShalaev/vpn-hub/commit/9b225122dbb5b0dbe40cc4a5610e28c1282fcf30))
* **monitoring:** имена external-клиентов из Amnezia clientsTable ([6450eb4](https://github.com/AlexeyShalaev/vpn-hub/commit/6450eb437e66be121a8f4f71a3186d91a903d499))
* **monitoring:** мониторинг ресурсов сервера (CPU/RAM/диск/соединения) ([346a151](https://github.com/AlexeyShalaev/vpn-hub/commit/346a151ddcc00182f755d4d6ae0fba749e415a26))
* **monitoring:** мультивыбор серверов/протоколов + фильтр по пользователям ([cebfe0f](https://github.com/AlexeyShalaev/vpn-hub/commit/cebfe0fa2a6410a208c4b97eb1fe886c23371169))
* **monitoring:** сбор трафика OpenVPN/Outline + графики трафика клиента ([7d701d5](https://github.com/AlexeyShalaev/vpn-hub/commit/7d701d553d4b0c8f6975b777980fc457e791c3bd))
* **monitoring:** супер-мониторинг клиентов — трафик и онлайн по всем протоколам ([cbaf0fe](https://github.com/AlexeyShalaev/vpn-hub/commit/cbaf0fe2e1587016024e09d3ae991bcee2bd30e6))
* **monitoring:** фильтры-мультивыбор через выпадашки с поиском ([dcdadda](https://github.com/AlexeyShalaev/vpn-hub/commit/dcdadda800902e26bceda7ae669aba0b68d34500))
* **monitoring:** честный онлайн-счётчик клиентов по всем протоколам ([9691b39](https://github.com/AlexeyShalaev/vpn-hub/commit/9691b395ed82e9d0b86289645ccff475e13573b0))
* **multihop:** цепочки серверов entry → exit ([00c3d3a](https://github.com/AlexeyShalaev/vpn-hub/commit/00c3d3af403e4203b2ffad51032eacfb2f3ec661))
* **onboarding:** чеклист первого запуска для владельца ([66f5cc9](https://github.com/AlexeyShalaev/vpn-hub/commit/66f5cc97d43ec1441095c55cc10f2e53613dcc3c))
* **providers:** cache dynamic plans with cashews ([9b994a2](https://github.com/AlexeyShalaev/vpn-hub/commit/9b994a2c3a686c941786b5974c3fbc5d07476592))
* **providers:** cache provider plans in memory ([22067be](https://github.com/AlexeyShalaev/vpn-hub/commit/22067beb7bbf80229a5501209692497de436790f))
* **providers:** parse AHost plans ([656bde2](https://github.com/AlexeyShalaev/vpn-hub/commit/656bde2d9f76cd651894c0894bc3c56d63081830))
* **providers:** parse ISHOSTING plans ([f5a34a1](https://github.com/AlexeyShalaev/vpn-hub/commit/f5a34a1badec0a5c105b4e69fed215766c1f08f8))
* **providers:** parse Serverspace plans ([f79917f](https://github.com/AlexeyShalaev/vpn-hub/commit/f79917fc08e06ad29014be7c0fcd99b76e590355))
* **providers:** parse UFO Hosting plans ([6b710ec](https://github.com/AlexeyShalaev/vpn-hub/commit/6b710ecea034ed5c425012f2f51e3d5ee4bfd619))
* **providers:** динамический парсинг тарифов FirstByte ([34c06ee](https://github.com/AlexeyShalaev/vpn-hub/commit/34c06ee9f7af468c9d703cda0d4bebf6da3c0dcd))
* **providers:** каталог тарифов FirstByte + выбор плана при создании сервера ([d074592](https://github.com/AlexeyShalaev/vpn-hub/commit/d0745924d9840a1be216e18886502c1b95ec4d0a))
* **provisioning:** enable exact stats by default with auto-heal ([cf8204c](https://github.com/AlexeyShalaev/vpn-hub/commit/cf8204c7b091c85f284b569ec8682250f9a00acf))
* **realtime:** SSE вместо поллинга ([7ac076e](https://github.com/AlexeyShalaev/vpn-hub/commit/7ac076ed0274299381fe908a7d55c7ce85b096a7))
* **servers:** store provider metadata from form ([798c89c](https://github.com/AlexeyShalaev/vpn-hub/commit/798c89c6bb7b43bf0673e323a9085fd83259a35c))
* **servers:** миграция сервера на новый VPS ([2d229b9](https://github.com/AlexeyShalaev/vpn-hub/commit/2d229b90676f1e8b48a31151bc502d5109636c12))
* **servers:** обновление серверных компонентов ([898a1f4](https://github.com/AlexeyShalaev/vpn-hub/commit/898a1f4aa21fdc78542ea5163f50dac2595455b2))
* **sync:** ensure monitoring is completed for adopted protocols ([c10cf58](https://github.com/AlexeyShalaev/vpn-hub/commit/c10cf582fc1415a95e2d35dccb47048cfeccd0fd))
* **traffic:** tiered rollup storage (hourly/daily) with retention ([8c8e2dc](https://github.com/AlexeyShalaev/vpn-hub/commit/8c8e2dcbe304fc84fd71a98dc1384f6aa2438289))
* **traffic:** track peer counter state for O(1) deltas ([8404d74](https://github.com/AlexeyShalaev/vpn-hub/commit/8404d744ff63eed4cd1b4f71ae049259f3e071bb))
* **traffic:** дашборд трафика и подключений (owner) ([d929906](https://github.com/AlexeyShalaev/vpn-hub/commit/d92990640b9aecf00c24e8a6b765972b17e5c1c5))
* **ui:** superapp home launcher, slim bottom nav, responsive period pickers ([32d8e86](https://github.com/AlexeyShalaev/vpn-hub/commit/32d8e8649e7e17cf84daa7c497da72bd8f924a63))
* **ui:** three-way theme selector — system / dark / light ([c481e38](https://github.com/AlexeyShalaev/vpn-hub/commit/c481e38edc53636ef9a12b6622dec5e4142199f0))
* **ux:** пакет UX-улучшений (тема по системе, error boundary, skeleton, шаринг инвайта) ([3ed57d3](https://github.com/AlexeyShalaev/vpn-hub/commit/3ed57d3eef14485fad24495c4aa4835ce27b010d))
* **xray:** управление Reality (shortId, SNI/dest) ([cf238d8](https://github.com/AlexeyShalaev/vpn-hub/commit/cf238d87a70b29df3418756f6fc0e4185f5f6b13))
* роадмап — 14 фич (протоколы, мониторинг, i18n, UX) ([5b873a6](https://github.com/AlexeyShalaev/vpn-hub/commit/5b873a68c95b8f71a1aae2a15aa0b0afb343751f))


### Bug Fixes

* **backend:** register finance service in DI ([9e1a261](https://github.com/AlexeyShalaev/vpn-hub/commit/9e1a261a7b8d1c7b2fcda2c0d5876c81d4aa902e))
* **docs:** use root changelog in Makefile ([5389ea7](https://github.com/AlexeyShalaev/vpn-hub/commit/5389ea7877c20bf91f6bea69f451469119aa622f))
* **finance:** валидация цены — не-конечная (NaN/Inf) и огромная → 400, не 500 ([29f6d49](https://github.com/AlexeyShalaev/vpn-hub/commit/29f6d49f552ed443d9aa194f82d00c9a869ae473))
* **frontend:** clarify network traffic quota labels ([4d39037](https://github.com/AlexeyShalaev/vpn-hub/commit/4d39037f44b0502a005cdff5373c048404195aa6))
* **frontend:** clear auth cache on logout ([2ac6378](https://github.com/AlexeyShalaev/vpn-hub/commit/2ac6378498bf6409109180bb21a3043d9d4d3109))
* **frontend:** disable billing day for non-monthly prices ([f88476a](https://github.com/AlexeyShalaev/vpn-hub/commit/f88476a52c47010c90e5ae849cdd325ed1e9d3da))
* **frontend:** even catalog action button heights ([981a05b](https://github.com/AlexeyShalaev/vpn-hub/commit/981a05b81454edfe7b38aa758e8d846aad027497))
* **frontend:** grey out disabled inputs ([ee682ec](https://github.com/AlexeyShalaev/vpn-hub/commit/ee682ec0bb45c6c272a8c09cac66246402c7dbec))
* **frontend:** ignore self group member in onboarding ([10bf076](https://github.com/AlexeyShalaev/vpn-hub/commit/10bf0767dc6d6660452898180a82585307bd33bb))
* **frontend:** plan finder filters layout (clipped text) ([ec76ba3](https://github.com/AlexeyShalaev/vpn-hub/commit/ec76ba33a548b8e6ba4db7c35ef195d7b3b57eae))
* **frontend:** resolve dynamic provider plan catalogs ([cfd3377](https://github.com/AlexeyShalaev/vpn-hub/commit/cfd33772f5c3980615c68031d2f6a7d1a31469e4))
* **frontend:** show pending FirstByte tariff autofill ([49cdae2](https://github.com/AlexeyShalaev/vpn-hub/commit/49cdae234a155c208932a119b353493a9ce76457))
* **limits:** критичные баги отсечки из ревью 3b (suspended-статус, awg netns, сироты) ([825b469](https://github.com/AlexeyShalaev/vpn-hub/commit/825b46943e27491c8bd8042e07cdafd40affeaf9))
* **monitoring:** кнопка обновления + различать сбой запроса и «нет данных» ([e2ea104](https://github.com/AlexeyShalaev/vpn-hub/commit/e2ea1044ad3f571d0eaaf1b805286d072d5085c4))
* **monitoring:** экранировать $2 в чтении секрета hysteria trafficStats ([f61f135](https://github.com/AlexeyShalaev/vpn-hub/commit/f61f135d259e3511b0b634fd7dcede49a89f21d7))
* **nav:** иконка у пункта «Настройка» в режиме участника ([0366663](https://github.com/AlexeyShalaev/vpn-hub/commit/03666634d1e39507c731ce08dca5c7343e58c66d))
* **providers:** include all Serverspace locations ([8de73fc](https://github.com/AlexeyShalaev/vpn-hub/commit/8de73fcc2cedb1a976822638ecb9eaa392a39ca0))
* **release:** release-please root changelog without ".." path ([#38](https://github.com/AlexeyShalaev/vpn-hub/issues/38)) ([db2f73c](https://github.com/AlexeyShalaev/vpn-hub/commit/db2f73c9aa932ea7ccc5947bd39a6b7849778e5d))
* **traffic:** BIGINT для счётчиков трафика (int32 переполнялся) ([ee21c5e](https://github.com/AlexeyShalaev/vpn-hub/commit/ee21c5e0f9844f5b99eb5a363987cc24e9ce8586))
* **ui:** tidy the theme selector layout ([9f34061](https://github.com/AlexeyShalaev/vpn-hub/commit/9f340610c459e851f11288e1446b6fbb020cc684))


### Performance Improvements

* **metrics:** bound daily retention, index traffic_samples by (server_id, at), chunked retention deletes ([0f7205b](https://github.com/AlexeyShalaev/vpn-hub/commit/0f7205b068240350633633436c976d123ab3f866))

## [0.8.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.7.0...v0.8.0) - 2026-07-05

- A device's issued configs are grouped by server
- Fixed: server names no longer show %5B/%5D in share links

## [0.7.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.6.0...v0.7.0) - 2026-07-05

- The Kubernetes update button appears only when patch permission is granted (RBAC pre-check)
- Xray XHTTP configs are tagged "XHTTP" in the server name

## [0.6.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.5.0...v0.6.0) - 2026-07-05

- Bundlable Amnezia protocols are issued as a single choice
- Fixed: the bundle no longer leads when Xray XHTTP is chosen
- Fixed: each issued config stays on one line
- Official Android, Linux and Windows platform icons

## [0.5.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.4.0...v0.5.0) - 2026-07-05

- Apply updates from the panel across all deploy modes
- A distinct icon per device platform
- Official vendor logos on VPN software cards
- Fixed: the pool badge no longer overlaps the server name on mobile
- Server protocol management redesigned into a clean vertical card
- Fixed: the Hysteria2 accent dot in protocol cards

## [0.4.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.3.0...v0.4.0) - 2026-07-04

- Members can revoke their own issued configs
- A server's Amnezia protocols bundle into one vpn://
- Install Amnezia protocols individually, with add/remove
- Start/stop individual Amnezia protocols
- Fixed: require an explicit device and protocol before issuing a config

## [0.3.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.2.0...v0.3.0) - 2026-07-04

- Check official GitHub Releases for updates by default (zero-config)

## [0.2.0](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.1.1...v0.2.0) - 2026-07-04

- Added the Hysteria2 and Xray XHTTP protocols
- Auto-fix for failed VPN installs
- Required location with a picker, plus auto-named servers

## [0.1.1](https://github.com/AlexeyShalaev/vpn-hub/compare/v0.1.0...v0.1.1) - 2026-07-04

- Fixed external Postgres behind PgBouncer: transaction-mode migrations and DSN credential encoding

## 0.1.0 - 2026-07-03

- Initial public release
- Fixed the Kubernetes crashloop from an injected VPNHUB_PORT; hardened install-smoke stdin
