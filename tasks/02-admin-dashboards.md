## 2. Админ-дашборды внутри панели (без Grafana)
**Категория** Observability / Admin · **Сложность** L · **Зависимости** нет (prometheus-client уже в зависимостях; таблица по образцу traffic_samples; таб на существующем экране System)

### Зачем
Админу нужно видеть системное здоровье самого инстанса панели прямо в UI, без разворачивания Grafana/Prometheus рядом (self-hosted, один Docker-образ + PG). Речь именно о здоровье инстанса для роли admin: нагрузка HTTP-API, что фоновые планировщики реально тикают, сколько серверов online/offline и их latency, копятся ли ошибки provisioning, сколько длится sync. Это НЕ задача №1 (VPN-трафик клиентов для owner — та живёт в `traffic_samples` и owner-эндпоинте `GET /api/v1/servers/{sid}/traffic`).

### Что уже есть в коде (конкретные проверенные пути и механизмы)
- `/metrics` эндпоинт: `backend/src/vpnhub/api/routers/health.py` — `metrics()` вызывает `generate_latest()` из `prometheus_client`, авторизация токеном через чистую функцию `metrics_authorized(configured, header, query_token)` (`settings.metrics_token`, config.py:113). **ВАЖНО: в коде НЕТ ни одного `Counter/Histogram/Gauge` и нет FastAPI-инструментации** — `grep` по `Counter(|Histogram(|Gauge(|Instrumentator|make_asgi_app|REGISTRY` в `src/` даёт только импорт `generate_latest`. То есть сейчас `/metrics` отдаёт лишь дефолтные process/python-GC коллекторы. Прикладные метрики придётся создать с нуля.
- Планировщики: `backend/src/vpnhub/api/entrypoint.py`, `lifespan()` — `AsyncIOScheduler` с job'ами `backup-tick` (BackupService.run_tick, 1h), `audit-retention`, `traffic-retention`, `server-monitor` (`ServerService.run_tick`, `settings.monitor_interval=120`), `server-sync` (`SyncService.run_tick`, `settings.sync_interval=300`). Одна реплика, без лидер-элекшена (по ограничениям задачи).
- HTTP middleware уже есть: `entrypoint.py:184` `@app.middleware("http")` `_security_headers` — точка, куда встроить измерение длительности/кода ответа (или добавить отдельный middleware рядом).
- Мониторинг серверов: `services/servers.py` `run_tick(self) -> int` (возвращает число проверенных), проставляет `Server.status` (`online|offline|unknown`) и `Server.latency_ms` (models.py:64–66). Модель `Server` — `infra/db/orm/models.py:52`.
- Provisioning-ошибки: `ServerProtocol.state` (`absent|installing|installed|error`) и `ServerProtocol.error_code` (models.py:102,106) — готовый источник для метрики ошибок по коду.
- Sync: `services/sync.py` `SyncService.run_tick`; дренаж отзыва через `ServerProtocol.pending_revoke_json` (models.py:112).
- Прецедент таблицы сэмплов: `TrafficSample` (`models.py:199`, `__tablename__="traffic_samples"`, поля `at: Mapped[float]` epoch, индексы) + миграция `backend/migrations/versions/20260705_0014-c3d4e5f6a7b8_add_traffic_samples.py` (head; `down_revision="b2c3d4e5f6a7"`) + ретеншн-джоба `TrafficService.purge_old` с `settings.traffic_retention_days`. Это точный образец для `metric_samples`.
- Admin API: `api/routers/admin.py` (`prefix="/api/v1/admin"`, все ручки под `Depends(require_admin)` из `api/deps.py:81`), сервис `services/admin.py` (`AdminService.system()` уже возвращает версию/uptime/PG-версию). DI: `infra/di/__init__.py` — сервисы регистрируются через `provide(...)` (там уже `admin = provide(AdminService)`, `traffic = provide(TrafficService)`).
- Фронт: экран `frontend/src/screens/System.tsx` (`SystemScreen`, использует `q.adminSystem` через TanStack Query, есть `SectionLabel`), маршрут `system` в `frontend/src/nav.ts` (case "system" → "/system"). API-слой `frontend/src/lib/queries.ts` (`adminSystem`, `adminSystemUrl` и пр.). UI-кит `frontend/src/components/ui.tsx` уже содержит инлайновый SVG (иконки `<rect>/<path>/viewBox`) — свой график вписывается в стиль без новых зависимостей. Готового компонента графика (Sparkline/Chart) НЕТ — создаём.
- Тесты: `backend/tests/integration/conftest.py` строит схему `BaseTable.metadata.create_all` на in-memory SQLite (StaticPool, shim для `timezone()`), fixture `uow`/`session_maker`/`engine`. Новый ORM-класс попадёт в схему автоматически, конфтест править не нужно. Прецеденты тестов сервисов: `backend/tests/integration/services/test_admin.py`.

