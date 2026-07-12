"""Файловый стор каталога провайдеров (YAML).

Дефолт в образе (`data/providers.default.yaml`) копируется в `VPNHUB_PROVIDERS_FILE` при первом
старте; дальше файл — источник правды, редактируется руками или из админки (один процесс).

Чтобы новые дефолтные провайдеры доезжали до существующих пользователей после обновления версии,
на старте вызывается `sync_default_providers()`: он ДОЛИВАЕТ новые дефолты по id (в конец), не трогая
правки/добавления/удаления пользователя. Уже «сиженные» дефолтные id хранит sibling-маркер
`<providers>.seeded.json`; для установок, поставленных ДО этой фичи (маркера нет), стартовый набор
берётся из `_PRE_MERGE_DEFAULT_IDS`, чтобы удалённые пользователем дефолты не воскресали.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from vpnhub.api.config import Settings
from vpnhub.core.errors import BadRequest, NotFound

_DEFAULT = Path(__file__).resolve().parent.parent / "data" / "providers.default.yaml"

# Дефолтные провайдеры, поставлявшиеся ДО фичи мерджа-на-обновлении (до v0.10.0). Для существующих
# установок без маркера считаем их уже сиженными: тогда доливаются только более новые дефолты, а
# удалённые пользователем старые провайдеры не воскресают.
_PRE_MERGE_DEFAULT_IDS = frozenset({"firstbyte", "ufo", "ishosting", "ahost", "serverspace"})


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return s or "provider"


class ProviderStore:
    def __init__(self, settings: Settings) -> None:
        self.path = Path(settings.providers_file)
        self._seeded_path = self.path.with_name(f"{self.path.stem}.seeded.json")
        self._ensure()

    def _ensure(self) -> None:
        if not self.path.exists():
            self.path.parent.mkdir(parents=True, exist_ok=True)
            default = _DEFAULT.read_text(encoding="utf-8") if _DEFAULT.exists() else "[]\n"
            self.path.write_text(default, encoding="utf-8")

    def _default_items(self) -> list[dict]:
        try:
            data = yaml.safe_load(_DEFAULT.read_text(encoding="utf-8")) or []
        except Exception:
            data = []
        return [self._norm(p) for p in data if isinstance(p, dict)]

    def _read_seeded(self) -> set[str]:
        try:
            return {str(x) for x in json.loads(self._seeded_path.read_text(encoding="utf-8"))}
        except Exception:
            return set()

    def _write_seeded(self, ids: set[str]) -> None:
        try:
            self._seeded_path.write_text(json.dumps(sorted(ids)), encoding="utf-8")
        except OSError:
            pass

    def sync_default_providers(self) -> int:
        """Домердж новых дефолтных провайдеров (по id) в пользовательский файл. Возвращает число
        добавленных. Вызывать один раз на старте. Существующие/кастомные/удалённые записи не трогаем.
        """
        defaults = self._default_items()
        if not defaults:
            return 0
        all_ids = {d["id"] for d in defaults}
        # маркер есть → сиженные из него; маркера нет (установка до фичи) → берём базовый набор
        seeded = self._read_seeded() if self._seeded_path.exists() else set(_PRE_MERGE_DEFAULT_IDS)
        new_ids = all_ids - seeded
        appended: list[dict] = []
        if new_ids:
            items = self._read()
            have = {p["id"] for p in items}
            appended = [d for d in defaults if d["id"] in new_ids and d["id"] not in have]
            if appended:
                self._write(items + appended)
        self._write_seeded(all_ids | seeded)  # фиксируем маркер (в т.ч. первый раз)
        return len(appended)

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
