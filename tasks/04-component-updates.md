# Задача №4. Обновление серверных компонентов с панели

Панель детектит устаревшие версии серверных VPN-компонентов и позволяет обновить их
кнопкой — идемпотентной пересборкой контейнера по SSH (`docker build --no-cache --pull`).

## Что реализовано (этот коммит)

### Детект «доступно обновление»
- `backend/src/vpnhub/infra/provisioning/component_versions.py` — новый модуль:
  - `LATEST_COMPONENT_VERSIONS` — эталон актуальной версии компонента КОНСТАНТОЙ
    (proto_id → тег). Обоснование: контейнеры собираются из bundled-Dockerfile'ов с
    прибитой версией бинарника (`ARG XRAY_RELEASE`, `ARG HYSTERIA_VERSION`), значит
    «актуальная» версия = та, что соберёт текущий релиз панели. Registry-API не нужен,
    сеть при sync не дёргаем; обновление эталона = правка Dockerfile + этой константы
    в одном релизе (тест сверяет их совпадение).
  - `read_running_version(ssh, spec)` — читает версию бинарника из запущенного
    контейнера (`xray version` / `hysteria version`) — best-effort, тем же SSH-каналом,
    что клиенты/трафик.
  - `parse_component_version()` — разбор вывода `<bin> version` (в т.ч. `app/v2.6.2` у
    hysteria).
  - `update_available(proto_id, running)` — чистая функция: эталон строго новее → True
    (сравнение через `infra.updates.parse_version`); неизвестная/актуальная → False.
- Поддержаны **xray, xray_xhttp, hysteria2** (у них есть версионируемый бинарник).
  AWG/OpenVPN/Outline собираются из `:latest`-образов без понятного номера версии —
  детект для них не заявляется (`latest_version` → None, бейдж не показывается).

### Хранение и отдача
- `ServerProtocol.image_version` — новая nullable-колонка (миграция
  `20260705_0016-...add_server_protocol_image_version.py`).
- `sync.py` — в фазе чтения состояния читает версию компонента и пишет её в
  `image_version` (best-effort, не влияет на revoke/reconcile-решения).
- `serializers.protocol_to_dict` отдаёт `imageVersion`, `latestVersion`,
  `updateAvailable`.

### UI (owner)
- `frontend/src/lib/types.ts` — поля `imageVersion/latestVersion/updateAvailable` в `Protocol`.
- `ServerDetail.tsx` — per-protocol: бейдж «обновление» (title `текущая → эталон`) +
  кнопка «Обновить».
- `queries.ts` — `updateProtocol(id, proto)` → `POST /servers/{id}/protocols/{proto}/update`.

### Операция обновления (SSH)
- `ServerService.update_protocol` (роутится через существующий `protocol_op` с `op=update`):
  разрешена только когда `update_available` истинно (иначе no-op, не трогаем рабочий
  контейнер), помечает протокол `installing` и запускает фоновую переустановку
  (`schedule_install`). Install уже гоняет `docker build --no-cache --pull` → тянет свежий
  бинарник и пересоздаёт контейнер с теми же портом/конфигом — идемпотентно.

### Тесты
- `tests/unit/infra/provisioning/test_component_versions.py` — парсинг версий,
  `update_available` (older→True, equal/newer/unknown/unsupported→False), сверка
  эталонов-констант с `ARG`-версиями в Dockerfile'ах.
- Обновлён `tests/unit/common/test_serializers.py` под новые поля.

Зелёно: `make check`, `make test` (921), `make front-lint`.

## Что осталось (remaining)

- **Сохранение клиентов при обновлении.** Ключи/clientsTable в xray/hysteria2 лежат
  ВНУТРИ образа (не host-volume), поэтому пересборка контейнера теряет заведённых
  клиентов; их переустановка после rebuild сейчас не выполняется автоматически. Нужен
  либо recreate с переносом состояния (вынести clientsTable/материал на host-volume и
  монтировать), либо пост-rebuild реконсиляция — переустановить всех активных клиентов
  протокола из наших `DeviceConfig`. Кнопка сейчас — безопасный скелет под явным флагом
  обновления; до реализации переноса состояния использовать осознанно.
- **Registry API.** Узнавать самый свежий апстрим-тег на лету (Docker Hub / GitHub
  releases) вместо константы — чтобы «доступно обновление» реагировало без релиза панели.
- **Автообновления по расписанию.** Фоновая проверка + опциональный авто-апгрейд (по
  образцу sync-тика / watchtower для Outline).
- **Детект для AWG/OpenVPN/Outline.** Сейчас `:latest` без номера версии — можно
  сравнивать image digest (`docker inspect --format '{{.Image}}'`) с эталонным digest.
- **Дайджест вместо тега** для xray/hysteria (пиннинг по sha256 — устойчивее к
  ре-тегам апстрима).
