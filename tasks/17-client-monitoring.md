## 17. Супер-мониторинг клиентов (трафик + онлайн по всем протоколам)

**Категория** Мониторинг · **Сложность** L · **Зависимости** №1 (трафик-дашборд), №16 (честный онлайн)

### Зачем
Объединить готовые куски (per-server трафик №1 + честный онлайн №16) в ЕДИНЫЙ per-client мониторинг: какой реальный клиент (имя пользователя · устройство), по какому протоколу и на каком сервере, онлайн ли сейчас, сколько скачал/отдал и с какой скоростью — по ВСЕМ серверам владельца.

### Что собирается по каждому протоколу (в sync-тике, best-effort, `TrafficCollector.collect` диспетчит по `spec.kind`)
| Протокол | Источник (в одной SSH-сессии) | rx / tx | online |
|---|---|---|---|
| awg / awg_legacy | `{bin} show {iface} dump` в контейнере (как раньше) | кумулятив из dump | по свежести `last_handshake` (<`traffic_online_window_seconds`) |
| xray / xray_xhttp | `xray api statsquery --server=127.0.0.1:10085 -reset=false -pattern 'user>>>'` | `user>>>{uuid}>>>traffic>>>uplink` / `downlink` (кумулятив) | `user>>>{uuid}>>>online` > 0 |
| hysteria2 | trafficStats API: `curl -H "Authorization: <secret>" /traffic` + `/online` (секрет из config.yaml) | `{authid:{rx,tx}}` (кумулятив) | `/online`: `{authid:count}`, count>0 |
| openvpn | OpenVPN status-лог (`status openvpn-status.log` уже в server.conf, читаем `cat` в контейнере) | per-CN `Bytes Received` (rx=upload) / `Bytes Sent` (tx=download), кумулятив; форматы v2 и v3 | клиент присутствует в `CLIENT_LIST` |
| outline | `curl -sfk <local_api_url>/metrics/transfer` по SSH на localhost (apiUrl из материала протокола) | per-key `bytesTransferredByUserId` — **ТОЛЬКО суммарные байты**: кладём в tx, rx=0 (rx/tx-сплита нет) | **не поддержан** (`online=None`) |

**Кумулятив, не дельта.** Xray читаем с `-reset=false`, hysteria `/traffic` без `?clear=1` — счётчики НЕ сбрасываются. `TrafficService.record` сам считает дельты от прошлого сэмпла (как для wg; при рестарте счётчиков `curr<prev` → дельта = `curr`).

**Best-effort.** Сбой/выключенный stats одного протокола/сервера → пустой список, не роняет тик и не мешает остальным протоколам. Сбор врезан туда же, где собирается WG-трафик (`SyncService.run_tick` фаза 2, запись — фаза 4 отдельной транзакцией).

### Мэппинг client_id (проверено вживую)
Идентификатор в статистике движка = наш `device_configs.client_id`:
- **WireGuard** — pubkey; **Xray** — uuid (в server.json `email==id==uuid`, задача №16); **Hysteria2** — auth-id (первый столбец файла токенов).
Резолв имени: `traffic_samples.device_config_id → device_configs → devices(name, platform) → users(name)`. Клиент без нашего `DeviceConfig` → `external` (заведён вне панели).

### Чистые парсеры (юнит-тестируемы, без SSH) — `infra/trafficstats.py`
- `parse_xray_stats(traffic, online?) -> list[ClientTraffic]` — per-uuid uplink/downlink/online.
- `parse_hysteria_traffic(traffic, online?) -> list[ClientTraffic]` — per-authid rx/tx/online; online-only клиенты добавляются с rx=tx=0.
- `parse_openvpn_traffic(text) -> list[ClientTraffic]` — per-CN `Bytes Received`/`Bytes Sent` из status-лога (форматы v2 и v3); online=True по присутствию в `CLIENT_LIST`; дубли CN (`duplicate-cn`) суммируются.
- `parse_outline_transfer(text) -> list[ClientTraffic]` — per-key `bytesTransferredByUserId` → tx=total, rx=0, online=None (Outline даёт только суммарные байты).
- Пустой/битый ответ (`{}`, не-JSON, `""`, нет секции) → `[]`. Тесты: `tests/unit/infra/test_trafficstats.py`, диспетч коллектора — `tests/unit/services/test_traffic_parse.py`.

