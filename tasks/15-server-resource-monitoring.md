## 15. Per-server мониторинг ресурсов хоста

**Категория** Мониторинг / Observability · **Сложность** M · **Зависимости** переиспользует monitor-тик (№ статус-мониторинг), SSH-канал provisioning и график-компонент из № трафика/admin-дашбордов

### Зачем
Мониторинг серверов сейчас знает только `online/offline` + latency (TCP-зонд по SSH-порту). Владелец не видит, «дышит» ли машина: загрузку CPU, память, диск, load, аптайм, число соединений. Цель — по каждому серверу собирать ресурсы хоста и показывать их на странице сервера: текущие значения (гейджи/цифры) + мини-графики истории.

### Что собирается
Одной SSH-командой (`infra/hostmetrics.py::HOST_METRICS_CMD`, отлажена на живом сервере) снимается блок `KEY=VALUE` из `/proc` и утилит; парсится чистой функцией `parse_host_metrics` (без IO):
- **CPU %** — по двум снимкам `/proc/stat` (до/после `sleep 1`): `(1 - idle_delta/total_delta) * 100`.
- **load average** (1-минутный) — из `/proc/loadavg`.
- **RAM** used/total, байт — `MemTotal`/`MemAvailable` из `/proc/meminfo` (`used = total - available`).
- **Диск `/`** used/total, байт — `df -B1 --output=used,size /`.
- **TCP established** — `ss -tan state established | wc -l`.
- **uptime**, сек — `/proc/uptime`.
- **онлайн-VPN-клиенты** (опционально) — `sudo docker exec <amnezia-awg2|amnezia-awg> wg show all latest-handshakes` → число пиров со свежим handshake (`now - hs < 180`). Контейнеров нет/недоступно → поле `None` (необязательное).

Все поля best-effort: строку не удалось прочитать/распарсить → `None`, тик не падает. Значения памяти/диска — **BigInteger** (>2 ГБ переполнили бы int32; тот же баг уже ловили в `traffic_samples`).

### Где хранится / ретеншн
Таблица `server_metrics` (модель `models.ServerMetric`, миграция `a7b8c9d0e1f2`): `server_id` (FK CASCADE), `at` (epoch), `cpu_pct`, `load1`, `mem_used`, `mem_total`, `disk_used`, `disk_total`, `tcp_estab`, `uptime_s`, `online_clients` (nullable; байты — BigInteger), индекс `(server_id, at)`. Одна строка на сервер на monitor-тик.

Ретеншн — фоновой джобой `server-metrics-retention` (`HostMetricsService.purge_old`, `server_metrics_retention_days` = 14 дней по умолчанию), зарегистрирована в `entrypoint.py` рядом с traffic/metrics-retention.

### Сбор
`HostMetricsService.collect_for(server)` открывает отдельную короткую SSH-сессию (`monitor_timeout`), гоняет `collect_host_metrics` и пишет сэмпл. Врезано в `ServerService.run_tick` через `_collect_host_metrics(online_ids)` — **строго best-effort**: гоняется ПОСЛЕ записи статусов, для каждого онлайн-сервера отдельно (изоляция + семафор `monitor_concurrency`), сбой сбора НЕ влияет на `online/offline` и не роняет тик.

### API
`GET /api/v1/servers/{sid}/metrics` (owner-scoped, проверка владения как у `/traffic`) → `{ serverId, current, samples[] }`: `current` — последний сэмпл (гейджи), `samples` — последние N (`server_metrics_history_limit` = 120) в хронологическом порядке для графиков.

### UI
Карточка «Ресурсы сервера» на `ServerDetail.tsx` (`ServerMetricsCard`): плитки CPU %/load, память used/total + %, диск `/` used/total + %, аптайм, TCP-соединения, онлайн-клиенты (если есть) + мини-спарклайны (переиспользован `components/chart.tsx::LineChart`) по CPU/памяти и TCP. Query-хелпер `serverMetrics` в `queries.ts`, тип `ServerMetrics`/`ServerMetricSample` в `types.ts`. Обновление — `refetchInterval` 60с (как страховочный поллинг остального ServerDetail). Строки русские, захардкожены — в стиле файла (ServerDetail пока без i18n).

### Тесты
- Юнит `tests/unit/infra/test_hostmetrics.py` — чистый парсер (`parse_host_metrics`/`parse_online_clients`): разбор всех полей, CPU% из двух снимков, mem_used при значениях >int32, битые/пустые поля → None.
- Интеграция `tests/integration/services/test_hostmetrics.py` (in-memory SQLite, без SSH) — запись/чтение сэмплов (крупные BigInteger значения), хронологический порядок, `history_limit`, guard владельца, `purge_old`.

Реальный SSH в тестах не требуется. `make check` (ruff+mypy), `make test` (946 passed, +14 новых), `make front-lint` (tsc) + biome — зелёные.

### Что осталось (remaining)
- Ретеншн — только грубый purge по возрасту; даунсэмплинг/агрегаты истории (как размечено у traffic) не делаем.
- Онлайн-клиенты считаются только для amnezia-wireguard контейнеров; xray/hysteria2/outline/openvpn в счётчик пиров не входят (для них поле остаётся `None`).
- Периодичность сбора завязана на `monitor_interval` (общий с TCP-зондом); отдельный интервал именно для ресурсных метрик — при необходимости отдельной джобой.
- Порогов/алертов (например, «диск >90%») нет — только отображение.
