"""Зонды системы для админ-дашборда: способ развёртывания, рабочие директории, использование диска и БД.

Всё read-only и без секретов: имена/пути/размеры, метод деплоя (k8s/docker/host), рантайм-инфо.
Размер тома — `shutil.disk_usage`; размер директории — сумма размеров файлов (stat, без чтения содержимого);
размер БД — Postgres `pg_database_size` + топ таблиц (SQLite → None, как в metrics-retention).
"""

from __future__ import annotations

import os
import platform
import resource
import shutil
import sys
import time
from pathlib import Path
from typing import Any

from sqlalchemy import text

_K8S_NS_FILE = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
_DEPLOY_LABELS = {
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "compose": "Docker Compose",
    "docker": "Docker / контейнер",
    "host": "Хост-процесс (без контейнера)",
}


def _in_container() -> bool:
    """Признаки контейнера: /.dockerenv или docker/containerd/kubepods в cgroup pid 1."""
    if Path("/.dockerenv").exists():
        return True
    try:
        cgroup = Path("/proc/1/cgroup").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return False
    return any(marker in cgroup for marker in ("docker", "containerd", "kubepods", "crio"))


def _rss_bytes() -> int | None:
    """Резидентная память процесса (пиковая, ru_maxrss): Linux даёт КБ, macOS/BSD — байты."""
    try:
        maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (OSError, ValueError):
        return None
    return maxrss * 1024 if sys.platform.startswith("linux") else maxrss


def detect_deployment() -> dict[str, Any]:
    """Способ развёртывания + рантайм-инфо (без секретов). Явный `VPNHUB_DEPLOY` имеет приоритет."""
    k8s = bool(os.environ.get("KUBERNETES_SERVICE_HOST"))
    container = _in_container()
    if k8s:
        method = "kubernetes"
    elif container:
        method = "docker"
    else:
        method = "host"
    if override := os.environ.get("VPNHUB_DEPLOY", "").strip().lower():
        method = "kubernetes" if override == "k8s" else override
    namespace = None
    if k8s:
        namespace = os.environ.get("POD_NAMESPACE") or (
            _K8S_NS_FILE.read_text(encoding="utf-8").strip() if _K8S_NS_FILE.exists() else None
        )
    return {
        "method": method,
        "methodLabel": _DEPLOY_LABELS.get(method, method),
        "container": container,
        "hostname": platform.node(),
        "pid": os.getpid(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "cpuCount": os.cpu_count(),
        "rssBytes": _rss_bytes(),
        "namespace": namespace,
        "pod": os.environ.get("POD_NAME") or (platform.node() if k8s else None),
        "cwd": str(Path.cwd()),
        "tz": time.strftime("%Z"),
    }


def dir_usage(label: str, path: str, *, kind: str) -> dict[str, Any]:
    """Размер и статус рабочей директории: путь, существует ли, пишем ли, суммарный размер, число файлов.

    Символические ссылки не разыменовываем (не следуем за пределы дерева). Ошибки stat отдельных файлов
    молча пропускаем — отчёт не должен падать из-за гонки удаления.
    """
    p = Path(path)
    exists = p.exists()
    size, files = 0, 0
    if exists and p.is_dir():
        for root, _dirs, names in os.walk(p, followlinks=False):
            root_path = Path(root)
            for name in names:
                try:
                    size += (root_path / name).lstat().st_size
                    files += 1
                except OSError:
                    continue
    elif exists and p.is_file():
        size, files = p.stat().st_size, 1
    probe = p if exists else p.parent
    return {
        "label": label,
        "kind": kind,
        "path": str(p.resolve()) if exists else str(p),
        "exists": exists,
        "writable": os.access(probe, os.W_OK),
        "sizeBytes": size,
        "files": files,
    }


def volume_usage(paths: list[str]) -> list[dict[str, Any]]:
    """Использование тома (total/used/free) для набора путей, дедуп по точке монтирования (device id)."""
    seen: dict[int, dict[str, Any]] = {}
    for path in paths:
        p = Path(path)
        probe = p if p.exists() else p.parent
        try:
            usage = shutil.disk_usage(probe)
            dev = probe.stat().st_dev
        except OSError:
            continue
        if dev in seen:
            continue
        seen[dev] = {
            "path": str(probe),
            "totalBytes": usage.total,
            "usedBytes": usage.used,
            "freeBytes": usage.free,
        }
    return list(seen.values())


async def db_disk_usage(session: Any, *, top: int = 12) -> dict[str, Any]:
    """Размер БД целиком + топ таблиц по размеру (rows — оценка n_live_tup). Только Postgres; иначе None."""
    try:
        total = (await session.execute(text("SELECT pg_database_size(current_database())"))).scalar()
        rows = (
            await session.execute(
                text(
                    "SELECT relname, pg_total_relation_size(relid) AS bytes, n_live_tup "
                    "FROM pg_stat_user_tables ORDER BY bytes DESC LIMIT :n"
                ),
                {"n": top},
            )
        ).all()
    except Exception:  # SQLite/недоступная статистика: отдаём None, отчёт не падает
        return {"totalBytes": None, "tables": []}
    tables = [{"name": r[0], "sizeBytes": int(r[1] or 0), "rows": int(r[2] or 0)} for r in rows]
    return {"totalBytes": int(total or 0), "tables": tables}
