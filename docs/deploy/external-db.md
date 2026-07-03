# Внешняя база данных

Как подключить VPN Hub к **своей или managed-PostgreSQL** вместо встроенной. Панель — один
контейнер; при внешней БД собственный контейнер Postgres не поднимается, приложению нужен только
`DATABASE_URL` на внешний хост.

## Когда это нужно

- У вас уже есть **managed-PostgreSQL** — AWS RDS / Aurora, Google Cloud SQL, Neon, Supabase,
  Yandex Managed PostgreSQL и т.п. Тогда бэкапы, обновления и HA-БД берёт на себя провайдер.
- В компании есть **общая/существующая PostgreSQL**, и заводить вторую базу не нужно.
- Хотите держать состояние **отдельно от хоста панели**, чтобы пересоздание/переезд контейнера не
  задевал данные.

Если ничего из этого не про вас — проще встроенная БД: [Docker Compose](compose.md) или
[Kubernetes](kubernetes.md) со встроенным Postgres.

## Требования

- Доступная по сети **PostgreSQL 14+** (рекомендуется **17**, на ней гоняется CI).
- **База** и **пользователь** с полными правами на неё (см. ниже). Расширения PostgreSQL **не
  нужны** — панель их не использует.
- Готовый **`DATABASE_URL`** с драйвером `asyncpg` (и, как правило, TLS для managed).
- **Мастер-ключ**: `openssl rand -hex 32` (см. [Требования → Мастер-ключ](requirements.md#master-key)).
- Сетевой доступ с хоста панели до порта БД (обычно `5432`); у managed — добавьте IP панели в
  allow-list / VPC.

## Формат DATABASE_URL

```
postgresql+asyncpg://ПОЛЬЗОВАТЕЛЬ:ПАРОЛЬ@ХОСТ:5432/БАЗА
```

- **Драйвер `asyncpg` обязателен** — именно `postgresql+asyncpg://`, а не `postgresql://` или
  `postgres://`.
- Для managed-БД почти всегда нужен TLS — добавьте параметр запроса **`?ssl=require`** (или
  `?ssl=verify-full` с проверкой CA):

    ```
    postgresql+asyncpg://vpnhub:PASSWORD@db.example.com:5432/vpnhub?ssl=require
    ```

- **Спецсимволы в пароле URL-кодируйте**: `@` → `%40`, `:` → `%3A`, `/` → `%2F`. Проще всего
  сгенерировать пароль из hex (`openssl rand -hex 32`) — в нём нет символов, требующих кодирования.

!!! warning "Забыли `?ssl=require` — самая частая ошибка первого подключения"
    Managed-провайдеры (RDS, Cloud SQL, Neon, Supabase) обычно **требуют TLS** и отклоняют
    незашифрованные соединения. Без `?ssl=require` панель не поднимется, а в логах будет ошибка
    подключения к БД. Если провайдер даёт CA-сертификат и вы хотите проверять его — используйте
    `?ssl=verify-full` (с настроенным CA), иначе достаточно `?ssl=require`.

!!! info "Псевдоним переменной"
    Принимаются оба имени — `DATABASE_URL` и `VPNHUB_DATABASE_URL`, приоритет у `DATABASE_URL`.
    Полный справочник — [Переменные окружения](configuration.md).

## Что подготовить в БД

Создайте базу и пользователя, дайте пользователю права на неё. Пример для `psql` под администратором
кластера:

```sql
CREATE ROLE vpnhub LOGIN PASSWORD 'СГЕНЕРИРОВАННЫЙ_ПАРОЛЬ';
CREATE DATABASE vpnhub OWNER vpnhub;
```

!!! info "Права и расширения"
    Достаточно, чтобы пользователь был **владельцем** базы (или имел права на создание таблиц) —
    схему панель накатывает сама через `alembic upgrade head` при старте. **CREATE EXTENSION не
    требуется**: панель не использует расширений PostgreSQL, поэтому подойдёт и урезанный managed
    без суперпользователя. У многих провайдеров база и пользователь уже созданы через веб-консоль —
    тогда просто возьмите их DSN.

## Установка с внешней БД

Ниже — способы установки. Во всех БД внешняя, поэтому контейнер/StatefulSet Postgres отсутствует.

=== "Скрипт установки"

    Проще всего — [скрипт](scripts.md) с флагом `--external-db`:

    ```sh
    curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.sh \
      | bash -s -- --external-db 'postgresql+asyncpg://vpnhub:PA%40ss@db.example.com:5432/vpnhub?ssl=require'
    ```

    Скрипт проверяет DSN **до** установки: переписывает `postgres://`/`postgresql://` на
    обязательный `postgresql+asyncpg://`, напоминает про `?ssl=require` для не-локального хоста
    и экранирует `$` для compose. Сочетается с `--domain` (HTTPS) и остальными флагами.

=== "Docker Compose"

    Скачайте `compose.external-db.yaml` и пример окружения, затем скопируйте `.env`:

    ```sh
    cp .env.external-db.example .env
    ```

    Откройте `.env` и заполните **`DATABASE_URL`** (на ваш внешний хост) и **`VPNHUB_MASTER_KEY`**.
    Сгенерируйте ключ, если ещё нет:

    ```sh
    openssl rand -hex 32
    ```

    Поднимите стек, явно указав файл:

    ```sh
    docker compose -f compose.external-db.yaml up -d
    ```

    В этом compose-файле нет сервиса `postgres` — только `app` и тома для бэкапов
    (`/var/lib/vpnhub/backups`) и данных провайдеров (`/var/lib/vpnhub/data`). `DATABASE_URL` и
    `VPNHUB_MASTER_KEY` обязательны — без них compose завершится с ошибкой ещё до старта контейнера.

    Проверьте, что контейнер запустился и здоров:

    ```sh
    docker compose -f compose.external-db.yaml ps
    ```

    Успешный вывод — один сервис `app` в статусе `running`/`healthy`:

    ```
    NAME          IMAGE                                       STATUS                   PORTS
    vpnhub-app-1  ghcr.io/alexeyshalaev/vpn-hub:latest        Up 30 seconds (healthy)  127.0.0.1:8000->8000/tcp
    ```

=== "docker run"

    То же, что обычный запуск в [Docker без Compose](docker.md), но **без** контейнера Postgres —
    `DATABASE_URL` указывает на внешний хост. Подставьте свой DSN и мастер-ключ:

    ```sh
    docker run -d --name vpn-hub --restart unless-stopped \
      -p 127.0.0.1:8000:8000 \
      -e DATABASE_URL='postgresql+asyncpg://vpnhub:PASSWORD@db.example.com:5432/vpnhub?ssl=require' \
      -e VPNHUB_MASTER_KEY="$(openssl rand -hex 32)" \
      -e VPNHUB_BASE_URL='http://localhost:8000' \
      -v vpnhub-backups:/var/lib/vpnhub/backups \
      -v vpnhub-data:/var/lib/vpnhub/data \
      ghcr.io/alexeyshalaev/vpn-hub:latest
    ```

    !!! warning "Порт контейнера — всегда 8000"
        Порт внутри задаётся переменной `PORT` (дефолт `8000`), а `HEALTHCHECK` образа жёстко ходит
        на `:8000/healthz`. Не меняйте порт внутри — публикуйте наружу через `-p` (например,
        `-p 127.0.0.1:9000:8000`). Переменная `VPNHUB_PORT` на контейнер **не влияет**.

    Проверьте статус:

    ```sh
    docker ps --filter name=vpnhub
    ```

    Должен быть один контейнер `vpnhub` в статусе `Up … (healthy)`.

=== "Kubernetes"

    Используйте overlay **`external-db`** — он подключает `base/` **без** StatefulSet Postgres.
    Сначала создайте namespace:

    ```sh
    kubectl apply -f base/namespace.yaml
    ```

    Скопируйте шаблон Secret и заполните его:

    ```sh
    cp base/secret.example.yaml base/secret.yaml
    ```

    В `base/secret.yaml` укажите **`VPNHUB_MASTER_KEY`** и **`DATABASE_URL`** на внешний хост (с
    `?ssl=require` для managed). При внешней БД **`POSTGRES_PASSWORD` не нужен** — эта переменная
    относится к встроенному Postgres, её можно удалить/оставить пустой:

    ```yaml
    stringData:
      VPNHUB_MASTER_KEY: "<openssl rand -hex 32>"
      DATABASE_URL: "postgresql+asyncpg://vpnhub:PASSWORD@db.example.com:5432/vpnhub?ssl=require"
      # POSTGRES_PASSWORD при внешней БД не используется
    ```

    Примените Secret, затем overlay:

    ```sh
    kubectl apply -f base/secret.yaml
    kubectl apply -k overlays/external-db
    ```

    Домен и публичный адрес правятся в `overlays/external-db/patch-ingress.yaml` (Ingress host + TLS) и
    `patch-config.yaml` (`VPNHUB_BASE_URL`), тег образа — в `overlays/external-db/kustomization.yaml` (`images: newTag`).

    Проверьте, что под поднялся:

    ```sh
    kubectl -n vpnhub get pods
    ```

    Успех — один под `vpnhub` в состоянии `Running`, `READY 1/1`:

    ```
    NAME                      READY   STATUS    RESTARTS   AGE
    vpnhub-7d9c8b6f5c-abcde   1/1     Running   0          40s
    ```

    !!! warning "Держите панель на одной реплике"
        Планировщик (бэкапы, мониторинг, синхронизация) работает **в каждой реплике** без
        лидер-элекшена — при `replicas > 1` фоновые задачи дублируются. Миграции при этом безопасны
        (сериализованы транзакционным advisory-lock).

## Первый вход

Если вы **не** задали `VPNHUB_ADMIN_PHONE` и `VPNHUB_ADMIN_PASSWORD`, при первом входе откроется
**setup-экран** — создадите админа там (а если не задавали мастер-ключ в окружении — введёте и его).
Задавайте либо **обе** переменные админа, либо ни одной.

!!! danger "Мастер-ключ — самое важное"
    Из `VPNHUB_MASTER_KEY` выводятся ключи шифрования **SSH-доступов к вашим серверам** и
    **`.vhb`-бэкапов**. **Потеря ключа необратима**: без него нельзя расшифровать секреты и
    восстановить бэкапы. Храните его в менеджере паролей **отдельно** от сервера и от БД. На адресе
    с `https` панель **не стартует** с дефолтным/пустым ключом.

## Бэкапы и версии

- **`.vhb`-бэкапы панели** (логический дамп строк) **не зависят от версии PostgreSQL** — их можно
  восстановить на другой версии БД. Они лежат в томе `/var/lib/vpnhub/backups`.
- **Дампы самой PostgreSQL** (`pg_dump`, снапшоты, PITR) — на стороне вашего провайдера или вас: при
  внешней БД панель не управляет её резервным копированием.

!!! danger "Сделайте бэкап перед обновлением"
    Перед сменой тега образа снимите `.vhb`-бэкап панели (и/или дамп БД на стороне провайдера).
    Миграции накатываются автоматически и вперёд-совместимы, но резервная копия — обязательная
    страховка. Порядок обновления по способам — в [Обновление](updates.md).

---

**Дальше:** [Docker Compose →](compose.md) · [Kubernetes →](kubernetes.md) ·
[Переменные окружения →](configuration.md)
