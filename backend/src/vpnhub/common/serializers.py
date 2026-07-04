"""ORM → dict в форме прототипа (camelCase), плюс форматирование времени/латентности."""

from __future__ import annotations

import time

from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning import remediation


def rel_time(epoch: float | None) -> str | None:
    if not epoch:
        return None
    diff = max(0, int(time.time() - epoch))
    if diff < 45:
        return "только что"
    if diff < 3600:
        return f"{max(1, diff // 60)} мин назад"
    if diff < 86400:
        return f"{diff // 3600} ч назад"
    return f"{diff // 86400} дн назад"


def latency_str(ms: int | None) -> str | None:
    return f"{ms} мс" if ms is not None else None


def _ua_label(ua: str | None) -> str:
    if not ua:
        return "Неизвестное устройство"
    u = ua.lower()
    if "windows" in u:
        os_name = "Windows"
    elif "macintosh" in u or "mac os" in u:
        os_name = "macOS"
    elif "iphone" in u or "ipad" in u:
        os_name = "iOS"
    elif "android" in u:
        os_name = "Android"
    elif "linux" in u:
        os_name = "Linux"
    else:
        os_name = "—"
    if "edg" in u:
        browser = "Edge"
    elif "chrome" in u:
        browser = "Chrome"
    elif "firefox" in u:
        browser = "Firefox"
    elif "safari" in u:
        browser = "Safari"
    else:
        browser = "—"
    return f"{browser} · {os_name}"


def session_to_dict(s: m.Session, current: bool) -> dict:
    created = s.created_at.timestamp() if s.created_at else None
    seen = s.updated_at.timestamp() if s.updated_at else None
    return {
        "id": s.id,
        "ip": s.ip or "—",
        "device": _ua_label(s.user_agent),
        "userAgent": s.user_agent or "",
        "createdAt": time.strftime("%d.%m.%Y %H:%M", time.localtime(created)) if created else "",
        "lastSeen": rel_time(seen),
        "current": current,
    }


def vpn_to_dict(v: m.ServerVpn) -> dict:
    return {"type": v.type, "installed": v.installed, "running": v.running, "port": v.port}


def _remediation_dict(p: m.ServerProtocol) -> dict | None:
    """Подсказка-ремедиация для сбойного протокола (None, если состояние не error или код неизвестен)."""
    if p.state != "error":
        return None
    rem = remediation.resolve(p.error_code, p.error)
    return remediation.to_dict(rem) if rem is not None else None


def protocol_to_dict(p: m.ServerProtocol) -> dict:
    return {
        "vendor": p.vendor,
        "proto": p.proto,
        "container": p.container,
        "port": p.port,
        "state": p.state,
        "installed": p.installed,
        "running": p.running,
        "error": p.error,
        "errorCode": p.error_code,
        "remediation": _remediation_dict(p),
        "externalClients": p.external_clients,
    }


def server_to_dict(s: m.Server, secret: str | None = None) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "provider": s.provider,
        "ip": s.ip,
        "sshUser": s.ssh_user,
        "sshPort": s.ssh_port,
        "auth": s.ssh_auth,
        "secret": secret if secret is not None else "",
        "location": s.location,
        "status": s.status,
        "latency": latency_str(s.latency_ms),
        "lastCheck": rel_time(s.last_check_at),
        "vpns": [vpn_to_dict(v) for v in sorted(s.vpns, key=lambda x: x.type)],
        "protocols": [protocol_to_dict(p) for p in sorted(s.protocols, key=lambda x: x.proto)],
    }


def pool_to_dict(p: m.Pool, server_ids: list[str]) -> dict:
    return {"id": p.id, "name": p.name, "serverIds": server_ids}


def member_to_dict(mb: m.GroupMember) -> dict:
    return {"id": mb.id, "name": mb.display_name, "role": mb.role, "status": mb.status, "phone": mb.phone or ""}


def group_to_dict(g: m.Group, pools: list[str], servers: dict[str, list[str]]) -> dict:
    return {
        "id": g.id,
        "name": g.name,
        "token": g.token,
        "members": [member_to_dict(mb) for mb in g.members],
        "access": {"pools": pools, "servers": servers},
    }


def device_to_dict(d: m.Device) -> dict:
    return {
        "id": d.id,
        "name": d.name,
        "platform": d.platform,
        "configs": [
            {"serverId": c.server_id, "type": c.vpn_type, "proto": c.proto, "status": c.status} for c in d.configs
        ],
    }


def user_to_dict(u: m.User) -> dict:
    return {
        "id": u.id,
        "phone": u.phone,
        "name": u.name,
        "status": u.status,
        "createdAt": u.created_at.strftime("%d.%m.%Y") if u.created_at else "",
    }
