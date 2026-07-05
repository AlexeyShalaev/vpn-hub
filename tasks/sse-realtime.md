## 4. SSE вместо поллинга

**Категория** Realtime / UX · **Сложность** L · **Зависимости** №1 (мониторинг статусов) и №10 (прогресс установки) выигрывают напрямую; изолированно ни от чего не зависит

### Зачем
Сейчас свежесть данных держится агрессивным поллингом: `frontend/src/screens/ServerDetail.tsx` опрашивает `GET /servers/{id}` каждые 2.5с (`status==="unknown"`) / 4с (есть протокол в `state==="installing"`) / 15с иначе, `frontend/src/screens/Servers.tsx` — каждые 20с (`refetchInterval: 20000`). Это лишний трафик, задержка отображения прогресса установки протокола и «дёрганый» UX. Цель — статусы provisioning/серверов/sync приходят пушем: прогресс установки виден без ручного рефреша, а поллинг остаётся тонким страховочным механизмом на случай обрыва SSE.

### Что уже есть в коде (конкретные проверенные пути и механизмы)
- Фоновые задачи и их запуск: `backend/src/vpnhub/api/entrypoint.py` (`lifespan`, `AsyncIOScheduler`, джобы `server-monitor` → `ServerService.run_tick`, `server-sync` → `SyncService.run_tick`, `backup-tick`; `app.state.dishka_container`, `app.state.scheduler`). Одна реплика, планировщик без лидер-элекшена — подтверждено.
- Провижининг и переходы состояния: `backend/src/vpnhub/services/provisioning.py` — фоновые задачи через `_spawn()` (`asyncio.ensure_future`, множество `_bg_tasks`); `mark_installing()` ставит `state="installing"`; успех — `state="installed"`, ошибка — `state="error"` + `error_code` (строки 144–202). Модель `ServerProtocol` (`backend/src/vpnhub/infra/db/orm/models.py:87`): поля `state` (`absent|installing|installed|error`), `error`, `error_code`, `pending_revoke_json`. Модель `Server` (`models.py:52`): `status` (`online|offline|unknown`), `latency`.
- Auth по cookie-сессии: `backend/src/vpnhub/api/deps.py` — cookie `vpnhub_session` (`COOKIE`), `current_identity()` / `require_user()` / `require_admin()` через `AuthService.resolve(token)` (`backend/src/vpnhub/services/auth.py:146`, `Identity(kind,id,name,phone,role)`). SSE будет авторизоваться так же.
- Роутеры: `backend/src/vpnhub/api/routers/__init__.py` собирает `owner`/`member`/`admin`/`auth`/`health`; префиксы `/api/v1` (owner/auth/member) и `/api/v1/admin`. Операционные эндпоинты без версии — `backend/src/vpnhub/api/routers/health.py` (`/healthz`, `/readyz`, `/metrics`, `/api/config`) — образец «тонкого» роутера.
- DI: `backend/src/vpnhub/infra/di/__init__.py` — `AppProvider` (Scope.APP), `provide(...)` для всех сервисов; шину событий регистрируем здесь как APP-синглтон.
- Frontend: `frontend/src/lib/queries.ts` — весь API-слой; `frontend/src/lib/api.ts` — `fetch(BASE + path, {credentials:"include", headers:{"X-Requested-With":...}})`, `BASE="/api/v1"`. `frontend/src/main.tsx` — `QueryClient` (`staleTime: 5000`, `refetchOnWindowFocus:false`). Ключи react-query: `["servers"]`, `["server", id]`, `["server-access", id]`, `["vpn-advanced", id, vtype]`, `["devices"]`, `["providers"]`, `["me"]` (по grep в `src/`). Инвалидация уже используется в мутациях (`ServerDetail.tsx`, `VpnAdvanced.tsx`).
- Обратный прокси: `deploy/compose/Caddyfile` — `reverse_proxy app:8000` без спец-настроек буферизации (Caddy по умолчанию SSE не ломает, но нужен `flush`/heartbeat — см. риски). `EventSource` укладывается в CSP `connect-src 'self'` из `entrypoint.py`.
- Тесты: `backend/tests/integration/conftest.py` — in-memory SQLite (`StaticPool`, `BaseTable.metadata.create_all`), фикстуры `engine`/`uow`; сервисные тесты гоняют UoW напрямую (`tests/integration/services/test_provisioning.py`, `test_sync.py`, `test_servers.py`). Роутеры-тесты HTTP-клиентом почти отсутствуют: `tests/unit/api/test_health.py` дергает функции-хендлеры напрямую, `test_static.py` строит `FastAPI` и шлёт свой ASGI-scope. **HTTP TestClient/httpx-фикстуры в проекте нет** — SSE-эндпоинт тестируем через прямой вызов генератора/логики, а не через реальный ASGI-стрим.

