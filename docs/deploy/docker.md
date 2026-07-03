# Docker без Compose

Запуск VPN Hub напрямую через `docker run`. Подходит, когда вы предпочитаете руками
управлять контейнерами или хотите разобрать стек по шагам. Для одного сервера почти всегда проще
[**Docker Compose**](compose.md) — эта страница показывает тот же стек «вручную».

## Требования

- **Docker Engine 20.10+** (`docker version`).
- **`openssl`** — для генерации секретов (`openssl rand -hex 32`).
- Свободный порт **8000** на хосте (или любой другой — замапите снаружи).
- Всё остальное — из [Требований](requirements.md).

!!! info "Отдельного «на посмотреть» режима нет"
    Панель всегда работает с **PostgreSQL** — под него отлажены миграции, шифрование секретов и
    бэкапы, а строка подключения жёстко приводится к драйверу `asyncpg` (SQLite-адрес в
    `DATABASE_URL` не поддерживается и контейнер с ним не стартует). Быстрее всего поднять сразу и БД,
    и панель одной командой через [**Docker Compose**](compose.md). Ниже — тот же стек вручную на
    `docker run`, если Compose использовать не хотите.

## Полноценный запуск (ручной эквивалент `compose.yaml`)

Это те же образы, тома, переменные и порты, что и в [`compose.yaml`](compose.md) — только
разложенные на отдельные команды. Понадобится: сеть, контейнер PostgreSQL и контейнер приложения.

### 1. Подготовьте секреты

Сгенерируйте **мастер-ключ** и **пароль БД** (оба — hex, URL-safe) и сохраните их:

```sh
export VPNHUB_MASTER_KEY=$(openssl rand -hex 32)
export POSTGRES_PASSWORD=$(openssl rand -hex 32)
```

