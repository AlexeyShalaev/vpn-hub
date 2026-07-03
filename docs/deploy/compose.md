# Docker Compose

**Рекомендуемый способ** для одного сервера (VPS): панель и встроенный PostgreSQL 17 поднимаются
одним `docker compose up -d` из готовых файлов репозитория. Выбирайте его, если у вас обычный Linux-сервер
и базовое знание Docker.

## Требования

- **Docker Engine** 20.10+ и плагин **Compose v2** (команда `docker compose`, не `docker-compose`).
  Проверка — `docker compose version`.
- **Мастер-ключ** и пароль БД: сгенерируете командой `openssl rand -hex 32` (см. ниже).
- Домен и открытые порты 80/443 — **по желанию**, только если сразу нужен HTTPS
  (см. [HTTPS и домен](reverse-proxy.md)). Для первого запуска не обязательны.

Полный список платформ и ресурсов — в [Требованиях](requirements.md).

## 1. Получите файлы

Нужны три файла из каталога `deploy/compose/`: `compose.yaml`, `.env.example` и (для HTTPS)
`caddy.compose.yaml` с `Caddyfile`. Возьмите их любым способом.

=== "Клонировать репозиторий"

    Склонируйте репозиторий и перейдите в каталог с compose-файлами.

    ```sh
    git clone https://github.com/AlexeyShalaev/vpn-hub.git
    cd vpn-hub/deploy/compose
    ```

=== "Скачать отдельные файлы"

    Создайте рабочий каталог и скачайте в него нужные файлы напрямую с GitHub.

    ```sh
    mkdir vpnhub && cd vpnhub
    curl -O https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/compose/compose.yaml
    curl -O https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/compose/.env.example
    ```

    Для HTTPS докачайте оверлей Caddy и его конфиг.

    ```sh
    curl -O https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/compose/caddy.compose.yaml
    curl -O https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/compose/Caddyfile
    ```

## 2. Заполните `.env`

Скопируйте шаблон окружения в рабочий `.env`.

```sh
cp .env.example .env
```

Сгенерируйте два секрета — по одному на **мастер-ключ** и **пароль PostgreSQL** — и впишите их
в `.env` (значения `VPNHUB_MASTER_KEY` и `POSTGRES_PASSWORD`).

```sh
openssl rand -hex 32     # для VPNHUB_MASTER_KEY
openssl rand -hex 32     # для POSTGRES_PASSWORD
```

Обязательные и полезные переменные `.env`:

| Переменная | Что задать |
|---|---|
| `VPNHUB_MASTER_KEY` | Мастер-ключ восстановления (`openssl rand -hex 32`). **Обязателен.** |
| `POSTGRES_PASSWORD` | Пароль встроенного PostgreSQL, тоже hex (URL-safe). **Обязателен.** |
| `VPNHUB_BASE_URL` | Публичный адрес панели. По умолчанию `http://localhost:8000`; на проде — `https://ваш.домен`. |
| `VPNHUB_HTTP_ADDR` | Куда публиковать порт на хосте. По умолчанию `127.0.0.1:8000` (только localhost). |
| `VPNHUB_TAG` | Тег образа: `latest` или пин версии (`1.2.3` / `1.2`). На проде рекомендуется пин. |
| `VPNHUB_ADMIN_PHONE`, `VPNHUB_ADMIN_PASSWORD` | Необязательно: если заданы **обе** — админ создастся при старте, иначе будет setup-экран. |

