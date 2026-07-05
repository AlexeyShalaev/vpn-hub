# Настройка обфускации AmneziaWG из UI

**Категория** provisioning/UX · **Сложность** L · **Зависимости** общий механизм «параметры протокола» (эта задача задаёт его первую конкретную реализацию для AWG; xray-параметры переиспользуют тот же роут-паттерн `/protocols/{proto}/params`)

## Зачем
Сейчас obfuscation-параметры AmneziaWG (Jc, Jmin, Jmax, S1, S2, S3, S4, H1–H4) генерируются один раз случайно при установке контейнера и недоступны для правки. Владельцу нужно уметь задавать их вручную и применять готовые пресеты (по умолчанию / агрессивный / под мобильные сети), чтобы подстраивать маскировку трафика под конкретную сеть/DPI. Смена параметров обязана согласованно перегенерировать серверную сторону и заставить клиентов получить новые значения, иначе handshake сломается.

## Что уже есть в коде
- Модель `ServerProtocol` (`backend/src/vpnhub/infra/db/orm/models.py`) уже имеет `params_json: Mapped[str | None]` — JSON AwgParams. Отдельного поля/миграции добавлять НЕ нужно; колонка есть и в initial-миграции.
- `backend/src/vpnhub/infra/provisioning/awg_params.py`: `@dataclass AwgParams` со всеми полями jc/jmin/jmax/s1–s4/h1–h4/i1–i5/subnet; методы `script_vars()`, `config_json()`, `as_dict()`, `from_dict()`, `from_server_conf()`; функция `generate(is_awg2, rng)`. Валидатора и пресетов ПОКА НЕТ — их надо добавить.
- Провизионер `AwgProvisioner` (`backend/src/vpnhub/infra/provisioning/provisioners/awg.py`): держит `params`, `_syncconf(ssh)`, `add_client`/`revoke_client` правят живой `server_config_path`. Клиентский артефакт строится из `self.params` на лету.
- Оркестрация `ProvisioningService` (`backend/src/vpnhub/services/provisioning.py`): `loaded_provisioner(sp)` собирает AwgProvisioner из `sp.params_json`+material; `_install_one` пишет `sp.params_json`.
- Роутер `owner.py`: `POST /servers/{sid}/protocols/{proto}/{op}` → `ServerService.protocol_op`.
- `ServerAccessService.vpn_advanced` уже отдаёт `params` каждого протокола в ответе; фронт-тип `VpnAdvancedProtocol.params`.
- Экран `frontend/src/screens/VpnAdvanced.tsx`: блок «Параметры обфускации» показывал params read-only в `<details>`.

## Дизайн решения
**Модель/миграция.** Изменений схемы нет — используем существующий `params_json`. Пресеты не храним в БД, только их применённый результат.

**Пресеты и валидация (чистое ядро в `awg_params.py`).**
- `PRESETS: dict[str, dict[str,str]]` c ключами `default`, `aggressive`, `mobile`. Пресет задаёт только редактируемые obfuscation-поля (jc/jmin/jmax/s1–s4/h1–h4), а subnet/i1–i5/protocol_version берутся из текущего `AwgParams` сервера. `default` = «сгенерировать заново».
- `validate(params, is_awg2)` — поднимает `errors.make("invalid_params", ...)`: Jc∈[1,10], Jmin<Jmax, S1/S2∈[1,1000] и запрет равных размеров пакетов (`S1+148==S2+92` и для awg2 с S3), Sx уникальны; H1–H4 — целые >4 (для legacy) либо диапазоны «a-b» (для awg2), попарно различны.
- `merge_editable(current, patch)` — накладывает только редактируемые ключи на копию текущего.
- `rewrite_interface_params(conf_text, params, is_awg2)` — переписывает obfuscation-строки в `[Interface]` живого `awg0.conf`, не трогая `[Peer]`.

**Reprovision серверной стороны.** Выбран вариант B: переписать obfuscation-строки в `[Interface]` живого `awg0.conf` по SSH и выполнить `syncconf` — пиры сохраняются, простой ~секунды. `AwgProvisioner.set_params(ssh, new_params)`.

**Сервисный слой.** `ServerService.set_protocol_params(owner_id, sid, proto_id, preset|values)`: проверка kind=wireguard, владения, online-сервера и running-протокола; сборка целевого `AwgParams` (default→новый generate с сохранением subnet, иначе merge_editable), `validate`; вне транзакции SSH-применение через `ProvisioningService.set_protocol_params`; в транзакции запись `params_json`. При SSH-ошибке params_json НЕ меняется.

**API.** `PATCH /servers/{sid}/protocols/{proto}/params`, body `{ "preset"?, "values"? }`.

**UI.** В `VpnAdvanced.tsx` для awg/awg_legacy — форма: кнопки трёх пресетов + поля ручного ввода, warning-баннер о необходимости заново скачать конфиги, disable при остановленном протоколе. Query-хелпер `setProtocolParams`.

## Реализовано в этом коммите (MVP)
Бэкенд: `PRESETS` + `validate` + `merge_editable` + `rewrite_interface_params` в `awg_params.py`; `AwgProvisioner.set_params` и `ProvisioningService.set_protocol_params`-обёртка; `ServerService.set_protocol_params`; роут `PATCH /servers/{sid}/protocols/{proto}/params`; error_code `invalid_params`.
Фронт: форма пресетов + ручной ввод в `VpnAdvanced.tsx` с warning-баннером, query-хелпер `setProtocolParams`.
Тесты: юнит на `validate`/`merge_editable`/`rewrite_interface_params` (15 кейсов); сервис-тест смены пресета `aggressive` через фейковый провизионер + BadRequest для не-wireguard и offline.

Миграции: не требуются (колонка `params_json` уже есть; тесты используют `metadata.create_all`).

## Критерии приёмки
- `PATCH /servers/{sid}/protocols/{proto}/params` с `preset` или `values` для awg/awg_legacy: переписывает `[Interface]` в awg0.conf, делает syncconf, сохраняет валидированные значения в `params_json`, пиры сохранены.
- Для xray/openvpn/outline/hysteria2 и для offline/не установленного протокола — 400 BadRequest.
- Некорректный ручной набор (дубликаты Sx / равные размеры / Jmin≥Jmax) отклоняется с понятным сообщением.
- `make check`, `make test`, `make front-lint` зелёные.

## Осталось (вне этого коммита)
- Ветвление формы для awg2-диапазонов H (сейчас поля принимают «a-b», но без явного UI-хинта).
- E2e/визуальная проверка disable-состояния при offline (сейчас гейтится по `proto.running`).
