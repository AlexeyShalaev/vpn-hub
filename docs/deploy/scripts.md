# Скрипт установки

`install.sh` разворачивает панель на **Docker Compose** одной командой и без вопросов: проверяет
окружение, кладёт compose-файлы, сам генерирует секреты, поднимает стек и **ждёт, пока панель
реально ответит**. Всё, что нужно решить человеку, укладывается в один флаг — **профиль**.

## Три профиля

| Профиль | Команда | Что получаете |
|---|---|---|
| **Локально** (по умолчанию) | `curl -fsSL …/install.sh \| bash` | панель на `http://localhost:8000`, порт только на этой машине |
| **VPS с доменом** | `… \| bash -s -- --domain vpn.example.com` | **HTTPS сразу**: Caddy + Let's Encrypt, порт наружу не торчит |
| **По IP без HTTPS** | `… \| bash -s -- --lan` | `http://IP:8000` на всех интерфейсах — для теста/LAN, не для интернета |

=== "Локально попробовать"

    ```sh
    curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.sh | bash
    ```

=== "VPS с доменом (HTTPS)"

    ```sh
    curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.sh \
      | bash -s -- --domain vpn.example.com     # ← подставьте свой домен
    ```

    Скрипт сам: скачает Caddy-оверлей, подставит домен, включит `VPNHUB_TRUSTED_PROXY`,
    проверит DNS-запись и занятость портов 80/443, а в конце напечатает, что осталось
    сделать (обычно — A-запись в DNS и открыть 80/443 на файрволе). Сертификат Caddy
    выпустит автоматически, как только домен укажет на сервер.