### Дизайн решения
**Шина событий (in-process, asyncio).** Новый `backend/src/vpnhub/infra/events.py`: класс `EventBus` с методами `publish(topic: str, entity_id: str | None = None)` и `subscribe() -> AsyncIterator[Event]`. Внутри — набор подписчиков, каждому свой `asyncio.Queue(maxsize=…)`; `publish` кладёт событие во все очереди (при переполнении — дропаем старейшее, событие лишь «сигнал инвалидации», потеря не критична). `Event` — dataclass `(topic, entity_id, ts)`. Функция форматирования в SSE-строку `format_sse(event) -> str` («`event: <topic>\ndata: <json>\n\n`») выносится отдельно и тестируется чисто. Регистрируем `EventBus` как APP-синглтон в `AppProvider` (`provide` возвращает один инстанс) — контейнер общий и для запросов, и для scheduler-джоб, так что publisher и subscriber видят одну шину.

- **Развилка: где хранить шину.** Вариант А — синглтон в Dishka (выбран): сервисы получают её через конструктор, тесты — тривиально. Вариант Б — глобальный модульный синглтон (как `_bg_tasks`): проще, но хуже для тестовой изоляции. Берём А; для мест, где сервис создаётся без DI, допускаем optional-параметр `bus: EventBus | None = None` (при `None` — no-op).
- **Развилка: топики.** Выбираем крупнозернистые топики-«сущности», а не per-id стримы: `server`, `sync`, `system`. `data` несёт `{"id": <server_id|null>}`. Фронт по `server` инвалидирует `["servers"]` и (если пришёл id) `["server", id]`, `["server-access", id]`, `["vpn-advanced", id, "*"]`. Так эндпоинт один, а точечность даёт клиент. Не гоняем полезную нагрузку с данными — только сигнал (требование задачи).
- **Точки публикации (backend).** (1) `ProvisioningService`: после `mark_installing` и в финале установки/ошибки протокола (строки ~150/190/202) — `bus.publish("server", server_id)`. (2) `ServerService.run_tick` (монитор) — после обновления статусов публикуем `server` (для затронутых id или один общий сигнал). (3) `SyncService.run_tick` — `publish("sync")` + `publish("server")` при изменениях. (4) Ручные операции в `owner.py` (`check`, `sync`, `vpn_op`, `protocol_op`) уже возвращают свежий объект — там пуш не обязателен (клиент-инициатор и так инвалидирует), но публикация полезна для других открытых вкладок; добавляем в сервисном слое, не в роутере.
- **SSE-эндпоинт.** Новый роутер `backend/src/vpnhub/api/routers/events.py`, `GET /api/v1/events`, авторизация через `current_identity` (401 если нет). Отдаёт `StreamingResponse(media_type="text/event-stream")` с заголовками `Cache-Control: no-cache`, `Connection: keep-alive`, `X-Accel-Buffering: no` (отключает буферизацию у nginx-подобных; для Caddy добавляем flush — см. риски). Генератор: на каждое событие из `bus.subscribe()` — `yield format_sse(...)`; каждые ~15с — heartbeat-комментарий `": ping\n\n"`, чтобы прокси/браузер держали коннект и мы замечали разрыв. Реагируем на `await request.is_disconnected()` для очистки подписки. Роль в фильтрации на MVP не участвует (member тоже может слушать `server`-события — они его касаются через `/me/available`); при желании позже фильтровать по видимости.
- **Frontend.** Новый `frontend/src/lib/events.ts`: `subscribeEvents(qc: QueryClient): () => void` — открывает `new EventSource("/api/v1/events", {withCredentials:true})`, на `server`-событие вызывает соответствующие `qc.invalidateQueries`, на `error`/close — авто-reconnect с backoff (EventSource и сам переподключается, но добавим ограничение и лог). Подключаем один раз на уровне авторизованного приложения (`frontend/src/app/App.tsx`, там где уже есть `useQueryClient`). **Fallback:** существующие `refetchInterval` НЕ удаляем — снижаем частоту (например, `ServerDetail`: installing 4с→10с, обычный 15с→60с; `Servers` 20с→60с) и держим их страховкой на случай, что SSE не доехал (Caddy буферизует / соединение оборвано). Строки — русские, захардкожены (i18n нет).

