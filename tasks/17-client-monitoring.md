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
| openvpn | — (TODO: status-лог `bytes per CN`) | — | — |
| outline | — (TODO: `GET /metrics/transfer`, per-key байты, без rx/tx-сплита и online) | — | — |

**Кумулятив, не дельта.** Xray читаем с `-reset=false`, hysteria `/traffic` без `?clear=1` — счётчики НЕ сбрасываются. `TrafficService.record` сам считает дельты от прошлого сэмпла (как для wg; при рестарте счётчиков `curr<prev` → дельта = `curr`).

**Best-effort.** Сбой/выключенный stats одного протокола/сервера → пустой список, не роняет тик и не мешает остальным протоколам. Сбор врезан туда же, где собирается WG-трафик (`SyncService.run_tick` фаза 2, запись — фаза 4 отдельной транзакцией).

### Мэппинг client_id (проверено вживую)
Идентификатор в статистике движка = наш `device_configs.client_id`:
- **WireGuard** — pubkey; **Xray** — uuid (в server.json `email==id==uuid`, задача №16); **Hysteria2** — auth-id (первый столбец файла токенов).
Резолв имени: `traffic_samples.device_config_id → device_configs → devices(name, platform) → users(name)`. Клиент без нашего `DeviceConfig` → `external` (заведён вне панели).

### Чистые парсеры (юнит-тестируемы, без SSH) — `infra/trafficstats.py`
- `parse_xray_stats(traffic, online?) -> list[ClientTraffic]` — per-uuid uplink/downlink/online.
- `parse_hysteria_traffic(traffic, online?) -> list[ClientTraffic]` — per-authid rx/tx/online; online-only клиенты добавляются с rx=tx=0.
- Пустой/битый ответ (`{}`, не-JSON, `""`) → `[]`. Тесты: `tests/unit/infra/test_trafficstats.py`, диспетч коллектора — `tests/unit/services/test_traffic_parse.py`.

### Модель данных
`traffic_samples` + колонка `online BOOLEAN NULL` (миграция `c9d0e1f2a3b4`, за head `b8c9d0e1f2a3`). Для wg `online` пишется NULL (онлайн вычисляется по handshake на чтении); для xray/hysteria2 — флаг из stats (у них handshake нет). `PeerStat.online` пробрасывается через `record()`; `_aggregate_clients()` доверяет флагу движка, иначе падает на свежесть handshake. Скорость (`rxSpeed`/`txSpeed`) — байт/сек из последней дельты по интервалу между двумя последними сэмплами клиента (0 у офлайн).

### API (owner-scoped)
- `GET /api/v1/servers/{sid}/traffic?period=` — per-server overview (расширен: у клиентов теперь `online`, `rxSpeed`/`txSpeed`, `lastSeen`).
- `GET /api/v1/monitoring?period=` — ГЛОБАЛЬНО по всем серверам владельца: `summary{clientsTotal, clientsOnline, serversTotal, rxTotal, txTotal}` + `clients[]{userName, deviceName, proto, serverId, serverName, online, rxTotal, txTotal, rxSpeed, txSpeed, lastSeen, external}`. `period ∈ {1h,24h,7d}`.

### Экран «Мониторинг» (owner-навигация: `nav.ts` + `App.tsx` + иконка `monitoring`)
- Сводка сверху: онлайн сейчас (из N), скачано/отдано за период, число серверов.
- Таблица клиентов: имя · устройство · протокол · сервер · онлайн-индикатор · скачал · отдал · скорость ↓/↑ · активность (последний онлайн).
- Фильтры: сервер, протокол. Сортировка: по трафику / скорости / имени (онлайн выше при равенстве). Переключатель периода. Поллинг 30с.
- Карточка сервера (ServerDetail) обогащена секцией «Клиенты сервера» (переиспользует per-server overview).

### Что осталось (TODO)
- **openvpn**: per-CN байты из status-лога (`bytes_received`/`bytes_sent`), online через `CLIENT_LIST` (парсер №16 уже есть) — включить в коллектор.
- **outline**: `GET <apiUrl>/metrics/transfer` → `bytesTransferredByUserId` (только суммарные байты, без rx/tx-сплита и без online).
- Ретеншн/агрегация: даунсэмплинг старых сэмплов (сейчас — только purge по `traffic_retention_days`); графики per-client трафика на экране мониторинга (LineChart уже есть, данные в `series`).