### Дизайн решения (модели/миграции, API, UI, фоновые задачи; развилки)
**Развилка 1 — хранение: скрейпить свой /metrics в PG-сэмплы (фоновый tick) vs считать агрегаты напрямую.** Выбираем **PG-сэмплы**. Обоснование: prometheus-client держит счётчики только в памяти процесса → после рестарта контейнера истории нет, а график по времени требует ряда точек. Считать «напрямую из БД» можно лишь для того, что и так лежит в БД (статусы серверов, ошибки protocol) — но HTTP-нагрузка и тики планировщиков нигде не персистятся. Поэтому единый механизм: фоновая джоба `metrics-tick` раз в интервал снимает текущие значения выбранных счётчиков/гейджей из реестра prometheus-client и дописывает строки в `metric_samples`. Это переиспользует уже работающую in-process инструментацию (тот же реестр, что отдаёт `/metrics`), не заводит второй источник правды и переживает рестарты.

**Развилка 2 — какие метрики.** Инструментируем только реально существующие точки (не выдумываем):
- `vpnhub_http_requests_total{method,path_group,status}` (Counter) и `vpnhub_http_request_seconds` (Histogram) — в HTTP-middleware (`entrypoint.py`). `path_group` — нормализованный шаблон (без id), чтобы не плодить кардинальность.
- `vpnhub_scheduler_tick_total{job}` (Counter) + `vpnhub_scheduler_tick_seconds{job}` (Histogram) + `vpnhub_scheduler_tick_errors_total{job}` — обёртка вокруг job-функций (`run_tick`/`run_tick`/`run_tick`), либо APScheduler listener на `EVENT_JOB_EXECUTED/EVENT_JOB_ERROR`.
- `vpnhub_servers{status}` (Gauge: online/offline/unknown) и `vpnhub_server_latency_ms` (Gauge/Histogram) — из `Server.status/latency_ms`, обновляются в конце `ServerService.run_tick`.
- `vpnhub_provisioning_errors{error_code}` (Gauge) — счёт `ServerProtocol` с `state="error"` по `error_code`.
- `vpnhub_sync_seconds` (Histogram) — длительность `SyncService.run_tick`.

**Модель/миграция.** Новый ORM-класс `MetricSample` (`models.py`, `__tablename__="metric_samples"`) по образцу `TrafficSample`: `id: String(32) pk default _id`, `name: String(64) index` (имя метрики), `labels: String(160) default ""` (сериализованный ключ лейблов, напр. `status=online`), `at: float index` (epoch), `value: float`. Индекс `Index("metric_samples_scope_idx", "name", "at")`. Миграция `backend/migrations/versions/20260705_0015-<hash>_add_metric_samples.py`, `down_revision="c3d4e5f6a7b8"` (текущий head). Ретеншн — новая джоба или расширить существующий паттерн `purge_old` (новый `settings.metrics_retention_days`, дефолт как traffic — 30).

