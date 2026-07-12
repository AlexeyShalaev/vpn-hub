#!/bin/bash
# Поднимает ИЗОЛИРОВАННЫЙ демо-инстанс для съёмки скриншотов/ролика.
#
# Создаёт ОТДЕЛЬНУЮ базу (по умолчанию vpnhub_demo) — реальные данные НЕ трогает, —
# накатывает миграции, сеет синтетику и запускает backend с выключенными фоновыми
# джобами (monitor/sync/stats), чтобы статусы серверов и метрики оставались стабильными.
#
# Требует запущенный локальный Postgres: `make db-up` (контейнер vpnhub-pg на :5433).
# Оставьте процесс в этом терминале; в другом — `make screenshots` / `make reel`.
#
# Переопределяемо: DEMO_DB, PORT, PG_CONTAINER, PG_USER, PG_PASSWORD.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
DB="${DEMO_DB:-vpnhub_demo}"
PORT="${PORT:-8000}"
PG_CT="${PG_CONTAINER:-vpnhub-pg}"
PG_USER="${PG_USER:-vpnhub}"
PG_PW="${PG_PASSWORD:-secret}"
DSN="postgresql+asyncpg://${PG_USER}:${PG_PW}@localhost:5433/${DB}"

echo "→ пересоздаю изолированную БД ${DB} (реальные данные не трогаю)…"
docker exec "$PG_CT" psql -U "$PG_USER" -d postgres -c \
  "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname='${DB}' AND pid<>pg_backend_pid();" >/dev/null 2>&1 || true
docker exec "$PG_CT" psql -U "$PG_USER" -d postgres -c "DROP DATABASE IF EXISTS ${DB};" >/dev/null
docker exec "$PG_CT" psql -U "$PG_USER" -d postgres -c "CREATE DATABASE ${DB} OWNER ${PG_USER};" >/dev/null

echo "→ миграции…"
( cd "$ROOT/backend" && DATABASE_URL="$DSN" uv run alembic upgrade head >/dev/null )

echo "→ сею синтетические демо-данные…"
( cd "$ROOT/backend" && DATABASE_URL="$DSN" uv run python "$HERE/seed_demo.py" )

echo "→ backend на http://127.0.0.1:${PORT} (monitor/sync/stats выключены)…  Ctrl+C чтобы остановить."
cd "$ROOT/backend"
exec env DATABASE_URL="$DSN" \
  VPNHUB_MONITOR_ENABLED=0 VPNHUB_SYNC_ENABLED=0 VPNHUB_STATS_AUTO_ENABLE=0 \
  VPNHUB_DOCS_ENABLED=1 VPNHUB_VERSION=0.10.1 VPNHUB_LATEST_VERSION=0.10.1 \
  uv run uvicorn vpnhub.api.entrypoint:create_app --factory --port "$PORT" --host 127.0.0.1
