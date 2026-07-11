"""Роутеры администратора: пользователи и система."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse

from vpnhub.api.deps import req_lang, require_admin, service
from vpnhub.core.i18n import Lang
from vpnhub.infra.providers_store import ProviderStore
from vpnhub.services.admin import AdminService
from vpnhub.services.auth import Identity
from vpnhub.services.backups import BackupService
from vpnhub.services.metrics import MetricsService

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


@router.get("/users")
async def users(_: Identity = Depends(require_admin), svc: AdminService = Depends(service(AdminService))) -> list[dict]:
    return await svc.users()


@router.patch("/users/{uid}")
async def update_user(
    uid: str,
    body: dict[str, Any] = Body(...),
    _: Identity = Depends(require_admin),
    svc: AdminService = Depends(service(AdminService)),
) -> dict:
    return await svc.update_user(
        uid,
        body.get("name", ""),
        body.get("phone", ""),
        body.get("status", "active"),
        body.get("newPassword"),
    )


@router.delete("/users/{uid}")
async def delete_user(
    uid: str, _: Identity = Depends(require_admin), svc: AdminService = Depends(service(AdminService))
) -> dict:
    await svc.delete_user(uid)
    return {"ok": True}


@router.get("/system")
async def system(
    _: Identity = Depends(require_admin),
    svc: AdminService = Depends(service(AdminService)),
    lang: Lang = Depends(req_lang),
) -> dict:
    return await svc.system(lang)


@router.get("/system/storage")
async def system_storage(
    _: Identity = Depends(require_admin), svc: AdminService = Depends(service(AdminService))
) -> dict:
    """Развёртывание + дисковое использование (папки, тома, размер БД по таблицам) — для админ-дашборда."""
    return await svc.storage()


@router.get("/metrics")
async def metrics(
    period: str = "24h",
    _: Identity = Depends(require_admin),
    svc: MetricsService = Depends(service(MetricsService)),
) -> dict:
    """Временные ряды здоровья инстанса панели (не путать с owner-трафиком)."""
    return await svc.overview(period)


@router.post("/system/check-updates")
async def check_updates(
    _: Identity = Depends(require_admin),
    svc: AdminService = Depends(service(AdminService)),
    lang: Lang = Depends(req_lang),
) -> dict:
    return await svc.check_updates(lang)


@router.post("/system/upgrade")
async def upgrade(
    _: Identity = Depends(require_admin),
    svc: AdminService = Depends(service(AdminService)),
    lang: Lang = Depends(req_lang),
) -> dict:
    return await svc.apply_update(lang)


@router.get("/system/upgrade/status")
async def upgrade_status(
    _: Identity = Depends(require_admin), svc: AdminService = Depends(service(AdminService))
) -> dict:
    return svc.upgrade_status()


@router.post("/system/backups")
async def create_backup(
    _: Identity = Depends(require_admin), svc: BackupService = Depends(service(BackupService))
) -> dict:
    return await svc.create_backup("manual")


@router.delete("/system/backups/{bid}")
async def delete_backup(
    bid: str, _: Identity = Depends(require_admin), svc: BackupService = Depends(service(BackupService))
) -> dict:
    svc.delete_backup(bid)
    return {"ok": True}


@router.get("/system/backups/{bid}/download")
async def download_backup(
    bid: str, _: Identity = Depends(require_admin), svc: BackupService = Depends(service(BackupService))
) -> FileResponse:
    return FileResponse(svc.backup_path(bid), media_type="application/octet-stream", filename=bid)


@router.post("/system/backups/import")
async def import_backup(
    file: UploadFile = File(...),
    key: str = Form(...),
    _: Identity = Depends(require_admin),
    svc: BackupService = Depends(service(BackupService)),
) -> dict:
    return await svc.restore_from_bytes(await file.read(), key)


@router.put("/system/backup-settings")
async def backup_settings(
    body: dict[str, Any] = Body(...),
    _: Identity = Depends(require_admin),
    svc: BackupService = Depends(service(BackupService)),
) -> dict:
    if body.get("frequency") is not None:
        await svc.set_frequency(body["frequency"])
    if body.get("key"):
        await svc.set_key(body["key"])
    return {"ok": True}


@router.put("/system/device-limit")
async def set_device_limit(
    body: dict[str, Any] = Body(default={}),
    _: Identity = Depends(require_admin),
    svc: AdminService = Depends(service(AdminService)),
) -> dict:
    # кривой (нечисловой) ввод → 0, чтобы сервис вернул чистый 400, а не int() бросил 500
    raw = body.get("defaultDevicesPerUser") if isinstance(body, dict) else None
    n = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else 0
    await svc.set_default_devices(n)
    return {"ok": True}


@router.put("/system/user-byte-limit")
async def set_user_byte_limit(
    body: dict[str, Any] = Body(default={}),
    _: Identity = Depends(require_admin),
    svc: AdminService = Depends(service(AdminService)),
) -> dict:
    # body: { "defaultUserBytes": int | null } — глобальный дефолт трафика на пользователя (null/0 = без лимита)
    raw = body.get("defaultUserBytes") if isinstance(body, dict) else None
    n = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0 else None
    await svc.set_default_user_bytes(n)
    return {"ok": True}


@router.put("/system/metrics-retention")
async def set_metrics_retention(
    body: dict[str, Any] = Body(default={}),
    _: Identity = Depends(require_admin),
    svc: AdminService = Depends(service(AdminService)),
) -> dict:
    # body: { "rawRetentionDays": int|null (null/0 = env-дефолт), "sizeCapGb": number (0 = без лимита) }
    raw = body.get("rawRetentionDays") if isinstance(body, dict) else None
    cap = body.get("sizeCapGb") if isinstance(body, dict) else None
    raw_days = int(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) and raw > 0 else None
    size_cap = float(cap) if isinstance(cap, (int, float)) and not isinstance(cap, bool) and cap > 0 else None
    await svc.set_metrics_retention(raw_days, size_cap)
    return {"ok": True}


# ---------- providers (каталог VPS) ----------


@router.post("/providers")
async def create_provider(
    body: dict[str, Any] = Body(...),
    _: Identity = Depends(require_admin),
    store: ProviderStore = Depends(service(ProviderStore)),
) -> dict:
    return store.create(body)


@router.put("/providers/{pid}")
async def update_provider(
    pid: str,
    body: dict[str, Any] = Body(...),
    _: Identity = Depends(require_admin),
    store: ProviderStore = Depends(service(ProviderStore)),
) -> dict:
    return store.update(pid, body)


@router.delete("/providers/{pid}")
async def delete_provider(
    pid: str,
    _: Identity = Depends(require_admin),
    store: ProviderStore = Depends(service(ProviderStore)),
) -> dict:
    store.delete(pid)
    return {"ok": True}
