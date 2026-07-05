# Задача 05 — Мультихоп / цепочки серверов (entry → exit)

Клиент подключается к **entry**-серверу (например, с российским IP у нужного провайдера), а трафик
выходит в интернет через **exit**-сервер в другой стране. Юзкейсы: вход с локальным IP, сокрытие
адреса exit от локального провайдера.

## Выбранный вариант: (а) Xray outbound chaining

| Вариант | Суть | Вердикт |
|---|---|---|
| **(а) Xray outbound** | outbound entry-контейнера = vless-коннект на exit (entry становится обычным vless-клиентом exit) | **выбран** — чисто конфигом двух xray, без ядра/маршрутизации; переиспользует `_read_server_json`/`_write_and_restart` (как `set_reality` из cf238d8) и штатный `add_client` на exit |
| (б) WG-туннель + policy routing | ip rule/fwmark/NAT между серверами | сложно: правка ядра/маршрутизации, отдельный туннель, хрупко в проде |
| (в) Цепочка на клиенте | два хопа настраивает само приложение | отпадает — клиентские приложения обычно так не умеют |

Вариант (а) укладывается в текущую архитектуру буквально паттерном `set_reality`: правим один
`outbounds`-раздел живого `server.json` и рестартим контейнер. Поэтому он реализован **по-настоящему**,
а не остовом.

## Схема трафика

```
клиент ──vless/Reality──▶ entry (RU, amnezia-xray)
                              │  outbound больше не freedom, а
                              ▼  vless+Reality на exit (uuid, заведённый add_client-ом)
                          exit (NL, amnezia-xray) ──freedom──▶ интернет
```

Локальный провайдер клиента видит только соединение с entry; адрес exit ему не виден. Выходной IP в
интернете — это IP exit-сервера.

## Что реализовано

- **Модель `ChainLink`** (`entry_server_id`, `exit_server_id`, `proto=xray`, `exit_client_id`,
  `state`, `error`) + уникальность `(entry_server_id, proto)` — один outbound на entry-протокол.
  Миграция Alembic `f6a7b8c9d0e1` (линейно за `e5f6a7b8c9d0`).
- **Провизионер** `XrayProvisioner.set_outbound_chain` / `clear_outbound_chain` — переписывают
  `outbounds` живого `server.json` (`freedom` ⇄ vless-outbound на exit) + рестарт контейнера.
  Чистый билдер `vpn_uri.build_chain_outbound` (юнит-тест).
- **Оркестрация** `services/multihop.py::ChainService`:
  - валидация: оба сервера owned + online, tcp-Reality Xray installed+running с обеих сторон,
    entry ≠ exit, нет уже существующей цепочки;
  - `create`: `add_client` на exit → uuid, `set_chain` на entry; при сбое второго шага — откат
    клиента exit (не копим висячие uuid);
  - `delete`: `clear_chain` на entry + `revoke_client` на exit (оба best-effort) + удаление связки.
- **Эндпоинты**: `GET/POST /servers/{sid}/chains`, `DELETE /servers/{sid}/chains/{chain_id}`.
- **UI**: секция «Цепочка (мультихоп)» на странице сервера — выбор выходного сервера из подходящих
  (свой, онлайн, с запущенным Xray), создание/удаление, статус связки. Секция скрыта, если на entry
  нет запущенного Xray.
- **Тесты**: `test_multihop_service.py` (оркестрация/валидация/откат/каскад на in-memory SQLite с
  фейковым провизионером) + `test_chain_outbound.py` (чистый билдер outbound).

## Что осталось (вне первого коммита)

- **Материал exit из БД хранит только публичный** (`xray_public_key`/`short_id`/`site`) — этого хватает
  для vless-outbound. Но `exit_port` берётся из `ServerProtocol.port`; при нестандартном порту/смене
  Reality на exit цепочку нужно пересобрать (сейчас — вручную: удалить/создать).
- **Реакция на смену Reality/миграцию exit**: при `set_reality`/`migrate` exit-сервера цепочки на его
  entry не переприменяются автоматически — стоит добавить reconcile (перечитать материал и переписать
  outbound entry) или помечать связку `state=error`.
- **Только `xray` (tcp-Reality)**: `xray_xhttp`/awg/openvpn/outline как звенья цепочки не поддержаны.
- **Каскад при удалении сервера**: FK `ondelete=CASCADE` убирает строку `ChainLink`, но не снимает
  outbound/клиента по SSH (сервер и так удаляется). Для entry, оставшегося жить, — см. reconcile выше.
- **Цепочки длиннее 2 звеньев** (entry → mid → exit) — модель допускает по звену, оркестрация пока нет.
