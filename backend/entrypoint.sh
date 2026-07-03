#!/bin/sh
set -e
# Миграции накатывает само приложение в lifespan-startup (под advisory-lock).
# entrypoint только поднимает процесс — API + статика + планировщик в одном контейнере.
exec uvicorn vpnhub.api.entrypoint:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}"