=== "Безопаснее (скачать → прочитать → запустить)"

    ```sh
    curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.sh -o install.sh
    less install.sh          # прочитайте, что скрипт собирается сделать
    bash install.sh --domain vpn.example.com
    ```

    Схема `curl … | bash` выполняет код, который вы не видели. Вариант со скачиванием даёт
    момент проверить содержимое; ещё осторожнее — сначала [`--dry-run`](#dry-run).

В конце скрипт печатает адрес панели, напоминание про мастер-ключ и — последней строкой —
машиночитаемый JSON (`{"url":…,"dir":…,"profile":…}`) для автоматизации.

!!! danger "Мастер-ключ генерирует скрипт — сохраните его"
    В `<каталог>/.env` появляется `VPNHUB_MASTER_KEY` — из него выводятся ключи шифрования
    **SSH-доступов к вашим серверам** и **резервных копий**. **Потеря необратима.** Сразу после
    установки скопируйте значение в менеджер паролей отдельно от сервера. Файл `.env` создаётся
    с правами `0600` — не коммитьте его.

!!! info "Ставите по SSH с профилем по умолчанию?"
    Порт слушает только `127.0.0.1` — с вашего ноутбука адрес не откроется. Скрипт сам заметит
    SSH-сессию и подскажет три выхода: SSH-туннель (`ssh -L 8000:127.0.0.1:8000 …`), `--domain`
    или `--lan`.

## Повторный запуск = настройка

`.env` идемпотентен: секреты никогда не перезаписываются. Но **явно переданные флаги** меняют
конфигурацию существующей установки — скрипт печатает дифф «старое → новое»:

```console
$ bash install.sh --domain vpn.example.com
[ ok ] COMPOSE_FILE: compose.yaml → compose.yaml:caddy.compose.yaml
[ ok ] VPNHUB_BASE_URL: http://localhost:8000 → https://vpn.example.com
[ ok ] VPNHUB_DOMAIN = vpn.example.com
```

Так локальная установка «дорастает» до HTTPS одной командой. Обратно — `--local`. Не меняются
повторным запуском только **мастер-ключ** и **база данных** (см. [ниже](#immutable)).

!!! warning "Env-переменные при повторном запуске не считаются"
    На существующей установке конфигурацию меняют **только флаги CLI** — переменные окружения
    учитываются лишь при первой установке (чтобы случайно «прилипшая» в профиле шелла
    `VPNHUB_BASE_URL` не переписала рабочую панель).

## Флаги

Каждый флаг имеет env-эквивалент (в скобках) — удобно для cloud-init/Terraform.

| Флаг | По умолчанию | Что делает |
|---|---|---|
| `--local` / `--lan` / `--domain D` | `--local` | Профиль (взаимоисключающие, см. выше). (`VPNHUB_LAN`, `VPNHUB_DOMAIN`) |
| `--external-db DSN` | — | Не поднимать свой Postgres; подключиться к внешнему (`DATABASE_URL`). Только при новой установке. |
| `--tag TAG` | `latest` | Тег образа: `latest`, `1.2.3`, `1.2` (`VPNHUB_TAG`). |
| `--master-key HEX` | генерируется | Свой мастер-ключ — для переноса/восстановления; только при новой установке (`VPNHUB_MASTER_KEY`). |
| `--admin-phone P` + `--admin-password W` | setup-экран | Создать администратора при старте — строго **парой** (`VPNHUB_ADMIN_PHONE/PASSWORD`). |
| `--base-url URL` | по профилю | Публичный адрес вручную (`VPNHUB_BASE_URL`). |
| `--http-addr ADDR` | по профилю | Куда публиковать порт хоста, вид `host:port` (`VPNHUB_HTTP_ADDR`). |
| `--dir PATH` | `$HOME/vpn-hub` | Каталог установки (`INSTALL_DIR`). Он же нужен `update.sh`/`uninstall.sh`. |
| `--ref REF` | `master` | Ветка/тег репозитория, откуда качаются compose-файлы (`VPNHUB_REF`). |
| `--no-pull` | — | Не тянуть образы заранее (CI/air-gapped) (`VPNHUB_NO_PULL`). |
| `--dry-run` | — | Показать действия, ничего не выполняя (`VPNHUB_DRY_RUN`). |

Скрипт валидирует ввод **до** каких-либо изменений на диске: обрезает случайно вставленную
схему у домена (`https://Foo.Bar.com/x` → `foo.bar.com`), отказывается от литерального
`vpn.example.com`, проверяет пару админа и формат `host:port`.

### Внешняя база данных

```sh
bash install.sh --domain vpn.example.com \
  --external-db 'postgresql+asyncpg://vpnhub:PA%40ss@db.example.com:5432/vpnhub?ssl=require'
```

DSN тоже проверяется до установки: `postgres://` и `postgresql://` автоматически переписываются
на обязательный `postgresql+asyncpg://` (с предупреждением), при отсутствии `ssl=` для
не-локального хоста скрипт напомнит про `?ssl=require`, а `$` в пароле экранируется для compose.
Спецсимволы URL-кодируйте (`@`→`%40`, `:`→`%3A`). Подробнее — [Внешняя база данных](external-db.md).

### Перенос и восстановление {#immutable}

**Мастер-ключ** и **база** существующей установки скриптом не меняются — это защита от потери
данных. Перенос на новую машину: снимите `.vhb`-бэкап, поставьте панель заново с
`--master-key <ваш прежний ключ>` и восстановитесь из бэкапа
([Первый запуск → Из бэкапа](../guide/first-run.md#restore)).

### Предпросмотр без изменений {#dry-run}

```sh
bash install.sh --dry-run --domain vpn.example.com
```

Печатает все шаги (что скачает, что запишет в `.env`, какие команды выполнит), ничего не делая.
Не требует Docker и сети.

## Как это устроено внутри

- Скрипт пишет в `.env` строку `COMPOSE_FILE=compose.yaml:caddy.compose.yaml` (для `--domain`) —
  Docker Compose читает её сам, поэтому `update.sh`, `uninstall.sh` и любой `docker compose …`
  из каталога установки всегда видят **весь** стек. Двойной `-f` не нужен.
- Домен попадает в `Caddyfile` через плейсхолдер `{$VPNHUB_DOMAIN}` — файл не редактируется.
- Вместе с секретами генерируется `VPNHUB_METRICS_TOKEN` — `/metrics` закрыт с первого запуска
  ([Переменные окружения](configuration.md)).
- После `up` скрипт ждёт `/healthz` (до 2 минут: на первом старте идут миграции) и честно
  падает с командой для логов, если панель не поднялась.

## Обновление

Обновляйтесь скриптом `update.sh` из того же каталога: он тянет новый образ и пересоздаёт
контейнеры. **`.env` и тома (БД, бэкапы) не трогаются**; набор файлов берётся из `COMPOSE_FILE`,
поэтому Caddy-оверлей переживает обновления.

```sh
curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/update.sh | bash
```

Сменить версию — флагом `--tag` (запишет `VPNHUB_TAG` в `.env`):

```sh
bash update.sh --tag 1.3.0        # по умолчанию обновляет $HOME/vpn-hub; другой каталог — --dir PATH
```

!!! danger "Сначала бэкап"
    Обновление накатывает миграции схемы. Перед ним снимайте `.vhb`-бэкап через админку — это
    точка отката. Подробнее про стратегии и откат — [Обновление](updates.md).

## Удаление

`uninstall.sh` по умолчанию **безопасен**: контейнеры удаляются, тома с данными и `.env`
сохраняются (перед удалением томов — явное подтверждение).

```sh
curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/uninstall.sh | bash
```

| Флаг | Поведение |
|---|---|
| _(без флагов)_ | Контейнеры удалить, тома оставить; спросит `Удалить также ВСЕ данные? [y/N]`. |
| `--keep-data` | То же, что по умолчанию, без вопроса про тома. |
| `--purge` | Снести и **тома с данными** — **необратимо**, без вопроса. Затем спросит про каталог с `.env`. |
| `--dir PATH` | Каталог установки (по умолчанию `$HOME/vpn-hub`). |

!!! danger "`--purge` уничтожает данные"
    Восстановиться после `--purge` можно только из внешнего `.vhb`-бэкапа и только с сохранённым
    **мастер-ключом**.

## Windows {#windows}

На Windows Docker работает поверх **WSL2** (нужен Docker Desktop). `install.ps1` повторяет
`install.sh`, включая профили и повторный запуск с параметрами:

=== "Локально"

    ```powershell
    irm https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.ps1 | iex
    ```

=== "С параметрами"

    ```powershell
    irm https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.ps1 -OutFile install.ps1
    # прочитайте install.ps1, затем:
    powershell -ExecutionPolicy Bypass -File .\install.ps1 -Domain vpn.example.com
    ```

Параметры зеркалят bash-флаги: `-Domain`, `-Lan`, `-LocalOnly`, `-ExternalDb`, `-Tag`,
`-MasterKey`, `-AdminPhone`/`-AdminPassword`, `-BaseUrl`, `-HttpAddr`, `-InstallDir`, `-Ref`,
`-NoPull`, `-DryRun`. Env-эквиваленты — те же, что у `install.sh`.

!!! info "Альтернатива — bash-скрипт в WSL2"
    Раз Docker Desktop и так использует WSL2, можно открыть Ubuntu в WSL2 и запустить обычный
    `install.sh` со всеми флагами.

---

**Дальше:** [Первый запуск и вход →](../guide/first-run.md) · [Обновление →](updates.md) ·
[Переменные окружения →](configuration.md)
