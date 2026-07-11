"""Самообновление панели: драйверы command / webhook / k8s.

Контейнер не может пересоздать сам себя, поэтому кнопка «Обновить сейчас»
делегирует рестарт внешнему механизму — одному из трёх драйверов:

  • command — VPNHUB_UPDATE_COMMAND: произвольная команда на стороне инстанса
    (например, скрипт с примонтированным docker-сокетом или touch флаг-файла,
    который подхватывает хост);
  • webhook — VPNHUB_UPDATE_WEBHOOK_URL: HTTP-триггер внешнего апдейтера.
    В compose-оверлее selfupdate.compose.yaml это Watchtower HTTP API — он
    пуллит новый образ и пересоздаёт контейнер приложения;
  • k8s — внутри кластера (по serviceaccount-токену): PATCH образа собственного
    Deployment через Kubernetes API; rollout выполняет kubelet. Требует RBAC
    из deploy/k8s/base (ServiceAccount vpnhub + Role patch на deployments).

Статус применения хранится в памяти процесса — сознательно: успешный апдейт
перезапускает процесс с новой версией (UI видит смену версии поллингом),
а упавший — оставляет процесс живым вместе со статусом ошибки.

Без внешних зависимостей: stdlib urllib/ssl в отдельном потоке (как infra/updates.py).
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

import structlog

from vpnhub.core.i18n import DEFAULT_LANG, Lang, translate

if TYPE_CHECKING:
    from vpnhub.api.config import Settings

log = structlog.get_logger(__name__)

# стандартные пути serviceaccount внутри пода (константы модуля — подменяются в тестах)
K8S_TOKEN_FILE = Path("/var/run/secrets/kubernetes.io/serviceaccount/token")
K8S_CA_FILE = Path("/var/run/secrets/kubernetes.io/serviceaccount/ca.crt")
K8S_NAMESPACE_FILE = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")

_WEBHOOK_TIMEOUT = 300.0  # Watchtower отвечает после pull+recreate — это минуты, не секунды

# единственный «слот» применения: {state: running|failed|triggered, mode, target, from, at, log}
_status: dict = {"state": "idle"}
# держим ссылки на фоновые задачи — иначе event loop хранит их слабо и задача может быть собрана GC
_tasks: set[asyncio.Task] = set()

# кэш пре-чека прав в k8s (SelfSubjectAccessReview) — не дёргать API на каждый /system
_K8S_READY_TTL = 60.0
_k8s_ready_cache: dict = {}  # {at, ok, reason}


def detect_mode(settings: Settings) -> str:
    """Какой драйвер доступен: command > webhook > k8s > manual."""
    if settings.update_command:
        return "command"
    if settings.update_webhook_url:
        return "webhook"
    if settings.update_k8s and os.environ.get("KUBERNETES_SERVICE_HOST") and K8S_TOKEN_FILE.exists():
        return "k8s"
    return "manual"


def status() -> dict:
    return dict(_status)


def start(settings: Settings, target: str, lang: Lang = DEFAULT_LANG) -> dict:
    """Запустить применение обновления в фоне. Возвращает принятую заявку.

    Ответ уходит клиенту сразу: применение может убить текущий процесс
    (пересоздание контейнера/пода), и держать HTTP-запрос открытым нельзя.
    """
    if _status.get("state") == "running":
        return {"ok": False, "message": translate("update.already_running", lang), **status()}
    mode = detect_mode(settings)
    _status.clear()
    _status.update({"state": "running", "mode": mode, "target": target, "from": settings.version, "at": time.time()})
    task = asyncio.get_running_loop().create_task(_run(settings, mode, target))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return {"ok": True, "accepted": True, "mode": mode, "target": target, "from": settings.version}


async def _run(settings: Settings, mode: str, target: str) -> None:
    try:
        if mode == "command":
            ok, out = await _apply_command(settings.update_command, target)
        elif mode == "webhook":
            ok, out = await _apply_webhook(settings.update_webhook_url, settings.update_webhook_token)
        elif mode == "k8s":
            ok, out = await _apply_k8s(settings, target)
        else:
            ok, out = False, "Автообновление не настроено"
    except Exception as exc:  # драйвер не должен ронять процесс — любая ошибка в статус
        ok, out = False, str(exc)
    log.info("selfupdate_apply", mode=mode, target=target, ok=ok)
    # triggered ≠ done: сам рестарт делает внешний механизм; успех UI видит по смене версии
    _status.update({"state": "triggered" if ok else "failed", "log": out[-2000:]})


async def _apply_command(cmd: str, target: str) -> tuple[bool, str]:
    """Выполнить настроенную команду; {version} в ней заменяется на целевую версию."""
    cmd = cmd.replace("{version}", target)
    proc = await asyncio.create_subprocess_shell(cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT)
    out, _ = await proc.communicate()
    text = out.decode("utf-8", "replace") if out else ""
    if proc.returncode != 0:
        return False, f"Команда обновления завершилась с кодом {proc.returncode}\n{text}"
    return True, text


async def _apply_webhook(url: str, token: str) -> tuple[bool, str]:
    """Дёрнуть HTTP-апдейтер (Watchtower: POST /v1/update, Bearer-токен).

    Апдейтер пересоздаёт наш контейнер прямо во время запроса, поэтому обрыв
    соединения после успешной отправки — штатный исход, а не ошибка.
    """

    def _post() -> tuple[bool, str]:
        if not url.lower().startswith(("http://", "https://")):
            return False, "VPNHUB_UPDATE_WEBHOOK_URL должен начинаться с http(s)://"
        headers = {"User-Agent": "vpnhub-selfupdate"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        req = urllib.request.Request(url, data=b"", headers=headers, method="POST")  # noqa: S310 — схема проверена
        try:
            with urllib.request.urlopen(req, timeout=_WEBHOOK_TIMEOUT) as resp:  # noqa: S310
                body = resp.read().decode("utf-8", "replace")
                return True, body or f"HTTP {resp.status}"
        except urllib.error.HTTPError as exc:  # быстрый честный отказ: неверный токен/путь
            return False, f"Апдейтер ответил HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:500]}"
        except (TimeoutError, OSError) as exc:
            # запрос ушёл, но ответа нет — вероятнее всего апдейтер уже гасит наш контейнер
            return True, f"Апдейтер запущен, соединение прервано перезапуском ({exc.__class__.__name__})"

    return await asyncio.to_thread(_post)


def _k8s_request(settings: Settings, target: str, namespace: str, token: str) -> urllib.request.Request:
    """Собрать PATCH-запрос образа собственного Deployment (чистая функция — тестируется без кластера)."""
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    name = settings.update_k8s_deployment
    container = {"name": settings.update_k8s_container, "image": f"{settings.image}:{target}"}
    url = f"https://{host}:{port}/apis/apps/v1/namespaces/{namespace}/deployments/{name}?fieldManager=vpnhub-selfupdate"
    patch = {"spec": {"template": {"spec": {"containers": [container]}}}}
    return urllib.request.Request(  # noqa: S310 — https внутри кластера
        url,
        data=json.dumps(patch).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/strategic-merge-patch+json",
            "Accept": "application/json",
            "User-Agent": "vpnhub-selfupdate",
        },
        method="PATCH",
    )


async def _apply_k8s(settings: Settings, target: str) -> tuple[bool, str]:
    """PATCH образа своего Deployment; пересоздание пода выполняет kubelet (strategy Recreate)."""

    def _patch() -> tuple[bool, str]:
        token = K8S_TOKEN_FILE.read_text().strip()
        namespace = K8S_NAMESPACE_FILE.read_text().strip() if K8S_NAMESPACE_FILE.exists() else "default"
        req = _k8s_request(settings, target, namespace, token)
        ctx = ssl.create_default_context(cafile=str(K8S_CA_FILE)) if K8S_CA_FILE.exists() else None
        try:
            with urllib.request.urlopen(req, timeout=15, context=ctx) as resp:  # noqa: S310
                resp.read()
                return True, f"Deployment {settings.update_k8s_deployment} → {settings.image}:{target}"
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:500]
            hint = ""
            if exc.code == 403:
                hint = (
                    " Нет прав на patch deployments — примените RBAC-манифесты"
                    " из deploy/k8s/base (serviceaccount/role)."
                )
            return False, f"Kubernetes API ответил HTTP {exc.code}.{hint}\n{body}"

    return await asyncio.to_thread(_patch)


def _ssar_request(settings: Settings, namespace: str, token: str) -> urllib.request.Request:
    """Собрать SelfSubjectAccessReview «могу ли я patch-ить свой Deployment» (чистая функция)."""
    host = os.environ.get("KUBERNETES_SERVICE_HOST", "kubernetes.default.svc")
    port = os.environ.get("KUBERNETES_SERVICE_PORT", "443")
    review = {
        "apiVersion": "authorization.k8s.io/v1",
        "kind": "SelfSubjectAccessReview",
        "spec": {
            "resourceAttributes": {
                "namespace": namespace,
                "verb": "patch",
                "group": "apps",
                "resource": "deployments",
                "name": settings.update_k8s_deployment,
            }
        },
    }
    url = f"https://{host}:{port}/apis/authorization.k8s.io/v1/selfsubjectaccessreviews"
    return urllib.request.Request(  # noqa: S310 — https внутри кластера
        url,
        data=json.dumps(review).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "vpnhub-selfupdate",
        },
        method="POST",
    )


# сообщение, когда панель в k8s, но RBAC не применён (пре-чек вернул allowed=false)
K8S_NO_RBAC_HINT = (
    "Панель работает в Kubernetes, но у неё нет прав patch на свой Deployment. "
    "Примените RBAC: kubectl apply -k нужный оверлей из deploy/k8s "
    "(или kubectl apply -f deploy/k8s/base/rbac.yaml и задайте serviceAccountName: vpnhub у Deployment)."
)


def _k8s_ssar(settings: Settings) -> tuple[bool, str]:
    """Синхронный SSAR-запрос. allowed=false → (False, подсказка); сетевая ошибка → fail-open."""
    try:
        token = K8S_TOKEN_FILE.read_text().strip()
        namespace = K8S_NAMESPACE_FILE.read_text().strip() if K8S_NAMESPACE_FILE.exists() else "default"
    except OSError:
        return True, ""  # токен недоступен — не прячем кнопку, пусть решает само применение
    try:
        req = _ssar_request(settings, namespace, token)
        # контекст TLS строим ВНУТРИ try: битый/нечитаемый CA (ssl.SSLError ⊂ OSError) не должен
        # ронять /system — пре-чек обязан fail-open, а не 500-ить всю страницу.
        ctx = ssl.create_default_context(cafile=str(K8S_CA_FILE)) if K8S_CA_FILE.exists() else None
        with urllib.request.urlopen(req, timeout=8, context=ctx) as resp:  # noqa: S310
            data = json.loads(resp.read())
    except (urllib.error.HTTPError, TimeoutError, OSError, ValueError) as exc:
        log.warning("selfupdate_ssar_failed", error=str(exc))
        return True, ""  # fail-open: пре-чек не удался — не прячем кнопку из-за глюка сети/TLS
    status = data.get("status") if isinstance(data, dict) else None
    if not isinstance(status, dict):
        return True, ""  # ответ без внятного status — пре-чек неинформативен, fail-open
    return (True, "") if status.get("allowed") else (False, K8S_NO_RBAC_HINT)


async def k8s_ready(settings: Settings) -> tuple[bool, str]:
    """Может ли под патчить свой Deployment? Пре-чек через SelfSubjectAccessReview, кэш на TTL.

    SSAR доступен любому аутентифицированному SA (в т.ч. default), поэтому надёжно отличает
    «RBAC не применён» (allowed=false) от рабочего состояния — не наткнувшись на 403 при апдейте.
    """
    now = time.time()
    if _k8s_ready_cache and now - _k8s_ready_cache.get("at", 0.0) < _K8S_READY_TTL:
        return _k8s_ready_cache["ok"], _k8s_ready_cache["reason"]
    ok, reason = await asyncio.to_thread(_k8s_ssar, settings)
    _k8s_ready_cache.clear()
    _k8s_ready_cache.update({"at": now, "ok": ok, "reason": reason})
    return ok, reason
