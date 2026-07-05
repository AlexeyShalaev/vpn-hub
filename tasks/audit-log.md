## 9. Аудит-лог и страница «События»

**Категория** Наблюдаемость/безопасность · **Сложность** L · **Зависимости** нет жёстких (Home №10 переиспользует компактный список; сам аудит самодостаточен)

### Зачем
Сейчас в системе нет журнала действий: невозможно ответить «кто выдал/отозвал доступ», «кто скачал конфиг», «кто вошёл», «кто из админов заблокировал пользователя». Для self-hosted VPN-панели это базовое требование безопасности и разбора инцидентов. Нужна таблица событий, запись из сервисного слоя с актором из `Identity`, страница «События» с ролевой видимостью (owner — свои ресурсы, admin — всё) и фильтрами, плюс фоновой ретеншн.

### Что уже есть в коде (конкретные проверенные пути и механизмы)
- **Модели** — `backend/src/vpnhub/infra/db/orm/models.py`: строковые PK через `_id()` (`uuid.uuid4().hex[:16]`), базы `BaseTable` и `DatetimeColumnsMixin` из `sqlalchemy_foundation_kit`; epoch-время хранится как `Mapped[float]` (см. `Session.expires_at`, `Server.last_check_at`). Есть `User`(status pending|active|blocked), `Admin`(PK==FK users.id), `Session`, `Server`(owner_user_id), `Pool`, `Group`(owner_user_id), `GroupMember`, `Device`, `DeviceConfig`, `Setting`.
- **Актор** — `Identity` в `backend/src/vpnhub/services/auth.py:32` (`@dataclass`): поля `kind` (admin|user), `id`, `name`, `phone`, `role` (owner|member). Резолвится из cookie в `backend/src/vpnhub/api/deps.py` (`require_user`, `require_admin`, `current_identity`). IP/UA доступны через `client_meta(request)` там же.
- **UoW/репозитории** — `backend/src/vpnhub/infra/uow.py`: `UowTransaction.__init__` вручную инстанцирует репозитории (`admins`, `users`, `sessions`, `servers`, `pools`, `groups`, `devices`, `settings`); базовый `_Repo` в `backend/src/vpnhub/infra/repositories/__init__.py` (методы `get/all/add/delete`). Транзакции: `async with self.uow.transaction() as tx:` (запись) и `self.uow.query()` (чтение) — паттерн виден в `services/servers.py`, `services/configs.py`.
- **Точки инструментирования (реальные сигнатуры)**:
  - логин/логаут — `AuthService.login(...)` `auth.py:93` (создаёт `Session`), `AuthService.logout` `auth.py:165`;
  - вступление в группу — `GroupService.join(user_id, user_name, token)` `services/groups.py:125`; действия owner над членами — `add_member` `:85`;
  - генерация/скачивание конфига — `ConfigService.generate(...)` `services/configs.py:138`, вызывается из `POST /api/v1/configs` (`api/routers/member.py:64`); install/remove — `configs.py:366/387`;
  - выдача/отзыв клиента — `ServerAccessService.revoke_client` `services/server_access.py:251`, `rename_client` `:238`;
  - действия админа — `AdminService.update_user`/`delete_user` (`services/admin.py`, роутер `api/routers/admin.py:24/40`);
  - операции с серверами — `ServerService.create/update/delete` (`services/servers.py`, роутер `owner.py`).
