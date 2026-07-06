## 20. Лимиты — Этап 3a: байт-лимиты (учёт + квота сервера + пер-user), без отсечки

**Категория** Лимиты · **Сложность** L · **Зависимости** Этап 2 ([tasks/19](19-device-limits.md))

### Зачем и решения
Ограничить трафик per (user, server). По итогам обсуждения:
- **без лимита и с лимитом** — оба поддержаны (NULL = безлимит; у трафика дефолт — безлимит);
- **период** — привязка к дню оплаты сервера (`Server.billing_day` 1..31); не задан → 1-е число месяца;
- **при превышении** — резать доступ пользователя на сервере до сброса (**честная отсечка — Этап 3b**);
- **охват** — сразу и per (user, server), и **бюджет сервера** (квота трафика тарифа).
- **Смысл**: каталог провайдеров не хранит лимиты тарифа (многие RU-VDS вообще безлимитны с ограничением
  скорости порта), поэтому лимит задаёт владелец руками; назначение — fair-use + защита от overage там,
  где тариф метрируемый.

### Модель
- `Server.bandwidth_quota_bytes` (квота тарифа за период, NULL=безлимит) + `Server.billing_day` (1..31, NULL→1).
- `Group.max_bytes`, `GroupMember.max_bytes` (override пер-user лимита; NULL = наследовать).
- Настройка `default_user_bytes` (глобальный дефолт; 0/пусто = без лимита).
- **`TrafficUsage`** (накопитель): `(server_id, user_id|NULL, period_start, rx_bytes, tx_bytes)`, уникум по
  `(server, user, period)`. `user_id=NULL` — суммарный трафик сервера (вкл. external); иначе — пер-user.
  Переживает purge сырых `traffic_samples`. Миграция `a3b4c5d6e7f8`.

### Логика (`services/limits.py`)
- `period_start(now, billing_day)` — epoch начала периода; день клампится к длине месяца, откат на прошлый
  месяц/год если день ещё не наступил; локальное время.
- `effective_byte_limit(user)` — иерархия: самый щедрый ЯВНО заданный лимит (member > group), иначе
  глобальный дефолт; NULL везде = без лимита.
- `add_period_usage` / `period_usage` — инкремент и чтение накопителя.
- Инкремент врезан в `TrafficService.record`: из тех же дельт пишем счётчик сервера (NULL) для КАЖДОГО
  сэмпла (вкл. external) и пер-user для резолвящихся клиентов (`_user_ids`: client_id → Device.user_id).

### API
- `PATCH /servers/{sid}/quota` `{quotaBytes, billingDay}` (owner) → `set_bandwidth_quota`.
- `GET /servers/{sid}/usage` (owner) → `{periodStart, quota, serverUsed, users:[{userId,name,used,limit}]}`.
- `PATCH /groups/{gid}/byte-limit`, `/groups/{gid}/members/{mid}/byte-limit` `{maxBytes}` (owner).
- `PUT /admin/system/user-byte-limit` `{defaultUserBytes}` (admin); payload `defaultUserBytes`.
- Сериализаторы: `bandwidthQuota`/`billingDay` на сервере; `maxBytes` на группе/участнике.

### Enforcement (3a — мягкий)
`services/configs.py`: при выдаче НОВОГО конфига, если `used(rx+tx) ≥ effective_byte_limit` за текущий
период сервера → `BadRequest` («Достигнут лимит трафика…»). Уже выданные конфиги НЕ режутся (это 3b).
Квота сервера — индикатор/предупреждение владельцу (жёлтый ≥80%, красный ≥100%), без авто-отсечки всех.

### UI
- `ServerDetail`: карточка «Трафик и квота» — настройка квоты (ГБ) + дня сброса; бар использования сервера
  (used/quota, цвет по %) + топ-пользователи за период (с индикатором пер-user лимита).
- `GroupDetail`: в модалках группы/участника — поле «Трафик, ГБ за период» рядом с устройствами.
- `System`: глобальный дефолт трафика рядом с дефолтом устройств.

### Тесты
`test_limits.py`: `fmt_bytes`, `period_start` (якорь дня, кламп февраля), `global_user_bytes`,
`effective_byte_limit` (иерархия/None), `add_period_usage`/`period_usage` (сервер+пер-user, складывание,
изоляция периода). Сериализаторы обновлены под новые поля.

### Ревью (состязательное, 5 осей)
Нашло 1 реальный дефект (medium): `add_period_usage` делал неатомарный SELECT-then-INSERT в таблицу с
UNIQUE-констрейнтом → при гонке ручного `sync` со scheduled-тиком на одном сервере IntegrityError
откатывал весь тик (терялись сэмплы+учёт) либо read-modify-write терял инкремент. **Исправлено**:
атомарный upsert (UPDATE `x=x+delta`; при отсутствии строки INSERT в savepoint с ретраем по IntegrityError),
портируемо на SQLite/Postgres.

### Осталось
- **Этап 3b — честная отсечка**: suspend доступа пользователя на сервере при превышении (снять клиента,
  сохранив материал) + resume при сбросе периода / повышении лимита; авто-suspend/-resume в sync-тике.
- **Сериализация sync per server** (к 3b): scheduled `run_tick` и ручной `POST /servers/{sid}/sync` не
  сериализованы — при одновременном тике на одном сервере возможен double-count дельт (пре-существует и
  для сырых `traffic_samples`; для мягкого лимита влияние мало, но перед жёсткой отсечкой стоит закрыть
  per-server advisory-lock).
- Purge старых периодов `traffic_usage` (строки крошечные — по одной на user/server/месяц; отложено).