**API.** Новый роутер-хендлер в `api/routers/admin.py`: `GET /api/v1/admin/metrics?period=24h` под `require_admin` → метод нового сервиса `MetricsService.overview(period)` (регистрируется в DI как остальные, `provide(MetricsService)`). Возвращает JSON: серии {name, points:[{at,value}], labels} по whitelisted-периодам (`1h|24h|7d` — тот же словарь, что `_PERIODS` в traffic.py). Плюс «сводка сейчас» (последние значения гейджей). Инструментальный модуль — `infra/metrics.py` (определения метрик + helper'ы `observe_http/observe_tick`, чтобы всё было в одном месте и импортировалось и middleware, и джобой скрейпа).

**Фоновые задачи.** Добавить в `lifespan()` job `metrics-tick` (`interval`, напр. `settings.metrics_interval=60`, `max_instances=1, coalesce=True`) → `MetricsService.scrape_tick()`: читает текущие значения из реестра и/или из БД (серверы/ошибки) и пишет в `metric_samples`. Джоба сама инструментируется как `scheduler_tick`.

**UI.** На `System.tsx` — новый таб/секция «Мониторинг» (или отдельный подзаголовок через `SectionLabel`). Свой компонент `<LineChart>` в `components/ui.tsx` (или новый `components/chart.tsx`): чистый SVG (`<polyline>` по нормализованным точкам, оси/подписи `<text>`, `viewBox`, `preserveAspectRatio`) — без recharts/chart.js. Данные — новый query `adminMetrics(period)` в `queries.ts`, поллинг `refetchInterval` (как остальные экраны). Русские строки захардкожены в JSX (i18n нет). Селектор периода 1h/24h/7d.

### Минимальный первый коммит (MVP) — узкий вертикальный срез
Один зелёный коммит: (1) модуль `infra/metrics.py` с реестром и HTTP-инструментацией в middleware `entrypoint.py`; обёртка тиков планировщиков (`scheduler_tick_total/seconds`); (2) миграция + модель `MetricSample`; (3) джоба `metrics-tick`, пишущая хотя бы две серии — HTTP RPS (из счётчика) и число серверов по статусу (из БД); (4) `MetricsService.overview/scrape_tick` + `GET /api/v1/admin/metrics`; (5) фронт: секция «Мониторинг» на System.tsx с одним SVG-графиком серверов online/offline и мини-панелью HTTP-нагрузки; (6) тесты сервиса и роутера. Provisioning-ошибки и sync-длительность можно добить следующим коммитом, но точки инструментации закладываем сразу.

### План реализации
- [ ] Миграция `20260705_0015-<hash>_add_metric_samples.py` (`down_revision="c3d4e5f6a7b8"`): создать `metric_samples` + индекс, `downgrade` — drop.
- [ ] Модель `MetricSample` в `infra/db/orm/models.py` (поля/индекс по образцу `TrafficSample`).
- [ ] `infra/metrics.py`: определения `Counter/Histogram/Gauge`, helper'ы `observe_http()`, `record_scheduler_tick(job, seconds, error)`, `set_server_gauges(counts, latency)`, `set_provisioning_errors(by_code)`; `path_group()` для нормализации пути.
- [ ] `entrypoint.py`: HTTP-middleware измеряет длительность и код ответа; обернуть job-функции планировщика (или добавить APScheduler listener) для tick-метрик; зарегистрировать job `metrics-tick`; добавить `settings.metrics_interval` и `settings.metrics_retention_days` в `api/config.py`.
- [ ] `ServerService.run_tick`: в конце обновлять server-гейджи; посчитать provisioning-ошибки по `error_code`.
- [ ] `services/metrics.py` `MetricsService` (`overview(period)`, `scrape_tick()`, `purge_old()`); зарегистрировать в `infra/di/__init__.py` (`metrics = provide(MetricsService)`).
- [ ] `api/routers/admin.py`: `GET /system/metrics` (или `/metrics`) под `require_admin`, ретеншн-джоба в lifespan.
- [ ] Фронт: `queries.ts` — `adminMetrics(period)` + тип; `components/chart.tsx` (SVG LineChart); секция «Мониторинг» в `screens/System.tsx` с поллингом.
- [ ] Тесты backend (integration) + фронт `tsc --noEmit`.
- [ ] Docs: краткая заметка в docs (что за метрики, где смотреть, чем отличается от owner-трафика).

### Как тестировать (in-memory SQLite, без внешней инфры)
- Unit: `path_group()` нормализация (`/api/v1/servers/abc123/traffic` → `/api/v1/servers/{sid}/traffic`); формирование серий `overview` из подготовленных `MetricSample` (фильтр по `period`, сортировка по `at`).
- Integration (fixture `uow` из `tests/integration/conftest.py`): засидить `MetricSample`/`Server` с разными `status`, вызвать `MetricsService.overview("24h")` → проверить точки; `scrape_tick()` пишет строки, которые видит `overview`; `purge_old()` удаляет старьё за окном ретеншна. Схема поднимется автоматически через `BaseTable.metadata.create_all` — конфтест не трогать.
- Роутер: тест `GET /api/v1/admin/metrics` под admin → 200 и структура; без admin → 403 (по образцу `test_admin.py`).
- Метрики prometheus-client в тестах не трогать глобально или использовать локальный `CollectorRegistry`, чтобы не ловить `Duplicated timeseries` при повторном импорте.
- Прогнать `make check` (ruff+mypy) и `make test`; фронт `make front-lint` (`tsc --noEmit`).

### Риски и подводные камни
- `Duplicated timeseries in CollectorRegistry` при импортах/повторной регистрации — метрики объявлять модуль-уровнево один раз в `infra/metrics.py`; в тестах не переопределять.
- Кардинальность лейблов: `path` и `error_code` могут взорвать число серий — нормализовать путь до шаблона, лейблы хранить компактной строкой в `metric_samples`.
- mypy строгий (CI): грабля `list` vs метод — использовать `builtins.list`/явные аннотации; проверить `uv run mypy src` до push.
- `Server.latency_ms` бывает `None` (offline/unknown) — не писать `None` в `value: float`, пропускать/агрегировать только online.
- Одна реплика без лидер-элекшена: `metrics-tick` с `max_instances=1, coalesce=True` (как остальные джобы) — иначе дубли при отставании.
- Не смешать с owner-трафиком: имена таблиц/эндпоинтов/сторов должны явно различаться (`metric_samples` vs `traffic_samples`, `/admin/metrics` vs `/servers/{sid}/traffic`).
- `/metrics` авторизован токеном, а admin-эндпоинт — сессией: не завязывать внутренний скрейп на HTTP-вызов `/metrics` (читать реестр напрямую), иначе понадобится токен и лишний сетевой хоп.
- SVG-график должен корректно деградировать при 0/1 точке (без деления на ноль в масштабировании).

### Критерии приёмки
- `/metrics` (или внутренний реестр) реально экспонирует прикладные метрики HTTP/scheduler/servers/provisioning/sync (сейчас их нет).
- Таблица `metric_samples` создаётся миграцией; джоба `metrics-tick` наполняет её; ретеншн работает.
- `GET /api/v1/admin/metrics?period=24h` под admin отдаёт временные ряды; неадмин получает 403.
- На экране System есть секция «Мониторинг» со SVG-графиком (без внешних зависимостей) и поллингом; переключение периода 1h/24h/7d работает.
- Функция ясно отделена от owner-дашборда трафика (разные таблицы/эндпоинты/экраны).
- `make check`, `make test`, `make front-lint` зелёные; изменения — один conventional-commit (`feat: ...`).

---

## Что реализовано в этом коммите (MVP-срез)
- `infra/metrics.py` — in-process реестр прикладных метрик (HTTP `Counter/Histogram`, scheduler `Counter/Histogram/errors`, server/provisioning/sync `Gauge/Histogram`) + helper'ы `path_group`, `observe_http`, `record_scheduler_tick`, `instrument_job`, `set_server_gauges`, `set_provisioning_errors`, `read_gauge_samples`, `read_http_rps`.
- HTTP-middleware (`entrypoint.py`) измеряет длительность/код ответа → `observe_http`; все job'ы планировщика обёрнуты `instrument_job(...)` (tick success/error/seconds).
- Модель `MetricSample` (`metric_samples`) + миграция `20260705_0015-d4e5f6a7b8c9` (down_revision `c3d4e5f6a7b8`).
- `MetricsService` (`scrape_tick`/`overview`/`purge_old`) + DI `metrics = provide(MetricsService)`; job'ы `metrics-tick`/`metrics-retention` в lifespan; `settings.metrics_interval=60`, `metrics_retention_days=30`.
- `ServerService.run_tick` обновляет server-гейджи и provisioning-ошибки по `error_code` (best-effort).
- `GET /api/v1/admin/metrics?period=` под `require_admin` → временные ряды + «сводка сейчас».
- Фронт: `components/chart.tsx` (SVG `LineChart`, деградирует при 0/1 точке), `adminMetrics(period)` в queries + типы, секция «Мониторинг» на `System.tsx` с графиком серверов по статусу, мини-панелью HTTP-нагрузки, селектором периода 1h/24h/7d и поллингом.
- Тесты: unit `test_metrics.py` (`path_group`, `instrument_job`), integration `test_metrics.py` (`overview`/фильтр периода/`scrape_tick`/`purge_old`).

## Осталось на следующие коммиты
- Отдельные ряды/панели: HTTP RPS/латентность-перцентили, scheduler tick-rate и падения по job, provisioning-ошибки по `error_code`, длительность sync (`vpnhub_sync_seconds` — точка инструментации ещё не врезана в `SyncService.run_tick`).
- Тест роутера `GET /api/v1/admin/metrics` (admin 200 / не-admin 403) — в проекте пока нет HTTP-клиента для роутер-тестов, покрытие сделано на уровне сервиса.
- Заметка в `docs/` про набор метрик и отличие от owner-трафика.
