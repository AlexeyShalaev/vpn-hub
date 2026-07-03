# VPN Hub — один образ: FastAPI (API + статика React) + Postgres-клиент. Один процесс.

# 1) сборка фронтенда
FROM node:20-alpine AS frontend
WORKDIR /fe
COPY frontend/package.json frontend/package-lock.json ./
# npm ci — детерминированная установка строго по lock-файлу (воспроизводимый билд)
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# 2) зависимости python через uv (версия закреплена для воспроизводимости; обновляет dependabot)
FROM python:3.14-slim AS pydeps
COPY --from=ghcr.io/astral-sh/uv:0.11.25 /uv /uvx /bin/
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# 3) рантайм
FROM python:3.14-slim AS runtime
# бэкапы теперь логические (SQLAlchemy) — pg_dump/psql не нужны; только curl для HEALTHCHECK
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl \
    && rm -rf /var/lib/apt/lists/*
RUN addgroup --system --gid 1000 app \
    && adduser --system --uid 1000 --ingroup app --no-create-home --shell /usr/sbin/nologin app
WORKDIR /app
# Версия и дата сборки для экрана «Система» (иначе — дефолт 0.1.0 и mtime кода).
# CI (.github/workflows/publish.yml) прокидывает их через --build-arg из тега релиза.
ARG VPNHUB_VERSION=0.1.0
ARG VPNHUB_BUILT=""
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONPATH="/app/src" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VPNHUB_VERSION=${VPNHUB_VERSION} \
    VPNHUB_BUILT=${VPNHUB_BUILT}
COPY --from=pydeps /app/.venv /app/.venv
COPY backend/ /app/
COPY --from=frontend /fe/dist /app/src/vpnhub/static
RUN chmod +x /app/entrypoint.sh && mkdir -p /var/lib/vpnhub/backups && chown -R app:app /var/lib/vpnhub
USER app
EXPOSE 8000
HEALTHCHECK --interval=15s --timeout=3s --retries=5 \
    CMD curl -fs http://localhost:8000/healthz || exit 1
ENTRYPOINT ["/app/entrypoint.sh"]