!!! danger "Мастер-ключ — сохраните его отдельно"
    Из `VPNHUB_MASTER_KEY` выводятся ключи шифрования **SSH-доступов к вашим серверам** и
    **резервных копий**. **Потеря ключа = потеря доступа к секретам и невозможность восстановить
    бэкапы.** Держите его в менеджере паролей отдельно от сервера. На `https` панель **не запустится**
    с пустым/дефолтным ключом. Подробнее — [Требования → Мастер-ключ](requirements.md#master-key).

!!! warning "Порт по умолчанию — только localhost"
    `VPNHUB_HTTP_ADDR` по умолчанию `127.0.0.1:8000`: панель доступна только с самого хоста, наружу
    порт **не** выставляется. Это осознанная защита — публиковать на домен нужно через
    [reverse-proxy](reverse-proxy.md). Для доступа по IP без прокси (тест/LAN) задайте
    `VPNHUB_HTTP_ADDR=0.0.0.0:8000`.

## 3. Запустите стек

Поднимите оба сервиса в фоне.

```sh
docker compose up -d
```

Проверьте, что контейнеры поднялись: БД в статусе `healthy`, приложение — `Up`.

```sh
docker compose ps
```

Ожидаемый вывод примерно такой:

```text
NAME          IMAGE                                  STATUS                    PORTS
vpnhub-app-1  ghcr.io/alexeyshalaev/vpn-hub:latest   Up 30 seconds             127.0.0.1:8000->8000/tcp
vpnhub-db-1   postgres:17                            Up 40 seconds (healthy)
```

Приложение стартует только после того, как БД станет `healthy` (`depends_on: service_healthy`).
При первом старте прогоняются миграции (`alembic upgrade head`), это занимает несколько секунд.

!!! info "Порядок и миграции"
    Миграции при старте сериализованы транзакционным advisory-lock — параллельный запуск нескольких
    инстансов безопасен. Но фоновый планировщик (бэкапы/мониторинг/синхронизация) работает **в каждой
    реплике** без лидер-элекшена, поэтому в Compose держите приложение на **одной реплике**.

## 4. Первый вход

Откройте панель в браузере по адресу из `VPNHUB_BASE_URL` (по умолчанию `http://localhost:8000`).

- Если задали **обе** переменные `VPNHUB_ADMIN_PHONE` и `VPNHUB_ADMIN_PASSWORD` — входите под ними.
- Иначе откроется **setup-экран**: создадите первого администратора (а если не задавали
  `VPNHUB_MASTER_KEY` — введёте и мастер-ключ).

Дальше — установка VPN-софта на ваши серверы уже изнутри панели:
[Установка VPN на сервер](../owner/vpn.md).

## Управление стеком

| Команда | Что делает |
|---|---|
| `docker compose ps` | Статус сервисов. |
| `docker compose logs -f app` | Живой лог приложения (миграции, планировщик, ошибки). |
| `docker compose up -d` | Применить изменения `.env`/`compose.yaml` (пересоздаст изменившееся). |
| `docker compose down` | Остановить и удалить контейнеры. **Тома сохраняются.** |
| `docker compose down -v` | То же, но **удалить тома** — данные БД и бэкапы пропадут. |

!!! danger "`down -v` уничтожает данные"
    `docker compose down` без `-v` останавливает контейнеры, но **сохраняет** тома (`pgdata`,
    `backups`, `data`) — после `up -d` всё на месте. Флаг `-v` удаляет тома вместе с базой данных и
    бэкапами. Не используйте `-v`, если не хотите потерять данные.

## Что персистентно

Стек использует встроенный **PostgreSQL 17** и три именованных тома — при пересоздании контейнеров
данные не теряются:

| Том | Точка монтирования | Содержимое |
|---|---|---|
| `pgdata` | `/var/lib/postgresql/data` | Данные PostgreSQL. |
| `backups` | `/var/lib/vpnhub/backups` | `.vhb`-бэкапы БД. |
| `data` | `/var/lib/vpnhub/data` | Каталог провайдеров (`providers.yaml`, правится из админки). |

Порт PostgreSQL наружу **не** публикуется — база доступна только приложению по внутренней сети
Compose (`db:5432`).

## Варианты

- **Своя / managed PostgreSQL** (RDS, Cloud SQL, Neon) — не поднимайте вторую базу, подключитесь к
  своей: [Внешняя база данных](external-db.md).
- **HTTPS на домене** — добавьте оверлей Caddy (автосертификат Let's Encrypt). Скачайте
  `caddy.compose.yaml` и `Caddyfile`, допишите три строки в `.env` (домен подставится в
  `Caddyfile` сам, файлы редактировать не нужно), откройте 80/443 и перезапустите стек:

    ```sh title=".env"
    COMPOSE_FILE=compose.yaml:caddy.compose.yaml
    VPNHUB_DOMAIN=ваш.домен
    VPNHUB_BASE_URL=https://ваш.домен
    ```

    ```sh
    docker compose up -d
    ```

    Строка `COMPOSE_FILE` закрепляет оверлей за стеком — двойной `-f` не нужен, и обновления
    его не теряют. Подробнее — [HTTPS и домен](reverse-proxy.md).

- **Обновление** до новой версии образа — [Обновление](updates.md).
- **Все переменные окружения** — справочник [Переменные окружения](configuration.md).

---

**Дальше:** [HTTPS и домен →](reverse-proxy.md) · [Обновление →](updates.md)