!!! danger "Сохраните мастер-ключ отдельно от сервера"
    `VPNHUB_MASTER_KEY` HKDF-выводит ключи шифрования **SSH-доступов к вашим серверам** и
    **бэкапов**. Его **потеря необратима**: расшифровать доступы и восстановить `.vhb`-бэкапы будет
    нельзя. Положите значение в менеджер паролей **до** запуска. Подробнее —
    [Требования → Мастер-ключ](requirements.md#master-key).

### 2. Создайте сеть

Приложение и БД общаются по имени контейнера — им нужна общая пользовательская сеть:

```sh
docker network create vpnhub-net
```

### 3. Запустите PostgreSQL

Поднимите **postgres:17** с томом под данные и healthcheck (`pg_isready`), чтобы приложение
стартовало только после готовности БД:

```sh
docker run -d --name vpn-hub-db --network vpnhub-net \
  --restart unless-stopped \
  -e POSTGRES_USER=vpnhub \
  -e POSTGRES_DB=vpnhub \
  -e POSTGRES_PASSWORD="$POSTGRES_PASSWORD" \
  -v vpnhub-pgdata:/var/lib/postgresql/data \
  --health-cmd="pg_isready -U vpnhub -d vpnhub" \
  --health-interval=10s --health-timeout=5s --health-retries=5 \
  postgres:17
```

Дождитесь, пока БД станет `healthy`:

```sh
docker inspect --format '{{.State.Health.Status}}' vpn-hub-db
```

Должно вывести `healthy`. Порт БД наружу **не публикуется** — она доступна только внутри сети.

### 4. Запустите приложение

Поднимите контейнер панели в той же сети. `DATABASE_URL` указывает на контейнер БД по имени
`vpn-hub-db:5432`, драйвер **`asyncpg` обязателен**:

```sh
docker run -d --name vpn-hub --network vpnhub-net \
  --restart unless-stopped --pull=always \
  -p 127.0.0.1:8000:8000 \
  -e DATABASE_URL="postgresql+asyncpg://vpnhub:$POSTGRES_PASSWORD@vpn-hub-db:5432/vpnhub" \
  -e VPNHUB_MASTER_KEY="$VPNHUB_MASTER_KEY" \
  -e VPNHUB_BASE_URL="http://localhost:8000" \
  -e VPNHUB_BACKUP_DIR=/var/lib/vpnhub/backups \
  -e VPNHUB_PROVIDERS_FILE=/var/lib/vpnhub/data/providers.yaml \
  -v vpnhub-backups:/var/lib/vpnhub/backups \
  -v vpnhub-data:/var/lib/vpnhub/data \
  ghcr.io/alexeyshalaev/vpn-hub:latest
```

При старте контейнер сам накатит миграции (`alembic upgrade head`) и поднимет панель на порту 8000.

!!! info "Тома — чтобы не терять данные"
    Три именованных тома повторяют `compose.yaml`: `vpnhub-pgdata` (данные PostgreSQL),
    `vpnhub-backups` (`.vhb`-бэкапы БД) и `vpnhub-data` (каталог провайдеров — правится из админки и
    **пишется на диск**). Без них правки и бэкапы исчезнут при пересоздании контейнера.

!!! warning "Порт менять не нужно — маппьте снаружи"
    Внутри контейнера панель всегда слушает **8000** (порт берётся из `PORT`, дефолт 8000;
    `VPNHUB_PORT` игнорируется, а встроенный `HEALTHCHECK` образа жёстко ходит на `:8000/healthz`).
    Чтобы отдать панель на другом порту хоста — меняйте **левую** часть `-p`, например
    `-p 127.0.0.1:9000:8000`. Правую (`:8000`) оставляйте как есть.

!!! warning "По умолчанию — только localhost"
    `-p 127.0.0.1:8000:8000` публикует панель **только на самом хосте** — это безопасный дефолт,
    наружу её выводят через [reverse-proxy с HTTPS](reverse-proxy.md). Чтобы открыть доступ по IP
    для теста или LAN — замените на `-p 0.0.0.0:8000:8000`. Не выставляйте панель по HTTP в интернет.

### 5. Проверьте, что стек поднялся

Посмотрите статус контейнеров:

```sh
docker ps
```

Ожидаемый вывод — оба контейнера `Up`, БД `(healthy)`:

```text
CONTAINER ID   IMAGE                            STATUS                    PORTS                      NAMES
a1b2c3d4e5f6   ghcr.io/alexeyshalaev/vpn-hub…   Up 20 seconds             127.0.0.1:8000->8000/tcp   vpn-hub
f6e5d4c3b2a1   postgres:17                      Up 40 seconds (healthy)   5432/tcp                   vpn-hub-db
```

Если что-то не так — смотрите логи приложения: `docker logs -f vpn-hub`.

Откройте **`http://localhost:8000`** — откроется **setup-экран** (создание первого админа). Хотите
создать админа сразу, без setup-экрана — добавьте в команду из шага 4 **обе** переменные
`-e VPNHUB_ADMIN_PHONE=+7… -e VPNHUB_ADMIN_PASSWORD=…` (только одной телефона недостаточно —
см. [Переменные окружения](configuration.md)).

## Обновление

Обновление — это `pull` нового образа и пересоздание контейнера приложения; тома и БД остаются.

!!! danger "Перед обновлением сделайте бэкап"
    Скачайте свежий `.vhb`-бэкап из панели (или убедитесь, что он есть на томе `vpnhub-backups`)
    **до** обновления. И проверьте, что `VPNHUB_MASTER_KEY` сохранён — без него бэкап не
    восстановить.

Подтяните образ, удалите старый контейнер и запустите новый (тот же `docker run` из шага 4):

```sh
docker pull ghcr.io/alexeyshalaev/vpn-hub:latest
docker stop vpn-hub && docker rm vpn-hub
# затем повторите команду docker run из шага 4
```

Пошагово для всех способов, включая пин версий — [Обновление](updates.md).

## Управление

Полезные команды для этого стека:

```sh
docker logs -f vpn-hub                       # логи панели
docker restart vpn-hub                        # перезапуск
docker stop vpn-hub vpn-hub-db                # остановить стек
docker rm vpn-hub vpn-hub-db                  # удалить контейнеры (тома сохранятся)
docker volume rm vpnhub-pgdata vpnhub-backups vpnhub-data   # удалить данные (необратимо)
```

!!! tip "Проще — через Compose"
    Ручной `docker run` многословен и легко разъезжается с эталоном. На одном сервере тот же стек
    поднимается одной командой и обновляется одной командой — см. [**Docker Compose**](compose.md).

---

**Дальше:** [Docker Compose →](compose.md) · [Своя БД →](external-db.md) ·
[HTTPS →](reverse-proxy.md) · [Обновление →](updates.md)
