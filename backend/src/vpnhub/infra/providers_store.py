"""Файловый стор каталога провайдеров (YAML).

Дефолт в образе (`data/providers.default.yaml`) копируется в `VPNHUB_PROVIDERS_FILE` при первом
старте; дальше файл — источник правды, редактируется руками или из админки (один процесс).
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from vpnhub.api.config import Settings
from vpnhub.core.errors import BadRequest, NotFound

_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "providers.default.yaml"


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "provider"


class ProviderStore:
    def __init__(self, settings: Settings) -> None:
        self.path = Path(settings.providers_file)
        self._ensure()

    def _ensure(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            default = _DEFAULT.read_text(encoding="utf-8") if _DEFAULT.exists() else "[]\n"
            self.path.write_text(default, encoding="utf-8")

    @staticmethod
    def _norm(p: dict) -> dict:
        return {
            "id": str(p.get("id") or _slug(str(p.get("name", "")))),
            "name": str(p.get("name", "")),
            "url": str(p.get("url", "")),
            "blurb": str(p.get("blurb", "")),
            "tags": [str(t) for t in (p.get("tags") or [])],
        }

    def _read(self) -> list[dict]:
        try:
            data = yaml.safe_load(self.path.read_text(encoding="utf-8")) or []
        except Exception:
            data = []
        return [self._norm(p) for p in data if isinstance(p, dict)]

    def _write(self, items: list[dict]) -> None:
        self.path.write_text(yaml.safe_dump(items, allow_unicode=True, sort_keys=False), encoding="utf-8")

    def list(self) -> list[dict]:
        return self._read()

    def create(self, data: dict) -> dict:
        if not (data.get("name") or "").strip():
            raise BadRequest(key="provider.name_required")
        items = self._read()
        pid = (data.get("id") or _slug(str(data["name"]))).strip()
        if any(p["id"] == pid for p in items):
            pid = f"{pid}-{len(items) + 1}"
        item = self._norm({**data, "id": pid})
        items.append(item)
        self._write(items)
        return item

    def update(self, pid: str, data: dict) -> dict:
        items = self._read()
        for i, p in enumerate(items):
            if p["id"] == pid:
                items[i] = self._norm({**p, **data, "id": pid})
                self._write(items)
                return items[i]
        raise NotFound(key="provider.not_found")

    def delete(self, pid: str) -> None:
        items = self._read()
        kept = [p for p in items if p["id"] != pid]
        if len(kept) == len(items):
            raise NotFound(key="provider.not_found")
        self._write(kept)