- **Роутеры/DI** — роутеры собираются в `backend/src/vpnhub/api/routers/__init__.py` (`api_router.include_router(...)`); сервисы регистрируются в `backend/src/vpnhub/infra/di/__init__.py` (`AppProvider`, `provide(...)`, APP-scope). Зависимость `service(cls)` тянет сервис из Dishka.
- **Фоновые задачи** — `backend/src/vpnhub/api/entrypoint.py:78-105`: `AsyncIOScheduler`, джобы `backup-tick`, `server-monitor`, `server-sync` через `scheduler.add_job(..., "interval", ...)`. Одна реплика, без лидер-элекшена. Интервалы — из `Settings` (`api/config.py`).
- **Миграции** — `backend/migrations/versions/`, две: initial `ae99804150d1`, и `a1b2c3d4e5f6` (add error_code). Формат простой: `op.add_column/create_table`, `down_revision` цепочкой.
- **Сериализация** — `backend/src/vpnhub/common/serializers.py`: `rel_time(epoch)`, `session_to_dict`, `server_to_dict` и т.п. — сюда добавить `event_to_dict`.
- **Тесты создают схему из моделей** — `backend/tests/integration/conftest.py:39`: `await conn.run_sync(BaseTable.metadata.create_all)` на in-memory SQLite (StaticPool) + shim `timezone`. Значит новая модель попадает в тестовую схему автоматически, без правки conftest. Фабрики — `backend/tests/factories/`.
- **Фронт** — `frontend/src/lib/queries.ts` (весь API-слой, `http.get/post`), `frontend/src/nav.ts` (тип `Screen`, `screenToPath`/`pathToState`), `frontend/src/store.ts` (me/theme/viewRole/toast), экраны `frontend/src/screens/*.tsx`, UI-кит `frontend/src/components/ui.tsx`, токены `frontend/src/styles.css`. Экрана «События» и `Event`-типа сейчас **нет** — нужно добавить `"events"` в `Screen`, ветку в nav, `AuditEvent` в `lib/types.ts`, запрос в queries. Компонента «последние N событий» тоже нет — создаётся здесь и позже переиспользуется в Home.

### Дизайн решения
**Модель `AuditEvent`** (`models.py`), таблица `audit_events`:
- `id` (String(32), PK, default `_id`);
- `at: Mapped[float]` — epoch seconds (как `Server.last_check_at`), индекс для сортировки/ретеншна;
- `actor_kind` String(8) (admin|user|system), `actor_id` String(32) nullable+index, `actor_name` String(120) (денормализованный снимок, чтобы событие читалось после удаления пользователя);
- `type` String(48), index — стабильный код события из реестра (`auth.login`, `group.join`, `config.download`, `access.revoke`, `admin.user_update`, `server.create` …);
- `target_kind` String(24) nullable, `target_id` String(32) nullable+index — целевой ресурс;
- `owner_user_id` String(32) nullable+index — владелец затронутого ресурса (для ролевой фильтрации owner без джойнов; проставляется на записи);
- `meta_json: Mapped[str | None]` Text — доп. детали (ip, ua, имя устройства, старый/новый статус). **Развилка:** отдельные колонки vs JSON-строка — выбран JSON, т.к. набор полей событий разный, а SQLite-тесты не требуют JSONB. Индексы — обычные Text/String.

**Реестр типов** — модуль `backend/src/vpnhub/services/audit_types.py` (или константы в сервисе): набор строковых кодов + человекочитаемые русские подписи для фронта (подписи можно и на фронте — но код-константы держим на бэке, чтобы не расходились).

**Репозиторий `AuditRepo`** (`repositories/__init__.py`, `model = m.AuditEvent`): методы `add_event(...)` и `list(filters, limit)` с фильтрами по `type/actor_id/target_id/owner_user_id/at`-диапазону, сортировка `at desc`, лимит. Зарегистрировать в `UowTransaction.__init__` как `self.audit = AuditRepo(session)`.

**`AuditService`** (`services/audit.py`, зарегистрировать в DI `AppProvider`): `record(*, actor: Identity | None, type: str, target_kind=None, target_id=None, owner_user_id=None, meta: dict | None=None)` — записывает в **той же транзакции**, что и действие (принимает `tx` вариантом `record_tx(tx, ...)`), чтобы аудит и действие были атомарны; при отсутствии актора пишет `actor_kind="system"`. **Развилка:** писать событие в той же транзакции vs отдельной — выбрана та же (`record_tx(tx, ...)`), чтобы не плодить полусостояния; там где действие уже в `transaction()`, добавляем строку `tx.audit.add(...)`. `list_for(ident, filters)` — если `ident.kind=="admin"` без фильтра по owner, иначе `owner_user_id == ident.id`.

**API** — новый роутер `backend/src/vpnhub/api/routers/events.py`, включить в `routers/__init__.py`:
- `GET /api/v1/events` (`require_user`), query-параметры `type?`, `actor?`, `target?`, `since?`, `until?`, `limit?` (default 100, max 500). Внутри — `AuditService.list_for(ident, ...)`. Отдаёт `list[event_to_dict]`.
- (owner видит только события своих ресурсов через `owner_user_id`; admin — всё). Компактный режим — тот же эндпоинт с `limit=N` (для Home №10).

