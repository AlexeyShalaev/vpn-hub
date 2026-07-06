## 18. Лимиты — Этап 1: лимит числа конфигов на протоколе сервера

**Категория** Лимиты · **Сложность** M · **Зависимости** нет (первый этап системы лимитов)

### Зачем
Владельцу нужно уметь ограничить число конфигов (клиентов) на конкретном протоколе сервера — чтобы не раздувать сервер и держать его лёгким. Панель раньше НИКАК не ограничивала выдачу.

### Важная поправка (по итогам разведки)
«Жёсткого 254 у WG/OpenVPN», как казалось, НЕТ:
- **AmneziaWG** (`ipalloc.next_client_ip`) НАМЕРЕННО растёт за /24 (10.8.1.254→10.8.2.1→…), mirror Amnezia `wireguardConfigurator.cpp`, есть тест `wraps_to_next_subnet`. Пиры /32 маршрутизируются (cryptokey routing). → физического предела конфигов нет, `ipalloc` НЕ трогаем.
- **OpenVPN**: реальный предел — его пул /24 (~253), держит сам openvpn.
- **Xray/Hysteria2/Outline**: без предела.

Поэтому Этап 1 — не «жёсткий subnet-cap», а **настраиваемый владельцем мягкий лимит** (panel soft-cap), применимый к любому протоколу; null = без лимита.

### Что реализовано
- **Модель**: `ServerProtocol.max_clients: int | None` (nullable, null = без лимита) + миграция `e1f2a3b4c5d6`.
- **Занятость**: `services/limits.py::used_clients(session, sp)` = активные `DeviceConfig` (status=active, с client_id, по `spec.label` протокола) + `sp.external_clients`. `over_limit(used, max)` — предикат «выдавать новый нельзя».
- **Enforcement**: в `services/configs.py::_generate_provisioned` перед выдачей НОВОГО конфига (existing is None) — если `max_clients` задан и `used >= max` → `BadRequest` с внятным текстом. Уже выданные/переиздаваемые (existing) не блокируются.
- **API**: `vpn_advanced` отдаёт `maxClients`/`usedClients` на протоколе; `PATCH /servers/{sid}/protocols/{proto}/limit` (owner) body `{maxClients:int|null}` (0/null → снять) → `ServerService.set_protocol_limit` (только БД, без SSH).
- **UI**: в `VpnAdvanced.tsx` на каждом протоколе — `LimitForm`: «Клиентов: used / max» (жёлтый на ~80%, красный на 100%) + поле «Лимит конфигов» (пусто = без лимита) + Сохранить. Для openvpn — хинт про пул ≈253.
- **Тесты**: `test_limits.py` — over_limit-кейсы + used_clients (active+external, revoked/пустые/чужой прото не в счёт).

### Как тестировать
На in-memory SQLite: used_clients считает верно; enforcement — через over_limit (та же логика, что в configs). Живьём: задать лимит в advanced протокола, попробовать выдать конфиг сверх → ошибка.

### Осталось
- **Bundle**: если конфиг бандлит несколько amnezia-протоколов, проверка сейчас на основном запрошенном; докрутить проверку по каждому протоколу бандла.
- **Этап 2**: лимит устройств на пользователя (`settings.default_devices_per_user`=5, override группа/юзер, проверка при добавлении устройства).
- **Этап 3 (позже)**: лимит байт per (user, server) — данные уже собираются (traffic_samples).
