## 1. Дашборд трафика и подключений (owner)

**Категория** Наблюдаемость / UX · **Сложность** M · **Зависимости** мониторинг серверов и sync (данные собираются в уже открытой SSH-сессии sync-тика); фронт-графики — отдельной итерацией

### Зачем
Владельцу нужно видеть, кто и сколько качает через его сервер: активные подключения (онлайн/офлайн), суммарный трафик по клиентам за период и сопоставление «pubkey → устройство → пользователь». Раньше эта телеметрия нигде не хранилась. Цель первого среза — собирать и хранить дельта-сэмплы трафика по wireguard-протоколам и отдавать агрегаты через owner-API; визуализация (графики) — на будущее.

### Что реализовано в этом коммите
Вертикальный backend-срез «сбор → хранение → чтение»:

1. **Модель `TrafficSample`** (`backend/src/vpnhub/infra/db/orm/models.py`) — одна строка на клиента-протокол за один sync-тик. Поля: `server_id`, `proto`, `client_id` (pubkey; `None` — агрегат), `device_config_id` (`None` → external-клиент без нашего DeviceConfig), `at` (epoch), кумулятивы `rx_bytes/tx_bytes` (как отдаёт wg), приросты `rx_delta/tx_delta`, `last_handshake`. Индексы: `server_id`, `at`, составной `(server_id, proto, client_id)`.
2. **Миграция** `backend/migrations/versions/20260705_0014-c3d4e5f6a7b8_add_traffic_samples.py` (`down_revision = b2c3d4e5f6a7`, следом за audit_events) — таблица + три индекса. В тестах схема поднимается из моделей (`BaseTable.metadata.create_all`), миграция нужна для прода.
3. **`TrafficService`** (`backend/src/vpnhub/services/traffic.py`):
   - `parse_wg_dump(text)` — чистый парсер `wg/awg show <iface> dump` (TSV; первая строка-интерфейс пропускается, битые/короткие строки глотаются). Покрыт unit-тестами без SSH.
   - `TrafficCollector.collect(ssh, spec)` — читает статистику по уже открытому SSH-каналу; только `kind == "wireguard"` (awg/awg_legacy), прочие протоколы возвращают пусто (TODO-точки внутри).
   - `record(server_id, proto, stats)` — пишет сэмплы отдельной транзакцией; дельта = `curr - prev` (при рестарте счётчиков `curr < prev` → `curr`; первый сэмпл → кумулятив). Сопоставляет `client_id → DeviceConfig` по pubkey.
   - `overview(owner_id, sid, period)` — агрегаты per (proto, client) за период (`1h/24h/7d`, дефолт `24h`) + временной ряд `series`; онлайн-статус из свежести `last_handshake`; резолвит имена устройства/пользователя. Владение проверяется как в `ServerService` (чужой сервер → `NotFound`).
   - `purge_old()` — ретеншн старше `traffic_retention_days` (идемпотентно).
4. **Интеграция в sync** (`backend/src/vpnhub/services/sync.py`): сбор врезан в sync-тик строго **best-effort** — любой сбой сбора/записи глотается и НЕ влияет на решения sync/revoke. Запись сэмплов вынесена в отдельную «фазу 4» ОТДЕЛЬНОЙ транзакцией, чтобы изолировать от sync-инвариантов.
5. **owner-API** (`backend/src/vpnhub/api/routers/owner.py`): `GET /api/v1/servers/{sid}/traffic?period=24h` → `TrafficService.overview`.
6. **Фоновой ретеншн** (`backend/src/vpnhub/api/entrypoint.py`): джоба `traffic-retention` (`interval, hours=24`) → `purge_old`.
7. **Настройки** (`backend/src/vpnhub/api/config.py`): `traffic_retention_days=30`, `traffic_online_window_seconds=180`.
8. **DI** (`backend/src/vpnhub/infra/di/__init__.py`): `provide(TrafficService)`.

### Модель данных
`traffic_samples`: дельта-таблица. Один тик sync = по строке на каждого пира каждого wireguard-протокола. Дельта считается относительно последнего сэмпла того же `(server_id, proto, client_id)`. Кумулятивы хранятся тоже — для расчёта следующей дельты и отображения «всего с начала счётчика». `device_config_id = None` означает external-клиента (подключён к серверу, но без выданного нами конфига).

### Как собирается статистика
В sync-тике (`SyncService.sync`) для каждого читаемого wireguard-протокола вызывается `TrafficCollector.collect` в уже открытой SSH-сессии: `{spec.bin} show {spec.interface} dump` внутри контейнера `spec.container`. Результат парсится в `list[PeerStat]` и после «фазы 3» (сверка/запись sync) пишется `TrafficService.record` в отдельной транзакции. Онлайн-статус клиента в `overview` вычисляется как `now - last_handshake < traffic_online_window_seconds`.

### Тесты (in-memory SQLite, без внешней инфры)
- `backend/tests/unit/services/test_traffic_parse.py` — чистый парсер `parse_wg_dump` (пиры/пропуск интерфейса, пустой/битый ввод).
- `backend/tests/integration/services/test_traffic.py` — БД-логика через UoW: расчёт дельт (первый сэмпл, инкремент, рестарт счётчиков, no-op), overview (резолв имён устройства/пользователя, external-клиент, онлайн-статус из freshness, guard владельца, фолбэк периода), `purge_old`.
- `make check` (ruff format + ruff + mypy) и `make test` зелёные. Frontend не менялся — `front-lint` не запускался.

### Что осталось на будущие итерации
- **Фронт-дашборд**: экран/виджет с графиками трафика (`series`), таблицей клиентов (онлайн/офлайн, суммы rx/tx, имена), выбором периода. React-компоненты и запросы к `GET /servers/{sid}/traffic` — отдельным коммитом.
- **Парсеры для остальных протоколов**: сейчас собирается только wireguard. TODO-точки размечены в `TrafficCollector.collect`:
  - xray — `xray api statsquery` (per-uuid uplink/downlink);
  - hysteria2 — trafficStats API;
  - outline — `GET <apiUrl>/metrics/transfer` (bytesTransferredByUserId).
- **Даунсэмплинг агрегатов**: сейчас хранятся сырые тик-сэмплы с ретеншном `traffic_retention_days`. Для длинных горизонтов — периодическая свёртка в почасовые/суточные агрегаты.
- **Пуш-обновление дашборда**: связать с realtime-стримом (`GET /api/v1/stream`), чтобы дашборд обновлялся без поллинга.