**UI** — экран `frontend/src/screens/Events.tsx`: таблица/список событий, фильтры (тип — select, период — since/until, актор/ресурс — текст), поллинг через `refetchInterval` (как в остальных экранах). Добавить `"events"` в `Screen` (`nav.ts`) + путь `/events`, пункт навигации (видим и owner, и admin). В `lib/queries.ts` — `listEvents(params)`; в `lib/types.ts` — `AuditEvent`. Компонент `EventList` (компактный «последние N») — переиспользуемый, кладём в `components/` или прямо в `Events.tsx` с экспортом, чтобы Home импортировал. Строки русские, захардкожены (i18n нет).

**Фоновая чистка** — джоба `audit-retention` в `entrypoint.py` (`scheduler.add_job(audit.purge_old, "interval", hours=..., id="audit-retention")`), идемпотентно удаляет события старше `settings.audit_retention_days` (новое поле в `api/config.py`, default напр. 90). Метод `AuditService.purge_old()` — `DELETE where at < cutoff`.

### Минимальный первый коммит (MVP) — узкий вертикальный срез
Таблица `audit_events` + миграция; `AuditRepo` в UoW; `AuditService.record_tx/list_for`; инструментировать 4 действия (`auth.login`, `group.join`, `config.download` в `ConfigService.generate`, `access.revoke` в `revoke_client`); `GET /api/v1/events` с ролевой фильтрацией и фильтром по `type`/периоду; экран `Events.tsx` + пункт навигации + `listEvents` + тип. Ретеншн-джоба, остальные точки инструментирования (admin/server-операции), фильтры по актору/ресурсу и компонент для Home — следующими коммитами. Всё зелёное: `make check`, `make test`, `make front-lint`.

### План реализации
- [ ] **Миграция**: новый файл в `backend/migrations/versions/` с `down_revision="a1b2c3d4e5f6"`, `op.create_table("audit_events", ...)` со всеми колонками и индексами (`at`, `type`, `actor_id`, `target_id`, `owner_user_id`); `downgrade` — `op.drop_table`.
- [ ] **Модель**: класс `AuditEvent(BaseTable, DatetimeColumnsMixin)` в `models.py` (поля выше).
- [ ] **Репозиторий**: `AuditRepo(_Repo)` в `repositories/__init__.py` (`add_event`, `list(filters,...)`), экспорт; `self.audit = AuditRepo(session)` в `uow.py` + импорт.
- [ ] **Сервис**: `services/audit.py` (`AuditService.record_tx`, `list_for`, `purge_old`), реестр кодов `audit_types.py`; регистрация `provide(AuditService)` в `di/__init__.py`.
- [ ] **Инструментирование**: в `AuthService.login`, `GroupService.join`, `ConfigService.generate`, `ServerAccessService.revoke_client` добавить `tx.audit.add(...)`/вызов сервиса в существующей транзакции; актор — из `Identity`/user_id.
- [ ] **API**: `routers/events.py` (`GET /api/v1/events`), включить в `routers/__init__.py`; `event_to_dict` в `common/serializers.py`.
- [ ] **Config**: `audit_retention_days` в `api/config.py`; джоба `audit-retention` в `entrypoint.py`.
- [ ] **Frontend**: `Screen "events"` + маршрут в `nav.ts`; `AuditEvent` в `lib/types.ts`; `listEvents` в `lib/queries.ts`; экран `screens/Events.tsx` + пункт навигации; компонент `EventList`.
- [ ] **Тесты**: см. ниже.
- [ ] **Docs**: строка в `docs/` (если есть раздел о наблюдаемости) — опционально, не блокирует.