### Минимальный первый коммит (MVP)
Узкий вертикальный срез «прогресс установки виден вживую»:
1. `infra/events.py` — `EventBus` (publish/subscribe/`format_sse`) + регистрация синглтоном в `AppProvider`.
2. `api/routers/events.py` — `GET /api/v1/events` (cookie-auth, heartbeat, `X-Accel-Buffering:no`), включён в `api_router`.
3. Публикация `bus.publish("server", server_id)` в `ProvisioningService` на переходах `installing → installed/error`.
4. `frontend/src/lib/events.ts` + подключение в `App.tsx`: на `server`-событие инвалидируются `["server", id]`, `["servers"]`. Поллинг оставлен как fallback (частоту не трогаем в MVP или мягко снижаем).
5. Тесты шины и автопубликации при провижининге. `make check` (ruff+mypy), `make test`, `make front-lint` зелёные. Монитор/синк-публикация и снижение частот поллинга — следующими коммитами.

### План реализации
- [ ] Миграций НЕ требуется — новых полей/таблиц нет (сигнал, не персист). Явно отметить в описании коммита.
- [ ] backend: `infra/events.py` — `Event`, `EventBus.publish/subscribe`, `format_sse`; типизация под mypy (строгие сигнатуры, `AsyncIterator[Event]`).
- [ ] backend: зарегистрировать `EventBus` в `AppProvider` (`backend/src/vpnhub/infra/di/__init__.py`) как APP-синглтон; прокинуть в `ProvisioningService` (и опционально в `ServerService`/`SyncService`).
- [ ] backend: `api/routers/events.py` — `GET /api/v1/events`, `StreamingResponse`, cookie-auth через `current_identity`, heartbeat 15с, `X-Accel-Buffering:no`, обработка disconnect; подключить в `api/routers/__init__.py`.
- [ ] backend: вызовы `bus.publish("server", server_id)` в `ProvisioningService` (installing/installed/error); затем в `ServerService.run_tick` и `SyncService.run_tick` (`publish("sync")`).
- [ ] frontend: `lib/events.ts` — `subscribeEvents(qc)` через `EventSource`, маппинг топик→invalidateQueries, reconnect/backoff, cleanup.
- [ ] frontend: подключить в `app/App.tsx` (единожды, для авторизованного состояния); снизить `refetchInterval` в `ServerDetail.tsx`/`Servers.tsx` как fallback.
- [ ] tests: unit шины (`tests/unit/`), integration автопубликации через UoW+SQLite (`tests/integration/services/`).
- [ ] docs/deploy: в `deploy/compose/Caddyfile` при необходимости добавить `flush_interval -1` для `/api/v1/events`; отметить SSE в `deploy/README.md`/docs.

### Как тестировать (in-memory SQLite, без внешней инфры)
- **Unit шины (`tests/unit/`):** создать `EventBus`, оформить подписку, вызвать `publish("server", "sid")`, `await` получить событие из очереди подписчика — проверить `topic/entity_id`. Проверить `format_sse` (точный вид строки, `\n\n`-разделитель, корректный JSON в `data`). Проверить дроп при переполнении очереди и отсутствие взаимного влияния подписчиков.
- **Integration автопубликации (`tests/integration/services/`, фикстуры `uow`/`engine`):** сидлить `Server`+`ServerProtocol`, дать `ProvisioningService` шину, замокать SSH-слой как в существующем `test_provisioning.py`, прогнать установку → убедиться, что в шину пришло ≥1 события `server` с нужным id на переходах `installing`/`installed`/`error`. Аналогично точечный тест на `SyncService.run_tick` → событие `sync`.
- **SSE-эндпоинт:** т.к. HTTP-клиента в тестах нет, тестировать напрямую генератор-функцию эндпоинта с фейковым `EventBus` и фейковым `request.is_disconnected`: подать событие → получить корректно отформатированный chunk; отдельно — heartbeat и завершение по disconnect. Auth-ветку (нет cookie → `Unauthorized`) проверить прямым вызовом хендлера, как в `test_health.py`.
- **Frontend:** `make front-lint` (`tsc --noEmit`). Логику маппинга топик→ключи вынести в чистую функцию и покрыть vitest (в репозитории уже есть `*.test.ts`, напр. `lib/qr.test.ts`), мокая `EventSource` не обязательно.

