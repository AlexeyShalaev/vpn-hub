"""Роутеры авторизации и первичной настройки."""

from __future__ import annotations

from fastapi import APIRouter, Depends, File, Form, Request, Response, UploadFile
from pydantic import BaseModel

from vpnhub.api.deps import (
    COOKIE,
    clear_session_cookie,
    client_meta,
    current_identity,
    rate_limit,
    require_user,
    service,
    set_session_cookie,
)
from vpnhub.core.errors import BadRequest, Forbidden
from vpnhub.services.auth import AuthService, Identity
from vpnhub.services.backups import BackupService
from vpnhub.services.groups import GroupService
from vpnhub.services.servers import ServerService

router = APIRouter(prefix="/api/v1", tags=["auth"])


class RegisterIn(BaseModel):
    name: str = ""
    phone: str = ""
    password: str = ""
    password2: str = ""


class LoginIn(BaseModel):
    phone: str = ""
    password: str = ""


class ChangePasswordIn(BaseModel):
    current: str = ""
    new: str = ""


class SetupIn(BaseModel):
    name: str = ""
    phone: str = ""
    password: str = ""
    password2: str = ""
    masterKey: str = ""  # noqa: N815 — поле совпадает с JSON-ключом фронтенда (мастер-ключ восстановления)


async def build_me(request: Request, ident: Identity) -> dict:
    role = "owner"
    if ident.kind == "user":
        servers: ServerService = await request.app.state.dishka_container.get(ServerService)
        groups: GroupService = await request.app.state.dishka_container.get(GroupService)
        has = bool(await servers.list(ident.id)) or bool(await groups.list(ident.id))
        role = "owner" if has else "member"
    return {
        "id": ident.id,
        "kind": ident.kind,
        "name": ident.name,
        "phone": ident.phone,
        "isAdmin": ident.kind == "admin",
        "role": role,
    }


@router.get("/setup/status")
async def setup_status(auth: AuthService = Depends(service(AuthService))) -> dict:
    # keyFromEnv: ключ задан через VPNHUB_BACKUP_KEY → вводить его в форме не нужно
    return {"needed": await auth.setup_needed(), "keyFromEnv": bool(auth.settings.master_key)}


@router.post("/setup/admin", dependencies=[Depends(rate_limit("setup", 5, 600))])
async def setup_admin(
    body: SetupIn,
    request: Request,
    response: Response,
    auth: AuthService = Depends(service(AuthService)),
    backups: BackupService = Depends(service(BackupService)),
) -> dict:
    key_from_env = bool(backups.settings.master_key)
    if not key_from_env:
        if not body.masterKey:
            raise BadRequest(key="authApi.master_key_required")
        if len(body.masterKey) < 8:
            raise BadRequest(key="authApi.master_key_too_short")
    ip, ua = client_meta(request)
    token = await auth.create_first_admin(body.name, body.phone, body.password, body.password2, ip=ip, ua=ua)
    set_session_cookie(response, token, request=request)
    if not key_from_env:
        await backups.set_key(body.masterKey)
    ident = await auth.resolve(token)
    assert ident is not None
    return await build_me(request, ident)


@router.post("/setup/restore", dependencies=[Depends(rate_limit("restore", 5, 600))])
async def setup_restore(
    file: UploadFile = File(...),
    key: str = Form(...),
    auth: AuthService = Depends(service(AuthService)),
    backups: BackupService = Depends(service(BackupService)),
) -> dict:
    """Развернуть систему из существующего бэкапа (только пока система не настроена)."""
    if not await auth.setup_needed():
        raise Forbidden(key="authApi.system_already_configured")
    await backups.restore_from_bytes(await file.read(), key)
    return {"ok": True}


@router.post("/auth/register", dependencies=[Depends(rate_limit("register", 5, 600))])
async def register(
    body: RegisterIn,
    auth: AuthService = Depends(service(AuthService)),
) -> dict:
    # Номер не подтверждается по SMS — новая учётка создаётся в статусе pending
    # и активируется администратором (или автоматически при наличии приглашения).
    await auth.register(body.name, body.phone, body.password, body.password2)
    return {"ok": True}


@router.post("/auth/login", dependencies=[Depends(rate_limit("login", 10, 300))])
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    auth: AuthService = Depends(service(AuthService)),
) -> dict:
    ip, ua = client_meta(request)
    token = await auth.login(body.phone, body.password, ip=ip, ua=ua)
    set_session_cookie(response, token, request=request)
    ident = await auth.resolve(token)
    assert ident is not None
    return await build_me(request, ident)


@router.post("/auth/change-password", dependencies=[Depends(rate_limit("change-password", 10, 300))])
async def change_password(
    body: ChangePasswordIn,
    request: Request,
    ident: Identity = Depends(require_user),
    auth: AuthService = Depends(service(AuthService)),
) -> dict:
    await auth.change_password(ident.id, body.current, body.new, request.cookies.get(COOKIE))
    return {"ok": True}


@router.get("/auth/sessions")
async def list_sessions(
    request: Request,
    ident: Identity = Depends(require_user),
    auth: AuthService = Depends(service(AuthService)),
) -> list[dict]:
    return await auth.list_sessions(request.cookies.get(COOKIE), ident.id)


@router.delete("/auth/sessions/{sid}")
async def revoke_session(
    sid: str,
    request: Request,
    ident: Identity = Depends(require_user),
    auth: AuthService = Depends(service(AuthService)),
) -> dict:
    await auth.revoke_session(request.cookies.get(COOKIE), ident.id, sid)
    return {"ok": True}


@router.post("/auth/sessions/revoke-others")
async def revoke_other_sessions(
    request: Request,
    ident: Identity = Depends(require_user),
    auth: AuthService = Depends(service(AuthService)),
) -> dict:
    n = await auth.revoke_others(request.cookies.get(COOKIE), ident.id)
    return {"ok": True, "revoked": n}


@router.post("/auth/logout")
async def logout(request: Request, response: Response, auth: AuthService = Depends(service(AuthService))) -> dict:
    await auth.logout(request.cookies.get("vpnhub_session"))
    clear_session_cookie(response)
    return {"ok": True}


@router.get("/auth/me")
async def me(request: Request) -> dict | None:
    ident = await current_identity(request)
    if not ident:
        return None
    return await build_me(request, ident)
