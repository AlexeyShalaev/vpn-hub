## 16. Честный онлайн-счётчик клиентов по всем протоколам

**Категория** Мониторинг · **Сложность** L · **Зависимости** №15 (per-server ресурс-мониторинг)

### Зачем
В №15 «онлайн-клиенты» считались только для AmneziaWG (по handshake). Нужен ЧЕСТНЫЙ per-protocol online по всем протоколам — без выдуманных чисел: где счётчик реально доступен, показываем точное значение; где нет — «неизвестно» (—), а не 0.

### Как считается online по протоколам (проверено вживую на боевых серверах)
| Протокол | Источник | Точность |
|---|---|---|
| awg / awg_legacy | `wg show all latest-handshakes` в контейнере, пиры с (now−hs)<180с | точно |
| xray / xray_xhttp | Xray **Stats API**: `xray api statsquery -pattern ">>>online"` → число пользователей с online>0 | точно, требует включения |
| hysteria2 | **trafficStats** API: `GET /online` (Authorization) → ключи с count>0 | точно, требует включения |
| openvpn | status-лог `CLIENT_LIST` (парсер есть) | точно, если status-лог настроен (сбор — TODO) |
| outline | нет нативного счётчика сессий (Shadowsocks) → **None** («—») | не поддерживается честно |

### Два правила
1. **Коллектор только читает.** Нет stats-API → online=None (неизвестно), контейнер НЕ трогается.
2. **Включение stats — явное действие** (эндпоинт + кнопка), идемпотентно, рестарт контейнера только при реальном изменении конфига.

### Что реализовано
- **Парсеры** `infra/onlinestats.py` (чистые, без IO): `parse_xray_online` / `parse_hysteria_online` / `parse_openvpn_online` → `int|None`. Контракт: int≥0 — известно; None — неизвестно (не 0).
- **Провизионеры**: `XrayProvisioner.enable_stats(ssh)->bool` (включает Stats API в server.json: stats/api/policy.statsUserOnline + email каждому клиенту + dokodemo-door api-inbound :10085 + routing; рестарт), `XrayProvisioner.query_online(ssh)->int|None`. `HysteriaProvisioner.enable_stats(ssh)->secret` (дописывает `trafficStats:` в config.yaml + рестарт; секрет читается обратно из конфига), `HysteriaProvisioner.query_online(ssh, secret)->int|None`, `_read_stats_secret`.
- **Сбор** `services/hostmetrics.collect_online_by_proto(ssh, protocols)` — read-only, per-installed-протокол, одной SSH-сессией; сбой одного протокола → его None. Врезан в `HostMetricsService.collect_for` (monitor-тик).
- **Хранение**: `ServerMetric.online_by_proto` (JSON {proto:count|null}, миграция b8c9d0e1f2a3); `online_clients` = сумма ИЗВЕСТНЫХ (None не считаются).
- **API**: `GET /servers/{sid}/metrics` отдаёт `onlineByProto` в current; `POST /servers/{sid}/stats/enable` (owner-scoped) включает Stats API/trafficStats на xray/hysteria2 сервера.
- **UI** (карточка «Ресурсы сервера»): бейджи online по протоколам (число / «—» с подсказкой почему), кнопка «Включить точную онлайн-статистику» (с предупреждением о рестарте xray/hysteria) — показывается, пока есть xray/hysteria без включённого stats.
- **Тесты**: `tests/unit/infra/test_onlinestats.py` — парсеры (включая пустые/битые) + `_sum_known` + диспетч `collect_online_by_proto` на fake-ssh.

### Как тестировать
Парсеры и диспетч — юнит на in-memory (fake ssh). Живая проверка — на реальном сервере: включить stats (кнопка/эндпоинт) → на следующем тике `onlineByProto` показывает точные числа.

### Осталось (remaining)
- Сбор online для **OpenVPN** через status-лог (парсер готов; нужно включить `status <path>` в конфиге и читать файл) — сейчас None.
- **Авто-enable stats при install** новых xray/hysteria серверов (сейчас — явной кнопкой; existing-парк включается кнопкой/эндпоинтом).
- Xray statsUserOnline требует `email` у клиентов — enable его проставляет; для очень старых конфигов без клиентов online будет 0 до первого клиента.
- Даунсэмплинг истории online, пороги/алерты — вне охвата.
