# VPN Hub

Self-hosted панель управления VPN-инфраструктурой: серверы (Amnezia / OpenVPN / Outline), группы,
выдача доступов близким, получение конфигов. Один Docker-образ, единственная внешняя зависимость —
PostgreSQL.

[![License](https://img.shields.io/github/license/AlexeyShalaev/vpn-hub)](LICENSE)
[![CI](https://github.com/AlexeyShalaev/vpn-hub/actions/workflows/ci.yml/badge.svg?branch=master)](https://github.com/AlexeyShalaev/vpn-hub/actions/workflows/ci.yml)
[![Image](https://img.shields.io/badge/ghcr.io-vpn--hub-blue?logo=docker)](https://github.com/AlexeyShalaev/vpn-hub/pkgs/container/vpn-hub)
[![Docs](https://img.shields.io/badge/docs-online-blue)](https://AlexeyShalaev.github.io/vpn-hub/)

![Обзор VPN Hub](docs/assets/reel/reel.gif)

## Требования

- **Docker** 20.10+ и **Docker Compose** v2 — либо кластер **Kubernetes** 1.27+.
- **PostgreSQL** — встроенный (Compose/overlay) или внешний.
- ~512 МБ RAM и 1 vCPU на инстанс; приложение держат в **одной реплике** (фоновый планировщик
  без лидер-элекшена — см. [deploy/](deploy/)).

## Установка

Готовый образ — `ghcr.io/alexeyshalaev/vpn-hub` (linux/amd64 + arm64). Быстрее всего — скрипт:
он проверит Docker, сам сгенерирует секреты и поднимет панель со встроенным PostgreSQL:

```sh
curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.sh | bash
# открыть http://localhost:8000

# VPS с доменом — сразу HTTPS (Caddy + Let's Encrypt; подставьте свой домен):
curl -fsSL https://raw.githubusercontent.com/AlexeyShalaev/vpn-hub/master/deploy/scripts/install.sh \
  | bash -s -- --domain vpn.example.com
```

То же вручную через Docker Compose:

```sh
cd deploy/compose
cp .env.example .env
# задайте VPNHUB_MASTER_KEY и POSTGRES_PASSWORD:  openssl rand -hex 32
docker compose up -d
```

Все способы (Compose, Kubernetes, `docker run`, флаги скрипта, HTTPS, внешняя БД) — в
[папке `deploy/`](deploy/) и в
[документации по установке](https://AlexeyShalaev.github.io/vpn-hub/deploy/).

Первый вход: на пустой БД без env-админа открывается setup-экран (создание администратора и
мастер-ключа восстановления). Либо задайте `VPNHUB_ADMIN_PHONE` / `VPNHUB_ADMIN_PASSWORD` —
админ создастся при старте.

> **Мастер-ключ.** `VPNHUB_MASTER_KEY` шифрует SSH-доступы и бэкапы; потеря = потеря секретов.
> На `https` панель не стартует с дефолтным ключом. Подробности — в
> [документации](https://AlexeyShalaev.github.io/vpn-hub/deploy/).

## Запуск (dev)

```sh
make db-up          # Postgres в docker на :5433
make install        # uv sync (backend) + npm install (frontend)
make front-build    # собрать React → статика backend
make run            # backend на :8000 (миграции на старте)
# либо отдельно фронт:  make front-dev   (Vite :3000, proxy /api → :8000)
```

## Разработка

```sh
make check          # ruff lint + format check + mypy (backend)
make test           # pytest (in-memory SQLite, без внешней инфры)
make front-lint     # tsc --noEmit (frontend)
```

## Стек

Python 3.14 · FastAPI (Onion: `api`/`core`/`services`/`infra`) · Dishka · SQLAlchemy 2.0 async +
Alembic · `sqlalchemy-foundation-kit` · React 19 + Vite + TS (отдаётся тем же FastAPI). Реальный
provisioning по SSH (Amnezia/AmneziaWG, OpenVPN, Outline, Xray).

## Структура

| Путь | Что |
|---|---|
| [backend/](backend/) | FastAPI-приложение (`src/vpnhub/`), Alembic-миграции, тесты |
| [frontend/](frontend/) | React + Vite UI (собирается в статику backend) |
| [deploy/](deploy/) | Docker Compose, скрипты установки, Kubernetes-манифесты |
| [docs/](docs/) | сайт документации + research-заметки по provisioning |

## Лицензия

Apache 2.0 — см. [LICENSE](LICENSE).