### Риски и подводные камни
- **Буферизация Caddy.** Дефолтный `reverse_proxy` может копить ответ; для SSE добавить в `Caddyfile` matcher на `/api/v1/events` с `flush_interval -1` (streaming). `X-Accel-Buffering: no` помогает nginx, не Caddy — поэтому heartbeat + flush обязательны. Без этого события «залипают».
- **Одна реплика — намеренно.** Шина in-process; при масштабировании >1 реплики события не долетят до чужих подписчиков. Это допустимое ограничение продукта (одна реплика, планировщик без лидер-элекшена); зафиксировать в docs, не тащить Redis.
- **Утечки подписок.** Обязательно снимать подписку в `finally` генератора и реагировать на `request.is_disconnected()`; иначе очереди копятся при переоткрытии вкладок. Ограничить `maxsize` очереди и дропать старое.
- **Fallback не удалять.** Если убрать `refetchInterval`, при тихом обрыве SSE (прокси/сеть) UI замрёт. Оставляем поллинг с бОльшим интервалом.
- **CSRF/auth.** `EventSource` — это GET, под CSRF-middleware (`_UNSAFE_METHODS`) не попадает; заголовок `X-Requested-With` для GET не требуется. Auth — только cookie, что для SSE и нужно (EventSource не умеет кастомные заголовки).
- **mypy/ruff (CI).** Строго типизировать `AsyncIterator`/`StreamingResponse`; не забыть про грабли `list` vs метод (из MEMORY: `builtins.list`). Прогнать `uv run mypy src` до push.
- **StrictMode двойной эффект.** В `App.tsx` подключение `EventSource` в `useEffect` под React 19 StrictMode вызовется дважды в dev — гарантировать идемпотентность и cleanup, иначе два коннекта.

### Критерии приёмки
- `GET /api/v1/events` под валидной cookie-сессией отдаёт `text/event-stream`, шлёт heartbeat и события `server`/`sync`; без сессии — 401.
- При установке протокола на сервере (переход `installing → installed/error`) открытая вкладка `ServerDetail` обновляет статус БЕЗ ожидания поллинга (визуально в течение ~1–2с).
- При обрыве SSE UI продолжает обновляться за счёт fallback-поллинга (пониженной частоты).
- События несут только сигнал (`{topic, id}`), полные данные тянет react-query через инвалидацию ключей.
- Миграций нет; `make check`, `make test`, `make front-lint` зелёные; изменение — один conventional-commit (`feat: SSE realtime status updates`).

---

### Отклонения при реализации (факт кода)
- Путь `/events` уже занят аудит-логом (`api/routers/events.py`, задача «Аудит-лог»). SSE-эндпоинт вынесен в отдельный тонкий роутер `api/routers/realtime.py` → **`GET /api/v1/stream`** (auth через `current_identity`, heartbeat 15с, `X-Accel-Buffering:no`, завершение по `request.is_disconnected()`).
- Шина `infra/events.py` — **модульный синглтон** `get_event_bus()` (плюс регистрация в `AppProvider` как APP-синглтон, возвращающий тот же инстанс). Причина: `ProvisioningService` конструируется ad-hoc по всему сервисному слою (`ProvisioningService(uow, settings)`), не через DI; синглтон гарантирует, что publisher (ad-hoc-сервисы) и subscriber (SSE через DI) видят одну шину. Optional-параметр `bus: EventBus | None = None` в конструкторах сервисов дефолтит на синглтон.
- Dishka не резолвит `EventBus | None` (Optional) — для `ServerService`/`SyncService` заведены явные `@provide`-фабрики, инжектящие `EventBus`.
- Frontend `lib/events.ts` слушает `EventSource("/api/v1/stream")`; чистая функция `keysToInvalidate(topic, id)` покрыта vitest (`lib/events.test.ts`). Подключение — `useEffect(() => subscribeEvents(qc), [qc])` в `Shell` (авторизованное приложение), cleanup закрывает коннект (идемпотентно под StrictMode).
- Поллинг снижен как fallback: `ServerDetail` unknown 2.5с→10с, installing 4с→10с, обычный 15с→60с; `Servers` 20с→60с.
- Caddyfile: matcher `@sse path /api/v1/stream` + `reverse_proxy … { flush_interval -1 }`.
- Точки публикации: `ProvisioningService._install_one` (installed/error), `ServerService.run_tick` (при смене статуса), `SyncService.run_tick` (`sync` + `server` при `done>0`).