### Модель данных
`traffic_samples` + колонка `online BOOLEAN NULL` (миграция `c9d0e1f2a3b4`, за head `b8c9d0e1f2a3`). Для wg `online` пишется NULL (онлайн вычисляется по handshake на чтении); для xray/hysteria2 — флаг из stats (у них handshake нет). `PeerStat.online` пробрасывается через `record()`; `_aggregate_clients()` доверяет флагу движка, иначе падает на свежесть handshake. Скорость (`rxSpeed`/`txSpeed`) — байт/сек из последней дельты по интервалу между двумя последними сэмплами клиента (0 у офлайн).
+ колонка `ext_name VARCHAR NULL` (миграция `d0e1f2a3b4c5`, за head `c9d0e1f2a3b4`) — имя клиента из Amnezia `clientsTable` (`userData.clientName`), проброшено через `PeerStat.name`.

### API (owner-scoped)
- `GET /api/v1/servers/{sid}/traffic?period=` — per-server overview (расширен: у клиентов теперь `online`, `rxSpeed`/`txSpeed`, `lastSeen`).
- `GET /api/v1/monitoring?period=` — ГЛОБАЛЬНО по всем серверам владельца: `summary{clientsTotal, clientsOnline, serversTotal, rxTotal, txTotal}` + `clients[]{userName, deviceName, extName, proto, serverId, serverName, online, rxTotal, txTotal, rxSpeed, txSpeed, lastSeen, external}` (`extName` — имя из Amnezia clientsTable для external-клиентов; в обоих ответах). `period ∈ {1h,24h,7d}`.

### Экран «Мониторинг» (owner-навигация: `nav.ts` + `App.tsx` + иконка `monitoring`)
- Сводка сверху: онлайн сейчас (из N), скачано/отдано за период, число серверов.
- Таблица клиентов: имя · устройство · протокол · сервер · онлайн-индикатор · скачал · отдал · скорость ↓/↑ · активность (последний онлайн).
- Фильтры: сервер, протокол. Сортировка: по трафику / скорости / имени (онлайн выше при равенстве). Переключатель периода. Поллинг 30с.
- Карточка сервера (ServerDetail) обогащена секцией «Клиенты сервера» (переиспользует per-server overview).
- **Клик по строке клиента** → модалка с графиком его трафика за период (`LineChart`): две линии — download (tx) и upload (rx). Данные берём из per-server overview этого клиента (`serverTraffic(serverId, period).series`), фильтруем по `clientId`+`proto` и группируем по времени `at`; значения — МБ за интервал сбора. Оси/легенда подписаны человекочитаемо.

### Собрано по всем протоколам (готово)
- **имена external-клиентов из Amnezia `clientsTable`**: клиент без нашего `DeviceConfig` (заведён мимо панели) больше не безликий «Внешний клиент» — коллектор для amnezia-протоколов (awg/awg_legacy, xray/xray_xhttp, hysteria2, openvpn) читает `clientsTable` контейнера (`base.read_clients_table`, best-effort) и проставляет `PeerStat.name` из `userData.clientName` по `clientId` (== наш `client_id`). Имя сохраняется в `traffic_samples.ext_name`; `overview`/`global_overview` отдают его как `extName` для external-клиентов (у нон-external имя по-прежнему из device_config). Фронт (`Monitoring.clientName`/`ServerDetail.clientLabel`) показывает `extName` вместо «Внешний клиент», сохраняя тег «вне панели». Outline `clientsTable` не использует — там имя недоступно. Чистый хелпер `clients_table_names(rows)` (юнит-тест на реальном формате + битые/пустые строки).
- **openvpn**: per-CN трафик+online из OpenVPN status-лога. `status openvpn-status.log` уже в `server.conf` (configure_container.sh) — демон стартует из `/`, поэтому лог в корне контейнера; коллектор пробует `/openvpn-status.log` и `/opt/amnezia/openvpn/openvpn-status.log`, берёт первый непустой (best-effort, без правки конфига/рестарта). rx=`Bytes Received`, tx=`Bytes Sent`, кумулятив; online по `CLIENT_LIST`.
- **outline**: per-key суммарный трафик через Management API `GET /metrics/transfer` (curl по SSH на localhost, apiUrl из материала протокола — провизионер передаётся в `collect(ssh, spec, provo)` из sync-тика). Outline даёт ТОЛЬКО суммарные байты: `tx=total`, `rx=0`, **online не поддержан** (`None`).

### Что осталось (TODO)
- Ретеншн/агрегация: даунсэмплинг старых сэмплов (сейчас — только purge по `traffic_retention_days`).
- **outline**: разбить суммарный трафик на приём/отдачу (Management API отдаёт только суммарные байты — нужен либо ss-access-log, либо доработка shadowbox) и честный online (у Shadowsocks нет понятия сессии).
- **openvpn**: для полностью машинного парсинга можно перевести status-лог в v3 (`status <path> 5\nstatus-version 3`) — сейчас парсер поддерживает оба формата, доп. настройка не требуется.
