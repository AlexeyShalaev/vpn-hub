"""Роутеры администратора: пользователи и система."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Depends, File, Form, UploadFile
from fastapi.responses import FileResponse

from vpnhub.api.deps import require_admin, service
from vpnhub.infra.providers_store import ProviderStore
from vpnhub.services.admin import AdminService
from vpnhub.services.auth import Identity
from vpnhub.services.backups import BackupService

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
async def system(_: Identity = Depends(require_admin), svc: AdminService = Depends(service(AdminService))) -> dict:
    return await svc.system()


@router.post("/system/check-updates")
async def check_updates(
    _: Identity = Depends(require_admin), svc: AdminService = Depends(service(AdminService))
) -> dict:
    return await svc.check_updates()


@router.post("/system/upgrade")
async def upgrade(_: Identity = Depends(require_admin), svc: AdminService = Depends(service(AdminService))) -> dict:
    return await svc.apply_update()


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
