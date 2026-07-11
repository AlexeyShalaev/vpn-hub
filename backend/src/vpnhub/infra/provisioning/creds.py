"""Единый маппинг ORM-сервера в SSH-креды (общий для provisioning и hostmetrics)."""

from __future__ import annotations

from vpnhub.infra.db.orm import models as m
from vpnhub.infra.provisioning.ssh import ServerCreds
from vpnhub.infra.security import decrypt_secret


def server_creds(server: m.Server, secret_key: str) -> ServerCreds:
    """Построить `ServerCreds` из строки Server (дешифруя ssh-секрет). Дефолты: root@:22, auth=key."""
    return ServerCreds(
        host=server.ip,
        port=int(server.ssh_port or 22),
        username=server.ssh_user or "root",
        auth=server.ssh_auth or "key",
        secret=decrypt_secret(secret_key, server.ssh_secret_encrypted or ""),
    )
