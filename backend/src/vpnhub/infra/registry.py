"""Есть ли тег образа в container registry (OCI distribution API, анонимно).

Зачем: release-please публикует релиз на GitHub раньше, чем publish.yml успевает собрать и
запушить образ (10-15 минут). Панель, увидев релиз в фиде, не должна предлагать и тем более
применять обновление на тег, которого ещё нет в реестре: в k8s (strategy Recreate) старый под
гасится до старта нового, и новый навсегда застревает в ImagePullBackOff.

Протокол: HEAD /v2/<repo>/manifests/<tag>. Публичные реестры (ghcr.io, Docker Hub и др.)
отвечают 401 с `WWW-Authenticate: Bearer realm=...,service=...,scope=...` — берём анонимный
токен у realm и повторяем запрос.

Результат трёхзначный: True — тег есть, False — реестр уверенно сказал «нет» (404),
None — не удалось выяснить (сеть, приватный реестр, нестандартный ответ). Вызывающий сам
решает, как трактовать None; блокируем обновление только на уверенном False.

Без внешних зависимостей: stdlib urllib в отдельном потоке (как infra/updates.py).
"""

from __future__ import annotations

import asyncio
import json
import re
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

import certifi
import structlog

log = structlog.get_logger(__name__)

_DOCKER_HUB = "registry-1.docker.io"
_TIMEOUT = 8.0
_MANIFEST_ACCEPT = ", ".join(
    [
        "application/vnd.oci.image.index.v1+json",
        "application/vnd.oci.image.manifest.v1+json",
        "application/vnd.docker.distribution.manifest.list.v2+json",
        "application/vnd.docker.distribution.manifest.v2+json",
    ]
)
_AUTH_PARAM = re.compile(r'(\w+)="([^"]*)"')


def _ssl_context() -> ssl.SSLContext:
    # certifi, а не системное хранилище: как в provider_plans/http.py — не зависим от CA образа/хоста
    return ssl.create_default_context(cafile=certifi.where())


@dataclass(frozen=True)
class ImageRef:
    registry: str  # хост[:порт] без схемы
    repository: str  # путь внутри реестра (library/nginx, alexeyshalaev/vpn-hub)


def parse_image(image: str) -> ImageRef:
    """`ghcr.io/owner/name` → (ghcr.io, owner/name); `nginx` → (registry-1.docker.io, library/nginx).

    Первый сегмент считается хостом реестра, если в нём есть точка или порт, либо это localhost —
    то же правило, что у docker. Тег/дайджест в image не ожидаем (тег передаётся отдельно).
    """
    name = image.strip().split("@", 1)[0]
    first, _, rest = name.partition("/")
    if rest and ("." in first or ":" in first or first == "localhost"):
        registry, repository = first, rest
    else:
        registry, repository = _DOCKER_HUB, name
    if registry in ("docker.io", "index.docker.io"):
        registry = _DOCKER_HUB
    if registry == _DOCKER_HUB and "/" not in repository:
        repository = f"library/{repository}"
    return ImageRef(registry=registry, repository=repository.lower())


def _manifest_request(ref: ImageRef, tag: str, token: str | None = None) -> urllib.request.Request:
    url = f"https://{ref.registry}/v2/{ref.repository}/manifests/{urllib.parse.quote(tag, safe='')}"
    headers = {"Accept": _MANIFEST_ACCEPT, "User-Agent": "vpnhub-update-check"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return urllib.request.Request(url, headers=headers, method="HEAD")  # noqa: S310 — всегда https


def _token_url(challenge: str, ref: ImageRef) -> str | None:
    """URL анонимного токена из `WWW-Authenticate: Bearer realm=..,service=..,scope=..`."""
    scheme, _, params = challenge.partition(" ")
    if scheme.lower() != "bearer":
        return None
    fields = dict(_AUTH_PARAM.findall(params))
    realm = fields.get("realm", "")
    if not realm.lower().startswith("https://"):
        return None
    query = {"scope": fields.get("scope") or f"repository:{ref.repository}:pull"}
    if fields.get("service"):
        query["service"] = fields["service"]
    sep = "&" if "?" in realm else "?"
    return f"{realm}{sep}{urllib.parse.urlencode(query)}"


def _fetch_token(url: str) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": "vpnhub-update-check"})  # noqa: S310 — https
    with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ssl_context()) as resp:  # noqa: S310
        data = json.loads(resp.read().decode("utf-8", "replace") or "{}")
    token = data.get("token") or data.get("access_token")
    return str(token) if token else None


def _head(req: urllib.request.Request) -> tuple[int, str]:
    """Код ответа + WWW-Authenticate (для 401). HTTPError — это тоже ответ, а не сбой."""
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=_ssl_context()) as resp:  # noqa: S310
            return resp.status, ""
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("WWW-Authenticate", "") if exc.headers else ""


def _verdict(code: int) -> bool | None:
    if 200 <= code < 300:
        return True
    if code == 404:
        return False
    return None


def _check(ref: ImageRef, tag: str) -> bool | None:
    code, challenge = _head(_manifest_request(ref, tag))
    if code == 401 and challenge:
        token_url = _token_url(challenge, ref)
        if not token_url:
            return None
        token = _fetch_token(token_url)
        if not token:
            return None
        code, _ = _head(_manifest_request(ref, tag, token))
    return _verdict(code)


async def tag_exists(image: str, tag: str) -> bool | None:
    """Есть ли `image:tag` в реестре: True / False (уверенный 404) / None (не удалось выяснить)."""
    if not image or not tag:
        return None
    ref = parse_image(image)
    try:
        return await asyncio.to_thread(_check, ref, tag)
    except Exception as exc:  # сеть/DNS/кривой JSON — «не знаем», решает вызывающий
        log.warning("registry_tag_check_failed", image=image, tag=tag, error=str(exc))
        return None
