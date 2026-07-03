# Установка

Установить VPN Hub — это поднять **один Docker-образ** `ghcr.io/alexeyshalaev/vpn-hub`
(linux/amd64 и arm64) рядом с **PostgreSQL** (поднимается автоматически). Всё, что нужно, —
машина с **Docker** (Engine 20.10+ с Compose v2). Займёт пару минут.

## Быстрая установка

=== "Одной командой (скрипт)"

    Скрипт проверит Docker, сам сгенерирует секреты, поднимет панель со встроенным PostgreSQL
    и дождётся её готовности. Локально попробовать:

    ```sh
    curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.sh | bash
    ```

    На VPS с доменом — сразу с HTTPS (Caddy и сертификат Let's Encrypt настроятся сами):

    ```sh
    curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.sh \
      | bash -s -- --domain vpn.example.com     # ← подставьте свой домен
    ```

    Остальные флаги (внешняя БД, свой каталог, Windows) и путь «сначала скачать и прочитать
    скрипт» — на странице [Скрипт установки](scripts.md).

=== "Docker Compose"

    Скачайте файлы, впишите два секрета и поднимите стек:

    ```sh
    git clone https://github.com/AlexeyShalaev/vpn-hub.git && cd vpn-hub/deploy/compose
    cp .env.example .env
    openssl rand -hex 32     # впишите в .env как VPNHUB_MASTER_KEY
    openssl rand -hex 32     # впишите в .env как POSTGRES_PASSWORD
    docker compose up -d
    ```

    Разбор каждого шага и управление стеком — [Docker Compose](compose.md).

Готово. Откройте **`http://localhost:8000`** — панель предложит создать первого администратора:
[Первый запуск и вход](../guide/first-run.md).

!!! danger "Сразу сохраните мастер-ключ"
    `VPNHUB_MASTER_KEY` из `.env` шифрует **SSH-доступы к вашим серверам** и **резервные копии**.
    **Потеря ключа необратима** — без него не расшифровать секреты и не восстановить бэкапы.
    Скопируйте его в менеджер паролей отдельно от сервера прямо сейчас.
    Подробнее — [Требования → Мастер-ключ](requirements.md#master-key).

!!! tip "Не путать с установкой VPN на серверы"
    Здесь ставится **сама панель**. VPN-софт (Amnezia, OpenVPN, Outline) на арендованные серверы
    вы потом установите **изнутри панели** по SSH — см. [Установка VPN на сервер](../owner/vpn.md).

## Все способы установки

Любой способ даёт один результат — работающую панель на `http(s)://ваш-адрес`. Разница — в том,
что у вас уже есть и чем удобнее управлять.

| Способ | Когда выбирать | Страница |
|---|---|---|
| **Docker Compose** | стандарт для одного сервера (VPS) — рекомендуем большинству | [Docker Compose](compose.md) |
| **Скрипт установки** | «просто подними за меня» — тот же Compose одной командой | [Скрипт](scripts.md) |
| **Docker без Compose** | хотите собрать стек руками через `docker run` | [Docker без Compose](docker.md) |
| **Kubernetes** | у вас уже есть кластер | [Kubernetes](kubernetes.md) |

Перед установкой на прод загляните в [**Требования**](requirements.md) — платформы, порты, ресурсы.

## После установки

- **HTTPS на домене** — [HTTPS и домен](reverse-proxy.md): готовый оверлей Caddy получит
  сертификат сам; есть примеры для Traefik и nginx.
- **Своя PostgreSQL** (managed RDS / Cloud SQL / Neon или существующая) — не поднимайте вторую
  базу: [Внешняя база данных](external-db.md).
- **Обновление на новую версию** — [Обновление](updates.md).
- **Все настройки** — справочник [Переменные окружения](configuration.md).

## Что дальше

1. [Первый запуск и вход](../guide/first-run.md) — администратор, мастер-ключ, вход.
2. [Быстрый старт владельца](../guide/quickstart.md) — от пустой панели до работающего VPN у близких.
