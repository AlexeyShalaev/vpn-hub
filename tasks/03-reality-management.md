# Управление Reality (shortId, SNI/dest, проверка домена)

**Категория** provisioning/UX · **Сложность** M · **Зависимости** паттерн «редактируемые параметры протокола + reprovision + UI», заданный ЗАДАЧЕЙ №2 (AWG-обфускация, коммит b8b2c0f). Здесь тот же паттерн для Xray/Reality.

## Зачем
Xray-Reality (VLESS+REALITY) маскируется под чужой TLS-домен (SNI/dest) и различает shortId. Эти значения генерятся один раз при установке контейнера и недоступны для правки. Владельцу нужно уметь ротировать shortId и менять маскировочный домен из панели — например, если выбранный домен заблокирован или перестал отдавать TLS 1.3. Смена обязана согласованно перегенерировать серверную сторону (переписать `realitySettings` + рестарт Xray), после чего клиенты должны заново скачать конфиг.

## Что уже есть в коде (переиспользовано)
- Материал Xray (`short_id`, `site`, `xray_public_key`, `bootstrap_uuid`) хранится в `ServerProtocol.material_encrypted` (шифр мастер-ключом), а НЕ в `params_json` — в отличие от AWG. Отдельного поля/миграции не нужно.
- `XrayProvisioner` (`infra/provisioning/provisioners/xray.py`): уже читает/пишет `server.json` (`_read_server_json`/`_write_and_restart`), рестартит контейнер при смене клиентов.
- `realitySettings` в `server.json` — блок `dest`/`serverNames`/`shortIds`/`privateKey` (см. `scripts/xray/configure_container.sh`).
- Роутер `owner.py`: паттерн `PATCH /servers/{sid}/protocols/{proto}/params` (из №2).
- `ServerAccessService.vpn_advanced` отдаёт публичный материал в `proto.keys`; фронт-тип `VpnAdvancedProtocol.keys`.
- Экран `VpnAdvanced.tsx`: паттерн `ObfuscationForm` (details + warning-баннер + мутация + disable при offline).

## Дизайн решения (по аналогии с №2)
**Модель/миграция.** Изменений схемы нет — используем существующий `material_encrypted`. `short_id`/`site` в `ServerMaterial` уже есть.

**Чистое ядро `infra/provisioning/reality.py`** (без SSH/IO):
- `gen_short_id()` — 8 байт → 16 hex.
- `validate_short_id(s)` — hex чётной длины 2..16, нормализует регистр/пробелы; иначе `errors.make("invalid_reality", ...)`.
- `validate_sni(s)` — формат FQDN (метки RFC, есть точка, зона не число), нормализует к нижнему регистру без хвостовой точки.
- `rewrite_reality(doc, short_id, sni)` — возвращает копию `server.json` с обновлёнными `realitySettings.dest`/`serverNames`/`shortIds`; `clients` (uuid) и `privateKey` не трогаются.

**Reprovision серверной стороны.** `XrayProvisioner.set_reality(ssh, short_id, sni)`: прочитать `server.json`, переписать `realitySettings`, `_write_and_restart` (у Reality нет hot-reload — рестарт роняет активные сессии, но клиенты/uuid сохраняются), вернуть обновлённый `ServerMaterial`.

**Сервисный слой.** `ProvisioningService.set_reality(server, sp, short_id, sni)` — SSH-обёртка (грузит `XrayProvisioner`). `ServerService.set_reality(owner_id, sid, proto_id, rotate_short_id?, short_id?, sni?)`: проверка kind=xray/владения/online/running; сборка целевых shortId (ротация→gen, явный→validate, иначе текущий) и SNI (validate или текущий/дефолт); порядок «validate → SSH → БД» — при SSH-ошибке `material_encrypted` не меняется; запись обновлённого материала.

**Валидация домена.** Синхронная проверка формата SNI при сохранении (`validate_sni`). Реальная сетевая проверка TLS 1.3 / доступности домена — в remaining.

**API.** `PATCH /servers/{sid}/protocols/{proto}/reality`, body `{ "rotate_short_id"?: bool, "short_id"?: str, "sni"?: str }`.

**UI.** В `VpnAdvanced.tsx` для xray/xray_xhttp — `RealityForm`: текущий shortId + кнопка «Ротировать shortId», поле SNI + «Применить SNI», warning-баннер (рестарт оборвёт сессии, конфиги нужно перескачать), disable при остановленном протоколе. Query-хелпер `setReality`. `short_id`/`site` добавлены в `_PUBLIC_MATERIAL` (они и так публичны в vless://-ссылке) для префилла формы.

## Реализовано в этом коммите (MVP)
Бэкенд: `reality.py` (`gen_short_id`/`validate_short_id`/`validate_sni`/`rewrite_reality`); `XrayProvisioner.set_reality`; `ProvisioningService.set_reality`-обёртка; `ServerService.set_reality`; роут `PATCH .../reality`; error_code `invalid_reality`; `short_id`/`site` в публичном материале.
Фронт: `RealityForm` (ротация shortId + смена SNI) в `VpnAdvanced.tsx` с warning-баннером; query-хелпер `setReality`.
Тесты: юнит на `validate_short_id`/`validate_sni`/`rewrite_reality` (клиенты не трогаются); сервис-тест ротации shortId и смены SNI через фейковый провизионер + BadRequest для не-xray, offline и невалидного SNI.

Миграции: не требуются (материал уже в `material_encrypted`; тесты используют `metadata.create_all`).

## Критерии приёмки
- `PATCH .../reality` с `rotate_short_id`/`sni` для xray/xray_xhttp: переписывает `realitySettings`, рестартит контейнер, сохраняет обновлённый материал; клиенты (uuid) сохранены.
- Для не-xray и для offline/не установленного протокола — 400 BadRequest.
- Невалидный SNI (без точки / плохие символы / зона-число) и невалидный shortId (нечёт/нехекс/длинный) отклоняются с понятным сообщением.
- `make check`, `make test`, `make front-lint` зелёные.

## Осталось (вне этого коммита)
- Реальная сетевая проверка пригодности домена для Reality (TLS 1.3 handshake, доступность :443) — синхронный probe при сохранении и/или фоновая периодическая проверка со сменой статуса протокола.
- Планировщик периодической переоценки маскировочного домена (см. паттерн check_server).
- Управление несколькими shortId/serverNames (сейчас массивы из одного элемента).
