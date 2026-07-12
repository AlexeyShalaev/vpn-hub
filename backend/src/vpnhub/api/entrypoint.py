"""FastAPI entrypoint: create_app() factory + main() (uvicorn)."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response

from vpnhub.api.config import get_settings
from vpnhub.api.routers import api_router
from vpnhub.api.static import add_static
from vpnhub.core.errors import DomainError
from vpnhub.core.i18n import resolve_lang, translate
from vpnhub.infra import keyring
from vpnhub.infra import metrics as mx
from vpnhub.infra.db.migrate import run_migrations
from vpnhub.infra.di import build_container
from vpnhub.infra.keyring import resolve_keys
from vpnhub.infra.providers_store import ProviderStore
from vpnhub.infra.security import gen_master_key
from vpnhub.infra.uow import Uow
from vpnhub.services.audit import AuditService
from vpnhub.services.backups import BackupService
from vpnhub.services.bootstrap import ensure_bootstrap_admin, normalize_user_phones
from vpnhub.services.hostmetrics import HostMetricsService
from vpnhub.services.metrics import MetricsService
from vpnhub.services.servers import ServerService
from vpnhub.services.sync import SyncService
from vpnhub.services.traffic_rollup import TrafficRollupService

_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL обязателен: задайте строку подключения к PostgreSQL.")
    container = build_container()
    app.state.dishka_container = container
    log.info("starting", version=settings.version)

    await run_migrations(settings)

    uow = await container.get(Uow)

    # Мастер-ключ: env → БД → (fresh-инсталл задаёт на setup). Выводит data-ключ в settings.secret_key.
    # bootstrap-админ создаётся ДО проверки ключа: тогда он считается «уже развёрнутым» инстансом,
    # и дефолтный ключ на https приведёт к отказу старта (а не к тихому шифрованию известным ключом).
    await resolve_keys(uow, settings)
    await ensure_bootstrap_admin(uow, settings)
    async with uow.query() as tx:
        setup_pending = (await tx.admins.count()) == 0
    action = keyring.startup_key_action(
        insecure=keyring.master_insecure(),
        setup_pending=setup_pending,
        is_https=settings.base_url.startswith("https"),
    )
    if action == "block":
        raise RuntimeError(
            "Мастер-ключ небезопасен (дефолт из репозитория) — секреты шифровались бы известным ключом. "
            "Задайте VPNHUB_MASTER_KEY (openssl rand -hex 32) или пройдите первичную настройку."
        )
    if action == "warn":
        log.warning("insecure_master_key", suggestion=gen_master_key())
    elif action == "setup":
        log.info("master_key_unset", note="ключ будет задан на экране первичной настройки")

    if not settings.metrics_token:
        log.warning(
            "metrics_unauthenticated",
            note="/metrics отдаётся без токена — задайте VPNHUB_METRICS_TOKEN или закройте на обратном прокси",
        )

    await normalize_user_phones(uow)

    # Домердж новых дефолтных провайдеров в каталог: после обновления версии они доезжают до
    # существующих пользователей (их правки/удаления/кастомные провайдеры сохраняются).
    added_providers = (await container.get(ProviderStore)).sync_default_providers()
    if added_providers:
        log.info("providers_synced", added=added_providers)

    scheduler = AsyncIOScheduler()
    backups = await container.get(BackupService)
    scheduler.add_job(mx.instrument_job("backup-tick", backups.run_tick), "interval", hours=1, id="backup-tick")

    audit = await container.get(AuditService)
    scheduler.add_job(
        mx.instrument_job("audit-retention", audit.purge_old),
        "interval",
        hours=24,
        id="audit-retention",
        max_instances=1,
        coalesce=True,
    )

    traffic_rollup = await container.get(TrafficRollupService)
    scheduler.add_job(
        mx.instrument_job("traffic-rollup", traffic_rollup.run_tick),
        "interval",
        hours=1,
        id="traffic-rollup",
        max_instances=1,
        coalesce=True,
    )

    host_metrics = await container.get(HostMetricsService)
    scheduler.add_job(
        mx.instrument_job("server-metrics-rollup", host_metrics.rollup_tick),
        "interval",
        hours=1,
        id="server-metrics-rollup",
        max_instances=1,
        coalesce=True,
    )

    metrics_svc = await container.get(MetricsService)
    scheduler.add_job(
        mx.instrument_job("metrics-tick", metrics_svc.scrape_tick),
        "interval",
        seconds=settings.metrics_interval,
        id="metrics-tick",
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        mx.instrument_job("metrics-retention", metrics_svc.purge_old),
        "interval",
        hours=24,
        id="metrics-retention",
        max_instances=1,
        coalesce=True,
    )

    monitor = await container.get(ServerService)
    if settings.monitor_enabled:
        scheduler.add_job(
            mx.instrument_job("server-monitor", monitor.run_tick),
            "interval",
            seconds=settings.monitor_interval,
            id="server-monitor",
            max_instances=1,
            coalesce=True,
        )

    if settings.sync_enabled:
        syncer = await container.get(SyncService)
        scheduler.add_job(
            mx.instrument_job("server-sync", syncer.run_tick),
            "interval",
            seconds=settings.sync_interval,
            id="server-sync",
            max_instances=1,
            coalesce=True,
        )

    scheduler.start()
    app.state.scheduler = scheduler

    # стартовый прогон, чтобы статусы не висели «не проверено» до первого тика
    if settings.monitor_enabled:

        async def _initial_sweep() -> None:
            try:
                await monitor.run_tick()
            except Exception:
                log.warning("initial_server_sweep_failed", exc_info=True)

        app.state.monitor_task = asyncio.create_task(_initial_sweep())

    # стартовая сверка: подхватить внешние изменения и «оживить» зависшие installing после рестарта
    if settings.sync_enabled:

        async def _initial_sync() -> None:
            try:
                await syncer.run_tick()
            except Exception:
                log.warning("initial_sync_sweep_failed", exc_info=True)

        app.state.sync_task = asyncio.create_task(_initial_sync())

    yield

    scheduler.shutdown(wait=False)
    for attr in ("monitor_task", "sync_task"):
        task = getattr(app.state, attr, None)
        if task is not None:
            task.cancel()
    await container.close()


def create_app() -> FastAPI:
    settings = get_settings()
    # Swagger/ReDoc/OpenAPI выключены по умолчанию (см. Settings.docs_enabled) — в проде не нужны.
    on = settings.docs_enabled
    app = FastAPI(
        title="VPN Hub",
        version=settings.version,
        lifespan=lifespan,
        docs_url="/docs" if on else None,
        redoc_url="/redoc" if on else None,
        openapi_url="/openapi.json" if on else None,
    )

    @app.exception_handler(DomainError)
    async def _domain_error(request: Request, exc: DomainError) -> JSONResponse:
        headers = {}
        retry_after = getattr(exc, "retry_after", 0)
        if retry_after:
            headers["Retry-After"] = str(retry_after)
        lang = resolve_lang(request.headers.get("accept-language"))
        return JSONResponse(
            {"code": exc.code, "message": exc.localized(lang)}, status_code=exc.http_status, headers=headers or None
        )

    # Шрифты самохостятся (@fontsource) — внешние CDN в CSP не нужны, политика строже.
    csp = (
        "default-src 'self'; "
        "img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; "
        "script-src 'self'; "
        "connect-src 'self'; "
        "font-src 'self' data:; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'"
    )
    hsts_on = settings.base_url.startswith("https")

    @app.middleware("http")
    async def _security_headers(request: Request, call_next: Any) -> Response:
        # CSRF: cookie-сессия + требуем кастомный заголовок, который кросс-сайт не выставит
        # (браузер не даст задать X-Requested-With на cross-origin запрос без CORS-preflight).
        if (
            request.method in _UNSAFE_METHODS
            and request.url.path.startswith("/api/")
            and not request.headers.get("x-requested-with")
        ):
            lang = resolve_lang(request.headers.get("accept-language"))
            return JSONResponse({"code": "CSRF", "message": translate("error.csrf", lang)}, status_code=403)
        t0 = time.perf_counter()
        resp: Response = await call_next(request)
        # прикладная метрика HTTP для admin-дашборда (path нормализуется до шаблона без id)
        mx.observe_http(request.method, request.url.path, resp.status_code, time.perf_counter() - t0)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Content-Security-Policy", csp)
        if hsts_on:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return resp

    app.include_router(api_router)
    add_static(app)
    return app


def main() -> None:
    import uvicorn  # noqa: PLC0415 — ленивый импорт CLI-раннера

    settings = get_settings()
    uvicorn.run(
        "vpnhub.api.entrypoint:create_app",
        factory=True,
        host="0.0.0.0",
        port=settings.port,
    )


if __name__ == "__main__":
    main()