### Как тестировать — на in-memory SQLite, без внешней инфры
- Схема поднимается автоматически (`BaseTable.metadata.create_all` в `tests/integration/conftest.py`) — правок conftest не требуется.
- `tests/integration/`: `AuditService.record_tx` пишет строку, поля актора/типа/owner корректны; `list_for` для admin возвращает все события, для owner — только с его `owner_user_id`; фильтр `type` и диапазон `since/until` работают; `purge_old` удаляет старьё и идемпотентен (повторный вызов — 0 удалений, без ошибок).
- Инструментирование: вызвать `ConfigService.generate` / `GroupService.join` / `ServerAccessService.revoke_client` через `uow`-фикстуру и убедиться, что появилось событие с ожидаемым `type`/`target`.
- Атомарность: если действие в транзакции падает, событие не сохраняется (rollback общий).
- Фронт: `make front-lint` (`tsc --noEmit`) — типы `AuditEvent`/queries согласованы. Логику nav можно покрыть существующим стилем юнит-тестов (`frontend/src/lib/*.test.ts`), если он есть для nav.

### Риски и подводные камни
- **Атомарность vs шум**: запись в той же транзакции — правильно, но нельзя логировать до успешного `flush` целевого действия; ставить `tx.audit.add(...)` после основной мутации.
- **Ролевая фильтрация owner** зависит от корректно проставленного `owner_user_id` на событии — для событий без ресурса (login) owner не должен видеть чужие; login-события owner о самом себе имеют `actor_id==owner`, но `owner_user_id` можно не ставить → owner login-события фильтруются по `actor_id`, а не только owner_user_id (учесть в `list_for`).
- **Денормализация имени**: `actor_name` — снимок; при переименовании пользователя старые события останутся со старым именем (это ожидаемо для аудита).
- **Рост таблицы**: без ретеншна таблица распухает; джоба обязательна, но одна реплика — дублирования джоб нет.
- **mypy/ruff** (`make check`): следить за типами `Mapped[float]`, `dict | None`, `Identity | None`; не ломать `builtins.list` (грабля из CI-памяти) — использовать `list[...]` из `__future__ annotations`.
- **SQLite**: не использовать JSONB/PG-специфику в модели — только Text/String/Integer/Boolean/float (как весь остальной код).

### Критерии приёмки
- Миграция применяется и откатывается; `audit_events` создаётся с индексами.
- Значимые действия (минимум login, join, config.download, access.revoke) порождают событие с корректным актором из `Identity`.
- `GET /api/v1/events`: admin видит все события, owner — только свои ресурсы; фильтр по типу и периоду работает; лимит соблюдается.
- Экран «События» доступен owner и admin, показывает список с поллингом и фильтрами; русские строки; переиспользуемый компактный список готов для Home.
- Фоновая чистка удаляет события старше ретеншна и идемпотентна.
- `make check`, `make test`, `make front-lint` — зелёные; изменения одним conventional-commit (`feat: audit log and events page`).

---

### Что реализовано в этом коммите (MVP)
- Модель `AuditEvent` + миграция `b2c3d4e5f6a7` (таблица `audit_events` с индексами `at/type/actor_id/target_id/owner_user_id`).
- `AuditRepo` (`add_event`, `list`, `purge_old`) в UoW; `AuditService` (`record_tx`, `list_for`, `purge_old`); реестр `audit_types.py`; регистрация в DI.
- Инструментированы: `auth.login`, `group.join`, `config.download` (в `ConfigService.generate`), `access.revoke` (в `revoke_client`).
- `GET /api/v1/events` (роутер `events.py`) с ролевой видимостью (admin — всё, owner — свои ресурсы/действия) и фильтрами `type/since/until/limit`; `event_to_dict` в сериализаторах.
- Config `audit_retention_days` (default 90) + фоновая джоба `audit-retention` (раз в сутки) в `entrypoint.py`.
- Фронт: тип `AuditEvent`, `listEvents`, экран `Events.tsx` + переиспользуемый `EventList`, пункт навигации «События», маршрут `/events`, иконка `events`.
- Тесты: `backend/tests/integration/services/test_audit.py` (запись, ролевая видимость, фильтры, ретеншн-идемпотентность, инструментирование login/join/revoke).

### Отложено на следующие коммиты
- Остальные точки инструментирования: admin-операции (`update_user`/`delete_user`), server-операции (`create/update/delete`), logout, rename_client, install/remove config.
- Фильтры по актору/ресурсу (`actor?`/`target?`) на API и в UI.
- Переиспользование `EventList` на экране Home (№10).
