# Установка VPN Hub

Готовый образ: **`ghcr.io/alexeyshalaev/vpn-hub`** (linux/amd64 + arm64). Единственная внешняя
зависимость — PostgreSQL. Выберите способ под свой сценарий; подробные пошаговые инструкции
(требования, ОС, HTTPS, обновления, все переменные) — в **[документации](https://alexeyshalaev.github.io/vpn-hub/deploy/)**.

| Способ | Кому | Быстрый старт |
|---|---|---|
| **Скрипт** | «поставь за меня» | `curl -fsSL .../deploy/scripts/install.sh \| bash` — локально; `… \| bash -s -- --domain vpn.example.com` — VPS с HTTPS |
| **Docker Compose** | стандарт для одного сервера | [`compose/`](compose/) → `docker compose up -d` |
| **Один `docker run`** | попробовать / уже есть Postgres | см. [docs → Docker](https://alexeyshalaev.github.io/vpn-hub/deploy/docker/) |
| **Kubernetes** | кластер | [`k8s/`](k8s/) → `kubectl apply -k` |

## Что внутри

```
deploy/
├── compose/                    # Docker Compose (рекомендуемый способ)
│   ├── compose.yaml            #   приложение + PostgreSQL 17
│   ├── compose.external-db.yaml#   приложение + ваша внешняя БД
│   ├── caddy.compose.yaml      #   оверлей: автоматический HTTPS (Caddy)
│   ├── Caddyfile               #   конфиг Caddy (домен берётся из VPNHUB_DOMAIN в .env, править не нужно)
│   ├── .env.example            #   шаблон переменных (встроенная БД)
│   └── .env.external-db.example #  шаблон переменных (внешняя БД)
├── scripts/                    # Скрипты установки
│   ├── install.sh              #   установка одной командой (Linux/macOS)
│   ├── update.sh               #   обновление (pull + up -d, .env не трогает)
│   ├── uninstall.sh            #   удаление (данные — по подтверждению)
│   └── install.ps1             #   Windows (Docker Desktop + WSL2)
└── k8s/                        # Kubernetes (Kustomize)
    ├── base/                   #   приложение (БД-агностично)
    └── overlays/
        ├── bundled-db/         #   + встроенный PostgreSQL 17
        └── external-db/        #   без БД (внешний DATABASE_URL)
```

## Минимальные команды

=== "Compose (встроенная БД)"

    ```sh
    cd deploy/compose
    cp .env.example .env
    # задайте VPNHUB_MASTER_KEY и POSTGRES_PASSWORD:  openssl rand -hex 32
    docker compose up -d
    # откройте http://localhost:8000
    ```

=== "Скрипт"

    ```sh
    # локально
    curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.sh | bash
    # VPS с доменом — сразу HTTPS (подставьте свой домен)
    curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.sh \
      | bash -s -- --domain vpn.example.com
    ```

=== "Kubernetes"

    ```sh
    cd deploy/k8s
    kubectl apply -f base/namespace.yaml
    cp base/secret.example.yaml base/secret.yaml   # заполните секреты
    kubectl apply -f base/secret.yaml
    kubectl apply -k overlays/bundled-db           # или overlays/external-db
    ```

## Обязательно к прочтению

> **Мастер-ключ.** Задайте `VPNHUB_MASTER_KEY` (`openssl rand -hex 32`) — из него выводятся
> ключи шифрования SSH-доступов и бэкапов. **Потеря ключа = потеря доступа к секретам и бэкапам.**
> На `https`-адресе приложение **не стартует** с дефолтным/пустым ключом. Либо задайте ключ на
> setup-экране при первом входе.

> **Одна реплика.** Фоновые задачи (мониторинг, синхронизация, авто-бэкапы) выполняются в
> каждом инстансе приложения — держите **одну реплику** (k8s-манифесты так и настроены:
> `replicas: 1`, стратегия `Recreate`). Масштабируйте отдельно только PostgreSQL; HA самого
> приложения потребует leader-election планировщика (пока не поддерживается).

> **`/metrics`.** Prometheus-эндпоинт по умолчанию открыт — закройте его на reverse-proxy
> или задайте `VPNHUB_METRICS_TOKEN` (тогда нужен заголовок `Authorization: Bearer <токен>`).

Полное руководство, включая требования, разные ОС, reverse-proxy/TLS, внешнюю БД, обновления и
справочник всех переменных — в **[документации по установке](https://alexeyshalaev.github.io/vpn-hub/deploy/)**.
